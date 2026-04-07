from __future__ import annotations

from fastapi import APIRouter

from app.api.routers.chat import router as chat_router
from app.api.routers.files import router as files_router
from app.api.routers.upload import router as upload_router
from app.api.routers.users import router as users_router
from app.api.routers.voice_chat import router as voice_chat_router

api_router = APIRouter()

api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(files_router, prefix="/files", tags=["files"])
api_router.include_router(upload_router, prefix="/upload", tags=["upload"])
api_router.include_router(voice_chat_router, prefix="/voice-chat", tags=["voice-chat"])
api_router.include_router(users_router, prefix="/users", tags=["users"])


@api_router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
