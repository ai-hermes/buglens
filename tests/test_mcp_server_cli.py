from __future__ import annotations

import types

from buglens import mcp_server


class _DummySettings:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 8000
        self.streamable_http_path = "/mcp"
        self.transport_security = object()


class _DummyMCP:
    def __init__(self) -> None:
        self.settings = _DummySettings()
        self.called_transport: str | None = None

    def run(self, transport: str = "stdio") -> None:
        self.called_transport = transport


def test_mcp_server_main_streamable_http(monkeypatch) -> None:
    dummy = _DummyMCP()
    monkeypatch.setattr(mcp_server, "mcp", dummy)
    monkeypatch.setattr(mcp_server, "bootstrap_process_env_from_dotenv", lambda: None)
    monkeypatch.setattr(mcp_server, "_registered_tool_names", lambda: ["gitlab_list_projects"])
    monkeypatch.setattr(
        mcp_server,
        "_configure_logging",
        lambda _: None,
    )
    monkeypatch.setattr(
        mcp_server,
        "logger",
        types.SimpleNamespace(
            info=lambda *_, **__: None,
            debug=lambda *_, **__: None,
            warning=lambda *_, **__: None,
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "buglens-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "18000",
            "--streamable-path",
            "/custom-mcp",
        ],
    )

    mcp_server.main()

    assert dummy.called_transport == "streamable-http"
    assert dummy.settings.host == "0.0.0.0"
    assert dummy.settings.port == 18000
    assert dummy.settings.streamable_http_path == "/custom-mcp"
    assert dummy.settings.transport_security is not None


def test_mcp_server_main_stdio_default(monkeypatch) -> None:
    dummy = _DummyMCP()
    monkeypatch.setattr(mcp_server, "mcp", dummy)
    monkeypatch.setattr(mcp_server, "bootstrap_process_env_from_dotenv", lambda: None)
    monkeypatch.setattr(mcp_server, "_registered_tool_names", lambda: ["gitlab_list_projects"])
    monkeypatch.setattr(
        mcp_server,
        "_configure_logging",
        lambda _: None,
    )
    monkeypatch.setattr(
        mcp_server,
        "logger",
        types.SimpleNamespace(
            info=lambda *_, **__: None,
            debug=lambda *_, **__: None,
            warning=lambda *_, **__: None,
        ),
    )
    monkeypatch.setattr("sys.argv", ["buglens-mcp"])

    mcp_server.main()

    assert dummy.called_transport == "stdio"
    assert dummy.settings.host == "127.0.0.1"
    assert dummy.settings.port == 8000
    assert dummy.settings.streamable_http_path == "/mcp"


def test_mcp_server_non_local_disables_dns_rebinding_by_default(monkeypatch) -> None:
    dummy = _DummyMCP()
    monkeypatch.setattr(mcp_server, "mcp", dummy)
    monkeypatch.setattr(mcp_server, "bootstrap_process_env_from_dotenv", lambda: None)
    monkeypatch.setattr(mcp_server, "_registered_tool_names", lambda: ["gitlab_list_projects"])
    monkeypatch.setattr(
        mcp_server,
        "_configure_logging",
        lambda _: None,
    )
    monkeypatch.setattr(
        mcp_server,
        "logger",
        types.SimpleNamespace(
            info=lambda *_, **__: None,
            debug=lambda *_, **__: None,
            warning=lambda *_, **__: None,
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "buglens-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "18002",
        ],
    )

    mcp_server.main()

    assert dummy.called_transport == "streamable-http"
    assert dummy.settings.transport_security.enable_dns_rebinding_protection is False


def test_registered_tool_names_are_unprefixed_for_mcp_scoped_naming() -> None:
    names = mcp_server._registered_tool_names()
    assert "gitlab_list_projects" in names
    assert "arms_rum_list_apps" in names
    assert "buglens_gitlab_list_projects" not in names
