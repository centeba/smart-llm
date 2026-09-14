"""SafetyGuard — the mandatory content-safety pipeline for agents.

Composes three screens over every untrusted text surface (user input, tool
results, model output, cross-hop orchestrator text):

1. **Injection** — hardened :class:`PromptInjectionFilterTool` (regex +
   Unicode normalization). Defense-in-depth, not a primary control.
2. **Moderation** — :class:`ChainModerator` (OpenAI ``/moderations`` →
   LLM-classifier fallback). Blocks illegal/abusive content. Fail-closed.
3. **Scope** — :class:`ScopeGuard` topicality check against the agent's
   ``allowed_scope``. Soft guard (fail-open on classifier error).

Unlike the opt-in budget gate, the guard is constructed **by default** inside
``Agent.__init__`` so every entry point is covered. Behaviour is configured via
``SMART_LLM_*`` env vars (see :class:`SafetyConfig`). ``SMART_LLM_SAFETY_SHADOW``
turns blocking into log-only for staged rollout.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .moderation import (
    ChainModerator,
    LLMClassifierModerator,
    ModerationError,
    ModerationResult,
    ModerationUnavailableError,
    OpenAIImageModerator,
    OpenAIModerator,
)
from .prompt_injection import PromptInjectionError, PromptInjectionFilterTool
from .scope import OffTopicError, ScopeGuard

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SafetyConfig:
    moderation_enabled: bool = True
    fail_open: bool = False
    timeout_s: float = 5.0
    injection_sensitivity: str = "high"
    scope_guard_enabled: bool = True
    shadow: bool = False
    # Image/vision moderation posture: 'auto' (moderate when a backend is
    # available, else allow), 'required' (no backend → block), or 'off'.
    image_moderation: str = "auto"

    @classmethod
    def from_env(cls) -> SafetyConfig:
        try:
            timeout = float(os.getenv("SMART_LLM_MODERATION_TIMEOUT_S", "5"))
        except ValueError:
            timeout = 5.0
        sens = os.getenv("SMART_LLM_INJECTION_SENSITIVITY", "high").strip().lower()
        if sens not in ("high", "medium", "low"):
            sens = "high"
        img = os.getenv("SMART_LLM_IMAGE_MODERATION", "auto").strip().lower()
        if img not in ("auto", "required", "off"):
            img = "auto"
        return cls(
            moderation_enabled=_env_bool("SMART_LLM_MODERATION_ENABLED", True),
            fail_open=_env_bool("SMART_LLM_MODERATION_FAIL_OPEN", False),
            timeout_s=timeout,
            injection_sensitivity=sens,
            scope_guard_enabled=_env_bool("SMART_LLM_SCOPE_GUARD_ENABLED", True),
            shadow=_env_bool("SMART_LLM_SAFETY_SHADOW", False),
            image_moderation=img,
        )


class SafetyGuard:
    def __init__(
        self,
        *,
        provider: Any = None,
        key_getter: Callable[[], str | None] | None = None,
        config: SafetyConfig | None = None,
    ):
        self.config = config or SafetyConfig.from_env()
        self._provider = provider
        self._injection = PromptInjectionFilterTool(
            mode="block", sensitivity=self.config.injection_sensitivity
        )
        backends: list[Any] = []
        if key_getter is not None:
            backends.append(
                OpenAIModerator(key_getter, timeout_s=self.config.timeout_s)
            )
        if provider is not None:
            backends.append(
                LLMClassifierModerator(
                    provider, timeout_s=max(self.config.timeout_s, 8.0)
                )
            )
        self._moderator: ChainModerator | None = (
            ChainModerator(backends, fail_open=self.config.fail_open)
            if backends
            else None
        )
        # Image moderation runs through OpenAI's multimodal moderation endpoint,
        # so it needs an OpenAI key (the LLM-classifier fallback is text-only).
        self._image_moderator: OpenAIImageModerator | None = (
            OpenAIImageModerator(key_getter, timeout_s=max(self.config.timeout_s, 8.0))
            if key_getter is not None
            else None
        )
        self._scope = ScopeGuard(provider) if self.config.scope_guard_enabled else None

    # ── individual screens ────────────────────────────────────────────────────

    def _screen_injection(self, text: str, *, surface: str) -> None:
        try:
            self._injection.run(text)
        except PromptInjectionError:
            logger.warning("prompt injection detected in %s", surface)
            if not self.config.shadow:
                raise

    async def _moderate(self, text: str, *, surface: str) -> None:
        if not self.config.moderation_enabled:
            return
        if self._moderator is None:
            # No backend at all. Fail-closed unless explicitly relaxed.
            if self.config.fail_open or self.config.shadow:
                logger.error("no moderation backend configured; allowing %s", surface)
                return
            raise ModerationUnavailableError("no moderation backend configured")
        result: ModerationResult = await self._moderator.moderate(text)
        if result.flagged:
            logger.warning(
                "moderation flagged %s: categories=%s backend=%s",
                surface,
                result.categories,
                result.backend,
            )
            if not self.config.shadow:
                raise ModerationError(
                    f"Content flagged by moderation ({surface})",
                    categories=result.categories,
                    backend=result.backend,
                )

    # ── public surfaces ───────────────────────────────────────────────────────

    async def screen_input(self, text: str) -> None:
        """Screen text on the way INTO the model (user prompt / resolved input)."""
        if not (text or "").strip():
            return
        self._screen_injection(text, surface="input")
        await self._moderate(text, surface="input")

    async def screen_tool_result(self, text: str) -> None:
        """Screen a tool/RAG/document result before feeding it back to the model."""
        if not (text or "").strip():
            return
        self._screen_injection(text, surface="tool_result")
        await self._moderate(text, surface="tool_result")

    async def screen_image(
        self, image_bytes: bytes, mime_type: str = "image/jpeg"
    ) -> None:
        """Screen an image on the way INTO a vision model.

        Posture from ``config.image_moderation``:
        - ``off``      → skip.
        - ``auto``     → moderate when a backend (OpenAI key) is available; when
                         none is, allow (the text prompt is still screened).
        - ``required`` → no backend ⇒ block (unless fail_open/shadow).
        A flagged image blocks the call (unless shadow)."""
        if self.config.image_moderation == "off" or not self.config.moderation_enabled:
            return
        if not image_bytes:
            return
        if self._image_moderator is None:
            if self.config.image_moderation == "required" and not (
                self.config.fail_open or self.config.shadow
            ):
                raise ModerationUnavailableError(
                    "image moderation required but no backend configured"
                )
            return
        import base64

        data_uri = (
            f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        )
        try:
            result = await self._image_moderator.moderate_image(data_uri)
        except Exception as exc:  # noqa: BLE001 — backend outage
            logger.warning("image moderation backend failed: %s", exc)
            if (
                self.config.fail_open
                or self.config.shadow
                or (self.config.image_moderation == "auto")
            ):
                return  # auto/relaxed → allow on backend outage
            raise ModerationUnavailableError("image moderation unavailable") from exc
        if result.flagged:
            logger.warning("image moderation flagged: categories=%s", result.categories)
            if not self.config.shadow:
                raise ModerationError(
                    "Image flagged by moderation",
                    categories=result.categories,
                    backend=result.backend,
                )

    async def screen_output(
        self, text: str, *, allowed_scope: str | None = None
    ) -> None:
        """Screen the model's final output before it reaches the user/store."""
        if not (text or "").strip():
            return
        await self._moderate(text, surface="output")
        if self._scope is not None and allowed_scope:
            in_scope = await self._scope.in_scope(text, allowed_scope)
            if not in_scope:
                logger.warning("output off-scope (scope=%r)", allowed_scope)
                if not self.config.shadow:
                    raise OffTopicError("Output is unrelated to the agent's task scope")
