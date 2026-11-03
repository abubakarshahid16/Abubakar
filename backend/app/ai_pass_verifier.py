# ruff: noqa: RUF001 - the unreadable-value table names look-alike dashes and spaces on purpose
"""AI engineering review pass, part 4: the AI may CREATE A PASS, only when CODE verifies both quotes. Lane 6 (owner order).

DANGER ZONE: this is the one place a Pass is created. Behind `AI_REVIEW_PASS_ENABLED` (default OFF; the owner turns it on).
The AI reads and proposes (`type: "pass"`); code verifies and decides; the engineer decides last (the row is never
confirmed). A Pass is accepted ONLY when every one of these holds, the first failure being the refusal:

  1. the switch is on;
  2. one DOCUMENT quote stands, whole, on the cited page, and is EXACTLY `<field> [:=] <plain value>`: nothing else may sit
     before, between or after (a comparator word or symbol, a range, a tolerance, an exponent, a percentage, "or less",
     "approx." make the quote unreadable, so no Pass). Placeholders (TBA, TBC, by others, excluded, omitted...) and
     edition/revision wording are never a Pass;
  3. the standard and clause resolve to STORED clause text, the CLAUSE quote stands in it, the scope is confirmed (the
     clause's condition or exception text is quoted from the stored text, and `scope_applies` is exactly "yes");
  4. the comparator is read from the clause quote BY CODE with a closed table (longest phrase first; exactly one match; no
     other negation; one plain figure) and the value from the document quote BY CODE; the unit-aware comparison
     (`claims`) must say the value satisfies it. A requirement with no figure is read BY CODE from the clause as
     "shall be <term>" (not from the AI's word) and the document's value must equal that term exactly, so "low carbon steel",
     "non-stainless steel", "316 stainless steel" for a 304 clause, "instead of..." all fail;
  5. no Fail row on the sheet whose field overlaps the field, and the document does not give an overlapping field two values
     (matching is by the words of the field, hyphens joined, any shared word counts: "Test pressure" and "Hydro-test
     pressure" are caught; over-refusal is the safe side);
  6. two independent readings agree: `call_id` and `second.call_id` are two DIFFERENT ids the runner issued
     (`Context.reading_ids`), never the AI's own words, and the second reading repeats field, page, document quote, clause
     quote, standard, clause and scope.

Silence, negation, "no contradiction", "unless stated" are never a Pass (CLAUDE.md rule 4). The AI still never removes a Fail
(`ai_review_proposals`). Nothing here reads the database or calls a model: the stored clause text arrives in the context.
"""

from __future__ import annotations

import re

from . import ai_review_proposals as arp
from . import claims, standard_ids
from .config import settings
from .reader_api import _fold

PASS_ROW_KIND = "ai_judged_pass"
INTERNAL_LABEL = "Pass, decided by AI judgement with verified quotes"

#: The closed comparator table. Longest phrase first inside each group; the whole quote must hold exactly ONE match.
_GE = (
    r"not\s+(?:to\s+)?(?:be\s+)?(?:less|lower|smaller)\s+than",
    r"no\s+(?:less|lower|smaller)\s+than",
    r"(?:greater|more|higher)\s+than\s+or\s+equal\s+to",
    r"not\s+(?:to\s+)?(?:be\s+)?below",
    r"at\s+least",
    r"minimum(?:\s+of)?",
    r"min\.?",
    r"≥",
    r">=",
)
_LE = (
    r"not\s+(?:to\s+)?(?:be\s+)?(?:more|greater|higher|larger)\s+than",
    r"no\s+(?:more|greater|higher|larger)\s+than",
    r"(?:less|lower|smaller)\s+than\s+or\s+equal\s+to",
    r"not\s+(?:to\s+)?(?:be\s+)?above",
    r"not\s+exceed(?:ing)?",
    r"at\s+most",
    r"maximum(?:\s+of)?",
    r"max\.?",
    r"≤",
    r"<=",
)
_COMPARATOR = re.compile(
    r"(?<![\w])(?:(?P<ge>"
    + "|".join(_GE)
    + r")|(?P<le>"
    + "|".join(_LE)
    + r"))(?![\w])"
)
_NEGATION = re.compile(
    r"\b(?:no|not|non|never|none|without|unless|except|excluding|exclude|excluded|omitted|nil|absent|missing|pending|"
    r"instead|replaced|replace|replacing|optional|alternative|alternatively|other\s+than|or|but|only\s+if)\b"
)
_PLACEHOLDER = re.compile(
    r"\b(?:tba|tbc|tbd|tbn|n/?a|by\s+others|by\s+vendor|by\s+contractor|vendor\s+to\s+advise|to\s+be\s+"
    r"(?:provided|confirmed|advised|determined|decided|agreed|supplied|announced)|not\s+applicable|not\s+available|"
    r"see\s+\w+|as\s+per|per\s+\w+|latest|current)\b"
)
_EDITION = re.compile(
    r"\b(?:editions?|revisions?|versions?|latest|current|amended|amendments?|addend\w+)\b"
)
_MODAL_TERM = re.compile(
    r"\b(?:shall|must|is\s+to|are\s+to|will)\s+be(?:\s+of|\s+made\s+of)?\s+(?P<t>.+)$"
)
_SCOPE_MARKERS = re.compile(
    r"\b(?:except|unless|provided that|exception|where|if|when|only for|applies to|does not apply|not apply|for)\b"
)
#: Anything that makes a quoted value a range, a tolerance, an exponent, a sign, a percentage or an ambiguous number.
_UNREADABLE = re.compile(
    r"±|\+\s*/?\s*-|-\s*/\s*\+|[+\-−]\s*\d|\d\s*(?:to|through|thru|and|~|\.\.|…|–|—|−|-)\s*\d|"
    r"\bbetween\b|\brange\b|\btol(?:erance)?\b|\d\s*(?:x|\*|\^|e)\s*-?\d|\d\s*%|\bpercent\b|\bapprox\w*\b|\babout\b|"
    r"≈|~|\bor\s+(?:less|more|higher|lower)\b|\d[  ]\d{3}\b|\d[.,]\d{3}(?!\d)|\d,\d+,\d|\d\.\d+\.\d"
)
_NUMBER_UNIT = re.compile(r"(?P<n>\d+(?:[.,]\d+)?)\s*(?P<u>[a-z°][a-z0-9°/]*)")


class PassReason:
    SWITCH_OFF = "pass_switch_off"
    NO_DOC_QUOTE = "pass_document_quote_not_verified"
    NO_CLAUSE = "pass_clause_not_in_stored_text"
    CLAUSE_QUOTE = "pass_clause_quote_not_in_stored_text"
    SCOPE = "pass_scope_not_confirmed"
    NO_FIGURE = "pass_no_single_figure"
    NOT_COMPARABLE = "pass_units_not_comparable"
    NOT_SATISFIED = "pass_requirement_not_satisfied"
    NO_TERM = "pass_required_term_not_read_from_the_clause_or_not_the_value"
    NEGATION = "pass_quote_is_silence_or_negation"
    UNREADABLE = "pass_quote_value_not_plainly_readable"
    PLACEHOLDER = "pass_quote_is_a_placeholder"
    EDITION = "pass_edition_or_revision_is_never_a_pass"
    FAIL_PRESENT = "pass_fail_on_the_sheet"
    CONFLICT = "pass_field_has_two_values"
    READINGS = "pass_readings_disagree"


def _clause_text(proposal: dict, ctx) -> str | None:
    """The stored clause text for the standard and clause the proposal names, or None."""
    standard = str(proposal.get("standard") or "")
    clause = str(proposal.get("clause") or "").strip()
    if not standard or not clause:
        return None
    for (name, number), text in (getattr(ctx, "clause_text", None) or {}).items():
        stem = re.sub(r"\.(pdf|docx?)$", "", str(name), flags=re.IGNORECASE)
        if number == clause and standard_ids.same_standard(standard, stem):
            return str(text)
    return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_/]+", " ", _fold(text))).strip()


def _tokens(label: str) -> set[str]:
    """Significant words of a field label, hyphenated compounds joined ("Hydro-test" is "hydrotest")."""
    joined = re.sub(r"(?<=[a-z])-(?=[a-z])", "", _fold(label))
    return {
        w
        for w in re.findall(r"[a-z]{3,}", joined)
        if w not in {"the", "and", "for", "per"}
    }


def _overlap(a: set[str], b: set[str]) -> bool:
    """True when the two labels share a word (or one word contains the other, from 4 letters): over-refusal on purpose."""
    return any(
        x == y or (len(x) >= 4 and len(y) >= 4 and (x in y or y in x))
        for x in a
        for y in b
    )


def _readings_agree(proposal: dict, ctx) -> bool:
    """Two independent readings: two different call ids the runner issued, and the same reading."""
    second = proposal.get("second")
    ids = getattr(ctx, "reading_ids", frozenset())
    first_id = str(proposal.get("call_id") or "")
    if not isinstance(second, dict) or not first_id or first_id not in ids:
        return False
    second_id = str(second.get("call_id") or "")
    if not second_id or second_id == first_id or second_id not in ids:
        return False
    same = ("page", "clause")
    if any(str(second.get(k)) != str(proposal.get(k)) for k in same):
        return False
    if _squash(str(second.get("field") or "")) != _squash(
        str(proposal.get("field") or "")
    ):
        return False
    if not standard_ids.same_standard(
        str(second.get("standard") or ""), str(proposal.get("standard") or "")
    ):
        return False
    first_doc = str((proposal.get("evidence") or [{}])[0].get("quote") or "")
    if _fold(str(second.get("doc_quote") or "")) != _fold(first_doc):
        return False
    if _fold(str(second.get("clause_quote") or "")) != _fold(
        str(proposal.get("clause_quote") or "")
    ):
        return False
    return str(second.get("scope_applies") or "").strip().lower() == "yes"


def _plain_number(text: str) -> str | None:
    """Decimal comma to dot; None when the text is not plainly readable (range, tolerance, sign, exponent, thousands...)."""
    folded = _fold(text)
    if _UNREADABLE.search(folded):
        return None
    return re.sub(r"(\d),(\d{1,2})(?!\d)", r"\1.\2", folded)


def _satisfies(observed: claims.Measurement, limit: claims.Measurement) -> bool | None:
    crossed = claims.compare_across_units(observed, limit)
    if crossed is not None:
        return crossed.verdict
    return claims._compatible(observed, limit)


def _document_quote(proposal: dict, ctx) -> tuple[str | None, str | None]:
    """(quote, None) when one document quote stands, whole, on the cited page and starts with the field's name."""
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
    ):
        return None, PassReason.NO_DOC_QUOTE
    quote = str(evidence[0]["quote"]).strip()
    folded = _fold(quote)
    if _EDITION.search(folded):
        return None, PassReason.EDITION
    if _PLACEHOLDER.search(folded):
        return None, PassReason.PLACEHOLDER
    return quote, None


def _value_cell(field: str, quote: str) -> str | None:
    """The text after the field's name: the quote must BEGIN with the field and hold nothing else before the value."""
    m = re.fullmatch(rf"{re.escape(_fold(field))}\s*[:=]?\s*(?P<v>\S.*)", _fold(quote))
    return m.group("v").strip() if m else None


def _clause_quote(proposal: dict, ctx) -> tuple[str | None, str | None]:
    """(clause quote, None) when the clause resolves to stored text, the quote stands in it and the scope is confirmed."""
    clause_text = _clause_text(proposal, ctx)
    if clause_text is None:
        return None, PassReason.NO_CLAUSE
    quote = str(proposal.get("clause_quote") or "").strip()
    if len(quote) < arp.MIN_QUOTE_CHARS or _fold(quote) not in _fold(clause_text):
        return None, PassReason.CLAUSE_QUOTE
    if _EDITION.search(_fold(quote)):
        return None, PassReason.EDITION
    if str(proposal.get("scope_applies") or "").strip().lower() != "yes":
        return None, PassReason.SCOPE
    if _SCOPE_MARKERS.search(_fold(clause_text)):
        shown = str(proposal.get("scope_quote") or "").strip()
        if len(shown) < arp.MIN_QUOTE_CHARS or _fold(shown) not in _fold(clause_text):
            return None, PassReason.SCOPE
    return quote, None


def _numeric(
    field: str, clause_quote: str, doc_quote: str
) -> tuple[str | None, str | None]:
    """The figure path: the closed comparator table on the clause, a plain `<field> <number> <unit>` in the document."""
    clause = _plain_number(clause_quote)
    value_cell = _value_cell(field, doc_quote)
    plain_cell = _plain_number(value_cell) if value_cell is not None else None
    if clause is None or value_cell is None or plain_cell is None:
        return None, PassReason.UNREADABLE
    matches = list(_COMPARATOR.finditer(clause))
    if len(matches) != 1:
        return None, PassReason.NO_FIGURE
    rest = clause[: matches[0].start()] + " " + clause[matches[0].end() :]
    if _NEGATION.search(rest) or len(re.findall(r"\d+(?:\.\d+)?", rest)) != 1:
        return None, PassReason.NEGATION if _NEGATION.search(
            rest
        ) else PassReason.NO_FIGURE
    limit_figure = claims.extract_measurements(rest)
    if _NEGATION.search(plain_cell):
        return None, PassReason.NEGATION
    cell = _NUMBER_UNIT.fullmatch(plain_cell)
    if len(limit_figure) != 1 or cell is None:
        return None, PassReason.NO_FIGURE
    observed = claims.extract_measurements(plain_cell)
    if len(observed) != 1 or observed[0].comparator is not None:
        return None, PassReason.UNREADABLE
    symbol = ">=" if matches[0].group("ge") else "<="
    limit = claims.normalise(
        limit_figure[0].raw_value, limit_figure[0].raw_unit, symbol
    )
    value = claims.normalise(observed[0].raw_value, observed[0].raw_unit)
    verdict = _satisfies(value, limit)
    if verdict is None:
        return None, PassReason.NOT_COMPARABLE
    if verdict is not True:
        return None, PassReason.NOT_SATISFIED
    return (
        f"the submittal states {observed[0].raw_value} {observed[0].raw_unit} and the clause requires "
        f"{symbol} {limit_figure[0].raw_value} {limit_figure[0].raw_unit}",
        None,
    )


def _term(
    field: str, clause_quote: str, doc_quote: str
) -> tuple[str | None, str | None]:
    """The term path: the required term is read from the clause ("shall be <term>") by code, never taken from the AI, and the
    document's value must equal it exactly (whole value, so "low carbon steel" or "316 stainless steel" fail)."""
    cell = _value_cell(field, doc_quote)
    m = _MODAL_TERM.search(_fold(clause_quote).rstrip(" .;"))
    if cell is None or m is None:
        return None, PassReason.NO_TERM
    term = m.group("t").strip()
    if (
        not re.search(r"[a-z]", term)
        or _NEGATION.search(term)
        or _PLACEHOLDER.search(term)
    ):
        return None, PassReason.NO_TERM
    if _NEGATION.search(cell):
        return None, PassReason.NEGATION
    if _squash(cell) != _squash(term):
        return None, PassReason.NO_TERM
    return f'the submittal states "{cell}" and the clause requires "{term}"', None


def _figures(
    field: str, clause_quote: str, doc_quote: str
) -> tuple[str | None, str | None]:
    if _COMPARATOR.search(_fold(clause_quote)):
        return _numeric(field, clause_quote, doc_quote)
    return _term(field, clause_quote, doc_quote)


def _sheet_check(field: str, ctx) -> str | None:
    """A reason when the sheet holds a Fail whose field overlaps this one, or the document gives an overlapping field two
    values. Keyed on the words of the field, not on the AI's exact wording."""
    mine = _tokens(field)
    for row in ctx.rows.values():
        about = " ".join(
            str(row.get(k) or "")
            for k in ("page_section", "crs_field_label", "comment")
        )
        if arp.is_fail_row(row) and _overlap(mine, _tokens(about)):
            return PassReason.FAIL_PRESENT
    values: set[tuple[float, str]] = set()
    for text in ctx.pages.values():
        for line in text.splitlines():
            label = re.split(r"\d", line, maxsplit=1)[0]
            if not _overlap(mine, _tokens(label)):
                continue
            plain = _plain_number(line) or line
            for meas in claims.extract_measurements(plain)[:1]:
                if meas.normalized_value is not None:
                    values.add(
                        (meas.normalized_value, meas.normalized_unit or meas.raw_unit)
                    )
    return PassReason.CONFLICT if len(values) > 1 else None


def verify_pass(proposal: dict, ctx) -> arp.Verdict:
    """THE PASS GATE. Accept only when every check in the module docstring holds; the first failure is the refusal."""
    if not settings.ai_review_pass_enabled:
        return arp.Verdict(False, PassReason.SWITCH_OFF, proposal)
    bad = arp._common(proposal, ctx)  # confidence, reason present, size
    doc_quote, bad = (None, bad) if bad else _document_quote(proposal, ctx)
    clause_quote = None
    if not bad:
        clause_quote, bad = _clause_quote(proposal, ctx)
    field = str(proposal.get("field") or "").strip()
    shown = None
    if not bad:
        shown, bad = _figures(field, clause_quote, doc_quote)
    bad = bad or _sheet_check(field, ctx)
    if not bad and not _readings_agree(proposal, ctx):
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
