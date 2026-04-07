from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.dependencies import get_settings_dep, require_registered_user
from app.core.config import Settings
from app.schemas.upload import UploadResponse
from app.utils.files import ensure_directory, sanitize_filename

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls",".png", ".jpg", ".jpeg", ".gif",".md",".txt", ".pdf", ".docx", ".pptx"}

router = APIRouter()


@router.post("/{user_id}", response_model=UploadResponse)
async def upload_file(
    user_id: str,
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Overwrite file when target already exists."),
    registered_user_id: str = Depends(require_registered_user),
    settings: Settings = Depends(get_settings_dep),
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    safe_name = sanitize_filename(file.filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only CSV and Excel uploads are allowed.")

    user_upload_dir = settings.USERS_DIR / registered_user_id / "workspace"
    ensure_directory(user_upload_dir)
    target_path = (user_upload_dir / safe_name).resolve()

    if target_path.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"File '{safe_name}' already exists. Use overwrite=true to replace it.",
        )

    size = 0
    with target_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            out.write(chunk)

    return UploadResponse(
        user_id=registered_user_id,
        filename=safe_name,
        stored_path=str(target_path),
        mime_type=file.content_type,
        size_bytes=size,
    )
