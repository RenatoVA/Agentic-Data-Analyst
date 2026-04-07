from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.services.tools import build_tool_registry as _build_tool_registry


def build_tool_registry(
    root_dir: Path,
    *,
    user_id: str | None = None,
    url_signer: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    return _build_tool_registry(root_dir, user_id=user_id, url_signer=url_signer)
