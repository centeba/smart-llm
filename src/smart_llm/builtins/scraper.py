"""Web-scraper action tool — makes the platform scraper callable by AI agents.

The tool does NOT drive a browser in-process; it POSTs to mit-stack's
``/api/v1/internal/scraper/run`` (X-Internal-Key), which dispatches the scrape to
the worker where headless Chromium lives and returns ``{url, data}``. This keeps
the heavy browser dependency in one place and lets any agent (or any service that
can reach mit-stack) scrape via a single tool call.

Self-registers on import like every other builtin; needs no host package, so it
registers unconditionally (unlike the integration_hub action-tools).
"""

import os
from typing import Any, cast

import httpx
from pydantic import BaseModel, Field

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool


class ScrapeUrlArgs(BaseModel):
    url: str = Field(..., description="The URL to load and scrape.")
    selectors: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Data to extract. Each: {name, css|xpath, attr?, multiple?}. "
            "attr defaults to innerText; set multiple=true to return a list."
        ),
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Optional pre-extraction steps. Each: {type: click|fill|select|"
            "wait|wait_for_selector|scroll, selector?, value?, seconds?}."
        ),
    )
    session_id: str | None = Field(
        None,
        description="Optional saved scraper-session id for authenticated scrapes.",
    )
    wait_for_selector: str | None = Field(
        None, description="Wait for this selector before extracting."
    )
    # Injected by the agent runtime from the caller's tenant context.
    company_id: str | None = Field(
        None, description="Tenant/org id (injected by the runtime)."
    )


class ScrapeUrlSkill(ActionTool):
    """Scrape a URL via mit-stack's worker-backed scrape endpoint."""

    args_model = ScrapeUrlArgs
    read_only = False
    risk = "external"  # makes an outbound request to an arbitrary site

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        args = cast(ScrapeUrlArgs, args)
        # SSRF guard: the scrape target is model-controllable, so block any URL
        # that points at internal / cloud-metadata / private addresses before the
        # worker fetches it. Returns a structured error (never raises into the
        # loop). An allowlist is available via SMART_LLM_EGRESS_ALLOW_HOSTS.
        from smart_llm.security.egress import EgressBlockedError, validate_egress_url

        try:
            validate_egress_url(args.url)
        except EgressBlockedError as exc:
            return {"error": f"egress blocked: {exc}"}

        base = os.environ.get("MIT_STACK_URL", "http://mit-stack-api:8000").rstrip("/")
        key = os.environ.get("INTERNAL_API_KEY", "")
        payload = {
            "org_id": getattr(args, "company_id", None) or "",
            "url": args.url,
            "selectors": args.selectors,
            "actions": args.actions,
            "session_id": args.session_id,
            "wait_for_selector": args.wait_for_selector,
        }
        async with httpx.AsyncClient(timeout=130.0) as client:
            resp = await client.post(
                f"{base}/api/v1/internal/scraper/run",
                json=payload,
                headers={"X-Internal-Key": key} if key else {},
            )
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())


register_tool(
    "scrape_url",
    ScrapeUrlSkill,
    label="Web Scraper: Scrape URL",
    description=(
        "Load a web page and extract structured data with CSS/XPath selectors. "
        "Supports optional pre-scrape actions (click/fill/wait) and an optional "
        "authenticated session. Returns {url, data}."
    ),
    modality=MODALITY_TEXT,
    risk="external",
)
