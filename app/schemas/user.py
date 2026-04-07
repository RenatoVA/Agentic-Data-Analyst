from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RegisterUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="User display name.")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be empty.")
        return stripped


class RegisterUserResponse(BaseModel):
    username: str
    user_id: str
    agent_name: str
