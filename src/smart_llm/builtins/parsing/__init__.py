"""Built-in parsing skills — convert raw documents/media into text the
agent can analyse. Each module self-registers on import."""

from __future__ import annotations

from . import (
    classify_image,  # noqa: F401  — vision-LLM image classifier
    parse_audio,  # noqa: F401
    parse_docx,  # noqa: F401
    parse_image_ocr,  # noqa: F401
    parse_pdf,  # noqa: F401
    parse_video,  # noqa: F401
    summarize_video,  # noqa: F401  — transcribe → summarise composer
)
