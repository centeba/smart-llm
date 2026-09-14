"""Built-in tool registry for smart-llm.

A ``Tool`` (or ``OutputTool``) subclass registers itself once at import time
via :func:`register_tool`. Two consumers care:

1. The workflow builder palette calls :func:`list_tools` to enumerate every
   draggable tool node (modality-grouped).
2. ``Agent.run_with_skills`` calls :func:`get_tool` to instantiate a Python
   tool by name when a skill row has ``kind="python_tool"``.

The registry intentionally lives in-process, populated at import time. It is
**not** a database — DB-backed skills (``kind="prompt"``) are looked up
separately by ``run_with_skills`` and wrapped on the fly.

Built-in skill modules self-register by being imported from
:mod:`smart_llm.builtins`. Hosts that want extra Python tools can call
``register_tool`` from their own startup hooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from smart_llm.base import ActionTool, OutputTool, Tool
from smart_llm.db.models import (
    MODALITIES,
    MODALITY_ANY,
    SKILL_KIND_PYTHON_TOOL,
)

# ── Metadata record returned by list_tools ────────────────────────────────────


@dataclass(frozen=True)
class ToolMeta:
    name: str  # canonical registry key, also stored as AISkill.content
    label: str  # human-friendly UI label
    description: str
    modality: str  # one of MODALITIES
    kind: str  # always SKILL_KIND_PYTHON_TOOL for registry entries
    cls: type  # Tool or OutputTool subclass
    params_schema: dict[str, Any] | None = None  # optional JSONSchema for node config
    # Risk tier for the autonomous-agent tool-policy gate. Only meaningful
    # for ActionTool entries; Tool/OutputTool (prompt-shapers) are "read".
    risk: str = "read"
    # Name of the args_model field carrying a cross-tenant target company id,
    # or None if the tool can't act cross-company (see ActionTool.cross_tenant_arg).
    cross_tenant_arg: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "modality": self.modality,
            "kind": self.kind,
            "params_schema": self.params_schema,
            "risk": self.risk,
        }


# ── Registry storage ──────────────────────────────────────────────────────────

_TOOL_REGISTRY: dict[str, ToolMeta] = {}
_LOCK = RLock()


def register_tool(
    name: str,
    cls: type,
    *,
    label: str,
    description: str,
    modality: str = MODALITY_ANY,
    params_schema: dict[str, Any] | None = None,
    risk: str | None = None,
    overwrite: bool = False,
) -> ToolMeta:
    """Register a Python tool class under a stable name.

    ``name`` is the canonical handle stored in
    ``AISkill.content`` (when ``kind=python_tool``) and referenced by
    workflow nodes. It MUST be stable across releases — renaming breaks
    every saved workflow that uses it.
    """
    if not issubclass(cls, (Tool, OutputTool, ActionTool)):
        raise TypeError(
            f"register_tool('{name}'): {cls!r} must subclass Tool, OutputTool, or ActionTool"
        )
    if modality not in MODALITIES:
        raise ValueError(
            f"register_tool('{name}'): modality '{modality}' is not one of {MODALITIES}"
        )

    # ActionTool subclasses carry a typed Pydantic args model — derive the
    # JSONSchema for Phase E1 form rendering when the caller did not pass
    # one explicitly. Tool / OutputTool subclasses have no implicit schema
    # (their input is just ``input_text``) so we leave params_schema=None.
    if params_schema is None and issubclass(cls, ActionTool):
        args_model = getattr(cls, "args_model", None)
        if args_model is not None and hasattr(args_model, "model_json_schema"):
            try:
                params_schema = args_model.model_json_schema()
            except Exception:
                # A misconfigured args_model shouldn't block registration —
                # the form just falls back to generic key/value editing.
                params_schema = None

    # Resolve the risk tier: explicit kwarg wins, else the class's own
    # ``effective_risk()`` (ActionTool), else "read" for prompt-shapers.
    if risk is not None:
        resolved_risk = risk
    elif issubclass(cls, ActionTool):
        resolved_risk = cls.effective_risk()
    else:
        resolved_risk = "read"
    cross_tenant_arg = (
        getattr(cls, "cross_tenant_arg", None) if issubclass(cls, ActionTool) else None
    )

    meta = ToolMeta(
        name=name,
        label=label,
        description=description,
        modality=modality,
        kind=SKILL_KIND_PYTHON_TOOL,
        cls=cls,
        params_schema=params_schema,
        risk=resolved_risk,
        cross_tenant_arg=cross_tenant_arg,
    )
    with _LOCK:
        if name in _TOOL_REGISTRY and not overwrite:
            existing = _TOOL_REGISTRY[name]
            if existing.cls is cls:
                # Idempotent re-import: same class, same name, no-op.
                return existing
            raise ValueError(
                f"Tool '{name}' is already registered to {existing.cls!r}; "
                f"pass overwrite=True to replace."
            )
        _TOOL_REGISTRY[name] = meta
    return meta


def get_tool(name: str) -> type:
    """Return the registered tool class for ``name``. Raises KeyError if missing."""
    with _LOCK:
        meta = _TOOL_REGISTRY.get(name)
    if meta is None:
        raise KeyError(f"No tool registered under name '{name}'")
    return meta.cls


def get_tool_meta(name: str) -> ToolMeta | None:
    """Return the registry metadata for ``name`` or ``None``."""
    with _LOCK:
        return _TOOL_REGISTRY.get(name)


def list_tools(modality: str | None = None) -> list[ToolMeta]:
    """List all registered tools, optionally filtered by modality.

    Result is sorted by ``(modality, name)`` for stable UI ordering.
    """
    with _LOCK:
        items = list(_TOOL_REGISTRY.values())
    if modality is not None:
        if modality not in MODALITIES:
            raise ValueError(f"Unknown modality '{modality}'")
        items = [
            m for m in items if m.modality == modality or m.modality == MODALITY_ANY
        ]
    items.sort(key=lambda m: (m.modality, m.name))
    return items


def clear_registry() -> None:
    """Test helper — empties the registry. Do not call from production code."""
    with _LOCK:
        _TOOL_REGISTRY.clear()


def registered_names() -> list[str]:
    """Return the names of all registered tools, sorted."""
    with _LOCK:
        return sorted(_TOOL_REGISTRY.keys())


# Importing this module does **not** auto-load builtins — that would create a
# circular import (builtins → registry). Hosts opt in via:
#
#     from smart_llm import builtins  # noqa: F401  (triggers self-registration)
#
# The :mod:`smart_llm.builtins` package executes ``register_tool`` calls at
# import time for every shipped skill.
