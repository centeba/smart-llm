"""``MaskingProvider`` — the single egress choke point.

Wraps a concrete provider (Anthropic / OpenAI / Gemini / OpenRouter) so that
*every* outbound call has its content masked and *every* response re-hydrated,
with no change to :class:`~smart_llm.agent.Agent` or the agent loop. Because
every ``Agent`` builds its provider through ``Agent._init_provider``, wrapping
there closes every path at once — chat, documents, the no-tools broker, and the
autonomous tool-calling loop.

Unknown attributes delegate to the inner provider (``last_usage``,
``model_name``, ``NAME``, the ``_build_*_turn`` helpers the loop calls), so the
wrapper is a transparent stand-in for duck-typed call sites.
"""

import logging
from collections.abc import AsyncIterator, Iterable
from typing import Any, cast

from .firewall import PiiFirewall, PiiMaskingError, StreamRestorer, TokenVault
from .policy import DETECT_ONLY, ENFORCE, STRICT, allow_vision

logger = logging.getLogger(__name__)

# Policies under which a masking failure aborts the call before egress.
_FAIL_CLOSED = (ENFORCE, STRICT)


class MaskingProvider:
    """Egress-masking decorator around a concrete provider.

    One instance per request (providers are already built per request), so its
    :class:`TokenVault` gives stable placeholders across every turn of one agent
    loop while never leaking values between requests.
    """

    def __init__(
        self,
        inner: Any,
        firewall: PiiFirewall,
        policy: str,
        *,
        allow_vision_pii: bool = False,
        hints: Iterable[tuple[str, str]] | None = None,
    ):
        self._inner = inner
        self._firewall = firewall
        self._policy = policy
        self._allow_vision_pii = allow_vision_pii
        # Declared-field hints (exact (value, type) pairs) are seeded into the
        # request vault so they mask with 100% precision alongside the detector.
        self._vault = TokenVault(hints=hints)
        # Audit counters (counts only, never values).
        self._vision_blocked = 0
        self._vision_unmasked = 0
        self._fail_closed = False

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes MaskingProvider doesn't define itself.
        # Guard against recursion before _inner is set during __init__.
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    # ── Masking helper (fail-closed under enforce/strict) ───────────────────

    def _mask(self, system: Any, provider_input: Any) -> tuple[Any, Any]:
        try:
            return self._firewall.mask_payload(system, provider_input, self._vault)
        except Exception as e:  # noqa: BLE001
            if self._policy in _FAIL_CLOSED:
                self._fail_closed = True
                raise PiiMaskingError(
                    f"PII masking failed under policy={self._policy!r}; "
                    "aborting before any raw content egresses"
                ) from e
            # detect-only: never block — log and proceed with best effort.
            logger.warning(
                "pii: masking error under detect-only (proceeding unmasked): %s", e
            )
            return system, provider_input

    # ── Provider surface ────────────────────────────────────────────────────

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        masked_system, masked_input = self._mask(system_prompt, user_prompt)
        data = await self._inner.complete(masked_system, masked_input)
        return cast(dict[str, Any], self._firewall.restore_obj(data, self._vault))

    async def complete_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        if not allow_vision(self._policy, allow_vision_pii=self._allow_vision_pii):
            self._vision_blocked += 1
            raise PiiMaskingError(
                "vision blocked under PII policy "
                f"({self._policy!r}) — image bytes cannot be text-masked"
            )
        if self._policy == DETECT_ONLY:
            self._vision_unmasked += 1
        # The image itself can't be masked; the accompanying text prompt is.
        masked_system, masked_prompt = self._mask(system_prompt, user_prompt)
        result = await self._inner.complete_with_image(
            masked_system, masked_prompt, image_bytes, mime_type
        )
        return cast(list[dict[str, Any]], self._firewall.restore_obj(result, self._vault))

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        masked_system, masked_input = self._mask(system_prompt, user_prompt)
        restorer = StreamRestorer(self._vault)
        async for chunk in self._inner.stream(masked_system, masked_input):
            out = restorer.push(chunk)
            if out:
                yield out
        tail = restorer.flush()
        if tail:
            yield tail

    async def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
        **kwargs: Any,
    ) -> Any:
        masked_system, masked_messages = self._mask(system_prompt, messages)
        turn = await self._inner.call_with_tools(
            masked_system, masked_messages, action_tools, **kwargs
        )
        return self._restore_turn(turn)

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        masked_system, masked_messages = self._mask(system_prompt, messages)
        text_restorer = StreamRestorer(self._vault)
        # Per-tool-call restorers so token boundaries inside streamed argument
        # JSON are rebuilt correctly; the consumer concatenates our restored
        # fragments and parses the assembled (real-value) JSON.
        arg_restorers: dict[str, StreamRestorer] = {}

        async for event in self._inner.stream_with_tools(
            masked_system, masked_messages, action_tools, **kwargs
        ):
            etype = event.get("type") if isinstance(event, dict) else None

            if etype == "text_delta":
                out = text_restorer.push(event.get("delta", ""))
                if out:
                    yield {"type": "text_delta", "delta": out}
                continue

            if etype == "tool_use_start":
                tid = event.get("id")
                if tid is not None:
                    arg_restorers[tid] = StreamRestorer(self._vault)
                yield event
                continue

            if etype == "tool_use_input_delta":
                r = arg_restorers.get(event.get("id"))
                if r is None:
                    yield event
                    continue
                out = r.push(event.get("partial_json", ""))
                if out:
                    yield {
                        "type": "tool_use_input_delta",
                        "id": event.get("id"),
                        "partial_json": out,
                    }
                continue

            if etype == "tool_use_stop":
                r = arg_restorers.pop(event.get("id"), None)
                if r is not None:
                    tail = r.flush()
                    if tail:
                        yield {
                            "type": "tool_use_input_delta",
                            "id": event.get("id"),
                            "partial_json": tail,
                        }
                yield event
                continue

            if etype == "turn_complete":
                # Flush any held-back text before the terminal event.
                tail = text_restorer.flush()
                if tail:
                    yield {"type": "text_delta", "delta": tail}
                yield event
                continue

            yield event  # error / unknown — pass through untouched

        # Safety net for streams that ended without a turn_complete event.
        tail = text_restorer.flush()
        if tail:
            yield {"type": "text_delta", "delta": tail}

    # ── Restoration + audit ─────────────────────────────────────────────────

    def _restore_turn(self, turn: Any) -> Any:
        if turn is None:
            return turn
        content = getattr(turn, "content", None)
        if content:
            turn.content = self._vault.restore_text(content)
        for tc in getattr(turn, "tool_calls", None) or []:
            if isinstance(getattr(tc, "input", None), dict):
                tc.input = self._firewall.restore_obj(tc.input, self._vault)
        return turn

    def masking_summary(self) -> dict[str, Any]:
        """Counts-only audit summary of this request's masking (never values)."""
        return {
            "policy": self._policy,
            "token_count": self._vault.token_count(),
            "per_type_counts": self._vault.type_counts(),
            "vision_blocked": self._vision_blocked,
            "vision_unmasked": self._vision_unmasked,
            "fail_closed": self._fail_closed,
            "backend": "regex",
        }
