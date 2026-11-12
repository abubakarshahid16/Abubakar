"""The steadiness number (order 13, point E): how many lines changed class since the previous run of the same paper.

Free: it reads the stored lines of two finished runs and calls nothing. It is said when a run finishes (not stopped, no line "not run")
and an earlier finished, not partial run of the same paper exists (a paper is one document id; the document table holds one row per
checksum, so the same id is the same file). Lines are compared on the class BEFORE the optional steps (the second readers keep it as
`base`); a line the page re-read recovered is left out, as its class depends on a switch. Ids and class words only, no text.

A DECISION is a class where the AI reviewer gives a verdict: "Proven by code" (Pass or Fail), or "AI opinion, engineer to confirm"
with "AI thinks: met" or "AI thinks: not met". A changed line is "of which decisions" when either its old or its new class is one.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

PROVEN = "Proven by code"
OPINION = "AI opinion, engineer to confirm"
OPINION_WORDS = ("AI thinks: met", "AI thinks: not met")
OPTIONAL_STEPS = ("two_reader", "two_reader_absence", "two_reader_other")


def class_key(line: Mapping) -> tuple[str, str] | None:
    """(class, word) of the line BEFORE the optional steps; None when the line is left out of the comparison."""
    if not isinstance(line, Mapping) or line.get("error"):
        return None
    reread = line.get("reread")
    if isinstance(reread, Mapping) and reread.get("outcome") == "recovered":
        return None
    cls, label = line.get("verdict_class"), line.get("verdict_label")
    for step in OPTIONAL_STEPS:
        base = (
            (line.get(step) or {}).get("base")
            if isinstance(line.get(step), Mapping)
            else None
        )
        if isinstance(base, Mapping) and base.get("verdict_class"):
            cls, label = base.get("verdict_class"), base.get("verdict_label")
            break
    if not cls:
        return None
    if cls == PROVEN:
        return cls, str(line.get("verdict") or label or "")
    if cls == OPINION:
        return cls, str(label or "")
    return str(cls), ""


def is_decision(key: tuple[str, str]) -> bool:
    return key[0] == PROVEN or (key[0] == OPINION and key[1] in OPINION_WORDS)


def compare(before: Mapping[str, Mapping], after: Mapping[str, Mapping]) -> dict:
    """{"lines_compared", "changed", "decisions", "items": [{item_id, from, to, decision}]} for the items in both."""
    items, compared = [], 0
    for item_id in sorted(set(before) & set(after)):
        a, b = class_key(before[item_id]), class_key(after[item_id])
        if a is None or b is None:
            continue
        compared += 1
        if a != b:
            items.append(
                {
                    "item_id": item_id,
                    "from": list(a),
                    "to": list(b),
                    "decision": is_decision(a) or is_decision(b),
                }
            )
    return {
        "lines_compared": compared,
        "changed": len(items),
        "decisions": sum(1 for i in items if i["decision"]),
        "items": items,
    }


def _lines_of(conn, run_id: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ?", (run_id,)
    ):
        try:
            out[r["item_id"]] = json.loads(r["line_json"])
        except ValueError:
            continue
    return out


def previous_run(conn, run_id: str, submittal: str) -> str | None:
    """The latest earlier run of this paper that finished whole (not partial)."""
    # by row order, not by clock second: a run row is written when the run starts and rewritten when it finishes, so a run that
    # finished before this one started sits before it
    row = conn.execute(
        "SELECT run_id FROM agent_review_run WHERE submittal_document_id = ? AND run_id != ? AND finished_at IS NOT NULL"
        " AND COALESCE(partial, 0) = 0 AND COALESCE(items_total, 0) > 0 AND rowid <"
        " COALESCE((SELECT rowid FROM agent_review_run WHERE run_id = ?), 0) ORDER BY rowid DESC LIMIT 1",
        (submittal, run_id, run_id),
    ).fetchone()
    return row["run_id"] if row else None


def since_previous(
    conn, run_id: str, submittal: str, lines: Iterable[Mapping]
) -> dict | None:
    """The comparison of this run's lines with the previous finished run of the paper, or None when there is no such run."""
    before_id = previous_run(conn, run_id, submittal)
    if before_id is None:
        return None
    after = {str(ln.get("item_id")): ln for ln in lines}
    out = compare(_lines_of(conn, before_id), after)
    return {"previous_run_id": before_id, **out}


def summary_of(found: Mapping) -> dict:
    """What the run summary keeps: counts and the previous run's id, never the item list (that is in the trace)."""
    return {
        k: found[k]
        for k in ("previous_run_id", "lines_compared", "changed", "decisions")
    }
