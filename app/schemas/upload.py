from __future__ import annotations

from pydantic import BaseModel


class UploadResponse(BaseModel):
    user_id: str
    filename: str
    stored_path: str
    mime_type: str | None = None
    size_bytes: int

