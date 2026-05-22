from __future__ import annotations

from typing import Any

from buglens.agent import LangGraphRunner
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
                                    "name": "arms_get_related_api",
                                    "arguments": '{"trace_id":"t1","app":"web"}',
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
        assert tool_call["function"]["name"] == "arms_get_related_api"
        return tool_call["id"], '{"related_api":{"url":"https://api.example.local"}}'

    monkeypatch.setattr(runner, "_call_litellm_json", fake_call_litellm_json)
    monkeypatch.setattr(runner, "_execute_tool_call", fake_execute_tool_call)

    result = await runner.run(InvokeRequest(task="diagnose"), config)

    assert result.output == "final answer"
    assert len(calls) == 2
    assert any(message.get("role") == "tool" for message in calls[1])


def test_langgraph_tool_registry_contains_gitlab_list_projects() -> None:
    runner = LangGraphRunner()
    config = SubAgentConfig.model_validate({"enable_mcp_tools": True})
    tools = runner._build_mcp_tools(config)
    assert any(tool.name == "gitlab_list_projects" for tool in tools)


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
