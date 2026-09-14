"""Phase SLM2 — multi-turn chat wrapper around :class:`Agent`.

Accumulates ``user``/``assistant`` turns in a plain list of
``{"role", "content"}`` dicts. Each :meth:`send` call:

  1. Appends the new user turn to the local history.
  2. Sends the full history to the agent's underlying provider via
     :meth:`Agent.analyze` with the ``messages=`` kwarg.
  3. Extracts the assistant text from the parsed JSON response and
     appends it back to history before returning to the caller.

The agent's prompt-shaping ``Tool`` list still runs on the *latest*
user message only — multi-turn doesn't change the single-input
contract those tools were written against.

Example
-------

::

    from smart_llm import Agent, Conversation

    agent = Agent(name='chat', provider_type='anthropic', api_key=...,
                  system_prompt='You are a helpful assistant.')
    conv = Conversation(agent)

    await conv.send("My name is Alice.")
    reply = await conv.send("What's my name?")
    assert "Alice" in reply
"""

import json
from typing import Any

from .agent import Agent
from .base import LLMResponse
from .session import ConversationManager


class Conversation:
    """Multi-turn chat session bound to a single :class:`Agent`."""

    def __init__(
        self,
        agent: Agent,
        *,
        history: list[dict[str, Any]] | None = None,
        manager: ConversationManager | None = None,
    ) -> None:
        self.agent = agent
        # Caller can seed prior turns (e.g. resuming a saved
        # conversation). Defensive copy so external mutations don't
        # leak into our internal state.
        self.messages: list[dict[str, Any]] = list(history or [])
        # Optional context-window manager (sliding-window / summarizing). When
        # None the conversation grows unbounded, exactly as before.
        self._manager = manager

    async def send(self, user_text: str) -> str:
        """Append ``user_text`` to the history, dispatch to the agent,
        and return the assistant's textual response.

        The assistant turn is also appended to ``self.messages`` so
        subsequent ``send()`` calls see the full back-and-forth.
        """
        self.messages.append({"role": "user", "content": user_text})
        # Bound the window (if a manager is set) before sending, so the reduced
        # history is what goes to the provider and what we persist forward.
        if self._manager is not None:
            self.messages = await self._manager.apply(self.messages)
        response: LLMResponse = await self.agent.analyze(messages=self.messages)
        text = self._extract_text(response)
        self.messages.append({"role": "assistant", "content": text})
        return text

    def reset(self) -> None:
        """Clear the conversation. Keeps the agent + system prompt."""
        self.messages.clear()

    @staticmethod
    def _extract_text(response: LLMResponse) -> str:
        """Best-effort assistant-text extraction.

        Providers return parsed JSON via :meth:`Agent.analyze`. A common
        shape is ``{"content": "..."}`` (the smart-llm convention used
        by tool-calling code). When the shape differs, we fall back to
        the raw JSON string so the caller still sees something useful.
        """
        data = response.data
        if isinstance(data, dict):
            for key in ("content", "text", "response", "message"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return json.dumps(data, ensure_ascii=False)
