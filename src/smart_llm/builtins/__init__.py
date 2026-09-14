"""Built-in skills for smart-llm.

Importing this package triggers self-registration of every shipped skill
into :mod:`smart_llm.registry` via top-level ``register_tool(...)`` calls.

Hosts opt in by importing ``smart_llm.builtins`` once at startup::

    from smart_llm import builtins  # noqa: F401

Each subpackage owns one functional area:

- ``parsing`` — file/binary → text extraction (PDF, DOCX, OCR, A/V).
- ``nlp`` — pre-LLM directive shapers (entities, summarize, intent).
- ``tagging`` — tag generation, persistence, and per-modality composers.

Keep imports lazy and side-effect-only: each submodule should only call
``register_tool`` at module top level and avoid importing host code.
"""

from __future__ import annotations

from . import (
    calculate,  # noqa: F401  — calculate (safe arithmetic)
    email,  # noqa: F401  — extract_email_fields
    integration_hub,  # noqa: F401  — Phase F action-tools + rule-builder
    legal,  # noqa: F401  — contract_clause_scan, red_flag_detection
    nlp,  # noqa: F401  — extract_entities, summarize, classify_intent
    parsing,  # noqa: F401  — parse_pdf, parse_docx, parse_image_ocr, ...
    scraper,  # noqa: F401  — scrape_url (worker-backed web scraper)
    tagging,  # noqa: F401  — generate_tags, auto_create_tag, tag_document, ...
    triage,  # noqa: F401  — document_triage_orchestrator
    web_search,  # noqa: F401  — web_search (registered only if configured)
)
