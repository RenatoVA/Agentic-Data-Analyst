from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
import httpx

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import AzureChatOpenAI
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import Settings
from app.services.config_loader import AgentConfigBundle, ConfigLoader
from app.services.tool_registry import build_tool_registry
from app.utils.files import ensure_directory
from app.utils.hashing import sha256_from_named_bytes
from app.utils.url_signing import generate_signed_url


@dataclass(slots=True)
class CachedAgent:
    config_hash: str
    agent: Any
    created_at: datetime
    last_used_at: datetime


CONVERSATION_MODE_ON = "ACTIVADO"
CONVERSATION_MODE_OFF = "DESACTIVADO"
VALID_CONVERSATION_MODES = {CONVERSATION_MODE_ON, CONVERSATION_MODE_OFF}


class AgentFactory:
    def __init__(self, settings: Settings, tool_registry: dict[str, Any]):
        self.settings = settings
        self.tool_registry = tool_registry
        self.config_loader = ConfigLoader(settings=settings, tool_registry=tool_registry)
        self._cache: dict[tuple[str, str, str], CachedAgent] = {}
        self._checkpointers: dict[tuple[str, str], MemorySaver] = {}
        self._locks: dict[tuple[str, str, str], Lock] = {}
        self._locks_guard = Lock()

    def get_or_create_agent(
        self,
        *,
        user_id: str,
        agent_id: str,
        conversation_mode: str = CONVERSATION_MODE_OFF,
    ) -> Any:
        mode = self._normalize_conversation_mode(conversation_mode)
        key = (user_id, agent_id, mode)
        lock = self._get_lock(key)
        with lock:
            bundle = self.config_loader.load(user_id=user_id, agent_id=agent_id)
            config_hash = sha256_from_named_bytes(bundle.hash_parts)
            cached = self._cache.get(key)
            now = datetime.now(timezone.utc)

            if cached and cached.config_hash == config_hash:
                cached.last_used_at = now
                return cached.agent

            agent = self._build_agent(bundle, conversation_mode=mode)
            self._cache[key] = CachedAgent(
                config_hash=config_hash,
                agent=agent,
                created_at=now,
                last_used_at=now,
            )
            return agent

    def invalidate(self, *, user_id: str, agent_id: str, conversation_mode: str | None = None) -> None:
        with self._locks_guard:
            if conversation_mode is None:
                to_remove = [key for key in self._cache.keys() if key[0] == user_id and key[1] == agent_id]
                for key in to_remove:
                    self._cache.pop(key, None)
                self._checkpointers.pop((user_id, agent_id), None)
                return

            mode = self._normalize_conversation_mode(conversation_mode)
            key = (user_id, agent_id, mode)
            self._cache.pop(key, None)

    def cache_snapshot(self) -> dict[str, dict[str, str]]:
        snapshot: dict[str, dict[str, str]] = {}
        for (user_id, agent_id, mode), cached in self._cache.items():
            snapshot[f"{user_id}/{agent_id}/{mode}"] = {
                "config_hash": cached.config_hash,
                "created_at": cached.created_at.isoformat(),
                "last_used_at": cached.last_used_at.isoformat(),
            }
        return snapshot

    def _build_agent(self, bundle: AgentConfigBundle, *, conversation_mode: str) -> Any:

        if self.settings.PROVIDER == "azure":
            model = AzureChatOpenAI(
                azure_deployment=self.settings.AZURE_DEPLOYMENT,
                #temperature=self.settings.CHAT_TEMPERATURE,
                api_key=self.settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=self.settings.AZURE_OPENAI_ENDPOINT,
                api_version=self.settings.AZURE_API_VERSION,
                http_async_client=httpx.AsyncClient(verify=False),
                streaming=True,
            )
        else:
            model = ChatOpenAI(
                model=self.settings.OPENROUTER_MODEL_NAME,
                temperature=self.settings.CHAT_TEMPERATURE,
                api_key=self.settings.OPENROUTER_API_KEY,
                base_url=self.settings.OPENROUTER_BASE_URL,
                http_async_client=httpx.AsyncClient(verify=False),
                cache=False,
            )

        def _url_signer(file_path: str) -> str:
            return generate_signed_url(
                secret=self.settings.FILE_SIGNING_SECRET,
                user_id=bundle.user_id,
                file_path=file_path,
            )

        workspace_tools = build_tool_registry(
            bundle.workspace_path,
            user_id=bundle.user_id,
            url_signer=_url_signer,
        )
        subagents_list = []
        interrupt_on: dict[str, bool] = {}

        for item in bundle.subagents_config["subagents"]:
            sub_name = str(item["name"])
            sub_tools = [workspace_tools[str(tool_name)] for tool_name in item.get("tools", [])]
            sub_interrupt_on: dict[str, bool] = {}
            for task_name in item.get("interrupt_on", []):
                sub_interrupt_on[str(task_name)] = True

            subagents_list.append(
                {
                    "name": sub_name,
                    "description": str(item.get("description", "")),
                    "system_prompt": bundle.subagent_prompts.get(sub_name, ""),
                    "tools": sub_tools,
                    "interrupt_on": sub_interrupt_on
                }
            )
        for task_name in bundle.main_config.get("interrupt_on", []):
            interrupt_on[str(task_name)] = True

            

        main_tools = [workspace_tools[str(tool_name)] for tool_name in bundle.main_config.get("tools", [])]
        main_prompt = self._render_main_prompt(bundle.main_prompt, conversation_mode=conversation_mode)
        ensure_directory(bundle.workspace_path)

        return create_deep_agent(
            model=model,
            memory=["/AGENTS.md"],
            backend=FilesystemBackend(root_dir=str(bundle.workspace_path), virtual_mode=True),
            subagents=subagents_list,
            system_prompt=main_prompt,
            checkpointer=self._get_checkpointer(bundle.user_id, bundle.agent_id),
            tools=main_tools,
            interrupt_on=interrupt_on or None,
        )

    @staticmethod
    def _normalize_conversation_mode(conversation_mode: str) -> str:
        normalized = str(conversation_mode).strip().upper()
        if normalized not in VALID_CONVERSATION_MODES:
            return CONVERSATION_MODE_OFF
        return normalized

    @staticmethod
    def _render_main_prompt(prompt_template: str, *, conversation_mode: str) -> str:
        placeholder = "{modo_conversacion}"
        if placeholder in prompt_template:
            return prompt_template.replace(placeholder, conversation_mode)
        return f'{prompt_template}\n\nMODO_CONVERSACION = "{conversation_mode}"'

    def _get_checkpointer(self, user_id: str, agent_id: str) -> MemorySaver:
        key = (user_id, agent_id)
        if key not in self._checkpointers:
            self._checkpointers[key] = MemorySaver()
        return self._checkpointers[key]

    def _get_lock(self, key: tuple[str, str, str]) -> Lock:
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = Lock()
            return self._locks[key]
