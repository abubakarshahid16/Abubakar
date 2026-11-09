"""Applying an engineer's repair of a rule to a WORK COPY, verified by code (Lane 1).

The engineer check proposes, code verifies, a person applies (an explicit call with a named approver). A repair is
`{field?, comparator?, value?, unit?, figures?: [{value, unit?, condition?}], conditions: [...], exceptions: [...]}`.
Every part is checked on its own; a part that fails is refused with its reason and the others are still applied:

  figure     value and unit stand inside the quote (step a passes with it laid over); a figure with a condition is
             applied only if its condition is verified too
  comparator one the quote implies for that figure
  text       a field, condition or exception: every content word and every number is on the standard's page text of the
             rule's page or the next (the repo's fold; numbers by numparse)

Rows go to `rule_finish_repair` (append-only) of the copy; the rulebook rows are never changed. A step record is written
for every step the repair touched, and an earlier engineer check (e) is set back to pending: it must be run again.
"""

from __future__ import annotations

import json
import re
import sqlite3

from . import numparse
from .converter_gates import fold
from .rule_finish import (
    COMPARATORS_ALLOWED,
    INCOMPLETE,
    MODEL_NONE,
    PASS,
    limit_and_unit,
)
from .rule_finish_figures import fraction_spans, implied_comparator
from .rule_finish_guard import require_work_copy
from .rule_finish_store import (
    _REPAIR,
    _append_step,
    ensure_table,
    latest_steps,
    load_rules_by_version,
    now_utc,
    overlay_applied,
    record_code_step,
)

_WORD = re.compile(r"[a-z]+")
_FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "or",
        "and",
        "to",
        "for",
        "in",
        "on",
        "is",
        "are",
        "be",
        "by",
        "with",
        "that",
        "this",
        "it",
        "as",
        "at",
        "from",
        "per",
        "into",
        "than",
        "its",
        "their",
    ]
)


def _page_text(
    conn: sqlite3.Connection, rule: dict, pages: dict[int, str] | None
) -> dict[int, str]:
    if pages is not None:
        return pages
    from .compiled_rule_report import pages_of

    return pages_of(conn, rule["standard_document_id"])


def verify_text(text: str, rule: dict, pages: dict[int, str]) -> tuple[bool, str]:
    """Every content word and every number of `text` stand in the standard's page text of the rule's page or the next."""
    page = rule.get("page")
    body = "\n".join(pages.get(p) or "" for p in (page, (page or 0) + 1))
    if not body.strip():
        return False, "page_text_missing"
    folded = fold(body)
    words = set(_WORD.findall(folded))
    for word in _WORD.findall(fold(text)):
        if word not in _FILLER and word not in words:
            return False, "word_not_on_page"
    have = {n.value for n in numparse.find_numbers(folded) if n.value is not None}
    have |= {f.value for f in fraction_spans(folded)}
    for n in numparse.find_numbers(text):
        if n.value is not None and n.value not in have:
            return False, "number_not_on_page"
    return True, "stands_on_page"


class _Check:
    """The parts of one repair, each verified on its own: what is applied, what is refused and why, the rows to write."""

    def __init__(
        self, conn: sqlite3.Connection, rule: dict, pages: dict[int, str] | None
    ):
        self.conn, self.rule, self.pages = conn, rule, pages
        self.applied: list[dict] = []
        self.refused: list[dict] = []
        self.rows: list[tuple[str, dict]] = []
        self.figures_applied: list[tuple[float, str | None]] = []

    def text(self, part: str, text: str) -> bool:
        if self.pages is None:
            self.pages = _page_text(self.conn, self.rule, None)
        ok, why = verify_text(text, self.rule, self.pages)
        (self.applied if ok else self.refused).append({"part": part, "reason": why})
        return ok

    def figure(self, fig: dict, unit: str | None) -> None:
        name = f"figure {fig['value']}"
        trial = dict(
            self.rule,
            figures=None,
            value=fig["value"],
            value_low=None,
            value_high=None,
            unit=unit,
        )
        result, reason, _ = limit_and_unit(trial)
        if result != PASS:
            self.refused.append({"part": name, "reason": reason})
        elif fig.get("condition") and not self.text(
            f"condition of {name}", fig["condition"]
        ):
            self.refused.append({"part": name, "reason": "its condition was refused"})
        else:
            self.applied.append({"part": name, "reason": "stands_in_quote"})
            self.figures_applied.append((fig["value"], unit))
            self.rows.append(
                (
                    "figure",
                    {
                        "value": fig["value"],
                        "unit": unit,
                        "condition": fig.get("condition"),
                    },
                )
            )
            if fig.get("condition"):
                self.rows.append(("condition", {"text": fig["condition"]}))

    def comparator(self, comparator: str) -> None:
        """The comparator must be the one the quote's own phrase gives EACH figure it is applied to (the figures of this
        repair, else the rule's own value)."""
        quote = " ".join(str(self.rule.get("quote") or "").split())
        targets = self.figures_applied or (
            [(self.rule["value"], self.rule.get("unit"))]
            if self.rule.get("value") is not None
            else []
        )
        ok = (
            comparator in COMPARATORS_ALLOWED
            and bool(targets)
            and all(implied_comparator(quote, v, u) == comparator for v, u in targets)
        )
        if ok:
            self.applied.append({"part": "comparator", "reason": "implied_by_quote"})
            self.rows.append(("comparator", {"text": comparator}))
        else:
            self.refused.append(
                {"part": "comparator", "reason": "comparator_not_in_quote"}
            )

    def run(self, repair: dict) -> None:
        figures = list(repair.get("figures") or [])
        if repair.get("value") is not None:
            figures.append({"value": repair["value"], "unit": repair.get("unit")})
        for fig in figures:
            self.figure(fig, fig.get("unit") or repair.get("unit"))
        if repair.get("comparator"):
            self.comparator(repair["comparator"])
        if repair.get("field") and self.text("field", repair["field"]):
            self.rows.append(("field", {"text": repair["field"]}))
        for kind in ("conditions", "exceptions"):
            for text in repair.get(kind) or []:
                if self.text(kind[:-1], text):
                    self.rows.append((kind[:-1], {"text": text}))


def _write_rows(
    conn: sqlite3.Connection, version_id: str, rows: list, approver: str, at: str
) -> None:
    ensure_table(conn)
    conn.execute(_REPAIR)
    done: set[tuple[str, str]] = set()
    for kind, payload in rows:
        key = (kind, json.dumps(payload, sort_keys=True))
        if (
            key not in done
        ):  # the same row twice (a figure's condition listed again) is one row
            done.add(key)
            conn.execute(
                "INSERT INTO rule_finish_repair (rule_version_id, kind, payload_json, approver, at) VALUES (?,?,?,?,?)",
                (version_id, kind, key[1], approver, at),
            )
    conn.commit()


def _record_touched(
    conn: sqlite3.Connection,
    version_id: str,
    rule: dict,
    rows: list,
    approver: str,
    at: str,
) -> dict:
    kinds = {k for k, _ in rows}
    steps: dict = {}
    if kinds & {"figure", "comparator"}:
        steps["a"] = None
    if kinds & {"condition", "exception"}:
        steps["d"] = None
    if rows:
        steps["b"] = None
    for step in steps:
        steps[step] = record_code_step(
            conn,
            rule,
            step,
            run_id="apply-repair",
            note="repair_applied: ",
            checker=approver,
            at=at,
        )
    if rows and "e" in latest_steps(
        conn, version_id
    ):  # the engineer check must be run again
        _append_step(
            conn,
            version_id,
            "e",
            INCOMPLETE,
            "pending_recheck_after_repair",
            {"approver": approver},
            checker=approver,
            model=MODEL_NONE,
            run_id="apply-repair",
            at=at,
        )
    return {k: v[:2] for k, v in steps.items()}


def apply_repair(
    conn_copy: sqlite3.Connection,
    rule_version_id: str,
    repair: dict,
    approver: str,
    pages: dict[int, str] | None = None,
) -> dict:
    """Apply the verified parts of `repair` to the copy; returns {applied, refused, steps}. Refuses at once an original
    database, an empty approver and an unknown rule version."""
    require_work_copy(conn_copy)
    if not (approver or "").strip():
        raise ValueError("an approver is required")
    found = load_rules_by_version(conn_copy, rule_version_id)
    if not found:
        raise ValueError("no such rule version in this copy")
    check = _Check(conn_copy, overlay_applied(conn_copy, found[0]), pages)
    check.run(repair)
    at = now_utc()
    _write_rows(conn_copy, rule_version_id, check.rows, approver, at)
    steps = _record_touched(
        conn_copy,
        rule_version_id,
        overlay_applied(conn_copy, found[0]),
        check.rows,
        approver,
        at,
    )
    return {"applied": check.applied, "refused": check.refused, "steps": steps}
