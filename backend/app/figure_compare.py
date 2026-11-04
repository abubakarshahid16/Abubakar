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

# --- refusals of anything the code cannot read with certainty (#1689 review): each returns "cannot decide", never a verdict ---
# A negated COMPARATOR ("not more than") is a direction the comparison module reads; these are removed before looking for any other negation.
_NEGATED_COMPARATOR = re.compile(
    r"\b(?:not|no)\s+(?:to\s+)?(?:be\s+)?(?:more|less|greater|higher|lower|smaller|larger|fewer|below|above|under|over|exceed\w*)\b",
    re.IGNORECASE,
)
_ANY_NEGATION = re.compile(
    r"\b(?:not|no|nor|never|neither|none|without|cannot|prohibit\w*|forbid\w*|forbidden|unacceptable|inadmissible|disallow\w*|reject\w*|banned)\b|n't\b",
    re.IGNORECASE,
)
# a single separator followed by exactly three digits ("1.500", "1,500") may be a thousands separator or a decimal: not read.
_AMBIGUOUS_SEPARATOR = re.compile(r"(?<![\d.,])[1-9]\d{0,2}[.,]\d{3}(?!\d)")
_QUALIFIER = re.compile(
    r"\b(?:min|minimum|max|maximum|approx\w*|about|around|circa|ca|abt|typ|typical\w*|nominal|nom|up\s+to|at\s+least|at\s+most|"
    r"less|more|greater|higher|lower|above|below|over|under|exceed\w*|limit|rated|average|mean)\b|[~\u2248\u00b1<>\u2264\u2265]",
    re.IGNORECASE,
)
_EXCEPTION = re.compile(
    r"\b(?:as\s+agreed|agreed|except\w*|unless|where|wherever|when|whenever|whereas|while|if|provided|subject\s+to|otherwise|other\s+than|"
    r"apart\s+from|excluding|only\s+for|in\s+case|in\s+which\s+case|depending|according\s+to|as\s+per|per\s+\w+\s+approval|by\s+agreement|approved\s+by)\b",
    re.IGNORECASE,
)
_CONDITION_FIGURE = re.compile(
    r"\b(?:for|at|with|in|on|from|beyond)\b[^,;.]{0,60}?\b(?:above|below|over|under|exceeding|greater\s+than|more\s+than|less\s+than|higher\s+than|lower\s+than)\b",
    re.IGNORECASE,
)
_REQUIREMENT_VERB = re.compile(
    r"\b(?:is|are|shall|must|should|required|be|to\s+be|will)\b", re.IGNORECASE
)
_DIRECTION_WORD = re.compile(
    r"(?P<le>\bnot\s+(?:to\s+)?(?:be\s+)?(?:exceed\w*|more|greater|higher|larger|above|over)\b|\bno\s+(?:more|greater|higher|larger)\b|"
    r"\bat\s+most\b|\bmax(?:imum)?\b|\bup\s+to\b|\bless\s+than\b|\blower\s+than\b|\bsmaller\s+than\b|\bbelow\b|\bunder\b|<=|\u2264|<)"
    r"|(?P<ge>\bnot\s+(?:to\s+)?(?:be\s+)?(?:less|lower|smaller|below|under)\b|\bno\s+(?:less|lower|smaller)\b|\bat\s+least\b|\bmin(?:imum)?\b|"
    r"\bgreater\s+than\b|\bmore\s+than\b|\bhigher\s+than\b|\babove\b|\bover\b|\bexceed\w*|>=|\u2265|>)",
    re.IGNORECASE,
)
_REF_UNIT = r"(?:bar|mbar|psi|kpa|mpa|pa|atm|torr|kgf?/cm2|kg/cm\u00b2)"
_REF_AFTER_UNIT = re.compile(
    rf"\b{_REF_UNIT}\s*[(\[]?\s*(?P<r>g|ga|gage|gauge|a|abs|absolute)\b", re.IGNORECASE
)
_REF_GLUED = re.compile(r"\b(?:bar|psi|kpa|mpa|pa|mbar)(?P<r>g|a)\b", re.IGNORECASE)
_REF_WORD = re.compile(r"\b(?P<r>gauge|gage|absolute|abs)\b", re.IGNORECASE)
_REF_PAREN = re.compile(r"\((?P<r>g|a)\)", re.IGNORECASE)


def _pressure_references(text: str) -> set[str]:
    """Which pressure references ('g', 'a') the text states, in any spelling."""
    found: set[str] = set()
    for rx in (_REF_AFTER_UNIT, _REF_GLUED, _REF_WORD, _REF_PAREN):
        for m in rx.finditer(text):
            found.add("g" if m.group("r").lower().startswith("g") else "a")
    return found


def _clause_refusal(clause: str) -> str | None:
    """Why the CLAUSE quote cannot be read with certainty, or None."""
    if _ANY_NEGATION.search(_NEGATED_COMPARATOR.sub(" ", clause)):
        return "the clause holds a negation or a prohibition the code does not read"
    if _AMBIGUOUS_SEPARATOR.search(clause):
        return (
            "a clause figure has a separator that may be a thousands mark or a decimal"
        )
    stripped = _NEGATED_COMPARATOR.sub(" ", clause)
    if _EXCEPTION.search(clause) or _CONDITION_FIGURE.search(stripped):
        return "the clause holds an exception or a condition the figure may belong to"
    head, sep, tail = clause.partition(",") if "," in clause else clause.partition(";")
    if sep and re.search(r"\d", head) and _REQUIREMENT_VERB.search(tail):
        return "the figure may belong to a condition before a separate requirement"
    kinds = {
        k for m in _DIRECTION_WORD.finditer(clause) for k in ("le", "ge") if m.group(k)
    }
    if len(kinds) > 1:
        return "the clause holds two directions"
    return None


def _document_refusal(text: str) -> str | None:
    """Why the DOCUMENT quote is not one plain, certain value, or None."""
    if _AMBIGUOUS_SEPARATOR.search(text):
        return "the document figure has a separator that may be a thousands mark or a decimal"
    if _QUALIFIER.search(text):
        return "the document figure carries a qualifier (min, max, approx, typical ...)"
    return None


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
    refusal = _clause_refusal(clause_quote)
    if refusal:
        return _undecided(refusal, direction)
    text = document_quote or ""
    refusal = _document_refusal(text)
    if refusal:
        return _undecided(refusal, direction)
    if asked.dimension == "pressure":
        stated = (_pressure_references(text), _pressure_references(clause_quote))
        if (stated[0] or stated[1]) and (stated[0] != stated[1] or len(stated[0]) != 1):
            return _undecided("gauge and absolute pressure are not compared", direction)
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
