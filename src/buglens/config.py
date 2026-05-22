from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    runner: Literal["langgraph"] = "langgraph"
    llm_provider: Literal["litellm"] = "litellm"
    enable_mcp_tools: bool = True
    mcp_tool_call_max_steps: int = Field(default=6, ge=1, le=30)
    model: str = "deepseek-v3.2"
    system_prompt: str | None = None
    max_turns: int = Field(default=6, ge=1, le=100)
    timeout_seconds: int = Field(default=180, ge=10, le=3600)
    first_packet_timeout_seconds: int = Field(default=30, ge=1, le=600)
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = (
        "bypassPermissions"
    )
    allowed_tools: list[str] = Field(default_factory=lambda: ["Read", "Write", "Edit", "Bash"])
    mcp_servers: dict[str, Any] = Field(default_factory=dict)

    anthropic_auth_token: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    anthropic_model: str | None = None

    alibaba_access_key_id: str | None = None
    alibaba_access_key_secret: str | None = None
    alibaba_security_token: str | None = None
    alibaba_region_id: str | None = None
    arms_endpoint: str | None = None
    sls_endpoint: str | None = None
    rum_sls_project: str | None = None
    rum_sls_logstore: str | None = None
    monitoring_max_retries: int = Field(default=2, ge=0, le=10)
    monitoring_base_backoff_seconds: float = Field(default=0.25, ge=0.01, le=10.0)
    monitoring_max_backoff_seconds: float = Field(default=5.0, ge=0.1, le=120.0)
    monitoring_max_concurrency: int = Field(default=4, ge=1, le=64)

    cwd: Path = Field(default_factory=Path.cwd)
    mock_response: str | None = None

    @field_validator("runner", mode="before")
    @classmethod
    def _reject_legacy_runner(cls, value: object) -> object:
        if value == "claude_sdk":
            raise ValueError(
                "BUGLENS_RUNNER=claude_sdk is no longer supported; use BUGLENS_RUNNER=langgraph"
            )
        return value

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

    def has_monitoring_credentials(self) -> bool:
        return bool(
            self.alibaba_access_key_id
            and self.alibaba_access_key_secret
            and self.alibaba_region_id
        )
