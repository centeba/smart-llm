"""Stripe adapters — list_invoices / get_customer."""

from __future__ import annotations

from typing import Any

from integration_hub_backend.mcp.tools import (
    StripeGetCustomerArgs,
    StripeListInvoicesArgs,
)
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

from ._dispatch import dispatch


class StripeListInvoicesSkill(ActionTool):
    args_model = StripeListInvoicesArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        result = await dispatch("stripe_list_invoices", args, db_session=db_session)
        return {"invoices": result}


class StripeGetCustomerSkill(ActionTool):
    args_model = StripeGetCustomerArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        result = await dispatch("stripe_get_customer", args, db_session=db_session)
        return {"customer": result}


register_tool(
    "stripe_list_invoices",
    StripeListInvoicesSkill,
    label="Stripe: List Invoices",
    description="List recent Stripe invoices.",
    modality=MODALITY_TEXT,
    risk="read",
)
register_tool(
    "stripe_get_customer",
    StripeGetCustomerSkill,
    label="Stripe: Get Customer",
    description="Fetch details of a specific Stripe customer.",
    modality=MODALITY_TEXT,
    risk="read",
)
