from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.core.config import Settings
from app.core.errors import ConfigNotFoundError, ConfigValidationError, ToolResolutionError


@dataclass(slots=True)
class AgentConfigBundle:
    user_id: str
    agent_id: str
    agent_dir: Path
    workspace_path: Path
    main_config: dict[str, Any]
    subagents_config: dict[str, Any]
    main_prompt: str
    subagent_prompts: dict[str, str]
    hash_parts: dict[str, bytes]


class ConfigLoader:
    def __init__(self, settings: Settings, tool_registry: dict[str, Any]):
        self.settings = settings
        self.tool_registry = tool_registry

    def load(self, user_id: str, agent_id: str) -> AgentConfigBundle:
        user_dir = self.settings.USERS_DIR / user_id
        agent_dir = user_dir / "agents" / agent_id
        main_path = agent_dir / "main_config.yaml"
        subagents_path = agent_dir / "subagents_config.yaml"

        main_bytes = self._read_required_file(main_path, "main_config.yaml")
        subagents_bytes = self._read_required_file(subagents_path, "subagents_config.yaml")

        main_cfg = self._load_yaml(main_bytes, "main_config.yaml")
        sub_cfg = self._load_yaml(subagents_bytes, "subagents_config.yaml")
        self._validate_schema(main_cfg, sub_cfg)
        workspace_path = self._resolve_workspace_path(
            user_dir=user_dir,
            workspace_value=main_cfg.get("workspace_path"),
        )
        main_cfg["workspace_path"] = str(workspace_path)
        self._validate_tools(main_cfg, sub_cfg)

        hash_parts = {
            "main_config.yaml": main_bytes,
            "subagents_config.yaml": subagents_bytes,
            "workspace_path": str(workspace_path).encode("utf-8"),
        }

        prompts_dir = agent_dir / "prompts"
        prompt_overrides = main_cfg.get("prompts", {})
        if prompt_overrides is None:
            prompt_overrides = {}
        if not isinstance(prompt_overrides, dict):
            raise ConfigValidationError("`prompts` in main_config.yaml must be a dictionary.")

        prompt_cache: dict[str, str] = {}

        def resolve_prompt_key(prompt_key: str) -> str:
            if prompt_key not in prompt_cache:
                prompt_cache[prompt_key] = self._resolve_prompt_by_key(
                    prompt_key=prompt_key,
                    prompt_overrides=prompt_overrides,
                    prompts_dir=prompts_dir,
                    hash_parts=hash_parts,
                )
            return prompt_cache[prompt_key]

        if "system_prompt" in main_cfg:
            main_prompt = self._resolve_prompt_value(
                value=main_cfg["system_prompt"],
                prompts_dir=prompts_dir,
                hash_parts=hash_parts,
                source="main.system_prompt",
            )
        else:
            main_prompt_key = str(main_cfg.get("system_prompt_key", "MAIN_PROMPT"))
            main_prompt = resolve_prompt_key(main_prompt_key)

        subagent_prompts: dict[str, str] = {}
        for subagent in sub_cfg["subagents"]:
            subagent_name = str(subagent["name"])
            if "system_prompt" in subagent:
                sub_prompt = self._resolve_prompt_value(
                    value=subagent["system_prompt"],
                    prompts_dir=prompts_dir,
                    hash_parts=hash_parts,
                    source=f"subagent:{subagent_name}.system_prompt",
                )
            else:
                key = subagent.get("system_prompt_key")
                if not key:
                    raise ConfigValidationError(
                        f"Subagent '{subagent_name}' must define system_prompt or system_prompt_key."
                    )
                sub_prompt = resolve_prompt_key(str(key))
            subagent_prompts[subagent_name] = sub_prompt

        return AgentConfigBundle(
            user_id=user_id,
            agent_id=agent_id,
            agent_dir=agent_dir,
            workspace_path=workspace_path,
            main_config=main_cfg,
            subagents_config=sub_cfg,
            main_prompt=main_prompt,
            subagent_prompts=subagent_prompts,
            hash_parts=hash_parts,
        )

    @staticmethod
    def _read_required_file(path: Path, label: str) -> bytes:
        if not path.exists():
            raise ConfigNotFoundError(f"Missing required config file: {label} ({path})")
        return path.read_bytes()

    @staticmethod
    def _load_yaml(raw_bytes: bytes, label: str) -> dict[str, Any]:
        try:
            loaded = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        except Exception as exc:
            raise ConfigValidationError(f"Invalid YAML in {label}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigValidationError(f"{label} must contain a YAML object.")
        return loaded

    def _validate_schema(self, main_cfg: dict[str, Any], sub_cfg: dict[str, Any]) -> None:
        tools = main_cfg.get("tools", [])
        if not isinstance(tools, list):
            raise ConfigValidationError("`tools` in main_config.yaml must be a list.")

        workspace_path = main_cfg.get("workspace_path")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise ConfigValidationError("`workspace_path` in main_config.yaml must be a non-empty string.")

        subagents = sub_cfg.get("subagents")
        if not isinstance(subagents, list):
            raise ConfigValidationError("`subagents` in subagents_config.yaml must be a list.")

        for item in subagents:
            if not isinstance(item, dict):
                raise ConfigValidationError("Each subagent entry must be a YAML object.")
            if "name" not in item:
                raise ConfigValidationError("Each subagent entry must include `name`.")
            if "tools" in item and not isinstance(item["tools"], list):
                raise ConfigValidationError(f"Subagent '{item['name']}' has invalid `tools` list.")

    def _validate_tools(self, main_cfg: dict[str, Any], sub_cfg: dict[str, Any]) -> None:
        known = set(self.tool_registry.keys())
        requested: set[str] = set()

        for tool_name in main_cfg.get("tools", []):
            requested.add(str(tool_name))

        for subagent in sub_cfg["subagents"]:
            for tool_name in subagent.get("tools", []):
                requested.add(str(tool_name))

        missing = sorted(requested - known)
        if missing:
            raise ToolResolutionError(f"Tools not registered: {', '.join(missing)}")

    def _resolve_prompt_by_key(
        self,
        *,
        prompt_key: str,
        prompt_overrides: dict[str, Any],
        prompts_dir: Path,
        hash_parts: dict[str, bytes],
    ) -> str:
        prompt_value = prompt_overrides.get(prompt_key, self._default_prompt_filename(prompt_key))
        return self._resolve_prompt_value(
            value=prompt_value,
            prompts_dir=prompts_dir,
            hash_parts=hash_parts,
            source=f"prompt_key:{prompt_key}",
        )

    def _resolve_prompt_value(
        self,
        *,
        value: Any,
        prompts_dir: Path,
        hash_parts: dict[str, bytes],
        source: str,
    ) -> str:
        if not isinstance(value, str):
            raise ConfigValidationError(f"Prompt value for {source} must be a string.")

        if value.endswith(".md"):
            path = self._safe_prompt_path(prompts_dir, value)
            if not path.exists():
                raise ConfigNotFoundError(f"Prompt file not found for {source}: {path}")
            raw = path.read_bytes()
            hash_parts[f"prompt_file:{path.name}:{source}"] = raw
            return raw.decode("utf-8")

        encoded = value.encode("utf-8")
        hash_parts[f"prompt_literal:{source}"] = encoded
        return value

    @staticmethod
    def _default_prompt_filename(prompt_key: str) -> str:
        if prompt_key == "MAIN_PROMPT":
            return "main_prompt.md"
        if prompt_key.startswith("PROMPT_"):
            suffix = prompt_key.removeprefix("PROMPT_").lower()
            return f"prompt_{suffix}.md"
        return f"{prompt_key.lower()}.md"

    @staticmethod
    def _safe_prompt_path(prompts_dir: Path, filename: str) -> Path:
        prompts_root = prompts_dir.resolve()
        path = (prompts_root / filename).resolve()
        if path != prompts_root and prompts_root not in path.parents:
            raise ConfigValidationError(f"Prompt path escapes prompts dir: {filename}")
        return path

    @staticmethod
    def _resolve_workspace_path(*, user_dir: Path, workspace_value: Any) -> Path:
        if not isinstance(workspace_value, str) or not workspace_value.strip():
            raise ConfigValidationError("`workspace_path` in main_config.yaml must be a non-empty string.")

        raw = workspace_value.strip()
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (user_dir / candidate).resolve()

        user_root = user_dir.resolve()
        if resolved != user_root and user_root not in resolved.parents:
            raise ConfigValidationError("`workspace_path` must be located inside the user directory.")

        return resolved
