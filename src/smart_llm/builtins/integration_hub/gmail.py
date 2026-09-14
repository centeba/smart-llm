"""Gmail adapters — send / list / read / reply.

Forwards to ``integration_hub_backend.api.services.email_service``
(``gmail_*`` methods). All four require a ``credential_id`` + ``company_id``
in the args so the service can look up the encrypted OAuth token.
"""

from __future__ import annotations

from typing import Any

from integration_hub_backend.mcp.tools import (
    GmailListArgs,
    GmailReadArgs,
    GmailReplyArgs,
    GmailSendArgs,
)
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

from ._dispatch import dispatch


def _action(
    name: str, args_cls: type[BaseModel], *, read_only: bool = False
) -> type[ActionTool]:
    """Build a one-method ActionTool subclass — keeps the file flat."""

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


GmailSendSkill = _action("gmail_send", GmailSendArgs)
GmailListSkill = _action("gmail_list", GmailListArgs, read_only=True)
GmailReadSkill = _action("gmail_read", GmailReadArgs, read_only=True)
GmailReplySkill = _action("gmail_reply", GmailReplyArgs)


register_tool(
    "gmail_send",
    GmailSendSkill,
    label="Gmail: Send",
    description="Send an email using a Gmail account.",
    modality=MODALITY_TEXT,
    risk="external",
)
register_tool(
    "gmail_list",
    GmailListSkill,
    label="Gmail: List Messages",
    description="List unread or filtered messages from a Gmail account.",
    modality=MODALITY_TEXT,
)
register_tool(
    "gmail_read",
    GmailReadSkill,
    label="Gmail: Read Message",
    description="Read a single Gmail message in full (headers + body) by message ID.",
    modality=MODALITY_TEXT,
)
register_tool(
    "gmail_reply",
    GmailReplySkill,
    label="Gmail: Reply",
    description="Reply to an existing Gmail thread.",
    modality=MODALITY_TEXT,
    risk="external",
)
