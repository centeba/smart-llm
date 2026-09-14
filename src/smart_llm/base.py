from abc import ABC, abstractmethod
from typing import Any, Literal, cast

from pydantic import BaseModel

# Risk tiers for ActionTools, consumed by the autonomous-agent tool-policy
# gate (smart_llm.security.tool_policy). "read" = no side effects; "write" =
# mutates tenant-owned state; "external" = the side effect is observable
# outside SentinelBuild (sends email, charges a card, calls a third party).
ToolRisk = Literal["read", "write", "external"]


class Tool(ABC):
    """
    Abstract base class for AI Agent Tools.
    Tools can filter, transform, or validate input before it reaches the AI.
    """

    @abstractmethod
    def run(self, input_text: str, **kwargs: Any) -> str:
        """Execute the tool's logic."""
        pass


class LLMResponse(BaseModel):
    """Standardized response from an LLM Agent."""

    data: dict[str, Any]
    provider: str
    metadata: dict[str, Any] = {}


class OutputTool(ABC):
    """
    Abstract base class for post-processing tools.
    These run AFTER the LLM call, operating on LLMResponse objects
    to sanitize, validate, or audit the output.
    """

    @abstractmethod
    def run(self, response: LLMResponse, **kwargs: Any) -> LLMResponse:
        """Process and potentially modify an LLM response."""
        pass


class ActionTool(ABC):
    """Side-effect-bearing tool. Distinct from :class:`Tool` because the
    call shape and runtime path differ:

    - ``Tool``       — synchronous prompt-shaper. Takes ``input_text:str``
                       and returns a string that augments the LLM prompt.
    - ``ActionTool`` — async I/O-bearing operation. Takes a typed Pydantic
                       ``args`` model + an injected DB session, performs
                       I/O (SQL, HTTP, etc.), and returns structured data.

    Phase-F integration-hub adapters (``postgres_run_query``,
    ``gmail_send``, ``stripe_get_customer``, …) are all ``ActionTool``s.
    They are callable directly from workflow nodes (no LLM in the loop)
    and — once Phase F2 lands provider-side function-calling — also
    advertised to the LLM as native function-call tools.

    Subclasses MUST set the class attribute ``args_model`` to a
    ``pydantic.BaseModel`` subclass. The registry derives the
    workflow-builder JSONSchema from ``args_model.model_json_schema()``
    so Phase E1 typed-config forms render automatically.
    """

    # Subclasses MUST override. The default ``BaseModel`` placeholder is
    # only here so static type checkers don't choke on the class attr.
    args_model: type[BaseModel] = BaseModel

    # When ``True``, any authenticated user may call this tool via
    # ``POST /ai-tools/run`` — no company_admin role required.
    # Use for tools that perform read-only operations (list/read), so
    # that non-admin members can reach their own data (e.g. email inbox).
    # Leave ``False`` (the default) for any tool that writes, deletes, or
    # has a meaningful side-effect.
    read_only: bool = False

    # Risk tier for the autonomous-agent tool-policy gate. When left as
    # ``None`` the gate derives it from ``read_only`` (read_only=True → "read",
    # else "write"). Tools whose effect leaves the tenant boundary (send email,
    # charge a card, third-party API with side effects) should set
    # ``risk = "external"`` explicitly — the strictest tier.
    risk: ToolRisk | None = None

    # Cross-company delegation (P5): when this tool can act on another
    # company's data, name the ``args_model`` field that carries the target
    # company id here. The policy gate reads ONLY this declared, validated
    # arg to determine the target tenant — never an inferred/opaque id. Tools
    # that leave this ``None`` may never target another company (the gate
    # denies any cross-tenant effect for them).
    cross_tenant_arg: str | None = None

    @classmethod
    def effective_risk(cls) -> ToolRisk:
        """Resolve the tool's risk tier, deriving from ``read_only`` when the
        explicit ``risk`` attribute is unset. Readable off the class with no
        instantiation (mirrors how the registry reads ``args_model``)."""
        explicit = getattr(cls, "risk", None)
        if explicit in ("read", "write", "external"):
            return cast(ToolRisk, explicit)
        return "read" if getattr(cls, "read_only", False) else "write"

    @abstractmethod
    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        """Execute the action and return structured data."""
        pass


class AbstractAgent(ABC):
    """
    Abstract base class for AI Agents.
    Agents use a provider, have a system prompt, and a list of tools.
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[Tool] | None = None,
        output_tools: list[OutputTool] | None = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.output_tools = output_tools or []

    @abstractmethod
    async def analyze(self, input_text: str, context: str | None = None) -> LLMResponse:
        """Main entry point for agent analysis."""
        pass

    def _apply_tools(self, input_text: str) -> str:
        """Sequentially applies all tools to the input text."""
        processed_text = input_text
        for tool in self.tools:
            processed_text = tool.run(processed_text)
        return processed_text

    def _apply_output_tools(self, response: LLMResponse) -> LLMResponse:
        """Sequentially applies all output tools to the LLM response."""
        processed = response
        for tool in self.output_tools:
            processed = tool.run(processed)
        return processed
