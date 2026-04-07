from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import streamlit as st

from frontend.config import DEFAULT_BACKEND_URL


def generate_thread_id() -> str:
    return f"thread-{uuid4().hex[:12]}"


def ensure_session_state() -> None:
    defaults = {
        "backend_url": DEFAULT_BACKEND_URL,
        "username": "",
        "user_id": "",
        "agent_name": "",
        "thread_id": generate_thread_id(),
        "messages": [],
        "events": [],
        "artifacts": [],
        "interrupts": [],
        "composer_text": "",
        "upload_overwrite": False,
        "last_error": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_thread_state() -> None:
    st.session_state.thread_id = generate_thread_id()
    st.session_state.messages = []
    st.session_state.events = []
    st.session_state.artifacts = []
    st.session_state.interrupts = []
    st.session_state.last_error = ""


def reset_user_session() -> None:
    st.session_state.username = ""
    st.session_state.user_id = ""
    st.session_state.agent_name = ""
    st.session_state.composer_text = ""
    reset_thread_state()


def append_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def append_event(kind: str, summary: str, payload: dict | None = None) -> None:
    st.session_state.events.append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "kind": kind,
            "summary": summary,
            "payload": payload or {},
        }
    )


def append_artifact(artifact: dict) -> None:
    st.session_state.artifacts.append(artifact)


def append_interrupt(interrupt: dict) -> None:
    st.session_state.interrupts.append(interrupt)
