import logging

from .agent import Agent
from .base import LLMResponse
from .key_manager import KeyManager, key_manager
from .resilience import (
    CircuitOpenError,
    breaker_state,
    resilient_section,
)

logger = logging.getLogger(__name__)


def _provider_breaker_name(agent: Agent) -> str:
    """Per-provider breaker key — shared across agents that hit the same vendor."""
    return f"llm-{agent.provider_type}"


class AgentManager:
    """
    Manages a pool of agents and handles failover logic.
    """

    def __init__(self, key_manager_instance: KeyManager = key_manager) -> None:
        self.agents: dict[str, Agent] = {}
        self.failover_sequence: list[str] = []
        self.key_manager = key_manager_instance

    def register_agent(self, agent: Agent) -> None:
        self.agents[agent.name] = agent
        if agent.name not in self.failover_sequence:
            self.failover_sequence.append(agent.name)

    async def analyze(self, input_text: str, context: str | None = None) -> LLMResponse:
        """
        Tries agents in the failover sequence until one succeeds.

        Failover now checks each agent's per-provider circuit breaker
        before the call. If the breaker is OPEN we skip the provider
        immediately rather than burning a request waiting for it to
        time out — this matters when one of three providers is down,
        because the previous behavior would still try the bad provider
        on every request just to fail through to the next.
        """
        last_error: BaseException | None = None
        skipped_open: list[str] = []
        for agent_name in self.failover_sequence:
            agent = self.agents.get(agent_name)
            if not agent:
                continue

            breaker = _provider_breaker_name(agent)
            if breaker_state(breaker) == "open":
                skipped_open.append(agent_name)
                logger.info(
                    "agent_skipped_circuit_open agent=%s provider=%s",
                    agent_name,
                    agent.provider_type,
                )
                continue

            try:
                async with resilient_section(
                    breaker, failure_threshold=5, recovery_timeout=30.0
                ):
                    # The agent holds the key; on transient failures
                    # the breaker records the miss and we fail over to
                    # the next provider in the sequence.
                    return await agent.analyze(input_text, context)
            except CircuitOpenError:
                # Raced into OPEN between the check above and the call —
                # treat as skip, keep iterating.
                skipped_open.append(agent_name)
                continue
            except Exception as e:
                logger.warning(f"Agent {agent_name} failed. Trying next in sequence...")
                self.key_manager.rotate_on_failure(agent.provider_type)
                last_error = e
                continue

        if last_error is not None:
            raise last_error
        if skipped_open:
            raise RuntimeError(
                f"All LLM providers have open circuits: {skipped_open}; "
                "no analysis attempted. Wait for breaker recovery."
            )
        raise Exception("All agents failed in analysis sequence.")

    async def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        context: str | None = None,
    ) -> LLMResponse:
        """Vision analysis with the same failover + breaker logic as :meth:`analyze`."""
        last_error: BaseException | None = None
        skipped_open: list[str] = []
        for agent_name in self.failover_sequence:
            agent = self.agents.get(agent_name)
            if not agent:
                continue
            breaker = _provider_breaker_name(agent)
            if breaker_state(breaker) == "open":
                skipped_open.append(agent_name)
                continue
            try:
                async with resilient_section(
                    breaker, failure_threshold=5, recovery_timeout=30.0
                ):
                    return await agent.analyze_image(image_bytes, mime_type, context)
            except CircuitOpenError:
                skipped_open.append(agent_name)
                continue
            except Exception as e:
                logger.warning(
                    f"Agent {agent_name} vision analysis failed. Trying next in sequence..."
                )
                self.key_manager.rotate_on_failure(agent.provider_type)
                last_error = e
                continue

        if last_error is not None:
            raise last_error
        if skipped_open:
            raise RuntimeError(
                f"All LLM providers have open circuits: {skipped_open}; "
                "no vision analysis attempted. Wait for breaker recovery."
            )
        raise Exception("All agents failed in vision analysis sequence.")
