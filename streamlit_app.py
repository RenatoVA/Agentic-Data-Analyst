from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from frontend.api_client import BackendClient, BackendClientError, StreamEvent
from frontend.config import DEMO_PROMPTS, EXAMPLE_DATASETS, EXAMPLES_DIR
from frontend.renderers import render_artifacts, render_chat_history, render_interrupts, render_runtime_events
from frontend.state import (
    append_artifact,
    append_event,
    append_interrupt,
    append_message,
    ensure_session_state,
    reset_thread_state,
    reset_user_session,
)


st.set_page_config(
    page_title="Agentic Data Analyst Demo",
    page_icon=":material/bolt:",
    layout="wide",
    initial_sidebar_state="expanded",
)


CUSTOM_CSS = """
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    .status-card {
        border: 1px solid rgba(49, 51, 63, 0.15);
        border-radius: 14px;
        padding: 0.9rem 1rem;
        background: rgba(246, 248, 251, 0.9);
        margin-bottom: 0.75rem;
    }
    .tiny-note {
        color: #5d6574;
        font-size: 0.92rem;
    }
</style>
"""


def normalize_artifact(raw_artifact: dict[str, Any], source: str, client: BackendClient) -> dict[str, Any]:
    artifact = dict(raw_artifact)
    artifact["agent"] = source
    artifact["absolute_url"] = client.resolve_artifact_url(artifact.get("url", ""))
    return artifact


def append_stream_event(event: StreamEvent, client: BackendClient) -> tuple[str | None, str | None]:
    payload = event.payload if isinstance(event.payload, dict) else {"raw": str(event.payload)}
    event_name = event.event

    if event_name == "transcript":
        transcript = str(payload.get("text", ""))
        append_event("transcript", "Voice transcript received from backend.", payload)
        return None, transcript

    if event_name == "error":
        detail = str(payload.get("detail", payload.get("raw", "Unknown backend error.")))
        append_event("error", detail, payload)
        return f"Backend error: {detail}", None

    if "tool_calls" in payload:
        append_event(
            "tool_call",
            f"{payload.get('agent', 'agent')} called `{payload['tool_calls']}`.",
            payload,
        )
        return None, None

    if payload.get("status") == "sending_files":
        raw_artifact = payload.get("artifact") or {}
        artifact = normalize_artifact(raw_artifact, payload.get("agent", "agent"), client)
        append_artifact(artifact)
        append_event("artifact", f"Generated artifact `{artifact.get('filename', 'artifact')}`.", artifact)
        return None, None

    if payload.get("status") == "interrupted":
        interrupt = {
            "agent": payload.get("agent", "agent"),
            "interrupts": payload.get("interrupts", {}),
        }
        append_interrupt(interrupt)
        append_event(
            "interrupt",
            "Execution paused for approval in the backend.",
            interrupt,
        )
        return None, None

    if "token" in payload:
        return str(payload["token"]), None

    if "sub_agent_token" in payload:
        return None, str(payload["sub_agent_token"])

    if "detail" in payload:
        detail = str(payload["detail"])
        append_event("status", detail, payload)
        return None, None

    if "raw" in payload:
        append_event("raw", "Received non-JSON SSE payload.", payload)
        return None, None

    return None, None


def process_chat_message(client: BackendClient, prompt: str) -> None:
    append_message("user", prompt)
    append_event("user_message", "User sent a message.", {"thread_id": st.session_state.thread_id})

    with st.chat_message("user"):
        st.markdown(prompt)

    assistant_text = ""
    subagent_text = ""
    tool_summaries: list[str] = []
    interrupt_notice = ""

    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        with st.expander("Live execution details", expanded=True):
            transcript_placeholder = st.empty()
            tool_placeholder = st.empty()
            subagent_placeholder = st.empty()
            interrupt_placeholder = st.empty()

        try:
            for event in client.stream_chat(
                user_id=st.session_state.user_id,
                agent_id=st.session_state.agent_name,
                message=prompt,
                thread_id=st.session_state.thread_id,
            ):
                token_chunk, subagent_chunk = append_stream_event(event, client)

                payload = event.payload if isinstance(event.payload, dict) else {}
                if event.event == "transcript" and payload.get("text"):
                    transcript_placeholder.info(f"Transcript: {payload['text']}")

                if "tool_calls" in payload:
                    tool_summaries.append(f"- `{payload['tool_calls']}` via {payload.get('agent', 'agent')}")
                    tool_placeholder.markdown("\n".join(tool_summaries[-8:]))

                if payload.get("status") == "interrupted":
                    interrupt_notice = "Approval required in backend. This frontend shows the interrupt but cannot resume it yet."
                    interrupt_placeholder.warning(interrupt_notice)

                if token_chunk:
                    assistant_text += token_chunk
                    response_placeholder.markdown(assistant_text)

                if subagent_chunk:
                    subagent_text += subagent_chunk
                    subagent_placeholder.code(subagent_text[-1500:])

        except BackendClientError as exc:
            append_event("error", str(exc), {"stage": "chat_stream"})
            response_placeholder.error(str(exc))
            st.session_state.last_error = str(exc)
            return

        final_text = assistant_text.strip()
        if not final_text:
            final_text = (
                "Execution completed without a final assistant message. "
                "Check runtime events, generated artifacts, or interrupt details."
            )
            if interrupt_notice:
                final_text = interrupt_notice
            response_placeholder.markdown(final_text)

        append_message("assistant", final_text)
        st.session_state.composer_text = ""
        st.rerun()


def handle_registration(client: BackendClient) -> None:
    with st.sidebar.form("register_user_form", clear_on_submit=False):
        st.markdown("### Register demo user")
        name = st.text_input(
            "Display name",
            value=st.session_state.username,
            placeholder="e.g. Rafael Vivas",
        )
        submitted = st.form_submit_button("Register user", use_container_width=True)

    if submitted:
        try:
            result = client.register_user(name.strip())
        except BackendClientError as exc:
            st.sidebar.error(str(exc))
            return

        st.session_state.username = result["username"]
        st.session_state.user_id = result["user_id"]
        st.session_state.agent_name = result["agent_name"]
        reset_thread_state()
        append_event("session", "Registered a new demo user.", result)
        st.sidebar.success(f"Registered as `{result['user_id']}`.")
        st.rerun()


def handle_example_uploads(client: BackendClient) -> None:
    st.sidebar.markdown("### Example datasets")
    st.sidebar.caption("One-click uploads from the repository examples folder.")
    overwrite = st.sidebar.checkbox("Overwrite demo uploads", key="upload_overwrite")

    for dataset in EXAMPLE_DATASETS:
        label = f"Upload {dataset['label']}"
        if st.sidebar.button(label, use_container_width=True, disabled=not st.session_state.user_id):
            example_path = EXAMPLES_DIR / dataset["filename"]
            if not example_path.is_file():
                st.sidebar.error(f"Missing example file: {example_path.name}")
                continue
            try:
                result = client.upload_path(
                    user_id=st.session_state.user_id,
                    file_path=example_path,
                    overwrite=overwrite,
                )
            except BackendClientError as exc:
                st.sidebar.error(str(exc))
                continue

            append_event("upload", f"Uploaded `{result['filename']}` from examples.", result)
            st.sidebar.success(f"Uploaded `{result['filename']}`.")

        st.sidebar.caption(dataset["description"])


def handle_manual_uploads(client: BackendClient) -> None:
    st.sidebar.markdown("### Upload your files")
    uploads = st.sidebar.file_uploader(
        "Choose files",
        accept_multiple_files=True,
        type=["csv", "xlsx", "xls", "json", "png", "jpg", "jpeg", "gif", "md", "txt", "pdf", "docx", "pptx"],
    )
    upload_clicked = st.sidebar.button(
        "Upload selected files",
        use_container_width=True,
        disabled=not (st.session_state.user_id and uploads),
    )

    if upload_clicked and uploads:
        for uploaded in uploads:
            try:
                result = client.upload_bytes(
                    user_id=st.session_state.user_id,
                    filename=uploaded.name,
                    content=uploaded.getvalue(),
                    content_type=uploaded.type,
                    overwrite=st.session_state.upload_overwrite,
                )
            except BackendClientError as exc:
                st.sidebar.error(f"{uploaded.name}: {exc}")
                continue

            append_event("upload", f"Uploaded `{result['filename']}` from local client.", result)
            st.sidebar.success(f"Uploaded `{result['filename']}`.")


def render_sidebar(client: BackendClient) -> None:
    st.sidebar.title("Demo controls")
    st.sidebar.text_input("Backend URL", key="backend_url", help="FastAPI base URL for the backend service.")

    if st.sidebar.button("Check backend", use_container_width=True):
        try:
            health = client.health()
            st.sidebar.success(f"Backend healthy: {health.get('status', 'ok')}")
        except BackendClientError as exc:
            st.sidebar.error(str(exc))

    if st.session_state.user_id:
        st.sidebar.markdown("### Session")
        st.sidebar.code(
            "\n".join(
                [
                    f"user_id: {st.session_state.user_id}",
                    f"agent: {st.session_state.agent_name}",
                    f"thread: {st.session_state.thread_id}",
                ]
            )
        )
        left, right = st.sidebar.columns(2)
        if left.button("New thread", use_container_width=True):
            reset_thread_state()
            st.rerun()
        if right.button("Reset user", use_container_width=True):
            reset_user_session()
            st.rerun()
    else:
        handle_registration(client)

    if st.session_state.user_id:
        handle_example_uploads(client)
        handle_manual_uploads(client)

    st.sidebar.markdown("### Suggested prompts")
    for label, prompt in DEMO_PROMPTS:
        if st.sidebar.button(label, use_container_width=True):
            st.session_state.composer_text = prompt
            st.rerun()
    st.sidebar.caption("These prompts are optimized for the example datasets included in the repo.")


def render_header() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.title("Agentic Data Analyst")
    st.caption("Streamlit demo client for the FastAPI multi-agent backend.")

    left, middle, right = st.columns(3)
    left.markdown(
        f"<div class='status-card'><strong>User</strong><br>{st.session_state.user_id or 'Not registered'}</div>",
        unsafe_allow_html=True,
    )
    middle.markdown(
        f"<div class='status-card'><strong>Agent</strong><br>{st.session_state.agent_name or 'Not assigned'}</div>",
        unsafe_allow_html=True,
    )
    right.markdown(
        f"<div class='status-card'><strong>Thread</strong><br>{st.session_state.thread_id}</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div class='tiny-note'>This UI is optimized for portfolio demos: chat, uploads, runtime visibility, artifacts, and approval interrupts.</div>",
        unsafe_allow_html=True,
    )


def render_chat_composer(client: BackendClient) -> None:
    with st.form("composer_form", clear_on_submit=False):
        prompt = st.text_area(
            "Message",
            key="composer_text",
            height=120,
            placeholder="Ask the agent to profile a dataset, compare files, generate a chart, or create a segmentation report...",
        )
        submitted = st.form_submit_button(
            "Send message",
            type="primary",
            use_container_width=True,
            disabled=not st.session_state.user_id,
        )

    if submitted:
        prompt = prompt.strip()
        if not prompt:
            st.warning("Write a message before sending.")
            return
        process_chat_message(client, prompt)


def main() -> None:
    ensure_session_state()
    client = BackendClient(st.session_state.backend_url)

    render_sidebar(client)
    render_header()

    if not st.session_state.user_id:
        st.info("Register a demo user from the sidebar to start uploading files and chatting with the agent.")

    render_chat_history(st.session_state.messages)

    artifacts_tab, events_tab, interrupts_tab = st.tabs(["Artifacts", "Runtime events", "Interrupts"])
    with artifacts_tab:
        render_artifacts(st.session_state.artifacts, client)
    with events_tab:
        render_runtime_events(st.session_state.events)
    with interrupts_tab:
        render_interrupts(st.session_state.interrupts)

    render_chat_composer(client)


if __name__ == "__main__":
    main()
