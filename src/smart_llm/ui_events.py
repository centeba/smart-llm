"""Generic ``ui_event`` streaming frame (G6).

A tool can emit a typed *presentational* event that the streaming agent loop
surfaces as its own frame — distinct from the ``tool_use_*`` frames and NOT
recorded as a tool invocation. The platform stays domain-pure: it only forwards
``{type:"ui_event", name, payload}`` opaquely; the event *names* and how they
render live in the vertical and its frontend.

Mechanism: the streaming loop installs a per-dispatch sink (a contextvar) around
tool execution; a tool calls :func:`emit_ui_event`, which appends to that sink;
the loop yields each collected frame after the tools run. Outside a streaming
dispatch (e.g. the non-streaming loop) ``emit_ui_event`` is a no-op.
"""

import contextvars
from typing import Any

_UI_EVENT_SINK: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("smart_llm_ui_event_sink", default=None)
)


def emit_ui_event(name: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a presentational event from inside a tool's ``run_action``.

    No-op when not running under a streaming dispatch that is collecting events.
    """
    sink = _UI_EVENT_SINK.get()
    if sink is not None:
        sink.append({"type": "ui_event", "name": name, "payload": payload or {}})


class collect_ui_events:
    """Context manager: collect ui_events emitted during the block into a list."""

    def __enter__(self) -> list[dict[str, Any]]:
        self._events: list[dict[str, Any]] = []
        self._token = _UI_EVENT_SINK.set(self._events)
        return self._events

    def __exit__(self, *exc: Any) -> None:
        _UI_EVENT_SINK.reset(self._token)
