"""Built-in NLP skills — operate on text the agent has already
extracted (entities, summaries, intents). Each module self-registers."""

from __future__ import annotations

from . import (
    classify_intent,  # noqa: F401
    extract_entities,  # noqa: F401
    summarize,  # noqa: F401
)
