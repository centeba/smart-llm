"""Conversation-window management (PR4 of the Strands-gap work).

Strands ships conversation managers that keep a long chat inside the model's
context window (sliding-window + summarizing strategies). smart-llm already had
the pure trimming primitives in :mod:`smart_llm.history`; this adds the small
manager layer on top so a multi-turn :class:`~smart_llm.conversation.Conversation`
can bound its own context automatically.

A ``ConversationManager`` is ``async apply(messages) -> messages`` — it takes the
running message list and returns a (possibly reduced) one. Persistence of the
messages stays with the host (as it does today); these managers only shape the
in-flight window.

Strategies:

* :class:`NullConversationManager` — no-op (the default; unchanged behaviour).
* :class:`SlidingWindowManager` — keep the most-recent N turns (wraps
  :func:`smart_llm.history.trim_history`, so tool pairs stay balanced).
* :class:`SummarizingManager` — once the history grows past a threshold,
  summarize everything but the last N turns into a single summary message using
  a provided summarizer agent, then keep the recent tail.
"""

import json
from typing import Any, Protocol, runtime_checkable

from .history import balance_tool_turns


@runtime_checkable
class ConversationManager(Protocol):
    async def apply(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class NullConversationManager:
    """Passthrough — the default, so managed and unmanaged conversations share
    one code path."""

    async def apply(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return messages


class SlidingWindowManager:
    """Keep only the last ``max_messages`` messages, re-balancing tool pairs.

    A predictable hard bound on the window (works on both the flat chat shape
    ``{"role","content": str}`` and the block/tool shape).
    :func:`smart_llm.history.balance_tool_turns` drops any tool_use / tool_result
    orphaned by the cut so the provider doesn't reject the request. For the
    tool-aware dual-quota trimming used inside the agent loop, use
    :func:`smart_llm.history.trim_history` directly.
    """

    def __init__(self, max_messages: int = 12):
        self._max = max(1, max_messages)

    async def apply(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(messages) <= self._max:
            return messages
        return balance_tool_turns(messages[-self._max :])


class SummarizingManager:
    """Summarize old turns once the history exceeds ``trigger_turns``.

    When triggered, everything except the last ``keep_recent`` turns is rendered
    to a transcript and summarized by ``summarizer`` (any object with an async
    ``analyze(prompt)`` returning an ``LLMResponse`` — i.e. a ``smart_llm.Agent``).
    The result becomes a single summary message prepended to the recent tail, so
    names / facts / decisions survive while the window stays bounded.
    """

    def __init__(
        self,
        summarizer: Any,
        *,
        keep_recent: int = 6,
        trigger_turns: int = 20,
        summary_role: str = "user",
    ):
        self._summarizer = summarizer
        self._keep_recent = max(0, keep_recent)
        self._trigger_turns = max(1, trigger_turns)
        self._summary_role = summary_role

    async def apply(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(messages) <= self._trigger_turns:
            return messages
        head = messages[: -self._keep_recent] if self._keep_recent else list(messages)
        tail = messages[-self._keep_recent :] if self._keep_recent else []
        if not head:
            return messages
        summary_text = await self._summarize(head)
        summary_msg = {
            "role": self._summary_role,
            "content": f"[Conversation summary so far]\n{summary_text}",
        }
        # Balance so a tool_result in the tail whose tool_use fell into the
        # summarized head doesn't orphan and get rejected by the provider.
        return balance_tool_turns([summary_msg, *tail])

    async def _summarize(self, messages: list[dict[str, Any]]) -> str:
        transcript = _render_transcript(messages)
        prompt = (
            "Summarize the conversation so far, preserving names, facts, "
            "decisions, and any open threads. Be concise.\n\n"
            f"{transcript}"
        )
        resp = await self._summarizer.analyze(prompt)
        data = getattr(resp, "data", None)
        if isinstance(data, dict):
            for key in ("summary", "content", "text"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
            return json.dumps(data, ensure_ascii=False)
        return str(data)


def _render_transcript(messages: list[dict[str, Any]]) -> str:
    """Flatten messages (flat or block shape) to a ``role: text`` transcript."""
    lines: list[str] = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for b in content:
                btype = b.get("type")
                if btype == "text":
                    parts.append(b.get("text", ""))
                elif btype == "tool_use":
                    parts.append(f"[calls tool {b.get('name')}]")
                elif btype == "tool_result":
                    parts.append("[tool result]")
            text = " ".join(p for p in parts if p)
        else:
            text = ""
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


__all__ = [
    "ConversationManager",
    "NullConversationManager",
    "SlidingWindowManager",
    "SummarizingManager",
]
