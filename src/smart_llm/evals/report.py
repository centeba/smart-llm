"""Render eval results to markdown (reports are markdown by repo convention)."""

from collections.abc import Sequence

from .runner import EvalResult


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def to_markdown(
    results: Sequence[EvalResult], *, title: str = "Agent eval report"
) -> str:
    """A pass/fail table (one row per case, one column per check) + a summary."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)

    # Union of check names, preserving first-seen order for stable columns.
    check_names: list[str] = []
    for r in results:
        for chk in r.checks:
            if chk.name not in check_names:
                check_names.append(chk.name)

    header = ["Case", "Result", *check_names]
    lines = [
        f"# {title}",
        "",
        f"**{passed}/{total} passed**",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for r in results:
        cid = r.case.id or (r.case.input[:40] + ("…" if len(r.case.input) > 40 else ""))
        by = {c.name: c for c in r.checks}
        cells = [_cell(cid), "✅" if r.passed else "❌"]
        for name in check_names:
            c = by.get(name)
            if c is None:
                cells.append("—")
            elif c.score is not None and c.name == "llm_judge":
                cells.append(f"{'✅' if c.passed else '❌'} {c.score:.2f}")
            else:
                cells.append("✅" if c.passed else "❌")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
