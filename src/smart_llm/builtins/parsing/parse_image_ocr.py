"""``parse_image_ocr`` skill — OCR an image into text.

Phase-E5 strategy chain: Tesseract first (fast, local), then a
vision-LLM fallback when Tesseract isn't installed or its mean
confidence drops below ``ocr_min_confidence``. The chain is
configurable via the host's ``model_configuration`` JSON on the
``AISkill`` row — see :mod:`fallback_chain` for the full key list.
"""

from __future__ import annotations

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_IMAGE
from smart_llm.registry import register_tool

from .fallback_chain import (
    run_chain_mixed,
    tesseract_strategy,
    vision_llm_strategy,
)


class ParseImageOcrSkill(Tool):
    """OCR with automatic vision-LLM fallback.

    Returns the extracted text. Hosts can inspect which strategy
    succeeded by setting ``include_strategy`` in kwargs (used by the
    workflow run-history viewer).
    """

    def run(self, input_text: str, **kwargs: Any) -> str:
        cfg = dict(kwargs)
        result = run_chain_mixed(
            input_text,
            cfg,
            [
                ("tesseract", tesseract_strategy),
                ("vision_llm", vision_llm_strategy),
            ],
        )
        if cfg.get("include_strategy"):
            return f"[strategy={result.strategy}]\n{result.text}"
        return result.text


register_tool(
    "parse_image_ocr",
    ParseImageOcrSkill,
    label="OCR Image",
    description=(
        "OCR an image with Tesseract; falls back to a vision-LLM if "
        "Tesseract is missing or confidence is below threshold. "
        "Configure via model_configuration: ocr_min_confidence, "
        "vision_provider, vision_model."
    ),
    modality=MODALITY_IMAGE,
)
