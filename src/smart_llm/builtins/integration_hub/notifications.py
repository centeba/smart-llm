"""Notification-rule adapters used by the Rule Builder agent.

Three ``ActionTool`` subclasses exposing the tenant's existing
``notification_rules`` machinery to the agent:

  * ``list_notification_rules`` — read existing rules (for context).
  * ``list_notification_event_types`` — discover available triggers
    so the agent picks a real ``event_type_id`` instead of inventing one.
  * ``create_notification_rule`` — persist a new rule.

The Rule Builder agent's system prompt drives the conversation;
when it has a structured rule definition, it calls
``create_notification_rule``. The two read-only tools give it
context to make valid choices.
"""

from __future__ import annotations

from typing import Any

from integration_hub_backend.mcp.tools import (
    CreateNotificationRuleArgs,
    ListNotificationEventTypesArgs,
    ListNotificationRulesArgs,
)
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

from ._dispatch import dispatch


class ListNotificationRulesSkill(ActionTool):
    args_model = ListNotificationRulesArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        rows = await dispatch("list_notification_rules", args, db_session=db_session)
        return {"rules": rows}


class ListNotificationEventTypesSkill(ActionTool):
    args_model = ListNotificationEventTypesArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        rows = await dispatch(
            "list_notification_event_types", args, db_session=db_session
        )
        return {"event_types": rows}


class CreateNotificationRuleSkill(ActionTool):
    args_model = CreateNotificationRuleArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        rule = await dispatch("create_notification_rule", args, db_session=db_session)
        return {"rule": rule}


register_tool(
    "list_notification_rules",
    ListNotificationRulesSkill,
    label="Rules: List Notification Rules",
    description="List notification rules configured for a company.",
    modality=MODALITY_TEXT,
    risk="read",
)
register_tool(
    "list_notification_event_types",
    ListNotificationEventTypesSkill,
    label="Rules: List Event Types",
    description=(
        "List the catalogue of event types (rule triggers) for a company. "
        "Use before create_notification_rule so the agent picks a real "
        "event_type_id."
    ),
    modality=MODALITY_TEXT,
    risk="read",
)
register_tool(
    "create_notification_rule",
    CreateNotificationRuleSkill,
    label="Rules: Create Notification Rule",
    description=(
        "Create a notification rule binding an event_type to one or more "
        "channels via a template, with optional conditions and recipient "
        "strategy."
    ),
    modality=MODALITY_TEXT,
    # SEC-M5 — this persists a rule (side effect); it was defaulting to "read",
    # which let the policy gate run it unattended under the "auto" mode. Mark it
    # "write" so auto → approval_required (only an explicit "allow" runs it).
    risk="write",
)
