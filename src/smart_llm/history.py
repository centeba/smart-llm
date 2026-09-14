"""Conversation-history utilities (G4).

Pure, storage-free helpers any multi-turn tool-calling chat needs and would
otherwise rebuild per vertical. They operate on the canonical provider message
shape used by the agent loop — Anthropic-style blocks:

    {"role": "assistant", "content": [{"type":"text","text":...},
                                      {"type":"tool_use","id","name","input"}]}
    {"role": "user",      "content": [{"type":"tool_result","tool_use_id","content"},
                                      {"type":"text","text":...}]}

and a flat, JSON-friendly *stored* shape for persistence:

    {"role","text"?, "tool_calls":[{id,name,input}]?, "tool_results":[{id,content}]?}

The vertical owns where messages are stored; these functions never touch a DB.
"""

from typing import Any

# ── stored ⇄ provider reconstruction ────────────────────────────────────────


def from_stored_messages(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct provider (block) messages from the flat stored shape."""
    out: list[dict[str, Any]] = []
    for m in stored or []:
        role = m.get("role", "user")
        tool_calls = m.get("tool_calls") or []
        tool_results = m.get("tool_results") or []
        text = m.get("text")
        if not tool_calls and not tool_results:
            out.append({"role": role, "content": text or ""})
            continue
        blocks: list[dict[str, Any]] = []
        if role == "assistant":
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc.get("input", {}),
                    }
                )
        else:
            for tr in tool_results:
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": tr.get("content", ""),
                    }
                )
            if text:
                blocks.append({"type": "text", "text": text})
        out.append({"role": role, "content": blocks})
    return out


def to_stored_messages(provider_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise provider (block) messages into the flat stored shape."""
    out: list[dict[str, Any]] = []
    for m in provider_messages or []:
        role = m.get("role", "user")
        content = m.get("content")
        sm: dict[str, Any] = {"role": role}
        if isinstance(content, str):
            if content:
                sm["text"] = content
            out.append(sm)
            continue
        texts: list[str] = []
        tcs: list[dict[str, Any]] = []
        trs: list[dict[str, Any]] = []
        for b in content or []:
            t = b.get("type")
            if t == "text":
                texts.append(b.get("text", ""))
            elif t == "tool_use":
                tcs.append(
                    {"id": b["id"], "name": b["name"], "input": b.get("input", {})}
                )
            elif t == "tool_result":
                trs.append(
                    {"id": b.get("tool_use_id"), "content": b.get("content", "")}
                )
        if texts:
            sm["text"] = "".join(texts)
        if tcs:
            sm["tool_calls"] = tcs
        if trs:
            sm["tool_results"] = trs
        out.append(sm)
    return out


# ── balance + trim ──────────────────────────────────────────────────────────


def balance_tool_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop orphaned tool_use / tool_result blocks so providers don't reject the
    request (every tool_use must have a matching tool_result and vice versa).
    Messages left empty after pruning are removed."""
    use_ids: set[Any] = set()
    res_ids: set[Any] = set()
    for m in messages or []:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get("type") == "tool_use":
                use_ids.add(b.get("id"))
            elif b.get("type") == "tool_result":
                res_ids.add(b.get("tool_use_id"))

    out: list[dict[str, Any]] = []
    for m in messages or []:
        c = m.get("content")
        if not isinstance(c, list):
            out.append(m)
            continue
        kept = []
        for b in c:
            t = b.get("type")
            if t == "tool_use" and b.get("id") not in res_ids:
                continue  # orphan request — no result for it
            if t == "tool_result" and b.get("tool_use_id") not in use_ids:
                continue  # orphan result — no request for it
            kept.append(b)
        if kept:
            out.append({**m, "content": kept})
    return out


def trim_history(
    messages: list[dict[str, Any]], keep_tool_turns: int = 4, keep_text_turns: int = 6
) -> list[dict[str, Any]]:
    """Keep the most recent ``keep_tool_turns`` tool-using turns and
    ``keep_text_turns`` text turns (most-recent first), then re-balance so no
    unbalanced tool pair survives the cut."""
    kept_rev: list[dict[str, Any]] = []
    tool_left = keep_tool_turns
    text_left = keep_text_turns
    for m in reversed(messages or []):
        c = m.get("content")
        is_tool = isinstance(c, list) and any(b.get("type") == "tool_use" for b in c)
        is_result = isinstance(c, list) and any(
            b.get("type") == "tool_result" for b in c
        )
        is_text = (isinstance(c, str) and c.strip()) or (
            isinstance(c, list)
            and any(b.get("type") == "text" for b in c)
            and not is_tool
        )
        if is_tool:
            if tool_left <= 0 and text_left <= 0:
                break
            if tool_left > 0:
                tool_left -= 1
        elif is_text and not is_result:
            if text_left <= 0 and tool_left <= 0:
                break
            if text_left > 0:
                text_left -= 1
        kept_rev.append(m)
    kept_rev.reverse()
    return balance_tool_turns(kept_rev)
