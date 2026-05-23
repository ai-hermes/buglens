from buglens.config import SubAgentConfig


def test_config_loads_from_dotenv(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "BUGLENS_ANTHROPIC_AUTH_TOKEN=test-token",
                "BUGLENS_ANTHROPIC_BASE_URL=https://example.local",
                "BUGLENS_ANTHROPIC_MODEL=test-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BUGLENS_ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("BUGLENS_ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("BUGLENS_ANTHROPIC_MODEL", raising=False)

    config = SubAgentConfig()

    assert config.anthropic_auth_token == "test-token"
    assert config.anthropic_base_url == "https://example.local"
    assert config.anthropic_model == "test-model"


def test_config_litellm_resolution() -> None:
    config = SubAgentConfig.model_validate(
        {
            "anthropic_base_url": "https://example.local",
            "anthropic_auth_token": "token-auth",
            "anthropic_api_key": None,
            "anthropic_model": "deepseek-v3.2",
            "model": "fallback-model",
        }
    )
    assert config.resolve_litellm_url() == "https://example.local/chat/completions"
    assert config.resolve_api_key() == "token-auth"
    assert config.resolve_model() == "deepseek-v3.2"


def test_config_defaults_for_mcp_tools() -> None:
    config = SubAgentConfig()
    assert config.enable_mcp_tools is True
    assert config.mcp_tool_call_max_steps == 6
    assert config.show_tool_call_trace is False
    assert config.monitoring_max_retries == 2
    assert config.monitoring_max_concurrency == 4


def test_config_parses_mcp_servers_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "BUGLENS_MCP_SERVERS",
        '{"alibaba_cloud_observability":{"url":"http://localhost:8080"}}',
    )
    config = SubAgentConfig()
    assert config.mcp_servers == {
        "alibaba_cloud_observability": {"url": "http://localhost:8080"}
    }


def test_config_monitoring_credentials_resolution() -> None:
    config = SubAgentConfig.model_validate(
        {
            "alibaba_access_key_id": "ak",
            "alibaba_access_key_secret": "sk",
            "alibaba_region_id": "cn-hangzhou",
        }
    )
    assert config.has_monitoring_credentials() is True


def test_config_rejects_legacy_claude_sdk_runner() -> None:
    try:
        SubAgentConfig.model_validate({"runner": "claude_sdk"})
    except Exception as exc:  # noqa: BLE001
        assert "no longer supported" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected runner=claude_sdk to be rejected")
