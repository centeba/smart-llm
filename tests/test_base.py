import pytest
from pydantic import BaseModel

from smart_llm.base import AbstractAgent, ActionTool, LLMResponse, Tool


class MockTool(Tool):
    def run(self, input_text: str, **kwargs) -> str:
        return f"processed_{input_text}"


class MockAgent(AbstractAgent):
    async def analyze(self, input_text: str, context: None = None) -> LLMResponse:
        processed = self._apply_tools(input_text)
        return LLMResponse(data={"result": processed}, provider="mock")


def test_llm_response_validation():
    """Verify LLMResponse Pydantic model works as expected."""
    response = LLMResponse(
        data={"foo": "bar"}, provider="test-provider", metadata={"tokens": 42}
    )
    assert response.data["foo"] == "bar"
    assert response.provider == "test-provider"
    assert response.metadata["tokens"] == 42


def test_abstract_agent_tool_sequence():
    """Verify tools are applied in order."""
    tool1 = MockTool()
    tool2 = MockTool()
    agent = MockAgent(
        name="test_agent", system_prompt="test prompt", tools=[tool1, tool2]
    )

    result = agent._apply_tools("input")
    # input -> processed_input -> processed_processed_input
    assert result == "processed_processed_input"


@pytest.mark.asyncio
async def test_mock_agent_analyze():
    """Verify analyze method in a concrete implementation of AbstractAgent."""
    agent = MockAgent(name="test", system_prompt="test", tools=[MockTool()])
    response = await agent.analyze("hello")
    assert response.data["result"] == "processed_hello"
    assert response.provider == "mock"


# ── ActionTool ────────────────────────────────────────────────────────────────


class _EmptyArgs(BaseModel):
    pass


class _ReadOnlyTool(ActionTool):
    args_model = _EmptyArgs
    read_only = True

    async def run_action(self, args, *, db_session=None):
        return {"ok": True}


class _WriteTool(ActionTool):
    args_model = _EmptyArgs
    # read_only defaults to False

    async def run_action(self, args, *, db_session=None):
        return {"written": True}


def test_action_tool_read_only_default_is_false():
    assert _WriteTool.read_only is False
    assert _WriteTool().read_only is False


def test_action_tool_read_only_can_be_set():
    assert _ReadOnlyTool.read_only is True
    assert _ReadOnlyTool().read_only is True


@pytest.mark.asyncio
async def test_action_tool_run_action():
    tool = _ReadOnlyTool()
    result = await tool.run_action(_EmptyArgs(), db_session=None)
    assert result == {"ok": True}


def test_action_tool_has_args_model():
    tool = _WriteTool()
    assert tool.args_model is _EmptyArgs
