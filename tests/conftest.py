import pytest

from smart_llm.base import LLMResponse
from smart_llm.key_manager import KeyManager


@pytest.fixture(autouse=True)
def _disable_default_safety(monkeypatch):
    """Run the legacy suite with the Agent's default safety screens OFF.

    Most tests mock the LLM provider and exercise non-safety behavior; the
    default-on moderation/scope guard would make extra (mocked) provider calls
    and trip fail-closed. This sets the documented break-glass env vars so those
    tests see pre-safety behavior. The dedicated safety tests
    (``test_moderation``/``test_scope_guard``/``test_agent_safety``) build guards
    with explicit ``SafetyConfig`` and are unaffected by these env vars.
    """
    monkeypatch.setenv("SMART_LLM_MODERATION_ENABLED", "false")
    monkeypatch.setenv("SMART_LLM_SCOPE_GUARD_ENABLED", "false")
    # The legacy loop tests exercise dispatch mechanics, not the tool-policy
    # gate, and dispatch write-tier tools without wiring a gate. The new
    # deny-by-default-when-ungated hardening is covered explicitly in
    # test_ungated_tools.py; keep the rest of the suite on the legacy behaviour.
    monkeypatch.setenv("SMART_LLM_ALLOW_UNGATED_TOOLS", "true")
    yield


@pytest.fixture
def key_manager():
    """Provides a fresh KeyManager for each test."""
    return KeyManager(rotation_interval=2)


@pytest.fixture
def sample_response_data():
    """Provides sample data for LLMResponse validation."""
    return {
        "data": {"result": "Success"},
        "provider": "openai",
        "metadata": {"tokens": 100},
    }


@pytest.fixture
def mock_llm_response(sample_response_data):
    """Provides a sample LLMResponse object."""
    return LLMResponse(**sample_response_data)
