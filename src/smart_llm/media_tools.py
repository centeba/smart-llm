"""
Media-processing tools for restoration technician workflows.

RestorationContextTool — pre-processing Tool that injects job/room context
    into the text prompt before it reaches the LLM.

JsonListOutputTool — post-processing OutputTool that normalises any LLM
    response into {"results": [...]}, regardless of whether the model
    returned a bare list, a wrapped dict, or a single object.
"""

from __future__ import annotations

from .base import LLMResponse, OutputTool, Tool


class RestorationContextTool(Tool):
    """Pre-processing: prepend job/room context to the user prompt."""

    def __init__(
        self,
        job_stage: str = "",
        room_name: str = "",
        media_type: str = "",
    ) -> None:
        self.job_stage = job_stage
        self.room_name = room_name
        self.media_type = media_type

    def run(self, input_text: str, **kwargs: object) -> str:
        ctx_parts = [
            p
            for p in [
                f"Stage: {self.job_stage}" if self.job_stage else "",
                f"Room: {self.room_name}" if self.room_name else "",
                f"Media: {self.media_type}" if self.media_type else "",
            ]
            if p
        ]
        header = f"[Context: {', '.join(ctx_parts)}]\n\n" if ctx_parts else ""
        return header + input_text


class JsonListOutputTool(OutputTool):
    """Post-processing: normalise response.data to {"results": [...]}."""

    def run(self, response: LLMResponse, **kwargs: object) -> LLMResponse:
        data = response.data
        if isinstance(data, list):
            response.data = {"results": data}
        elif isinstance(data, dict) and "results" not in data:
            # Single-object response — wrap it in a list
            response.data = {"results": [data]}
        # elif isinstance(data, dict) and "results" in data: already normalised
        return response
