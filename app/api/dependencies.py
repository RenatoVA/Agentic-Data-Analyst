from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.errors import UserNotRegisteredError
from app.services.agent_factory import AgentFactory
from app.services.stt_service import STTService
from app.services.tool_registry import build_tool_registry
from app.services.user_provisioning import UserProvisioningService


@lru_cache
def _tool_registry() -> dict[str, Any]:
    settings = get_settings()
    return build_tool_registry(settings.ROOT_DIR)


@lru_cache
def _agent_factory() -> AgentFactory:
    settings = get_settings()
    return AgentFactory(settings=settings, tool_registry=_tool_registry())


@lru_cache
def _stt_service() -> STTService:
    settings = get_settings()
    return STTService(settings=settings)


@lru_cache
def _user_provisioning_service() -> UserProvisioningService:
    settings = get_settings()
    return UserProvisioningService(settings=settings)


def get_settings_dep() -> Settings:
    return get_settings()


def get_agent_factory() -> AgentFactory:
    return _agent_factory()


def get_stt_service() -> STTService:
    return _stt_service()


def get_user_provisioning_service() -> UserProvisioningService:
    return _user_provisioning_service()


def require_registered_user(
    user_id: str,
    user_service: UserProvisioningService = Depends(get_user_provisioning_service),
) -> str:
    if not user_service.is_registered(user_id):
        raise UserNotRegisteredError(f"User '{user_id}' is not registered.")
    return user_id
