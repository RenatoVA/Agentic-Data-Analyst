from __future__ import annotations
from langgraph.graph.state import CompiledStateGraph
import json
from langchain.messages import AIMessage
from collections.abc import AsyncIterator
from typing import Any


def format_sse(event: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def _message_to_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")

    if hasattr(content, "value"):
        content = getattr(content, "value")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _normalize_messages(raw_messages: Any) -> list[Any]:
    if raw_messages is None:
        return []
    if hasattr(raw_messages, "value"):
        return _normalize_messages(getattr(raw_messages, "value"))
    if isinstance(raw_messages, list):
        return raw_messages
    if isinstance(raw_messages, tuple):
        return list(raw_messages)
    if isinstance(raw_messages, dict):
        return [raw_messages]
    return []


async def stream_chat_events(
    *,
    agent: CompiledStateGraph,
    message: str,
    thread_id: str,
    status: str = "streaming",
    stream_mode: list[str] = ["updates", "messages"],
) -> AsyncIterator[str]:
    payload = {"messages": [{"role": "user", "content": message}]}
    config = {"configurable": {"thread_id": thread_id,"recursion_limit": 100}}
    source  = "main"
    if status == "streaming":
        try:
            async for namespace, mode, chunk in agent.astream(payload, config, stream_mode=stream_mode, subgraphs=True):
                is_subagent = any(s.startswith("tools:") for s in namespace)
                if is_subagent:
                    source = "subagent" 
                if namespace==tuple():
                    source="main"
                if mode == "updates":
                    print(chunk)
                    # si el agente llamo a la herramienta para enviar archivos al usuario
                    if list(chunk.keys())[0]=="tools" and chunk["tools"]['messages'][0].name=="send_files_to_user":
                        print("AGENT_STREAM_EVENT: sending_files", chunk["tools"]['messages'][0].artifact)
                        yield f"data: {json.dumps({'status': 'sending_files','agent': source,'artifact': chunk['tools']['messages'][0].artifact})}\n\n"
                    
                    if list(chunk.keys())[0]=="__interrupt__":
                        print("AGENT_STREAM_EVENT: interrupted", chunk["__interrupt__"][0].value)
                        interrupts = chunk["__interrupt__"][0].value
                        yield f"data: {json.dumps({'status': 'interrupted','interrupts': interrupts,'agent': source})}\n\n"
                    
                if mode == "messages":
                    token,metadata=chunk
                    if namespace==tuple():
                        if isinstance(token, AIMessage) and token.content:
                            yield f"data: {json.dumps({'token': token.content})}\n\n"
                        if isinstance(token, AIMessage) and token.tool_calls and token.tool_calls[0]['name']!='':
                            print("AGENT_STREAM_EVENT: tool_call", token.tool_calls[0]['name'])
                            yield f"data: {json.dumps({'tool_calls': token.tool_calls[0]['name'],'agent': "main"})}\n\n"
                    if is_subagent:
                        if isinstance(token, AIMessage) and token.tool_calls and token.tool_calls[0]['name']!='':
                            print("AGENT_STREAM_EVENT: tool_call", token.tool_calls[0]['name'])
                            yield f"data: {json.dumps({'tool_calls': token.tool_calls[0]['name'],'agent': "subagent"})}\n\n"
                        if isinstance(token, AIMessage) and token.content:
                            yield f"data: {json.dumps({'sub_agent_token': token.content})}\n\n"

        except Exception as exc:
            print("Error during agent streaming: AGENT_STREAM_ERROR", exc)
    elif status == "interrupted":
        try:
            async for namespace, mode, chunk in agent.astream(payload, config, stream_mode=stream_mode, subgraphs=True):
                is_subagent = any(s.startswith("tools:") for s in namespace)
                if is_subagent:
                    source = "subagent" 
                if namespace==tuple():
                    source="main"
                if mode == "updates":
                    print(chunk)
                    # si el agente llamo a la herramienta para enviar archivos al usuario
                    if list(chunk.keys())[0]=="tools" and chunk["tools"]['messages'][0].name=="send_files_to_user":
                        print("AGENT_STREAM_EVENT: sending_files", chunk["tools"]['messages'][0].artifact)
                        yield f"data: {json.dumps({'status': 'sending_files','agent': source,'artifact': chunk['tools']['messages'][0].artifact})}\n\n"
                    
                    if list(chunk.keys())[0]=="__interrupt__":
                        print("AGENT_STREAM_EVENT: interrupted", chunk["__interrupt__"][0].value)
                        interrupts = chunk["__interrupt__"][0].value
                        yield f"data: {json.dumps({'status': 'interrupted','interrupts': interrupts,'agent': source})}\n\n"
                    
                if mode == "messages":
                    token,metadata=chunk
                    if namespace==tuple():
                        if isinstance(token, AIMessage) and token.content:
                            yield f"data: {json.dumps({'token': token.content})}\n\n"
                        if isinstance(token, AIMessage) and token.tool_calls and token.tool_calls[0]['name']!='':
                            print("AGENT_STREAM_EVENT: tool_call", token.tool_calls[0]['name'])
                            yield f"data: {json.dumps({'tool_calls': token.tool_calls[0]['name'],'agent': "main"})}\n\n"
                    if is_subagent:
                        if isinstance(token, AIMessage) and token.tool_calls and token.tool_calls[0]['name']!='':
                            print("AGENT_STREAM_EVENT: tool_call", token.tool_calls[0]['name'])
                            yield f"data: {json.dumps({'tool_calls': token.tool_calls[0]['name'],'agent': "subagent"})}\n\n"
                        if isinstance(token, AIMessage) and token.content:
                            yield f"data: {json.dumps({'sub_agent_token': token.content})}\n\n"

        except Exception as exc:
            print("Error during agent streaming: AGENT_STREAM_ERROR", exc)