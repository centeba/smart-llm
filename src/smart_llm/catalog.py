"""Curated hosted-model catalog for the multi-model chat picker.

A thin, pure derivation of :data:`smart_llm.usage.PRICING` so the set of models
a user may pick and the set we can price never drift apart. The chat catalog
endpoint composes this with the tenant's key'd providers
(``DatabaseKeyStore.list_providers``) to decide what to actually offer.

Kept deliberately minimal (v1): hosted providers only, a display label, and a
coarse capability set (``text`` / ``vision``) so the UI can disable image
attachment for text-only models. OpenRouter is represented as a single
meta-entry — its ``openrouter/auto`` slug routes across ~400 models and reports
its own cost, so it needs no PRICING row.
"""

from __future__ import annotations

from dataclasses import dataclass

from smart_llm.usage import PRICING

# Hosted providers a chat user may select. (Local/self-hosted is out of scope.)
HOSTED_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "gemini", "openrouter")

OPENROUTER_AUTO_MODEL = "openrouter/auto"

# Substrings marking a model as image-capable. Everything else is text-only.
# Conservative: a model absent here simply can't be picked for image turns.
_VISION_HINTS: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4.1",
    "o1",
    "o3",
    "claude-3",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "gemini",
)


@dataclass(frozen=True)
class ModelInfo:
    """One selectable model. ``capabilities`` ⊆ {"text", "vision"}."""

    provider: str
    model: str
    label: str
    capabilities: tuple[str, ...]


def _humanize(model: str) -> str:
    """Turn a slug (``claude-sonnet-4-6``) into a label (``Claude Sonnet 4 6``)."""
    return " ".join(w.capitalize() if w.isalpha() else w for w in model.split("-"))


def _capabilities(model: str) -> tuple[str, ...]:
    lowered = model.lower()
    if any(hint in lowered for hint in _VISION_HINTS):
        return ("text", "vision")
    return ("text",)


def hosted_models() -> list[ModelInfo]:
    """Every selectable hosted model, derived from ``PRICING`` + the OpenRouter
    meta-entry. Deterministic order (grouped by provider, then model)."""
    models: list[ModelInfo] = []
    for key in sorted(PRICING):
        provider, _, model = key.partition(":")
        if provider not in HOSTED_PROVIDERS or not model:
            continue
        models.append(
            ModelInfo(
                provider=provider,
                model=model,
                label=_humanize(model),
                capabilities=_capabilities(model),
            )
        )
    models.append(
        ModelInfo(
            provider="openrouter",
            model=OPENROUTER_AUTO_MODEL,
            label="OpenRouter (auto-route)",
            capabilities=("text",),
        )
    )
    return models


def is_selectable(provider: str, model: str) -> bool:
    """True when ``(provider, model)`` is an offerable hosted model. Used
    server-side to reject a client-supplied model before spending."""
    if provider == "openrouter":
        # Any slug is valid for the gateway; auto is the curated default.
        return True
    return any(m.provider == provider and m.model == model for m in hosted_models())
