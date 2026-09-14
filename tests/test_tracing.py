"""Agent-native OTEL tracing — spans + GenAI/tenant attributes, and no-op path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip the whole module if the OTEL SDK isn't installed (observability extra).
pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from smart_llm.agent import Agent  # noqa: E402

_exporter = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _otel_provider():
    # No global provider is configured during the unit suite (install_tracing
    # only runs when OTEL_EXPORTER_OTLP_ENDPOINT is set), so this set wins.
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace.set_tracer_provider(provider)
    yield


@pytest.fixture(autouse=True)
def _clear_spans():
    _exporter.clear()
    yield


def _patch_provider(token_counts=(0, 0), data=None):
    mock_cls = MagicMock()
    instance = mock_cls.return_value
    instance.complete = AsyncMock(return_value=data or {"content": "ok"})
    instance.last_usage = {
        "input_tokens": token_counts[0],
        "output_tokens": token_counts[1],
    }
    return patch("smart_llm.agent.AnthropicProvider", mock_cls), instance


@pytest.mark.asyncio
async def test_analyze_emits_agent_and_model_spans():
    prov_patch, _ = _patch_provider((100, 50), {"content": "ok"})
    with prov_patch:
        agent = Agent(
            name="t",
            provider_type="anthropic",
            system_prompt="s",
            api_key="k",
            model_name="claude-x",
            company_id="co-1",
            agent_id="ag-1",
            user_id="u-1",
            safety_enabled=False,
        )
        await agent.analyze("hello")

    spans = _exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "agent.analyze" in names
    assert "gen_ai.chat" in names

    agent_span = next(s for s in spans if s.name == "agent.analyze")
    a = agent_span.attributes
    assert a["gen_ai.system"] == "anthropic"
    assert a["gen_ai.request.model"] == "claude-x"
    assert a["gen_ai.operation.name"] == "analyze"
    # Tenant tags — traces split by company/agent/user.
    assert a["sentinelbuild.company_id"] == "co-1"
    assert a["sentinelbuild.agent_id"] == "ag-1"
    assert a["sentinelbuild.user_id"] == "u-1"
    # Same token numbers the billing ledger records.
    assert a["gen_ai.usage.input_tokens"] == 100
    assert a["gen_ai.usage.output_tokens"] == 50

    # The model span nests under the agent span.
    model_span = next(s for s in spans if s.name == "gen_ai.chat")
    assert model_span.parent is not None
    assert model_span.parent.span_id == agent_span.context.span_id


@pytest.mark.asyncio
async def test_agent_loop_emits_model_and_tool_spans():
    from pydantic import BaseModel

    from smart_llm.agent_loop import AgentTurn, ToolCall, run_agent_loop
    from smart_llm.base import ActionTool

    class _Args(BaseModel):
        x: int = 0

    class _MyTool(ActionTool):
        args_model = _Args
        risk = "read"

        async def run_action(self, args, *, db_session):
            return {"ok": True}

    class _FakeProv:
        provider_type = "anthropic"
        model_name = "m"

        def __init__(self):
            self.last_usage: dict = {}
            self._calls = 0

        async def call_with_tools(self, system, messages, tools, **kw):
            self._calls += 1
            if self._calls == 1:
                return AgentTurn(
                    content=None,
                    tool_calls=[ToolCall(id="t1", name="_MyTool", input={"x": 1})],
                    stop_reason="tool_use",
                    usage={},
                )
            return AgentTurn(content="done", tool_calls=[], stop_reason="end_turn", usage={})

        def _build_assistant_tool_use_turn(self, turn):
            return {"role": "assistant", "content": []}

        def _build_tool_results_turn(self, results):
            return {"role": "user", "content": []}

    out = await run_agent_loop(_FakeProv(), "sys", "hi", [_MyTool()], db_session=None)
    assert out == "done"

    spans = _exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "gen_ai.chat" in names  # per-round model span
    tool_spans = [s for s in spans if s.name == "gen_ai.execute_tool"]
    assert tool_spans, "expected a tool span"
    assert tool_spans[0].attributes["gen_ai.tool.name"] == "_MyTool"
    assert tool_spans[0].attributes["sentinelbuild.tool.risk"] == "read"


@pytest.mark.asyncio
async def test_no_spans_when_otel_disabled(monkeypatch):
    # Force the no-op path (simulates opentelemetry not installed).
    monkeypatch.setattr("smart_llm.tracing._OTEL", False)
    prov_patch, _ = _patch_provider((1, 1), {"content": "ok"})
    with prov_patch:
        agent = Agent(
            name="t",
            provider_type="anthropic",
            system_prompt="s",
            api_key="k",
            safety_enabled=False,
        )
        # Must run cleanly and emit nothing.
        await agent.analyze("hi")
    assert len(_exporter.get_finished_spans()) == 0
