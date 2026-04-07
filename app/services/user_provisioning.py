from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from app.core.config import Settings
from app.core.errors import ConfigValidationError, UserRegistrationError
from app.utils.files import ensure_directory

DEFAULT_AGENT_NAME = "geology_agent"
USER_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


@dataclass(slots=True)
class RegistrationResult:
    username: str
    user_id: str
    agent_name: str
    workspace_path: Path


class UserProvisioningService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.templates_dir = self.settings.ROOT_DIR / "templates"

    def ensure_registered(self, name: str) -> RegistrationResult:
        username = name.strip()
        user_id = self.slugify_user_id(username)
        user_dir = self.settings.USERS_DIR / user_id
        workspace_dir = user_dir / "workspace"
        agents_dir = user_dir / "agents"

        ensure_directory(user_dir)
        ensure_directory(agents_dir)
        ensure_directory(workspace_dir)
        self._ensure_default_agent(user_dir=user_dir, workspace_dir=workspace_dir)

        return RegistrationResult(
            username=username,
            user_id=user_id,
            agent_name=DEFAULT_AGENT_NAME,
            workspace_path=workspace_dir.resolve(),
        )

    def is_registered(self, user_id: str) -> bool:
        if not USER_ID_PATTERN.fullmatch(user_id):
            return False
        user_dir = self.settings.USERS_DIR / user_id
        agent_dir = user_dir / "agents" / DEFAULT_AGENT_NAME
        return user_dir.is_dir() and agent_dir.is_dir() and (agent_dir / "main_config.yaml").is_file()

    def get_workspace_path(self, user_id: str) -> Path:
        if not USER_ID_PATTERN.fullmatch(user_id):
            raise ConfigValidationError("Invalid user id.")
        return (self.settings.USERS_DIR / user_id / "workspace").resolve()

    @staticmethod
    def slugify_user_id(name: str) -> str:
        normalized = re.sub(r"\s+", "_", name.strip().lower())
        normalized = re.sub(r"[^a-z0-9_-]", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_-")
        if not normalized:
            raise ConfigValidationError("Invalid user name. Use at least one letter or number.")
        return normalized

    def _ensure_default_agent(self, *, user_dir: Path, workspace_dir: Path) -> None:
        template_agent_dir = self.templates_dir / DEFAULT_AGENT_NAME
        config_templates_dir = template_agent_dir / "config_files"
        prompts_templates_dir = template_agent_dir / "prompts"
        user_agent_dir = user_dir / "agents" / DEFAULT_AGENT_NAME
        user_prompts_dir = user_agent_dir / "prompts"

        ensure_directory(user_agent_dir)
        ensure_directory(user_prompts_dir)

        template_main = config_templates_dir / "main_config.yaml"
        template_sub = config_templates_dir / "subagents_config.yaml"
        if not template_main.is_file() or not template_sub.is_file():
            raise UserRegistrationError(
                f"Missing geology_agent templates in {config_templates_dir}."
            )

        self._write_main_config(
            template_main=template_main,
            target_main=user_agent_dir / "main_config.yaml",
            workspace_dir=workspace_dir,
        )

        target_sub = user_agent_dir / "subagents_config.yaml"
        if not target_sub.exists():
            target_sub.write_text(template_sub.read_text(encoding="utf-8"), encoding="utf-8")

        if not prompts_templates_dir.is_dir():
            raise UserRegistrationError(f"Missing prompts templates in {prompts_templates_dir}.")

        for prompt_file in prompts_templates_dir.glob("*.md"):
            target_prompt = user_prompts_dir / prompt_file.name
            if not target_prompt.exists():
                target_prompt.write_text(prompt_file.read_text(encoding="utf-8"), encoding="utf-8")

    def _write_main_config(self, *, template_main: Path, target_main: Path, workspace_dir: Path) -> None:
        template_cfg = self._load_yaml_object(template_main, "template main_config.yaml")
        template_cfg["workspace_path"] = str(workspace_dir.resolve())

        if target_main.exists():
            current_cfg = self._load_yaml_object(target_main, "user main_config.yaml")
            current_cfg["workspace_path"] = str(workspace_dir.resolve())
            target_main.write_text(
                yaml.safe_dump(current_cfg, sort_keys=False, allow_unicode=False),
                encoding="utf-8",
            )
            return

        target_main.write_text(
            yaml.safe_dump(template_cfg, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )

    @staticmethod
    def _load_yaml_object(path: Path, label: str) -> dict[str, Any]:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise UserRegistrationError(f"Invalid YAML in {label}: {exc}") from exc

        if not isinstance(loaded, dict):
            raise UserRegistrationError(f"{label} must contain a YAML object.")
        return loaded
