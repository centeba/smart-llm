"""``detect_signature_fields`` — find signature/initials/date placeholders.

Used by the esignature ``Scan-to-Sign`` flow. The directive instructs
the LLM to return a JSON array of field placements (page, x/y, size,
confidence, label) so the front-end can drop pre-positioned fields
on the document.
"""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_DOCUMENT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "Analyze the document text below and identify all locations where "
    "signatures, initials, dates, or other form fields should be "
    "placed.\n\n"
    "Return a JSON array of objects, each with:\n"
    "  field_type: 'signature' | 'initials' | 'date_signed' | 'text'\n"
    "  page_number: 0-indexed page number\n"
    "  x: x coord in PDF points (72 pts/inch) from left edge\n"
    "  y: y coord in PDF points from top edge\n"
    "  width: width in PDF points\n"
    "  height: height in PDF points\n"
    "  confidence: 0..1\n"
    "  label: e.g. 'Signer 1 Signature', 'Date'\n\n"
    "Indicators include: 'Signature: ____', 'Sign here', 'X____', "
    "'Date Signed', 'Initial:', 'Print Name:', and underline/blank "
    "fill-ins. Return ONLY the JSON array — no markdown, no commentary."
)


class DetectSignatureFieldsSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        # Cap input to keep token usage predictable.
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text[:20000], label='DOCUMENT')}"


register_tool(
    "detect_signature_fields",
    DetectSignatureFieldsSkill,
    label="Detect Signature Fields",
    description=(
        "Locate signature / initials / date / text fields in a document "
        "for the esignature Scan-to-Sign flow."
    ),
    modality=MODALITY_DOCUMENT,
)
