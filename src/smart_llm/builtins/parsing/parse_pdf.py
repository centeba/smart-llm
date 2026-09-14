"""``parse_pdf`` skill — extract text from a PDF byte-string or local path.

Wraps the optional ``pypdf`` dependency. Falls back to a clear runtime
error if the host hasn't installed it. Real OCR-fallback for
image-only PDFs lives behind the Phase E5 strategy chain.
"""

from typing import Any

import io
from pathlib import Path

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_DOCUMENT
from smart_llm.registry import register_tool


class ParsePdfSkill(Tool):
    """Input: file path or base64 PDF. Output: extracted text."""

    def run(self, input_text: str, **kwargs: Any) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "ParsePdfSkill requires 'pypdf'. Install with `pip install pypdf`."
            ) from exc

        # ``input_text`` may be a path or raw bytes (base64). Try path first.
        src: io.BytesIO | str = input_text
        path = Path(input_text) if input_text and len(input_text) < 1024 else None
        if path is not None and path.exists():
            reader = PdfReader(str(path))
        else:
            import base64

            try:
                data = base64.b64decode(input_text, validate=True)
            except Exception:
                # Treat as already-plain text — no-op pass-through.
                return input_text
            reader = PdfReader(io.BytesIO(data))

        out: list[str] = []
        for page in reader.pages:
            out.append(page.extract_text() or "")
        return "\n\n".join(out).strip()


register_tool(
    "parse_pdf",
    ParsePdfSkill,
    label="Parse PDF",
    description="Extract text from a PDF file (path or base64).",
    modality=MODALITY_DOCUMENT,
    params_schema={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "File path or base64 PDF"},
        },
    },
)
