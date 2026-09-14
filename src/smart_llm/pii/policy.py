"""Pure PII-policy resolution.

Mirrors :mod:`smart_llm.provider_policy` in spirit: a dependency-free decision
point that every host applies the same way. It combines a company-level policy
with an optional per-agent override into a single effective policy string that
the :class:`~smart_llm.pii.masking_provider.MaskingProvider` acts on.

Policy ladder (least → most restrictive):

* ``off``          — no detection, provider called with raw content.
* ``detect-only``  — mask + audit, but never fail-closed and vision allowed
                     (shadow / staged-rollout mode to validate detector fit).
* ``enforce``      — mask + audit + fail-closed; vision blocked unless a
                     per-agent ``allow_vision_pii`` escape hatch is set.
* ``strict``       — as ``enforce`` but the vision escape hatch is ignored.

A per-agent override may only *tighten* (move up the ladder), never loosen — so
the effective policy is the most-restrictive of the two. When a company hasn't
set a policy, the env default ``SMART_LLM_PII_DEFAULT_POLICY`` (itself
defaulting to ``enforce``) applies, so masking is on out-of-the-box.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

OFF = "off"
DETECT_ONLY = "detect-only"
ENFORCE = "enforce"
STRICT = "strict"

# Rank by restrictiveness — higher wins when combining company + agent.
POLICY_ORDER: dict[str, int] = {OFF: 0, DETECT_ONLY: 1, ENFORCE: 2, STRICT: 3}

_ENV_DEFAULT = "SMART_LLM_PII_DEFAULT_POLICY"
_FALLBACK = ENFORCE


def _normalize(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in POLICY_ORDER else None


def default_policy() -> str:
    """The company-level default when no explicit company policy is set.

    Reads ``SMART_LLM_PII_DEFAULT_POLICY`` (default ``enforce``). An
    unrecognised value falls back to ``enforce`` with a warning rather than
    silently disabling masking."""
    raw = os.getenv(_ENV_DEFAULT)
    norm = _normalize(raw)
    if raw and norm is None:
        logger.warning(
            "%s=%r is not a valid PII policy; falling back to %r",
            _ENV_DEFAULT,
            raw,
            _FALLBACK,
        )
    return norm or _FALLBACK


def resolve_pii_policy(
    company_policy: Any = None,
    model_configuration: Any = None,
) -> str:
    """Resolve the effective PII policy for one agent call.

    Args:
        company_policy: the company's configured policy string, or ``None``/an
            unrecognised value to fall back to the env default.
        model_configuration: the agent's ``model_configuration`` JSON (dict);
            an optional ``pii_masking_policy`` key tightens the policy.

    Returns one of ``off`` / ``detect-only`` / ``enforce`` / ``strict``.
    """
    company = _normalize(company_policy) or default_policy()
    agent = None
    if isinstance(model_configuration, dict):
        agent = _normalize(model_configuration.get("pii_masking_policy"))
    if agent is None:
        return company
    # Most-restrictive wins: an agent may tighten but never loosen.
    return company if POLICY_ORDER[company] >= POLICY_ORDER[agent] else agent


def is_active(policy: str) -> bool:
    """True when the policy calls for wrapping the provider (anything but off)."""
    return _normalize(policy) not in (None, OFF)


def allow_vision(policy: str, *, allow_vision_pii: bool = False) -> bool:
    """Whether a vision (image) call may proceed under ``policy``.

    ``detect-only`` allows it (audited); ``enforce`` allows it only with the
    per-agent escape hatch; ``strict`` never allows it; ``off`` always allows.
    """
    p = _normalize(policy) or OFF
    if p in (OFF, DETECT_ONLY):
        return True
    if p == ENFORCE:
        return bool(allow_vision_pii)
    return False  # strict
