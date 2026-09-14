"""Google Drive adapter — list_files."""

from __future__ import annotations

from typing import Any

from integration_hub_backend.mcp.tools import DriveListArgs
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_DOCUMENT
from smart_llm.registry import register_tool

from ._dispatch import dispatch


class DriveListSkill(ActionTool):
    args_model = DriveListArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        files = await dispatch("drive_list", args, db_session=db_session)
        return {"files": files}


register_tool(
    "drive_list",
    DriveListSkill,
    label="Google Drive: List Files",
    description="List files in a Google Drive account.",
    modality=MODALITY_DOCUMENT,
    risk="read",
)
