"""Legal-domain skills (Phase D).

Hosts the contract-scan + red-flag-detection prompts that the
``esignature`` service used to inline. Importing this package
self-registers both skills in :mod:`smart_llm.registry`.
"""

from __future__ import annotations

from . import (
    contract_clause_scan,  # noqa: F401
    detect_signature_fields,  # noqa: F401
    red_flag_detection,  # noqa: F401
)
