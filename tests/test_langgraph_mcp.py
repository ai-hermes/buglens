from __future__ import annotations

import json
from typing import Any

from buglens.agent import LangGraphRunner, MCPTool
from buglens.config import SubAgentConfig
from buglens.models import InvokeRequest


async def test_langgraph_runner_tool_call_loop(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "mcp_tool_call_max_steps": 3,
            "max_turns": 3,
        }
    )

    calls: list[list[dict[str, Any]]] = []
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "gitlab_list_projects",
                                    "arguments": '{"search":"buglens"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "final answer"}}],
            "usage": {"prompt_tokens": 2},
        },
    ]

    async def fake_call_litellm_json(messages, _config, _tools):
        calls.append(list(messages))
        return responses.pop(0)

    async def fake_execute_tool_call(_tool_map, tool_call):
        assert tool_call["function"]["name"] == "gitlab_list_projects"
        return tool_call["id"], '{"projects":[{"id":1,"name":"buglens"}]}'

    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)
    monkeypatch.setattr(runner, "_execute_tool_call", fake_execute_tool_call)

    result = await runner.run(InvokeRequest(task="diagnose gitlab project"), config)

    assert result.output == "final answer"
    assert len(calls) == 2
    assert any(message.get("role") == "tool" for message in calls[1])


async def test_langgraph_runner_returns_fallback_when_max_steps_reached(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "mcp_tool_call_max_steps": 1,
            "max_turns": 10,
        }
    )

    async def fake_call_litellm_json(_messages, _config, _tools):
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "gitlab_list_projects",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1},
        }

    async def fake_execute_tool_call(_tool_map, tool_call):
        return tool_call["id"], '{"ok":true}'

    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)
    monkeypatch.setattr(runner, "_execute_tool_call", fake_execute_tool_call)

    result = await runner.run(InvokeRequest(task="diagnose gitlab project"), config)

    assert "max tool-call steps" in result.output


def test_langgraph_tool_registry_contains_gitlab_list_projects() -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate({"enable_mcp_tools": True})
    tools = runner._build_mcp_tools(config)
    assert any(tool.name == "gitlab_list_projects" for tool in tools)


def test_langgraph_monitoring_registry_requires_credentials() -> None:
    runner = LangGraphRunner()
    tools = runner._build_monitoring_mcp_tools(
        SubAgentConfig.model_validate(
            {
                "enable_mcp_tools": True,
                "alibaba_access_key_id": None,
                "alibaba_access_key_secret": None,
                "alibaba_region_id": None,
            }
        )
    )
    assert tools == []


def test_langgraph_monitoring_registry_contains_rum_tools() -> None:
    runner = LangGraphRunner()
    tools = runner._build_monitoring_mcp_tools(
        SubAgentConfig.model_validate(
            {
                "enable_mcp_tools": True,
                "alibaba_access_key_id": "ak",
                "alibaba_access_key_secret": "sk",
                "alibaba_region_id": "cn-hangzhou",
            }
        )
    )
    names = [tool.name for tool in tools]
    assert "arms_rum_list_apps" in names
    assert "arms_get_error_detail" in names
    assert "arms_rum_search_errors" in names
    assert "sls_search_logs" not in names
    assert "sls_list_projects" not in names
    assert "arms_search_traces" not in names
    assert "arms_list_insights_events" not in names
    rum_apps_tool = next(tool for tool in tools if tool.name == "arms_rum_list_apps")
    properties = rum_apps_tool.parameters.get("properties", {})
    assert "page_token" in properties
    assert "page_size" in properties
    assert "extra_params" not in properties


async def test_langgraph_runner_stream_fallback_no_duplicate(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "enable_mcp_tools": False,
        }
    )

    async def fake_call_litellm_json(_messages, _config, _tools):
        return {"choices": [{"message": {"content": ""}}], "usage": {"prompt_tokens": 1}}

    async def fake_call_litellm_stream(_messages, _config, on_text):
        on_text("streamed answer")
        return "streamed answer", {"completion_tokens": 4}

    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)
    monkeypatch.setattr(runner, "_call_litellm_stream", fake_call_litellm_stream)

    chunks: list[str] = []
    result = await runner.run(InvokeRequest(task="ping"), config, on_text=chunks.append)

    assert result.output == "streamed answer"
    assert chunks == ["streamed answer"]


async def test_langgraph_runner_skips_gitlab_tools_for_non_gitlab_task(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "enable_mcp_tools": True,
            "alibaba_access_key_id": None,
            "alibaba_access_key_secret": None,
            "alibaba_region_id": None,
        }
    )
    seen_tool_counts: list[int] = []

    async def fake_call_litellm_json(_messages, _config, tools):
        seen_tool_counts.append(len(tools))
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1}}

    async def fake_discover_external(_config):
        return []

    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)
    monkeypatch.setattr(runner, "_discover_external_mcp_tools", fake_discover_external)

    result = await runner.run(InvokeRequest(task="分析 RUM 报错"), config)

    assert result.output == "ok"
    assert seen_tool_counts == [0]


async def test_langgraph_runner_includes_external_mcp_tools_for_non_gitlab_task(
    monkeypatch,
) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "enable_mcp_tools": True,
            "mcp_servers": {"ext_observability": {"url": "http://localhost:8080"}},
            "alibaba_access_key_id": None,
            "alibaba_access_key_secret": None,
            "alibaba_region_id": None,
        }
    )

    async def external_handler(**arguments: Any) -> dict[str, Any]:
        return {"source": "external", "arguments": arguments}

    async def fake_discover_external(_config: SubAgentConfig) -> list[MCPTool]:
        return [
            MCPTool(
                name="ext_rum_tool",
                description="external tool",
                parameters={"type": "object", "properties": {"app": {"type": "string"}}},
                handler=external_handler,
            )
        ]

    seen_tools: list[list[str]] = []
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "ext-1",
                                "type": "function",
                                "function": {
                                    "name": "ext_rum_tool",
                                    "arguments": '{"app":"monitor-example"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "final answer"}}],
            "usage": {"prompt_tokens": 2},
        },
    ]

    async def fake_call_litellm_json(messages, _config, tools):
        seen_tools.append([tool.name for tool in tools])
        return responses.pop(0)

    monkeypatch.setattr(runner, "_discover_external_mcp_tools", fake_discover_external)
    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)

    result = await runner.run(InvokeRequest(task="分析 RUM 报错"), config)

    assert result.output == "final answer"
    assert seen_tools and seen_tools[0] == ["ext_rum_tool"]


async def test_langgraph_runner_keeps_monitoring_tools_for_non_gitlab_task(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "enable_mcp_tools": True,
        }
    )

    async def fake_discover_external(_config: SubAgentConfig) -> list[MCPTool]:
        return []

    seen_tools: list[list[str]] = []

    async def fake_call_litellm_json(_messages, _config, tools):
        seen_tools.append([tool.name for tool in tools])
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1}}

    def fake_monitoring_tools(_config: SubAgentConfig) -> list[MCPTool]:
        return [
            MCPTool(
                name="arms_get_error_detail",
                description="monitoring",
                parameters={"type": "object", "properties": {}},
                handler=lambda **_kwargs: {"success": True},
            )
        ]

    monkeypatch.setattr(runner, "_discover_external_mcp_tools", fake_discover_external)
    monkeypatch.setattr(runner, "_build_monitoring_mcp_tools", fake_monitoring_tools)
    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)

    result = await runner.run(InvokeRequest(task="分析 RUM 报错"), config)

    assert result.output == "ok"
    assert seen_tools == [["arms_get_error_detail"]]


async def test_langgraph_runner_external_tool_overrides_builtin_same_name(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "runner": "langgraph",
            "anthropic_base_url": "https://example.local",
            "anthropic_api_key": "token",
            "anthropic_model": "deepseek-v3.2",
            "enable_mcp_tools": True,
            "mcp_servers": {"ext": {"url": "http://localhost:8080"}},
        }
    )

    async def external_gitlab_projects(**_arguments: Any) -> dict[str, Any]:
        return {"source": "external"}

    async def fake_discover_external(_config: SubAgentConfig) -> list[MCPTool]:
        return [
            MCPTool(
                name="gitlab_list_projects",
                description="external override",
                parameters={"type": "object", "properties": {}},
                handler=external_gitlab_projects,
            )
        ]

    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "ext-override-1",
                                "type": "function",
                                "function": {
                                    "name": "gitlab_list_projects",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "done"}}],
            "usage": {"prompt_tokens": 2},
        },
    ]

    async def fake_call_litellm_json(messages, _config, _tools):
        if len(responses) == 1:
            tool_messages = [message for message in messages if message.get("role") == "tool"]
            assert tool_messages, "expected tool message from previous tool call"
            payload = json.loads(tool_messages[-1]["content"])
            assert payload["source"] == "external"
        return responses.pop(0)

    monkeypatch.setattr(runner, "_discover_external_mcp_tools", fake_discover_external)
    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)

    result = await runner.run(InvokeRequest(task="diagnose gitlab project"), config)

    assert result.output == "done"


async def test_langgraph_external_mcp_discovery_fail_open(monkeypatch) -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate(
        {
            "mcp_servers": {
                "bad_server": {"url": "http://localhost:8081"},
                "good_server": {"url": "http://localhost:8080"},
            }
        }
    )

    async def fake_discover_from_url(server_name: str, server_url: str) -> list[MCPTool]:
        if server_name == "bad_server":
            raise RuntimeError("unreachable")
        return [
            MCPTool(
                name="good_tool",
                description=f"from {server_url}",
                parameters={"type": "object", "properties": {}},
                handler=lambda **_kwargs: {"ok": True},
            )
        ]

    monkeypatch.setattr(
        runner,
        "_discover_external_mcp_tools_from_url",
        fake_discover_from_url,
    )

    tools = await runner._discover_external_mcp_tools(config)

    assert "good_tool" in [tool.name for tool in tools]


def test_langgraph_summarize_exception_unwraps_exception_group() -> None:
    runner = LangGraphRunner()
    grouped = ExceptionGroup(
        "wrapper",
        [RuntimeError("connect refused"), ValueError("bad response")],
    )
    summary = runner._summarize_exception(grouped)
    assert "RuntimeError: connect refused" in summary
    assert "ValueError: bad response" in summary
