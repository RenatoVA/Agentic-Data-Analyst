from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.utils.files import resolve_workspace_path
from app.utils.url_signing import verify_signed_url

router = APIRouter()


@router.get("/{user_id}/{file_path:path}")
async def serve_file(
    user_id: str,
    file_path: str,
    token: str = Query(..., description="HMAC-SHA256 signed token"),
    expires: int = Query(..., description="Unix timestamp of token expiration"),
) -> FileResponse:
    settings = get_settings()

    if not verify_signed_url(
        secret=settings.FILE_SIGNING_SECRET,
        user_id=user_id,
        file_path=file_path,
        token=token,
        expires=expires,
    ):
        raise HTTPException(status_code=403, detail="Invalid or expired file token.")

    workspace_dir = settings.USERS_DIR / user_id / "workspace"
    if not workspace_dir.is_dir():
        raise HTTPException(status_code=404, detail="User workspace not found.")

    try:
        resolved_path = resolve_workspace_path(workspace_dir, file_path, must_exist=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied.")

    content_type = mimetypes.guess_type(str(resolved_path))[0] or "application/octet-stream"

    return FileResponse(
        path=str(resolved_path),
        media_type=content_type,
        filename=resolved_path.name,
        headers={
              "Access-Control-Allow-Origin": "*",
              "Cross-Origin-Resource-Policy": "cross-origin",
          },
    )
