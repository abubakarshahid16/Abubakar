"""Applying an engineer's repair of a rule to a WORK COPY, verified by code (Lane 1).

The engineer check proposes, code verifies, a person applies (an explicit call with a named approver). A repair is
`{field?, comparator?, value?, unit?, figures?: [{value, unit?, condition?}], conditions: [...], exceptions: [...]}`.
Every part is checked on its own; a part that fails is refused with its reason and the others are still applied:

  figure     value and unit stand inside the quote (step a passes with it laid over); a figure with a condition is
             applied only if its condition is verified too
  comparator one the quote implies for that figure
  text       a field, condition or exception: one entry of the closed vocabulary, or a CONTIGUOUS run of words of the
             standard's page text of the rule's page or the next (the repo's fold), numbers on that text, and a negation
             word in the text exactly when it is in the standard's clause

Rows go to `rule_finish_repair` (append-only) of the copy; the rulebook rows are never changed. A step record is written
for every step the repair touched; the engineer check (e) and the owner sample (f) are set back to incomplete.
"""

from __future__ import annotations

import json
import re
import sqlite3

from . import numparse
from . import rule_finish_figures as ff
from .converter_gates import fold
from .rule_finish import (
    COMPARATORS_ALLOWED,
    CONNECTION_WORDS,
    _stand,
    equipment_types_in,
)
from .rule_finish_figures import fraction_spans
from .rule_finish_guard import require_work_copy
from .rule_finish_record import record_code_step, reset_checks
from .rule_finish_store import (
    _APPLIED,
    _REPAIR,
    ensure_table,
    load_rules_by_version,
    now_utc,
    overlay_applied,
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


_NEGATION = frozenset(
    {"not", "no", "nor", "never", "neither", "without", "except", "unless"}
)
_BREAKS = re.compile(r"[.;,:]")


def _words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def _closed(text: str) -> bool:
    """The text is exactly one entry of the closed vocabulary: a connection word or an equipment type."""
    folded = " ".join(_words(text))
    return folded in CONNECTION_WORDS or (folded in equipment_types_in(folded))


def verify_text(text: str, rule: dict, pages: dict[int, str]) -> tuple[bool, str]:
    """A condition, exception or field of a repair stands only if it is one entry of the closed vocabulary, or its words
    are a CONTIGUOUS run of the standard's page text (the rule's page or the next; the repo's fold) and every number is
    on that text; and a negation word is in the text exactly when it is in the clause of the standard it matches."""
    page = rule.get("page")
    body = "\n".join(pages.get(p) or "" for p in (page, (page or 0) + 1))
    if not body.strip():
        return False, "page_text_missing"
    have = {n.value for n in numparse.find_numbers(fold(body)) if n.value is not None}
    have |= {f.value for f in fraction_spans(fold(body))}
    if any(
        n.value is not None and n.value not in have for n in numparse.find_numbers(text)
    ):
        return False, "number_not_on_page"
    wanted = _words(text)
    if not wanted:
        return False, "no_words"
    for clause in _BREAKS.split(fold(body)):
        run = _words(clause)
        at = next(
            (
                i
                for i in range(len(run) - len(wanted) + 1)
                if run[i : i + len(wanted)] == wanted
            ),
            None,
        )
        if at is not None:
            if bool(_NEGATION & set(run)) != bool(_NEGATION & set(wanted)):
                return False, "negation_differs"
            return True, "stands_on_page"
    if _closed(text):
        return True, "closed_vocabulary"
    return False, "not_a_contiguous_run_of_the_page"


def apply_proposal(
    conn_copy: sqlite3.Connection, rule_version_id: str, proposal: dict, approver: str
) -> dict:
    """Write a proposed value and unit (or the two ends of a range) into the WORK COPY (never automatic: only an explicit
    call, named approver). Code verifies NUMBERS only: each number and the unit stand in the rule's quote (numparse, the
    unit table). The comparator is the engineer's: a proposal with one is refused as `engineer_required`, and the stored
    comparator stays empty until a verified repair sets it. The rulebook rows stay as they are (append-only); the applied
    figure is kept in `rule_finish_applied` and step a is recomputed and recorded."""
    require_work_copy(conn_copy)
    if not (approver or "").strip():
        raise ValueError("an approver is required")
    rules = load_rules_by_version(conn_copy, rule_version_id)
    if not rules:
        raise ValueError("no such rule version in this copy")
    if proposal.get("comparator") not in (None, "", "?"):
        raise ValueError(
            "refused: engineer_required (a comparator is the engineer's, never code's)"
        )
    value, low, high, unit = (
        proposal.get(k) for k in ("value", "value_low", "value_high", "unit")
    )
    if value is None and low is None:
        raise ValueError("a proposal needs a value")
    quote = " ".join(str(rules[0].get("quote") or "").split())
    item = (
        ("limit", float(value), unit, None)
        if value is not None
        else ("range", float(low), float(high), unit)
    )
    wrong = _stand([item], ff.figures(quote), quote)
    if wrong:
        raise ValueError(
            f"refused: the proposal does not stand in the quote ({wrong[1]})"
        )
    ensure_table(conn_copy)
    conn_copy.execute(_APPLIED)
    at = now_utc()
    conn_copy.execute(
        "INSERT INTO rule_finish_applied (rule_version_id, value, value_low, value_high, unit, comparator, approver, at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (rule_version_id, value, low, high, unit, None, approver, at),
    )
    conn_copy.commit()
    record_code_step(
        conn_copy,
        rule_version_id,
        "a",
        run_id="apply-proposal",
        note="proposal_applied: ",
        checker=approver,
        at=at,
    )
    reset_checks(conn_copy, rule_version_id, approver, at)
    return {"value": value, "value_low": low, "value_high": high, "unit": unit}


def _figure_problem(quote: str, value: float, unit: str | None) -> str | None:
    """None when the number `value` and its `unit` stand in the quote (numparse, the unit table), else the reason."""
    wrong = _stand([("limit", float(value), unit, None)], ff.figures(quote), quote)
    return wrong[1] if wrong else None


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
        wrong = _figure_problem(
            " ".join(str(self.rule.get("quote") or "").split()), fig["value"], unit
        )
        if wrong:
            self.refused.append({"part": name, "reason": wrong})
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
        """A comparator row is a stored field: it must be an allowed one. Whether it is right is decided by step a (code in
        the simple shape, the engineer's confirmed figures in every other)."""
        if comparator in COMPARATORS_ALLOWED:
            self.applied.append({"part": "comparator", "reason": "stored_for_step_a"})
            self.rows.append(("comparator", {"text": comparator}))
        else:
            self.refused.append(
                {"part": "comparator", "reason": "comparator_not_allowed"}
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
    conn: sqlite3.Connection, version_id: str, rows: list, approver: str, at: str
) -> dict:
    """A step record for every step the repair touched (recomputed by the recorder), then e and f back to incomplete."""
    kinds = {k for k, _ in rows}
    names = [
        n
        for n, hit in (
            ("a", kinds & {"figure", "comparator"}),
            ("d", kinds & {"condition", "exception"}),
            ("b", rows),
        )
        if hit
    ]
    steps = {
        n: record_code_step(
            conn,
            version_id,
            n,
            run_id="apply-repair",
            note="repair_applied: ",
            checker=approver,
            at=at,
        )
        for n in names
    }
    if rows:
        reset_checks(conn, version_id, approver, at)
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
    steps = _record_touched(conn_copy, rule_version_id, check.rows, approver, at)
    return {"applied": check.applied, "refused": check.refused, "steps": steps}
