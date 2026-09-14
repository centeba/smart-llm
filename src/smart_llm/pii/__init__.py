"""PII masking firewall for AI egress.

Public surface used by hosts and by ``Agent._init_provider``:

* :func:`resolve_pii_policy` — combine company + per-agent policy (pure).
* :class:`PiiFirewall` — process-wide masker/re-hydrator (stateless singleton).
* :class:`MaskingProvider` — per-request decorator wrapping a concrete provider.
* :class:`PiiMaskingError` — raised (fail-closed) when masking can't complete.

All masking happens here; services only supply policy (config) and, later,
optional PII field hints (data). See ``docs`` / the PII masking plan.
"""

from .detectors import (
    CompositeDetector,
    Detector,
    NerDetector,
    PiiMatch,
    RegexDetector,
    load_entry_point_detectors,
)
from .firewall import PiiFirewall, PiiMaskingError, StreamRestorer, TokenVault
from .masking_provider import MaskingProvider
from .policy import (
    DETECT_ONLY,
    ENFORCE,
    OFF,
    POLICY_ORDER,
    STRICT,
    allow_vision,
    default_policy,
    is_active,
    resolve_pii_policy,
)

__all__ = [
    "DETECT_ONLY",
    "ENFORCE",
    "OFF",
    "POLICY_ORDER",
    "STRICT",
    "CompositeDetector",
    "Detector",
    "MaskingProvider",
    "NerDetector",
    "PiiFirewall",
    "PiiMaskingError",
    "PiiMatch",
    "RegexDetector",
    "StreamRestorer",
    "TokenVault",
    "allow_vision",
    "default_policy",
    "is_active",
    "load_entry_point_detectors",
    "resolve_pii_policy",
]
