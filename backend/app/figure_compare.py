"""One figure against one clause figure, decided by CODE (Part of #805, step 3: the AI senior review).

The AI senior review (`ai_senior_review`, later PRs) reads a document and a clause and quotes both. It may SAY a value meets a limit; it
never decides it. This module is the only place that turns two verified quotes into True / False / "cannot compare":

  * the clause's figure and unit come from the CLAUSE QUOTE, the document's figure from the DOCUMENT QUOTE, both through the comparison
    module's own readers (`claims.extract_measurements`, `comparators.direction_of`). A figure the model gives separately is never used;
  * the direction ("not more than", "at least") is read by `comparators.direction_of`, which holds a negated phrase it cannot read
    (both directions -> None). No direction -> no verdict;
  * units are converted by `claims` (decimal commas, kPa / bar / psi, gauge and absolute kept apart); a different kind of quantity, or
    gauge against absolute, is not compared;
  * the DOCUMENT quote must be one plain value: a range, a tolerance, a comparator-qualified value ("max 10 bar"), several figures, a
    placeholder ("By Contractor", "TBA", "n/a", "not ...") or a negation is refused;
  * a value equal to a STRICT limit ("less than 10 bar", 10 bar printed) is not decided: the verdict is None;
  * more than one clause figure of the same kind, or more than one kind of clause figure, is not decided.

Pure: no model, no database, no network. `None` from `compare` means "the clause quote asks no figure": the caller decides whether a text
requirement applies. A verdict of None inside a result means "asked a figure, could not decide": the row stays unclear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import blank_markers, claims, comparators, numparse

_NEGATED = re.compile(
    r"\b(?:not|no|none|nil|without|excluded|exclud\w*|omitted|deleted|void|spare|by\s+others|n/?a)\b",
    re.IGNORECASE,
)
_STRICT = re.compile(
    r"[<>]|less than|greater than|more than|higher than|lower than|below|above|under|over|exceed",
    re.IGNORECASE,
)
_NOT_STRICT = re.compile(
    r"or equal|at least|at most|not (?:more|less|greater|higher|lower|exceed)|no (?:more|less|greater)|minimum|maximum|≤|≥",
    re.IGNORECASE,
)
_EQUAL_TOLERANCE = 0.005


@dataclass(frozen=True)
class FigureResult:
    """`verdict` True: the document figure satisfies the clause; False: it breaks it; None: asked a figure, cannot decide (`reason` says why)."""

    verdict: bool | None
    reason: str
    direction: str | None = None


def _undecided(reason: str, direction: str | None = None) -> FigureResult:
    return FigureResult(None, reason, direction)


def compare(document_quote: str, clause_quote: str) -> FigureResult | None:
    """Decide the document quote against the clause quote, or None when the clause quote asks no figure."""
    clause_figures = [
        m
        for m in claims.extract_measurements(clause_quote or "")
        if m.normalized_value is not None
    ]
    if not clause_figures:
        return None
    if len({m.dimension for m in clause_figures}) != 1:
        return _undecided("the clause asks more than one kind of figure")
    if len({round(m.normalized_value, 9) for m in clause_figures}) != 1:
        return _undecided("the clause holds more than one figure of that kind")
    asked = clause_figures[0]
    direction = comparators.direction_of(clause_quote) or next(
        (m.comparator for m in clause_figures if m.comparator in (">=", "<=", "=")),
        None,
    )
    if direction not in (">=", "<=", "="):
        return _undecided("the clause gives no readable comparator", None)
    text = document_quote or ""
    if blank_markers.names_a_marker(text) or _NEGATED.search(text):
        return _undecided(
            "the document quote is a placeholder or a negation", direction
        )
    if len({numparse.canonical(n) for n in numparse.find_numbers(text)}) != 1:
        return _undecided(
            "the document quote holds no figure or several figures (a range or a list)",
            direction,
        )
    printed = [
        m
        for m in claims.extract_measurements(text)
        if m.normalized_value is not None and m.dimension == asked.dimension
    ]
    if len(printed) != 1:
        return _undecided(
            "the document figure is not the same kind of quantity as the clause figure",
            direction,
        )
    value = printed[0]
    if value.comparator:
        return _undecided(
            "the document figure is itself a limit or a range, not a plain value",
            direction,
        )
    if (
        asked.dimension == "pressure"
        and (value.reference or asked.reference)
        and value.reference != asked.reference
    ):
        return _undecided("gauge and absolute pressure are not compared", direction)
    a, b = value.normalized_value, asked.normalized_value
    tolerance = 1e-6 * max(abs(b), 1.0)
    if (
        abs(a - b) <= tolerance
        and _STRICT.search(clause_quote)
        and not _NOT_STRICT.search(clause_quote)
    ):
        return _undecided("equal to a strict limit: not decided by code", direction)
    ok = {
        ">=": a >= b - tolerance,
        "<=": a <= b + tolerance,
        "=": abs(a - b) <= max(tolerance, _EQUAL_TOLERANCE * abs(b)),
    }[direction]
    return FigureResult(
        ok,
        f"{value.raw_value} {value.raw_unit} against {direction} {asked.raw_value} {asked.raw_unit}",
        direction,
    )
