from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from langchain.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph


def format_sse(event: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def _to_sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _source_from_namespace(namespace: tuple[str, ...]) -> str:
    if any(part.startswith("tools:") for part in namespace):
        return "subagent"
    return "main"


def _handle_update_chunk(chunk: dict[str, Any], source: str) -> list[str]:
    events: list[str] = []
    first_key = next(iter(chunk), None)
    if first_key == "tools":
        messages = chunk["tools"].get("messages", [])
        if messages and getattr(messages[0], "name", "") == "send_files_to_user":
            events.append(
                _to_sse_data(
                    {
                        "status": "sending_files",
                        "agent": source,
                        "artifact": getattr(messages[0], "artifact", None),
                    }
                )
            )

    if first_key == "__interrupt__":
        interrupts = chunk["__interrupt__"][0].value
        events.append(
            _to_sse_data(
                {
                    "status": "interrupted",
                    "interrupts": interrupts,
                    "agent": source,
                }
            )
        )

    return events


def _handle_message_chunk(namespace: tuple[str, ...], chunk: tuple[Any, Any]) -> list[str]:
    events: list[str] = []
    token, _metadata = chunk
    source = _source_from_namespace(namespace)

    if isinstance(token, AIMessage) and token.content:
        key = "sub_agent_token" if source == "subagent" else "token"
        events.append(_to_sse_data({key: token.content}))

    if isinstance(token, AIMessage) and token.tool_calls:
        tool_name = token.tool_calls[0].get("name", "")
        if tool_name:
            events.append(_to_sse_data({"tool_calls": tool_name, "agent": source}))

    return events


async def stream_chat_events(
    *,
    agent: CompiledStateGraph,
    message: str,
    thread_id: str,
    status: str = "streaming",
    stream_mode: list[str] | None = None,
) -> AsyncIterator[str]:
    payload = {"messages": [{"role": "user", "content": message}]}
    config = {"configurable": {"thread_id": thread_id, "recursion_limit": 100}}
    active_stream_mode = stream_mode or ["updates", "messages"]

    if status not in {"streaming", "interrupted"}:
        yield format_sse("error", {"detail": f"Unsupported stream status: {status}"})
        return

    try:
        async for namespace, mode, chunk in agent.astream(
            payload,
            config,
            stream_mode=active_stream_mode,
            subgraphs=True,
        ):
            source = _source_from_namespace(namespace)

            if mode == "updates":
                for event in _handle_update_chunk(chunk, source):
                    yield event

            if mode == "messages":
                for event in _handle_message_chunk(namespace, chunk):
                    yield event

    except Exception as exc:
        yield format_sse("error", {"detail": f"AGENT_STREAM_ERROR: {exc}"})
