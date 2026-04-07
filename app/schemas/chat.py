from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User input message.")
    thread_id: str = Field(..., min_length=1, description="Conversation thread identifier.")

