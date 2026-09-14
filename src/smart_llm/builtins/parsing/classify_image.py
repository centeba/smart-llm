"""``classify_image`` — vision-only image classifier.

Unlike :class:`ParseImageOcrSkill` (which extracts text), this skill
asks a vision-LLM to *describe* the image: what kind of artefact is
it (photo / screenshot / document scan / diagram / chart / other),
what's its dominant subject, and an aesthetic 1-line caption. No
OCR is performed, so this works for images that contain no text
at all (pure photos, diagrams).

The output is a strict JSON object — the host (a workflow agent or
``GenerateTagsSkill``) can route on ``image_kind`` or feed the
``description`` directly into a tagging step.

Configuration mirrors :mod:`fallback_chain`:

- ``vision_provider`` — ``anthropic`` | ``openai`` | ``gemini``
  (required; this skill has no non-LLM fallback).
- ``vision_model`` — model name override.
- ``vision_api_key`` — explicit key (otherwise read from env).
"""

from __future__ import annotations

import json
from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_IMAGE
from smart_llm.registry import register_tool

from .fallback_chain import (
    _anthropic_vision,
    _env_key,
    _gemini_vision,
    _openai_vision,
    _read_b64,
    _run_coro,
)

_PROMPT = (
    "Classify this image. Reply with a single JSON object — no prose, "
    "no markdown — with these fields:\n"
    "  image_kind: one of ['photo','screenshot','document_scan',"
    "'diagram','chart','illustration','other']\n"
    "  subject: a short noun phrase describing the dominant subject\n"
    "  description: one neutral sentence describing what the image shows\n"
    "  contains_text: boolean\n"
    "  confidence: float 0.0-1.0\n"
)


class ClassifyImageSkill(Tool):
    """Vision-LLM image classifier; returns the JSON string the LLM
    produced (already validated to be JSON-parseable).

    Falls through to an empty-string failure result with a clear
    message if no ``vision_provider`` is configured — there's no
    non-LLM strategy here, by design.
    """

    def run(self, input_text: str, **kwargs: Any) -> str:
        cfg = dict(kwargs)
        provider = (cfg.get("vision_provider") or "").lower()
        if not provider:
            return json.dumps(
                {
                    "image_kind": "other",
                    "subject": "",
                    "description": "",
                    "contains_text": False,
                    "confidence": 0.0,
                    "error": "classify_image: no vision_provider configured",
                }
            )

        api_key = cfg.get("vision_api_key") or _env_key(provider)
        if not api_key:
            return json.dumps(
                {
                    "image_kind": "other",
                    "subject": "",
                    "description": "",
                    "contains_text": False,
                    "confidence": 0.0,
                    "error": f"classify_image: no api key for {provider}",
                }
            )

        image_b64 = _read_b64(input_text)
        if provider == "anthropic":
            coro = _anthropic_vision(api_key, cfg, image_b64, _PROMPT)
        elif provider == "openai":
            coro = _openai_vision(api_key, cfg, image_b64, _PROMPT)
        elif provider == "gemini":
            coro = _gemini_vision(api_key, cfg, image_b64, _PROMPT)
        else:
            return json.dumps(
                {
                    "image_kind": "other",
                    "subject": "",
                    "description": "",
                    "contains_text": False,
                    "confidence": 0.0,
                    "error": f"classify_image: unknown provider {provider!r}",
                }
            )

        raw = _run_coro(coro) or ""
        # Vision LLMs sometimes wrap JSON in ```json fences; strip them.
        cleaned = raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
        # Validate JSON-parseability so downstream agents can rely on it.
        try:
            json.loads(cleaned)
            return cleaned
        except Exception:  # noqa: BLE001
            return json.dumps(
                {
                    "image_kind": "other",
                    "subject": "",
                    "description": cleaned[:500],
                    "contains_text": False,
                    "confidence": 0.0,
                    "error": "classify_image: model returned non-JSON; raw text in description",
                }
            )


register_tool(
    "classify_image",
    ClassifyImageSkill,
    label="Classify Image",
    description=(
        "Vision-LLM image classifier. Returns JSON with image_kind, "
        "subject, description, contains_text, confidence. Configure "
        "via model_configuration: vision_provider, vision_model."
    ),
    modality=MODALITY_IMAGE,
    params_schema={
        "type": "object",
        "properties": {
            "vision_provider": {
                "type": "string",
                "enum": ["anthropic", "openai", "gemini"],
                "default": "anthropic",
            },
            "vision_model": {"type": "string"},
        },
    },
)
