"""``parse_audio_transcript`` skill — transcribe an audio file.

Phase-E5 strategy chain: local Whisper first (when ``WHISPER_BIN``
is configured / on PATH), then a hosted transcription API
(currently OpenAI's ``whisper-1``). Configure via the AISkill's
``model_configuration`` JSON — see :mod:`fallback_chain`.
"""

from __future__ import annotations

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_AUDIO
from smart_llm.registry import register_tool

from .fallback_chain import (
    run_chain_mixed,
    transcription_api_strategy,
    whisper_local_strategy,
)


class ParseAudioTranscriptSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        cfg = dict(kwargs)
        result = run_chain_mixed(
            input_text,
            cfg,
            [
                ("whisper_local", whisper_local_strategy),
                ("transcription_api", transcription_api_strategy),
            ],
        )
        if cfg.get("include_strategy"):
            return f"[strategy={result.strategy}]\n{result.text}"
        return result.text


register_tool(
    "parse_audio_transcript",
    ParseAudioTranscriptSkill,
    label="Transcribe Audio",
    description=(
        "Transcribe an audio file via local Whisper, falling back to "
        "OpenAI's hosted Whisper API. Set whisper_bin / "
        "transcription_provider via model_configuration."
    ),
    modality=MODALITY_AUDIO,
)
