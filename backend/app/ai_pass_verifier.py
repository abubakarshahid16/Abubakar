"""AI engineering review pass, part 4: the AI may CREATE A PASS, only when CODE verifies both quotes. Lane 6 (owner order).

DANGER ZONE: this is the one place a Pass is created. Behind `AI_REVIEW_PASS_ENABLED` (default OFF; the owner turns it on).
The AI reads and proposes (`type: "pass"`); code verifies and decides; the engineer decides last (the row is never
confirmed). A Pass is accepted ONLY when every one of these holds, the first failure being the refusal:

  1. the switch is on;
  2. one DOCUMENT quote stands, whole, on the cited page, and names the field;
  3. the standard and clause resolve to STORED clause text, the CLAUSE quote stands in that text, the clause's scope
     (when it has a condition or an exception) is shown as a quote of the stored text, and the AI states the scope applies
     (`scope_applies` exactly "yes"; unsure, missing or no = no Pass);
  4. the figure the clause asks for is read from the clause quote BY CODE and the document's value from the document quote
     BY CODE (`claims.extract_measurements`), and the unit-aware comparison (`claims`, the comparison's own) says the value
     satisfies the clause; no single extractable figure, a unit that cannot be compared, a doc quote with two figures = no
     Pass. A requirement with no figure needs its exact required term, whole-word, in BOTH quotes;
  5. no Fail row on the sheet for the same field, and the document does not give the field two values;
  6. a second, independent reading (`second`) agrees on field, page, document quote, standard, clause and scope.

Silence, negation ("no", "not", "without", "unless", "except"), "no contradiction" and the like in the document quote are never
a Pass (CLAUDE.md rule 4). The AI still never removes a Fail (`ai_review_proposals`). Nothing here reads the database or calls a
model: the stored clause text arrives in the context.
"""

from __future__ import annotations

import re

from . import ai_review_proposals as arp
from . import claims, numparse, standard_ids
from .config import settings
from .reader_api import _fold

PASS_ROW_KIND = "ai_judged_pass"
INTERNAL_LABEL = "Pass, decided by AI judgement with verified quotes"
COMPARATORS = (">=", "<=", "min", "max")
_NEGATION = re.compile(
    r"\b(?:no|not|never|none|without|unless|except|excluding|n/a|nil|absent|missing|tbd|tba|pending)\b"
)
_SCOPE_MARKERS = re.compile(
    r"\b(?:except|unless|provided that|exception|where|if|when|only for|applies to|does not apply|not apply|for)\b"
)


class PassReason:
    SWITCH_OFF = "pass_switch_off"
    NO_DOC_QUOTE = "pass_document_quote_not_verified"
    NO_CLAUSE = "pass_clause_not_in_stored_text"
    CLAUSE_QUOTE = "pass_clause_quote_not_in_stored_text"
    SCOPE = "pass_scope_not_confirmed"
    NO_FIGURE = "pass_no_single_figure"
    NOT_COMPARABLE = "pass_units_not_comparable"
    NOT_SATISFIED = "pass_requirement_not_satisfied"
    NO_TERM = "pass_required_term_not_in_both_quotes"
    NEGATION = "pass_quote_is_silence_or_negation"
    FAIL_PRESENT = "pass_fail_on_the_sheet"
    CONFLICT = "pass_field_has_two_values"
    READINGS = "pass_readings_disagree"


def _clause_text(proposal: dict, ctx) -> str | None:
    """The stored clause text for the standard and clause the proposal names, or None."""
    standard, clause = (
        str(proposal.get("standard") or ""),
        str(proposal.get("clause") or "").strip(),
    )
    if not standard or not clause:
        return None
    for (name, number), text in (getattr(ctx, "clause_text", None) or {}).items():
        stem = re.sub(r"\.(pdf|docx?)$", "", str(name), flags=re.IGNORECASE)
        if number == clause and standard_ids.same_standard(standard, stem):
            return str(text)
    return None


def _same_reading(proposal: dict, second: object) -> bool:
    if not isinstance(second, dict):
        return False
    fields = ("field", "page", "clause")
    if any(str(second.get(k)) != str(proposal.get(k)) for k in fields):
        return False
    if not standard_ids.same_standard(
        str(second.get("standard") or ""), str(proposal.get("standard") or "")
    ):
        return False
    if _fold(str(second.get("doc_quote") or "")) != _fold(
        str((proposal.get("evidence") or [{}])[0].get("quote") or "")
    ):
        return False
    return str(second.get("scope_applies") or "").strip().lower() == "yes"


def _field_values(field: str, ctx) -> set[tuple[float, str]]:
    """Every figure printed right after the field's name anywhere in the document."""
    label = _fold(field)
    found: set[tuple[float, str]] = set()
    for text in ctx.pages.values():
        folded = _fold(text)
        for m in re.finditer(re.escape(label), folded):
            for meas in claims.extract_measurements(folded[m.end() : m.end() + 40])[:1]:
                if meas.normalized_value is not None:
                    found.add(
                        (meas.normalized_value, meas.normalized_unit or meas.raw_unit)
                    )
    return found


def _satisfies(observed: claims.Measurement, limit: claims.Measurement) -> bool | None:
    crossed = claims.compare_across_units(observed, limit)
    if crossed is not None:
        return crossed.verdict
    return claims._compatible(observed, limit)


def _document_quote(proposal: dict, ctx) -> tuple[str | None, str | None]:
    """(quote, None) when one document quote stands, whole, on the cited page and names the field; else (None, reason)."""
    page = arp._page_of(proposal, ctx)
    evidence = proposal.get("evidence")
    field = str(proposal.get("field") or "").strip()
    if (
        page is None
        or not field
        or not isinstance(evidence, list)
        or len(evidence) != 1
        or not isinstance(evidence[0], dict)
        or evidence[0].get("page") != page
        or arp._evidence_ok(proposal, ctx) is not None
        or _fold(field) not in _fold(str(evidence[0].get("quote") or ""))
    ):
        return None, PassReason.NO_DOC_QUOTE
    quote = str(evidence[0]["quote"]).strip()
    if _NEGATION.search(_fold(quote)):
        return None, PassReason.NEGATION
    return quote, None


def _clause_quote(proposal: dict, ctx) -> tuple[str | None, str | None]:
    """(clause quote, None) when the clause resolves to stored text, the quote stands in it and the scope is confirmed."""
    clause_text = _clause_text(proposal, ctx)
    if clause_text is None:
        return None, PassReason.NO_CLAUSE
    quote = str(proposal.get("clause_quote") or "").strip()
    if len(quote) < arp.MIN_QUOTE_CHARS or _fold(quote) not in _fold(clause_text):
        return None, PassReason.CLAUSE_QUOTE
    if str(proposal.get("scope_applies") or "").strip().lower() != "yes":
        return None, PassReason.SCOPE
    if _SCOPE_MARKERS.search(_fold(clause_text)):
        shown = str(proposal.get("scope_quote") or "").strip()
        if len(shown) < arp.MIN_QUOTE_CHARS or _fold(shown) not in _fold(clause_text):
            return None, PassReason.SCOPE
    return quote, None


def _figure_check(
    proposal: dict, clause_quote: str, doc_quote: str
) -> tuple[str | None, str | None]:
    """(what was compared, None) when the document's value, read by code, satisfies the clause's, read by code."""
    clause_figures = claims.extract_measurements(clause_quote)
    limits = [m for m in clause_figures if m.comparator in COMPARATORS]
    observed = claims.extract_measurements(doc_quote)
    if limits:
        if len(limits) != 1 or len(clause_figures) != 1 or len(observed) != 1:
            return None, PassReason.NO_FIGURE
        limit = claims.normalise(
            limits[0].raw_value, limits[0].raw_unit, limits[0].comparator
        )
        value = claims.normalise(observed[0].raw_value, observed[0].raw_unit)
        verdict = _satisfies(value, limit)
        if verdict is None:
            return None, PassReason.NOT_COMPARABLE
        if verdict is not True:
            return None, PassReason.NOT_SATISFIED
        return (
            f"the submittal states {observed[0].raw_value} {observed[0].raw_unit} and the clause requires "
            f"{limits[0].comparator} {limits[0].raw_value} {limits[0].raw_unit}",
            None,
        )
    if clause_figures or observed:
        return None, PassReason.NO_FIGURE
    term = str(proposal.get("required_term") or "").strip()
    if (
        not term
        or not numparse.contains_whole(_fold(doc_quote), _fold(term))
        or not numparse.contains_whole(_fold(clause_quote), _fold(term))
    ):
        return None, PassReason.NO_TERM
    return f'the submittal states "{term}" and the clause requires it', None


def _sheet_check(field: str, ctx) -> str | None:
    """A reason when the sheet holds a Fail for the field, or the document gives the field two values."""
    for row in ctx.rows.values():
        about = _fold(
            str(row.get("page_section") or "") + " " + str(row.get("comment") or "")
        )
        if _fold(field) in about and arp.is_fail_row(row):
            return PassReason.FAIL_PRESENT
    return PassReason.CONFLICT if len(_field_values(field, ctx)) > 1 else None


def verify_pass(proposal: dict, ctx) -> arp.Verdict:
    """THE PASS GATE. Accept only when every check in the module docstring holds; the first failure is the refusal."""
    if not settings.ai_review_pass_enabled:
        return arp.Verdict(False, PassReason.SWITCH_OFF, proposal)
    bad = arp._common(proposal, ctx)  # confidence, reason present, size
    doc_quote, bad = (None, bad) if bad else _document_quote(proposal, ctx)
    clause_quote = None
    if not bad:
        clause_quote, bad = _clause_quote(proposal, ctx)
    shown = None
    if not bad:
        shown, bad = _figure_check(proposal, clause_quote, doc_quote)
    field = str(proposal.get("field") or "").strip()
    bad = bad or _sheet_check(field, ctx)
    if not bad and not _same_reading(proposal, proposal.get("second")):
        bad = PassReason.READINGS
    if bad:
        return arp.Verdict(False, bad, proposal)
    return arp.Verdict(
        True, None, proposal, row_kind=PASS_ROW_KIND, final_text=f"{field}: {shown}."
    )


def internal_words(plain: str) -> str:
    """What the internal copy's row says; the contractor copy shows only `plain`."""
    return f"{INTERNAL_LABEL}. {plain}"


def stored_clause_text(review_run_id: str) -> dict[tuple[str, str], str]:
    """(standard file name, clause) -> the stored requirement text, for the standards this run holds. Read only."""
    from .db import connect

    out: dict[tuple[str, str], str] = {}
    for r in connect().execute(
        """SELECT d.filename AS name, r.clause AS clause, r.requirement_text AS text, r.source_text AS source
           FROM review_applicable_standards a
           JOIN documents d ON d.id = a.standard_document_id
           JOIN standard_requirements r ON r.standard_document_id = a.standard_document_id
                AND r.superseded_at IS NULL
           WHERE a.review_run_id = ? AND COALESCE(a.included, 1) = 1 AND r.clause IS NOT NULL""",
        (review_run_id,),
    ):
        text = " ".join(t for t in (r["text"], r["source"]) if t)
        key = (r["name"], str(r["clause"]))
        out[key] = (out.get(key, "") + " " + text).strip()
    return out
