from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from frontend.config import DEFAULT_HTTP_TIMEOUT_SECONDS


class BackendClientError(RuntimeError):
    """Raised when the Streamlit frontend cannot complete a backend request."""


@dataclass(slots=True)
class StreamEvent:
    event: str | None
    payload: Any


class BackendClient:
    def __init__(self, base_url: str, timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS):
        normalized = base_url.strip().rstrip("/")
        self.base_url = normalized or "http://localhost:8000"
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health")

    def register_user(self, name: str) -> dict[str, Any]:
        return self._request_json("POST", "/users/register", json={"name": name})

    def upload_bytes(
        self,
        *,
        user_id: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        files = {"file": (filename, content, content_type or "application/octet-stream")}
        return self._request_json(
            "POST",
            f"/upload/{user_id}",
            params={"overwrite": str(overwrite).lower()},
            files=files,
        )

    def upload_path(self, *, user_id: str, file_path: Path, overwrite: bool = False) -> dict[str, Any]:
        return self.upload_bytes(
            user_id=user_id,
            filename=file_path.name,
            content=file_path.read_bytes(),
            overwrite=overwrite,
        )

    def stream_chat(
        self,
        *,
        user_id: str,
        agent_id: str,
        message: str,
        thread_id: str,
    ) -> Iterator[StreamEvent]:
        url = f"{self.base_url}/chat/{user_id}/{agent_id}"
        payload = {"message": message, "thread_id": thread_id}

        try:
            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    self._raise_for_status(response)
                    yield from self._parse_sse_stream(response)
        except httpx.HTTPError as exc:
            raise BackendClientError(f"Chat stream failed: {exc}") from exc

    def resolve_artifact_url(self, raw_url: str) -> str:
        return raw_url if raw_url.startswith("http") else urljoin(f"{self.base_url}/", raw_url.lstrip("/"))

    def fetch_artifact_bytes(self, artifact_url: str) -> bytes:
        absolute_url = self.resolve_artifact_url(artifact_url)
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(absolute_url)
                self._raise_for_status(response)
                return response.content
        except httpx.HTTPError as exc:
            raise BackendClientError(f"Artifact fetch failed: {exc}") from exc

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method, url, **kwargs)
                self._raise_for_status(response)
                return response.json()
        except httpx.HTTPError as exc:
            raise BackendClientError(f"Backend request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BackendClientError("Backend returned a non-JSON response.") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if not detail:
                detail = str(exc)
            raise BackendClientError(detail) from exc

    @staticmethod
    def _parse_sse_stream(response: httpx.Response) -> Iterator[StreamEvent]:
        current_event: str | None = None
        data_lines: list[str] = []

        for raw_line in response.iter_lines():
            line = raw_line.strip()
            if not line:
                if current_event is not None or data_lines:
                    yield StreamEvent(
                        event=current_event,
                        payload=BackendClient._parse_sse_payload("\n".join(data_lines)),
                    )
                current_event = None
                data_lines = []
                continue

            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line.partition(":")[2].strip()
                continue
            if line.startswith("data:"):
                data_lines.append(line.partition(":")[2].lstrip())

        if current_event is not None or data_lines:
            yield StreamEvent(
                event=current_event,
                payload=BackendClient._parse_sse_payload("\n".join(data_lines)),
            )

    @staticmethod
    def _parse_sse_payload(raw_payload: str) -> Any:
        if not raw_payload:
            return {}
        try:
            return json.loads(raw_payload)
        except json.JSONDecodeError:
            return {"raw": raw_payload}
