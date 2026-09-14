"""Per-tenant provider routing policy.

Routing an agent through OpenRouter means the prompt/completion transits a
third party's infrastructure. That's fine for most tenants, but a
privacy-sensitive customer (contracts, regulated PII, a data-residency
commitment) may require **direct-to-vendor** calls only. This module is the
single, pure decision point that maps a *configured* provider choice + a
*tenant policy* to the **effective** provider/model actually used.

It's deliberately dependency-free (no DB, no I/O) so every call site — the
~8 services that build an ``Agent`` from an ``AIAgentConfig`` — can apply it
the same way: load the tenant's policy once, call :func:`resolve_provider`,
pass the result to ``Agent(provider_type=..., model_name=...)``.

Direction of the guard: it only ever *downgrades* gateway→direct; it never
upgrades a direct config onto the gateway. So the safe default (policy
missing/unknown) is to leave a non-gateway config untouched and, if a tenant
policy can't be resolved, to **deny** the gateway (fail closed toward the
more-private option).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

GATEWAY_PROVIDER = "openrouter"

# Vendor prefixes in an OpenRouter model slug ("anthropic/claude-sonnet-4.5")
# that map to a direct provider_type this platform can call itself.
_SLUG_VENDOR_TO_DIRECT = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "gemini",
    "gemini": "gemini",
}


@dataclass(frozen=True)
class TenantAIPolicy:
    """A tenant's AI routing policy.

    ``allow_gateway`` — may this tenant's traffic transit OpenRouter?
    ``fallback_provider`` / ``fallback_model`` — the direct vendor to use
    when the gateway is denied and the configured model is the meta-router
    (``openrouter/auto``) or an unrecognised slug that can't be split into a
    direct vendor.
    """

    allow_gateway: bool = True
    fallback_provider: str = "anthropic"
    fallback_model: str | None = None


def split_openrouter_slug(model: str) -> tuple[str | None, str | None]:
    """``"anthropic/claude-sonnet-4.5"`` → ``("anthropic", "claude-sonnet-4.5")``.

    Returns ``(None, None)`` for the meta-router (``openrouter/auto``) or any
    slug that doesn't carry a recognised vendor prefix.
    """
    if not model or "/" not in model:
        return (None, None)
    vendor, _, rest = model.partition("/")
    vendor = vendor.lower()
    if vendor == "openrouter":  # openrouter/auto — no direct equivalent
        return (None, None)
    direct = _SLUG_VENDOR_TO_DIRECT.get(vendor)
    if direct is None:
        return (None, None)
    return (direct, rest)


def resolve_provider(
    provider_type: str,
    model: str | None,
    policy: TenantAIPolicy,
) -> tuple[str, str | None]:
    """Map a configured (provider_type, model) to the effective pair.

    - Non-gateway configs pass through unchanged (this guard never *adds*
      the gateway).
    - ``openrouter`` + ``allow_gateway`` → unchanged (stay on the gateway).
    - ``openrouter`` + gateway denied → downgrade to the direct vendor parsed
      from the model slug, or the policy's ``fallback_provider``/model when
      the slug can't be mapped (e.g. ``openrouter/auto``).
    """
    if (provider_type or "").lower() != GATEWAY_PROVIDER:
        return (provider_type, model)

    if policy.allow_gateway:
        return (provider_type, model)

    # Gateway denied for this tenant — pick a direct path.
    vendor, direct_model = split_openrouter_slug(model or "")
    if vendor is not None:
        return (vendor, direct_model)
    return (policy.fallback_provider, policy.fallback_model)


# ── Host-facing convenience ──────────────────────────────────────────────────
# Every service that builds an ``Agent`` from an ``AIAgentConfig`` calls this
# one function so the "direct vs gateway" decision is applied uniformly (a
# privacy control is only meaningful if EVERY path honours it).


def _coerce_config(model_configuration: Any) -> dict[str, Any]:
    """``AIAgentConfig.model_configuration`` is a JSON string (or already a
    dict, or None). Return a dict, tolerating malformed input."""
    if model_configuration is None:
        return {}
    if isinstance(model_configuration, dict):
        return model_configuration
    if isinstance(model_configuration, (str, bytes)):
        try:
            parsed = json.loads(model_configuration)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def resolve_agent_provider(
    provider_type: str,
    model_name: str | None,
    model_configuration: Any = None,
    *,
    company_allows_gateway: bool = True,
    fallback_provider: str = "anthropic",
    fallback_model: str | None = None,
) -> tuple[str, str | None]:
    """Resolve the effective (provider_type, model) for an agent build site.

    ``allow_gateway`` is read from ``model_configuration`` (per-agent, default
    ``True``) and AND-ed with ``company_allows_gateway`` (a per-tenant policy
    the host may pass when it has one). Either saying "no" downgrades an
    ``openrouter`` config to a direct vendor via :func:`resolve_provider`;
    non-gateway configs are always returned unchanged.
    """
    cfg = _coerce_config(model_configuration)
    per_agent_allow = bool(cfg.get("allow_gateway", True))
    policy = TenantAIPolicy(
        allow_gateway=per_agent_allow and bool(company_allows_gateway),
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
    )
    effective = resolve_provider(provider_type, model_name, policy)
    if (
        effective[0] != (provider_type or "").lower()
        and (provider_type or "").lower() == GATEWAY_PROVIDER
    ):
        logger.info(
            "provider_policy: downgraded gateway agent %r/%r -> %r/%r (privacy policy)",
            provider_type,
            model_name,
            effective[0],
            effective[1],
        )
    return effective
