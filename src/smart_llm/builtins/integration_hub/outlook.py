"""Outlook / Microsoft 365 adapters — send / list / read / reply."""

from __future__ import annotations

from typing import Any

from integration_hub_backend.mcp.tools import (
    OutlookListArgs,
    OutlookReadArgs,
    OutlookReplyArgs,
    OutlookSendArgs,
)
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

from ._dispatch import dispatch


def _action(
    name: str, args_cls: type[BaseModel], *, read_only: bool = False
) -> type[ActionTool]:
    class _Adapter(ActionTool):
        args_model = args_cls

        async def run_action(
            self, args: BaseModel, *, db_session: Any
        ) -> dict[str, Any]:
            result = await dispatch(name, args, db_session=db_session)
            return {"result": result}

    _Adapter.read_only = read_only
    _Adapter.__name__ = f"{args_cls.__name__.replace('Args', '')}Skill"
    return _Adapter


OutlookSendSkill = _action("outlook_send", OutlookSendArgs)
OutlookListSkill = _action("outlook_list", OutlookListArgs, read_only=True)
OutlookReadSkill = _action("outlook_read", OutlookReadArgs, read_only=True)
OutlookReplySkill = _action("outlook_reply", OutlookReplyArgs)


register_tool(
    "outlook_send",
    OutlookSendSkill,
    label="Outlook: Send",
    description="Send an email using an Outlook/Microsoft 365 account.",
    modality=MODALITY_TEXT,
    risk="external",
)
register_tool(
    "outlook_list",
    OutlookListSkill,
    label="Outlook: List Messages",
    description="List messages from an Outlook/Microsoft 365 mailbox folder.",
    modality=MODALITY_TEXT,
)
register_tool(
    "outlook_read",
    OutlookReadSkill,
    label="Outlook: Read Message",
    description="Read a single Outlook message in full (headers + body) by message ID.",
    modality=MODALITY_TEXT,
)
register_tool(
    "outlook_reply",
    OutlookReplySkill,
    label="Outlook: Reply",
    description="Reply to an existing Outlook message.",
    modality=MODALITY_TEXT,
    risk="external",
)
