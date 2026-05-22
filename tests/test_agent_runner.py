import pytest

from buglens.agent import LangGraphRunner, SubAgent
from buglens.config import SubAgentConfig


def test_default_runner_is_langgraph() -> None:
    agent = SubAgent(config=SubAgentConfig())
    assert isinstance(agent.runner, LangGraphRunner)


def test_claude_sdk_runner_is_rejected() -> None:
    with pytest.raises(ValueError, match="no longer supported"):
        SubAgentConfig.model_validate({"runner": "claude_sdk"})
