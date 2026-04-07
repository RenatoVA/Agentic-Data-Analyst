from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.utils.files import ensure_directory


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    ensure_directory(settings.USERS_DIR)

    app = FastAPI(
        title="Agentic YupAI API",
        version="0.1.0",
        description="Agents-as-a-Service backend with dynamic YAML-configured DeepAgents.",
    )

    origins = settings.cors_origins
    allow_credentials = origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
