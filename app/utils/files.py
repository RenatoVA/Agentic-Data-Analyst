from __future__ import annotations

import re
from pathlib import Path


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    return safe or "upload.bin"


def resolve_workspace_path(root_dir: Path, provided_path: str, *, must_exist: bool = False) -> Path:
    candidate = Path(provided_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root_dir / candidate).resolve()

    root_resolved = root_dir.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"Path '{provided_path}' is outside ROOT_DIR.")

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Path '{provided_path}' does not exist.")

    return resolved

