from buglens.agent import ClaudeCodeSDKRunner, LangGraphRunner, SubAgent
from buglens.config import SubAgentConfig


def test_default_runner_is_langgraph() -> None:
    agent = SubAgent(config=SubAgentConfig())
    assert isinstance(agent.runner, LangGraphRunner)


def test_can_select_claude_sdk_runner() -> None:
    agent = SubAgent(config=SubAgentConfig.model_validate({"runner": "claude_sdk"}))
    assert isinstance(agent.runner, ClaudeCodeSDKRunner)
