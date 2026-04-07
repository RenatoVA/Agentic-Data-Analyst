from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent_factory, get_stt_service, require_registered_user
from app.services.agent_factory import AgentFactory, CONVERSATION_MODE_ON
from app.services.streaming import format_sse, stream_chat_events
from app.services.stt_service import STTService

router = APIRouter()


@router.post("/{user_id}/{agent_id}")
async def voice_chat(
    user_id: str,
    agent_id: str,
    thread_id: str = Form(...),
    conversation_mode: str = Form(...),
    audio: UploadFile = File(...),
    registered_user_id: str = Depends(require_registered_user),
    stt_service: STTService = Depends(get_stt_service),
    agent_factory: AgentFactory = Depends(get_agent_factory),
) -> StreamingResponse:
    # FIX: Extraemos los datos del audio fuera del stream
    audio_bytes = await audio.read()
    filename = audio.filename or "voice_input.wav"
    content_type = audio.content_type

    agent = agent_factory.get_or_create_agent(
        user_id=registered_user_id,
        agent_id=agent_id,
        conversation_mode=conversation_mode,
    )

    async def event_stream():
        try:
            # FIX: Hacemos la transcripción dentro del generador para evitar bloquear la conexión inicial SSE
            transcript = await stt_service.transcribe(
                audio_bytes=audio_bytes,
                filename=filename,
                content_type=content_type,
            )
            print(transcript)
            
            yield format_sse("transcript", {"text": transcript, "thread_id": thread_id})
            
            async for event in stream_chat_events(
                agent=agent,
                message=transcript,
                thread_id=thread_id,
                stream_mode=["updates", "messages"],
            ):
                yield event
                
        except Exception as e:
            # FIX: Si algo falla (ej. Groq está caído), emitimos el error a través del stream activo
            yield format_sse("error", {"detail": str(e)})

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)
