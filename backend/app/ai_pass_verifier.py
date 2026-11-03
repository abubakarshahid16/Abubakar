# ruff: noqa: RUF001 - the unreadable-value table names look-alike dashes and spaces on purpose
"""AI engineering review pass, part 4: the AI may CREATE A PASS, only when CODE verifies both quotes. Lane 6 (owner order).

DANGER ZONE: this is the one place a Pass is created. Behind `AI_REVIEW_PASS_ENABLED` (default OFF; the owner turns it on).
The AI reads and proposes (`type: "pass"`); code verifies and decides; the engineer decides last (the row is never
confirmed). THE DESIGN IS AN ALLOW-LIST: a Pass exists only for text that reduces to one closed shape, and anything else
(any other sentence, any word the shape does not consume) is refused, so there is no list of synonyms to keep complete.

A Pass is accepted ONLY when, in order (the first failure is the refusal):

  1. the switch is on;
  2. the ENTIRE stored text of the clause (heading to next heading, all its sentences) is exactly ONE requirement sentence of
     the closed shape `<subject> shall be <comparator phrase> <plain number> <unit>.` (or `<subject> shall not exceed
     <number> <unit>.`) or `<subject> shall be <term>.`; the clause quote stands in it and carries the comparator and the
     figure; `scope_applies` is exactly "yes";
  3. the clause subject and the field name the same thing: the two word sets are EQUAL, both ways ("Maximum design pressure"
     is not "design pressure"), and so are their quantity words;
  4. one DOCUMENT quote stands whole on the cited page and is exactly `<field> [:=] <plain value>`: no comparator, range,
     tolerance, exponent, percentage, approximation or placeholder, no edition or revision wording;
  5. the figure is compared BY CODE with the comparison's own unit-aware test; a term must equal the value exactly;
  6. no Fail row on the sheet for the same field role OR the same clause (whatever its label), and in the WHOLE document (every
     page, the label's whole block down to a blank line) the field has one value only and no placeholder ("TBC", "not
     tested", "by others"...). The term path is guarded the same way;
  7. two independent readings agree: `call_id` and `second.call_id` are two DIFFERENT ids the runner issued
     (`Context.reading_ids`), and the second reading repeats field, page, document quote, clause quote, standard, clause, scope.

Silence, negation, "no contradiction", "unless stated" are never a Pass (CLAUDE.md rule 4). The AI still never removes a Fail
(`ai_review_proposals`). Nothing here reads the database or calls a model: the stored clause text arrives in the context.
"""

from __future__ import annotations

import re

from . import ai_review_proposals as arp
from . import claims, standard_ids, subject_pairing
from .config import settings
from .reader_api import _fold

PASS_ROW_KIND = "ai_judged_pass"
INTERNAL_LABEL = "Pass, decided by AI judgement with verified quotes"

#: The closed comparator phrases, as whole phrases. A clause is read only if its one sentence is built from exactly one.
_GE = (
    r"not\s+less\s+than|not\s+lower\s+than|not\s+smaller\s+than|not\s+below|at\s+least|"
    r"greater\s+than\s+or\s+equal\s+to|minimum\s+of|minimum"
)
_LE = (
    r"not\s+more\s+than|not\s+greater\s+than|not\s+higher\s+than|not\s+larger\s+than|not\s+above|at\s+most|"
    r"less\s+than\s+or\s+equal\s+to|maximum\s+of|maximum"
)
_SUBJECT = r"(?:the\s+)?(?P<subj>[a-z][a-z \-]*?)"
_SHAPE_NUMBER = re.compile(
    _SUBJECT
    + r"\s+shall\s+(?:be\s+(?:(?P<ge>"
    + _GE
    + r")|(?P<le>"
    + _LE
    + r"))|(?P<exceed>not\s+exceed))\s+(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[a-z\u00b0][a-z0-9\u00b0/]*)\s*\.?"
)
_SHAPE_TERM = re.compile(
    _SUBJECT + r"\s+shall\s+be\s+(?P<term>[a-z0-9][a-z0-9 \-]*?)\s*\.?"
)
_ANY_COMPARATOR = re.compile(r"\b(?:" + _GE + "|" + _LE + r"|not\s+exceed(?:ing)?)\b")
_NEGATION = re.compile(
    r"\b(?:no|not|non|never|none|without|unless|except|excepting|excluding|exclude|excluded|exempt|exempting|omitted|nil|"
    r"absent|missing|pending|instead|replaced|replace|replacing|optional|alternative|alternatively|other\s+than|or|and|"
    r"but|only|if|when|where|for|with|apart|aside|barring|save|whereas|although|subject|whichever|either|neither|nor)\b"
)
_PLACEHOLDER = re.compile(
    r"\b(?:tba|tbc|tbd|tbn|n[./]?a|by\s+others|by\s+vendor|by\s+contractor|vendor\s+to\s+advise|to\s+be\s+"
    r"(?:provided|confirmed|advised|determined|decided|agreed|supplied|announced)|not\s+applicable|not\s+available|"
    r"not\s+tested|not\s+required|not\s+known|unknown|see\s+\w+|as\s+per|per\s+\w+|latest|current)\b"
)
_EDITION = re.compile(
    r"\b(?:editions?|revisions?|versions?|latest|current|amended|amendments?|addend\w+)\b"
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
    SUBJECT = "pass_clause_subject_is_not_the_field"


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


def _words(label: str) -> frozenset[str]:
    """ALL the words of a name, hyphenated compounds joined ("Hydro-test" is "hydrotest"), articles dropped."""
    joined = re.sub(r"(?<=[a-z])-(?=[a-z])", "", _fold(label))
    return frozenset(
        w for w in re.findall(r"[a-z]+", joined) if w not in {"the", "a", "an", "of"}
    )


def _overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    """True when two names share a word (or one contains the other, from 4 letters): over-refusal on purpose."""
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
    if any(str(second.get(k)) != str(proposal.get(k)) for k in ("page", "clause")):
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
    """(quote, None) when one document quote stands, whole, on the cited page and holds no placeholder or edition wording."""
    page = arp._page_of(proposal, ctx)
    evidence = proposal.get("evidence")
    if (
        page is None
        or not str(proposal.get("field") or "").strip()
        or not isinstance(evidence, list)
        or len(evidence) != 1
        or not isinstance(evidence[0], dict)
        or evidence[0].get("page") != page
        or arp._evidence_ok(proposal, ctx) is not None
    ):
        return None, PassReason.NO_DOC_QUOTE
    quote = str(evidence[0]["quote"]).strip()
    if _EDITION.search(_fold(quote)):
        return None, PassReason.EDITION
    if _PLACEHOLDER.search(_fold(quote)):
        return None, PassReason.PLACEHOLDER
    return quote, None


def _value_cell(field: str, quote: str) -> str | None:
    """The text after the field's name: the quote must BEGIN with the field and hold nothing else before the value."""
    m = re.fullmatch(rf"{re.escape(_fold(field))}\s*[:=]?\s*(?P<v>\S.*)", _fold(quote))
    return m.group("v").strip() if m else None


def _clause_shape(proposal: dict, ctx):
    """((quote, match), None) when the ENTIRE stored clause text is one sentence of the closed shape and the quote stands in
    it; else (None, reason). `match` is the shape's regex match (kind "number" or "term")."""
    text = _clause_text(proposal, ctx)
    if text is None:
        return None, PassReason.NO_CLAUSE
    quote = str(proposal.get("clause_quote") or "").strip()
    if len(quote) < arp.MIN_QUOTE_CHARS or _fold(quote) not in _fold(text):
        return None, PassReason.CLAUSE_QUOTE
    if str(proposal.get("scope_applies") or "").strip().lower() != "yes":
        return None, PassReason.SCOPE
    plain = _plain_number(text)
    if plain is None or _EDITION.search(plain):
        return None, PassReason.EDITION if plain is not None else PassReason.UNREADABLE
    plain = plain.strip()
    number = _SHAPE_NUMBER.fullmatch(plain)
    if number is not None:
        if _NEGATION.search(number.group("subj")):
            return None, PassReason.NEGATION
        quoted = _plain_number(quote) or ""
        if f"{number.group('num')} {number.group('unit')}".replace(
            "  ", " "
        ) not in re.sub(r"\s+", " ", quoted):
            return (
                None,
                PassReason.CLAUSE_QUOTE,
            )  # the quote must carry the figure the sentence states
        return ("number", number), None
    if _ANY_COMPARATOR.search(plain) or (
        re.search(r"\d+\s*[a-z]", plain) and claims.extract_measurements(plain)
    ):
        return (
            None,
            PassReason.NO_FIGURE,
        )  # a comparator or a figure that is not in the closed shape
    term = _SHAPE_TERM.fullmatch(plain)
    if term is None:
        return None, PassReason.NO_TERM
    if _NEGATION.search(term.group("subj")) or _NEGATION.search(term.group("term")):
        return None, PassReason.NEGATION
    if _PLACEHOLDER.search(term.group("term")) or not re.search(
        r"[a-z]", term.group("term")
    ):
        return None, PassReason.NO_TERM
    return ("term", term), None


def _subject_ok(field: str, subject: str) -> bool:
    """The clause subject and the field name the same thing: the SAME words (both ways, nothing extra either side) and the
    same quantity words (the repo's own). "Maximum design pressure" is not "design pressure"."""
    mine, theirs = _words(field), _words(subject)
    if not mine or mine != theirs:
        return False
    quantity = subject_pairing.quantity_words(subject)
    return bool(quantity) and quantity == subject_pairing.quantity_words(field)


def _numeric(field: str, match, doc_quote: str) -> tuple[str | None, str | None]:
    """The figure path: the clause sentence is the closed shape, the document holds a plain `<field> <number> <unit>`."""
    value_cell = _value_cell(field, doc_quote)
    plain_cell = _plain_number(value_cell) if value_cell is not None else None
    if value_cell is None or plain_cell is None:
        return None, PassReason.UNREADABLE
    if _NEGATION.search(plain_cell):
        return None, PassReason.NEGATION
    if _NUMBER_UNIT.fullmatch(plain_cell) is None:
        return None, PassReason.NO_FIGURE
    observed = claims.extract_measurements(plain_cell)
    if len(observed) != 1 or observed[0].comparator is not None:
        return None, PassReason.UNREADABLE
    symbol = ">=" if match.group("ge") else "<="
    limit = claims.normalise(match.group("num"), match.group("unit"), symbol)
    value = claims.normalise(observed[0].raw_value, observed[0].raw_unit)
    verdict = _satisfies(value, limit)
    if verdict is None:
        return None, PassReason.NOT_COMPARABLE
    if verdict is not True:
        return None, PassReason.NOT_SATISFIED
    return (
        f"the submittal states {observed[0].raw_value} {observed[0].raw_unit} and the clause requires "
        f"{symbol} {match.group('num')} {match.group('unit')}",
        claims.unit_dimension(observed[0].raw_unit) or "",
    )


def _term(field: str, match, doc_quote: str) -> tuple[str | None, str | None]:
    """The term path: the term is read from the clause sentence by code, the document's whole value must equal it."""
    cell = _value_cell(field, doc_quote)
    term = match.group("term").strip()
    if cell is None or _NEGATION.search(cell) or _PLACEHOLDER.search(cell):
        return None, PassReason.NEGATION if cell is not None else PassReason.NO_TERM
    if _squash(cell) != _squash(term):
        return None, PassReason.NO_TERM
    return f'the submittal states "{cell}" and the clause requires "{term}"', ""


def _block(lines: list[str], i: int) -> list[str]:
    """The label's line and the lines after it down to a blank line (its cell block or table region), at most 12."""
    out = [lines[i]]
    for nxt in lines[i + 1 : i + 13]:
        if not nxt.strip():
            break
        out.append(nxt)
    return out


def _document_guard(field: str, ctx, dimension: str, my_cell: str) -> str | None:
    """Over EVERY page: the field must have one value only and no placeholder. Numeric: every figure of the quantity in the
    label's block. Term: the value cell of every line that begins with the field's name."""
    mine = _words(field)
    label = _fold(field)
    figures: set[tuple[float, str]] = set()
    cells: set[str] = set()
    for text in ctx.pages.values():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not _overlap(mine, _words(line)):
                continue
            block = _block(lines, i)
            if any(_PLACEHOLDER.search(_fold(b)) for b in block):
                return PassReason.PLACEHOLDER
            if dimension:
                for b in block:
                    plain = _plain_number(b) or b
                    for meas in claims.extract_measurements(plain):
                        if (
                            meas.normalized_value is not None
                            and claims.unit_dimension(meas.raw_unit) == dimension
                        ):
                            figures.add(
                                (
                                    meas.normalized_value,
                                    meas.normalized_unit or meas.raw_unit,
                                )
                            )
            elif _fold(line).startswith(label):
                cell = _value_cell(field, line)
                if cell is None or _PLACEHOLDER.search(cell) or _NEGATION.search(cell):
                    return (
                        PassReason.PLACEHOLDER
                        if cell is not None
                        else PassReason.CONFLICT
                    )
                cells.add(_squash(cell))
    if len(figures) > 1:
        return PassReason.CONFLICT
    if not dimension and (len(cells) > 1 or (cells and cells != {_squash(my_cell)})):
        return PassReason.CONFLICT
    return None


_REF_NUMBER = r"(?<![\w.]){}(?![\w])"


def _fail_check(field: str, clause_number: str, standard: str, ctx) -> str | None:
    """A reason when the sheet holds a Fail on the same field role, or on the same clause of the same standard, whatever the
    row's label says."""
    mine = _words(field)
    for row in ctx.rows.values():
        if not arp.is_fail_row(row):
            continue
        about = " ".join(str(v) for v in row.values() if isinstance(v, str))
        if _overlap(mine, _words(about)):
            return PassReason.FAIL_PRESENT
        cited = standard_ids.cited_standards(about)
        if any(
            standard_ids.same_standard(standard, name) for name in cited
        ) and re.search(_REF_NUMBER.format(re.escape(clause_number)), about):
            return PassReason.FAIL_PRESENT
    return None


def verify_pass(proposal: dict, ctx) -> arp.Verdict:
    """THE PASS GATE. Accept only when every check in the module docstring holds; the first failure is the refusal."""
    if not settings.ai_review_pass_enabled:
        return arp.Verdict(False, PassReason.SWITCH_OFF, proposal)
    field = str(proposal.get("field") or "").strip()
    clause_number = str(proposal.get("clause") or "").strip()
    bad = arp._common(proposal, ctx)  # confidence, reason present, size
    doc_quote, bad = (None, bad) if bad else _document_quote(proposal, ctx)
    shape = None
    if not bad:
        shape, bad = _clause_shape(proposal, ctx)
    if not bad and not _subject_ok(field, shape[1].group("subj")):
        bad = PassReason.SUBJECT
    shown, dimension = None, ""
    if not bad:
        shown, dimension = (_numeric if shape[0] == "number" else _term)(
            field, shape[1], doc_quote
        )
        if shown is None:
            bad, dimension = dimension, ""
    if not bad:
        bad = _fail_check(
            field, clause_number, str(proposal.get("standard") or ""), ctx
        )
    if not bad:
        bad = _document_guard(
            field, ctx, dimension or "", _value_cell(field, doc_quote) or ""
        )
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
    """(standard file name, clause) -> the stored text of that clause for the standards this run holds: the passage each
    requirement was read from (its requirement text when no passage is stored), distinct passages only. Read only."""
    from .db import connect

    out: dict[tuple[str, str], list[str]] = {}
    for r in connect().execute(
        """SELECT d.filename AS name, r.clause AS clause, r.requirement_text AS text, r.source_text AS source
           FROM review_applicable_standards a
           JOIN documents d ON d.id = a.standard_document_id
           JOIN standard_requirements r ON r.standard_document_id = a.standard_document_id
                AND r.superseded_at IS NULL
           WHERE a.review_run_id = ? AND COALESCE(a.included, 1) = 1 AND r.clause IS NOT NULL""",
        (review_run_id,),
    ):
        parts = out.setdefault((r["name"], str(r["clause"])), [])
        passage = (r["source"] or r["text"] or "").strip()
        if passage and passage not in parts:
            parts.append(passage)
    return {k: " ".join(v) for k, v in out.items()}
