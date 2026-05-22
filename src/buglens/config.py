from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def bootstrap_process_env_from_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from .env into process env if keys are absent.

    This complements Pydantic settings loading and ensures non-BUGLENS variables
    (e.g. GITLAB_URL/GITLAB_TOKEN) are visible to integration modules that read
    os.environ directly.
    """
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


class SubAgentConfig(BaseSettings):
    """Runtime configuration for the buglens sub-agent."""

    model_config = SettingsConfigDict(
        env_prefix="BUGLENS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    name: str = "buglens"
    version: str = "0.1.0"
    runner: Literal["langgraph", "claude_sdk"] = "langgraph"
    llm_provider: Literal["litellm"] = "litellm"
    enable_mcp_tools: bool = True
    mcp_tool_call_max_steps: int = Field(default=6, ge=1, le=30)
    model: str = "claude-sonnet-4-20250514"
    pass_model_to_cli: bool = False
    system_prompt: str | None = None
    max_turns: int = Field(default=6, ge=1, le=30)
    timeout_seconds: int = Field(default=180, ge=10, le=3600)
    first_packet_timeout_seconds: int = Field(default=30, ge=1, le=600)
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = (
        "bypassPermissions"
    )
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Write", "Edit", "Bash"])
    mcp_servers: dict[str, Any] = Field(default_factory=dict)

    disable_telemetry: bool = True
    disable_error_reporting: bool = True
    disable_nonessential_traffic: bool = True
    mcp_timeout_ms: int = Field(default=60000, ge=1000)
    api_timeout_ms: int = Field(default=3000000, ge=1000)

    anthropic_auth_token: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    anthropic_model: str | None = None
    anthropic_default_haiku_model: str | None = None
    anthropic_default_opus_model: str | None = None
    anthropic_default_sonnet_model: str | None = None
    extra_env: dict[str, str] = Field(default_factory=dict)

    cwd: Path = Field(default_factory=Path.cwd)
    mock_response: str | None = None

    def resolve_model(self) -> str:
        return self.anthropic_model or self.model

    def resolve_api_key(self) -> str | None:
        return self.anthropic_api_key or self.anthropic_auth_token

    def resolve_litellm_url(self) -> str | None:
        if not self.anthropic_base_url:
            return None
        base = self.anthropic_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def build_sdk_env(self) -> dict[str, str]:
        env: dict[str, str] = {
            "DISABLE_TELEMETRY": "1" if self.disable_telemetry else "0",
            "DISABLE_ERROR_REPORTING": "1" if self.disable_error_reporting else "0",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": (
                "1" if self.disable_nonessential_traffic else "0"
            ),
            "MCP_TIMEOUT": str(self.mcp_timeout_ms),
            "API_TIMEOUT_MS": str(self.api_timeout_ms),
        }
        optional_map = {
            "ANTHROPIC_AUTH_TOKEN": self.anthropic_auth_token,
            "ANTHROPIC_API_KEY": self.anthropic_api_key or self.anthropic_auth_token,
            "ANTHROPIC_BASE_URL": self.anthropic_base_url,
            "ANTHROPIC_MODEL": self.anthropic_model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": self.anthropic_default_haiku_model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": self.anthropic_default_opus_model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": self.anthropic_default_sonnet_model,
        }
        for key, value in optional_map.items():
            if value:
                env[key] = value
        env.update(self.extra_env)
        if logger.isEnabledFor(logging.DEBUG):
            redacted_env = {
                key: (
                    "***redacted***"
                    if any(
                        token in key.upper()
                        for token in ("TOKEN", "SECRET", "KEY", "AUTH", "PASSWORD")
                    )
                    else value
                )
                for key, value in env.items()
            }
            logger.debug(
                "build_sdk_env result: %s",
                json.dumps(redacted_env, ensure_ascii=False, sort_keys=True),
            )
        return env
