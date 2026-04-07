from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from frontend.api_client import BackendClient


def render_chat_history(messages: list[dict[str, str]]) -> None:
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def render_runtime_events(events: list[dict[str, Any]]) -> None:
    if not events:
        st.caption("No runtime events yet.")
        return

    for event in reversed(events[-20:]):
        st.markdown(f"**{event['time']}** · `{event['kind']}` · {event['summary']}")
        if event["payload"]:
            with st.expander("Payload", expanded=False):
                st.json(event["payload"])


def render_interrupts(interrupts: list[dict[str, Any]]) -> None:
    if not interrupts:
        st.caption("No interrupts captured in this thread.")
        return

    for index, interrupt in enumerate(reversed(interrupts), start=1):
        st.warning(
            f"Interrupt {index}: approval is required in the backend, but resume is not implemented in this Streamlit client yet."
        )
        st.caption(f"Agent: {interrupt.get('agent', 'unknown')}")
        st.json(interrupt.get("interrupts", {}))


def render_artifacts(artifacts: list[dict[str, Any]], client: BackendClient) -> None:
    if not artifacts:
        st.caption("No generated artifacts yet.")
        return

    for artifact in reversed(artifacts):
        filename = artifact.get("filename", "artifact")
        absolute_url = artifact.get("absolute_url", artifact.get("url", ""))
        artifact_type = artifact.get("type", "document")
        mime_type = artifact.get("mime_type", "application/octet-stream")

        with st.expander(f"{filename} · {artifact_type}", expanded=False):
            st.markdown(f"[Open artifact]({absolute_url})")
            st.caption(f"MIME type: {mime_type}")

            if artifact_type == "image":
                st.image(absolute_url, caption=filename, use_container_width=True)
            elif artifact_type == "data":
                render_data_artifact_preview(absolute_url, mime_type, client)
            elif mime_type.startswith("text/") or filename.endswith((".md", ".txt")):
                render_text_preview(absolute_url, client)


@st.cache_data(ttl=300, show_spinner=False)
def _download_artifact(url: str) -> bytes:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.content


def render_data_artifact_preview(artifact_url: str, mime_type: str, client: BackendClient) -> None:
    try:
        data = _download_artifact(client.resolve_artifact_url(artifact_url))
    except Exception as exc:
        st.info(f"Preview unavailable: {exc}")
        return

    if mime_type in {"text/csv", "application/csv"} or artifact_url.endswith(".csv"):
        frame = pd.read_csv(io.BytesIO(data))
        st.dataframe(frame.head(10), use_container_width=True)
        return

    if mime_type == "application/json" or artifact_url.endswith(".json"):
        parsed = json.loads(data.decode("utf-8"))
        st.json(parsed if isinstance(parsed, dict) else parsed[:10])
        return

    if artifact_url.endswith((".txt", ".md")) or mime_type.startswith("text/"):
        st.code(data.decode("utf-8")[:4000])
        return

    st.info("Preview not implemented for this data file type.")


def render_text_preview(artifact_url: str, client: BackendClient) -> None:
    try:
        data = _download_artifact(client.resolve_artifact_url(artifact_url))
    except Exception as exc:
        st.info(f"Preview unavailable: {exc}")
        return

    st.code(data.decode("utf-8")[:4000])
