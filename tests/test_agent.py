from unittest.mock import AsyncMock, patch

import pytest

from smart_llm.agent import Agent
from smart_llm.agent_manager import AgentManager
from smart_llm.base import LLMResponse
from smart_llm.key_manager import KeyManager


@pytest.fixture
def mock_provider_response():
    return {"result": "mocked success"}


@pytest.mark.asyncio
async def test_agent_analyze_success(mock_provider_response):
    """Test Agent.analyze when provider succeeds."""
    # We patch the specific provider used in the agent.
    # Since Agent.__init__ calls _init_provider, we patch the provider classes.
    with patch("smart_llm.agent.GeminiProvider") as MockGemini:
        mock_instance = MockGemini.return_value
        mock_instance.complete = AsyncMock(return_value=mock_provider_response)

        agent = Agent(
            name="test_agent",
            provider_type="gemini",
            system_prompt="sys",
            api_key="key123",
        )

        response = await agent.analyze("hello")

        assert isinstance(response, LLMResponse)
        assert response.data == mock_provider_response
        assert response.provider == "gemini"
        assert response.metadata["agent_name"] == "test_agent"
        mock_instance.complete.assert_called_once()


@pytest.mark.asyncio
async def test_agent_manager_failover(mock_provider_response):
    """Test AgentManager failover when the first agent fails."""
    # Patch GeminiProvider and OpenAIProvider
    with (
        patch("smart_llm.agent.GeminiProvider") as MockGemini,
        patch("smart_llm.agent.OpenAIProvider") as MockOpenAI,
    ):
        # Agent 1 (Gemini) - will fail
        gemini_mock = MockGemini.return_value
        gemini_mock.complete = AsyncMock(side_effect=Exception("Gemini Failed"))

        # Agent 2 (OpenAI) - will succeed
        openai_mock = MockOpenAI.return_value
        openai_mock.complete = AsyncMock(return_value=mock_provider_response)

        agent1 = Agent("a1", "gemini", "sys", "key1")
        agent2 = Agent("a2", "openai", "sys", "key2")

        km = KeyManager()
        km.register_provider("gemini", ["key1"])
        manager = AgentManager(key_manager_instance=km)
        manager.register_agent(agent1)
        manager.register_agent(agent2)

        # This should call a1, catch the exception, then call a2 and succeed.
        response = await manager.analyze("test")

        assert response.provider == "openai"
        assert response.data == mock_provider_response
        assert response.metadata["agent_name"] == "a2"

        # Verify KM rotation was called on failure
        # (Though we didn't mock the internal KM state change specifically
        # for this simple check, we check the logic flow)
        gemini_mock.complete.assert_called_once()
        openai_mock.complete.assert_called_once()


@pytest.mark.asyncio
async def test_agent_manager_all_fail():
    """Test AgentManager when all agents fail."""
    with patch("smart_llm.agent.GeminiProvider") as MockGemini:
        gemini_mock = MockGemini.return_value
        gemini_mock.complete = AsyncMock(side_effect=Exception("Final Failure"))

        agent = Agent("a1", "gemini", "sys", "key1")
        manager = AgentManager()
        manager.register_agent(agent)

        with pytest.raises(Exception) as excinfo:
            await manager.analyze("test")
        assert "Final Failure" in str(excinfo.value)
