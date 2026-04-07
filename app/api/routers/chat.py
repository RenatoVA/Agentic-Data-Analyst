from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent_factory, require_registered_user
from app.schemas.chat import ChatRequest
from app.services.agent_factory import AgentFactory, CONVERSATION_MODE_OFF
from app.services.streaming import stream_chat_events

router = APIRouter()


@router.post("/{user_id}/{agent_id}")
async def chat(
    user_id: str,
    agent_id: str,
    request: ChatRequest,
    registered_user_id: str = Depends(require_registered_user),
    agent_factory: AgentFactory = Depends(get_agent_factory),
) -> StreamingResponse:
    agent = agent_factory.get_or_create_agent(
        user_id=registered_user_id,
        agent_id=agent_id,
    )
    event_stream = stream_chat_events(
        agent=agent,
        message=request.message,
        thread_id=request.thread_id,
        stream_mode=["updates", "messages"],
    )
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream, media_type="text/event-stream", headers=headers)
