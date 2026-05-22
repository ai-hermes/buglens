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
