"""OpenRouter provider — SPIKE (build-vs-buy evaluation).

OpenRouter (https://openrouter.ai) exposes an **OpenAI-compatible** Chat
Completions API in front of ~400 models across ~60 upstream providers, plus
server-side model routing/fallback, provider preferences, and normalized
per-request usage+cost accounting. Because the wire protocol is
OpenAI-compatible, this provider is a thin subclass of
:class:`~smart_llm.providers.openai.OpenAIProvider`: every completion /
vision / tool-calling / streaming method is inherited **unchanged** — only
the transport (``base_url`` + optional attribution headers) and the default
model differ.

Why a dedicated ``openrouter`` provider_type rather than just reusing
``openai`` with a ``base_url``:
- It reads clearly in an ``AIAgentConfig`` (the "direct vs OpenRouter" switch
  is simply the provider value — see ``Agent._init_provider``).
- It gets its own env key slot (``OPENROUTER_API_KEY``) and its own circuit
  breaker bucket (``llm-openrouter``) so an OpenRouter outage trips
  independently of a direct-OpenAI path in the same failover chain.

Model names here are **OpenRouter slugs**, not bare vendor model ids, e.g.::

    "anthropic/claude-sonnet-4.5"
    "openai/gpt-5.1"
    "google/gemini-3.1-pro"
    "openrouter/auto"            # meta-router: picks a model per prompt

NOTE (spike scope): this reuses the OpenAI JSON/tool/stream code paths as-is.
Provider-native niceties the direct adapters use — Anthropic prompt-cache
``cache_control`` (G3), Gemini-specific knobs — are NOT wired here yet;
OpenRouter supports cache passthrough for some providers but that needs
explicit verification before this replaces the direct Anthropic path for
cache-heavy workloads. Keep the direct adapters for those + as an
OpenRouter-outage fallback and for privacy-sensitive tenants (all prompts
transit OpenRouter's infrastructure — a data-governance decision).
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from .openai import OpenAIProvider

logger = logging.getLogger(__name__)

NAME = "openrouter"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Meta-router default — OpenRouter picks a model per prompt. Override per
# AIAgentConfig with an explicit slug when you want a specific model.
DEFAULT_MODEL = "openrouter/auto"


class OpenRouterProvider(OpenAIProvider):
    """OpenAI-compatible client pointed at OpenRouter.

    Inherits ``complete`` / ``complete_with_image`` / ``call_with_tools`` /
    ``stream_with_tools`` / ``stream`` from :class:`OpenAIProvider`.
    """

    NAME = NAME

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_MODEL,
        base_url: str | None = None,
        *,
        referer: str | None = None,
        title: str = "smart-llm",
    ) -> None:
        resolved_base = base_url or OPENROUTER_BASE_URL
        super().__init__(api_key=api_key, model_name=model_name, base_url=resolved_base)
        # Re-create the client with OpenRouter's optional attribution headers
        # (they populate the app on OpenRouter's dashboard/leaderboards; not
        # required for the API to work).
        default_headers = {"X-Title": title}
        if referer:
            default_headers["HTTP-Referer"] = referer
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=resolved_base,
            default_headers=default_headers,
        )
        # last_usage grows a "cost_usd" key on each call (see below).
        self.last_usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}

    # ── Cost accounting (the reason to route through OpenRouter) ────────────
    def _extra_create_kwargs(self) -> dict[str, Any]:
        """Ask OpenRouter to return the request's real cost.

        ``usage: {include: true}`` makes OpenRouter attach a normalized
        ``usage`` block — including ``cost`` in USD — to the response (and to
        the final streaming chunk). This is the exact charge for whichever
        model/provider actually served the request, which we bill verbatim
        via ``record_usage(cost_usd=...)`` instead of guessing from a static
        price table.
        """
        return {"extra_body": {"usage": {"include": True}}}

    def _capture_provider_cost(self, response: Any) -> None:
        """Pull ``usage.cost`` (USD) off an OpenRouter response/chunk."""
        try:
            usage = getattr(response, "usage", None)
            cost = getattr(usage, "cost", None) if usage is not None else None
            if cost is None and isinstance(usage, dict):
                cost = usage.get("cost")
            if cost is not None:
                self.last_usage["cost_usd"] = float(cost)
        except Exception:  # noqa: BLE001 — cost is best-effort, never fatal
            logger.debug(
                "openrouter: could not read usage.cost from response", exc_info=True
            )

    # ── Prompt-cache passthrough seam (G3) ─────────────────────────────────
    # OpenRouter forwards Anthropic/OpenAI prompt-cache controls when the
    # request carries them in the OpenAI-compatible shape (``cache_control``
    # markers on message content parts, or provider-native fields via
    # extra_body). The direct AnthropicProvider applies these itself today;
    # routing a cache-heavy agent through OpenRouter needs the caller to emit
    # cache_control on the message parts. This is wired structurally but NOT
    # yet live-verified end-to-end (needs an OpenRouter key + a cacheable
    # workload) — keep cache-critical agents on the direct Anthropic path
    # until verified. See the provider-policy resolver for that routing.
