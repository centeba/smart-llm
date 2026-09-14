"""Tagging skills — generate, persist, and apply tags across modalities.

``generate_tags`` produces tag suggestions; ``auto_create_tag`` persists
new ones above a confidence threshold; the modality-specific
``tag_*`` skills compose these with the right parser to give a
single-shot "tag this asset" experience.
"""

from __future__ import annotations

from . import (
    auto_create_tag,  # noqa: F401
    generate_tags,  # noqa: F401
    tag_audio,  # noqa: F401
    tag_document,  # noqa: F401
    tag_image,  # noqa: F401
    tag_video,  # noqa: F401
)
