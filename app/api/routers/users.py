from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_user_provisioning_service
from app.schemas.user import RegisterUserRequest, RegisterUserResponse
from app.services.user_provisioning import UserProvisioningService

router = APIRouter()


@router.post("/register", response_model=RegisterUserResponse)
async def register_user(
    request: RegisterUserRequest,
    user_service: UserProvisioningService = Depends(get_user_provisioning_service),
) -> RegisterUserResponse:
    result = user_service.ensure_registered(request.name)
    return RegisterUserResponse(
        username=result.username,
        user_id=result.user_id,
        agent_name=result.agent_name,
    )
