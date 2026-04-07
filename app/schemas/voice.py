from __future__ import annotations

from pydantic import BaseModel, Field


class VoiceChatMetadata(BaseModel):
    thread_id: str = Field(..., min_length=1)
    transcription: str = Field(..., min_length=1)

