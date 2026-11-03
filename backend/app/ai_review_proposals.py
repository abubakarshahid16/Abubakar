"""AI engineering review pass, part 1: the proposal schema and the CODE verifier (pure functions, no model, no db).

Owner order 3 Nov 2026 (lane 6). After the draft CRS an AI pass reads the whole document and the draft and PROPOSES:
remove a comment that is wrong in context, add a missed comment, reword a comment, and a short document-understanding note.
AI UNDERSTANDS AND PROPOSES; CODE VERIFIES AND DECIDES; THE ENGINEER DECIDES. `verify` is the only way a proposal is accepted.

REFUSED, ENFORCED HERE (the first failure is the reason):
  * a value, page or clause the proposal cites that is not on the cited submittal page or not a clause read from a held
    standard (`ai_engineering_check` uses the same helpers);
  * a number in its words that is on no cited page and not in the row it touches;
  * a pass or fail word in its words (`ai_engineering_check.PASS_FAIL_WORDS`): the engine's and the engineer's words;
  * confidence "high" (CLAUDE.md rule 4);
  * a removal of a Fail (`non_compliant`) row unless its basis is verified: a MISREAD (`row_value`, the figure the row printed, is in the
    row's words and is not on the page, and the page shows `value`) or OUT OF SCOPE (the rulebook says the clause is outside this equipment).
    A removal of any other row must cite verified evidence quotes; "different tags with different values" is such a basis;
  * a removal of a safety row or of a "pages not readable" row, ever;
  * a PASS can never be created: an added row's kind is chosen by CODE (`ADDED_KIND`), never by the AI, and it is
    `needs_engineer_review` unless the code's own comparison (`Context.compare`) says `non_compliant`; there is no
    conforming kind in the schema, and a reworded row may not reverse its row (`crs_wording.lock`).
This module changes nothing: it returns a verdict per proposal. It is not in the danger zone list; it never decides a
row's compliance, it only refuses.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from . import crs_wording, numparse, standard_ids
from .ai_engineering_check import PASS_FAIL_WORDS
from .reader_api import _contains, _fold

TYPES = ("remove", "add", "reword", "understanding")
CONFIDENCES = ("low", "medium")  # never "high"
MAX_PROPOSALS = 30
MAX_TEXT_CHARS = 600
#: Rows an AI may never remove, whatever it says.
PROTECTED_KINDS = ("safety_tick", "pages_not_readable")
FAIL_KIND = "non_compliant"
#: The kind of a row the pass ADDS. Chosen by code. There is no conforming kind to choose.
ADDED_KIND = "needs_engineer_review"
BASES = ("misread", "out_of_scope", "tag_difference", "context")
#: Bases that may remove a Fail row. "tag_difference" and "context" never do.
FAIL_REMOVING_BASES = ("misread", "out_of_scope")
UNDERSTANDING_KEYS = ("equipment", "tags", "service", "fluids", "revision_stage")
MAX_UNDERSTANDING_ITEMS = 40
#: An evidence quote shorter than this proves nothing ("a", "Tag" occur on every page). 8 characters is a short tag
#: plus a word ("Tag P-101B"); a single character or a bare common word can never be a removal's evidence.
MIN_QUOTE_CHARS = 8
#: A document-understanding item shorter than this (one or two characters) occurs inside almost any page.
MIN_UNDERSTANDING_CHARS = 3
#: Words that read as a verdict in other spelling. Added to `PASS_FAIL_WORDS` for this pass: "in line with the standard",
#: "acceptable" and the like are the engine's and the engineer's words, never the AI's.
EXTRA_VERDICT_WORDS = (
    "in line with", "in accordance with", "in agreement with", "in conformity", "agrees with the standard",
    "consistent with the standard", "within limits", "within the limit", "within limit", "within range",
    "within spec", "within specification", "as required by", "ok", "okay", "correct", "good", "fine",
    "compliance", "non-conformity", "nonconformity", "per the standard", "per standard",
)
_REQUIREMENT_WORDS = re.compile(
    r"\b(?:requires?|required|not less than|not more than|not exceed|at least|at most|minimum|maximum|min\.|max\.|shall|must)\b",
    re.IGNORECASE,
)
_ROW_STATES = re.compile(r"\b(?:datasheet|states?|stated|shows?|reads?|reported|printed)\b", re.IGNORECASE)


class Reason(Enum):
    MALFORMED = "proposal_malformed"
    BAD_TYPE = "type_not_known"
    MISSING_FIELD = "missing_field"
    BAD_CONFIDENCE = "confidence_not_low_or_medium"
    TOO_LONG = "too_long"
    PAGE_NOT_IN_DOCUMENT = "page_not_in_document"
    VALUE_NOT_ON_PAGE = "value_not_on_page"
    NUMBER_NOT_VERIFIED = "number_not_on_page_or_row"
    CLAUSE_NOT_VERIFIED = "clause_not_verified"
    EVIDENCE_NOT_ON_PAGE = "evidence_not_on_page"
    EVIDENCE_TOO_SHORT = "evidence_quote_too_short"
    PASS_FAIL_WORD = "pass_fail_word"
    NO_SUCH_ROW = "row_not_in_this_run"
    PROTECTED_ROW = "row_never_removed_by_ai"
    FAIL_KEPT = "fail_kept_no_verified_reason"
    NO_BASIS = "removal_has_no_verified_basis"
    DUPLICATE_ROW = "row_already_exists_for_this_field_and_page"
    REWORD_REFUSED = "reword_refused_by_lock"
    NOT_IN_DOCUMENT = "understanding_text_not_in_document"
    TOO_MANY = "more_than_the_limit"


@dataclass(frozen=True)
class Context:
    """Everything the verifier may look at. Built by the runner from the run; here it is plain data."""

    pages: Mapping[int, str]  # submittal page number -> text
    rows: Mapping[str, Mapping]  # crs_row_key -> CRS row (row_kind, comment, ...)
    held: Mapping[str, list[str]] = field(
        default_factory=dict
    )  # held standard -> clauses read from it
    out_of_scope: frozenset[tuple[str, str]] = (
        frozenset()
    )  # (standard, clause) the rulebook says is outside scope
    #: (field, value, standard, clause) -> "non_compliant" | "needs_engineer_review" | None; the code comparison.
    compare: Callable[[str, str, str, str], str | None] | None = None


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str | None
    proposal: dict
    row_kind: str | None = None  # for an accepted "add": the kind CODE chose
    final_text: str | None = None


def _page_of(proposal: dict, ctx: Context) -> int | None:
    page = proposal.get("page")
    return (
        page
        if isinstance(page, int) and not isinstance(page, bool) and page in ctx.pages
        else None
    )


def _words_of(proposal: dict) -> str:
    return " ".join(str(proposal.get(k) or "") for k in ("reason", "text"))


def _has_pass_fail_word(text: str) -> bool:
    folded = _fold(text)
    return any(_contains(folded, word) for word in (*PASS_FAIL_WORDS, *EXTRA_VERDICT_WORDS))


def _numbers_verified(
    proposal: dict, ctx: Context, page_text: str, row: Mapping | None
) -> bool:
    """Every number in the words is on the cited page, in the row it touches, or is a standard's own designator or clause."""
    prose = _words_of(proposal)
    names = standard_ids.cited_standards(prose)
    given = " ".join(
        [
            page_text,
            str((row or {}).get("comment") or ""),
            str((row or {}).get("standard_reference") or ""),
            str((row or {}).get("page_section") or ""),
            str(proposal.get("clause") or ""),
            str(proposal.get("standard") or ""),
        ]
    )
    allowed = numparse.number_keys(given) | numparse.number_keys(_fold(given))
    stripped = _fold(prose)
    for name in [*names, *ctx.held]:
        piece = _fold(name)
        if piece:
            stripped = stripped.replace(piece, " ")
    stripped = re.sub(
        r"(?:\bclause|\bcl\.|\bpara(?:graph)?\.?|\bsection|\bsec\.|\bpage|\bp\.|§)\s*\d+(?:\.\d+)*[a-z]?",
        " ",
        stripped,
    )
    return numparse.number_keys(stripped) <= allowed


def _clause_held(proposal: dict, ctx: Context) -> bool:
    """A clause is verified only when it is one read from a held standard the proposal names."""
    clause = str(proposal.get("clause") or "").strip()
    if not clause:
        return True
    standard = str(proposal.get("standard") or "")
    for name, clauses in ctx.held.items():
        stem = re.sub(r"\.(pdf|docx?)$", "", name, flags=re.IGNORECASE)
        if (
            standard
            and standard_ids.same_standard(standard, stem)
            and clause in clauses
        ):
            return True
    return False


def _evidence_ok(proposal: dict, ctx: Context) -> str | None:
    """None when every evidence quote stands, whole, on the page it names; else the refusal reason."""
    evidence = proposal.get("evidence") or []
    if not isinstance(evidence, list):
        return Reason.MALFORMED.value
    for item in evidence:
        if not isinstance(item, dict):
            return Reason.MALFORMED.value
        page, quote = item.get("page"), str(item.get("quote") or "").strip()
        if not isinstance(page, int) or isinstance(page, bool) or page not in ctx.pages:
            return Reason.PAGE_NOT_IN_DOCUMENT.value
        if len(quote) < MIN_QUOTE_CHARS:
            return Reason.EVIDENCE_TOO_SHORT.value
        if _fold(quote) not in _fold(ctx.pages[page]):
            return Reason.EVIDENCE_NOT_ON_PAGE.value
    return None


def _evidence_carries_value(proposal: dict) -> bool:
    """When the proposal cites a value, at least one evidence quote contains it: the quote is what the reason relies on."""
    value = str(proposal.get("value") or "").strip()
    if not value:
        return True
    return any(
        isinstance(i, dict) and numparse.value_in_text(value, str(i.get("quote") or ""))
        for i in proposal.get("evidence") or []
    )


def _unit_of(figure: str) -> str:
    """The unit word of a figure like "14 barg" ("" when it is a bare number or a clause)."""
    rest = re.sub(r"^[\s+\-\u2212]*[\d.,]+\s*", "", _fold(figure)).strip()
    return rest if re.fullmatch(r"[a-z%/\u00b0\u00b2\u00b3.\-]+(?: ?[a-z/]+)?", rest) else ""


def _row_printed(figure: str, row: Mapping) -> bool:
    """`figure` is a figure the ROW states for the datasheet: in a sentence of its comment that reports the datasheet
    ("Datasheet p.1, MAWP states 13 barg") and in no sentence that gives the standard's requirement or clause."""
    comment = str(row.get("comment") or "")
    ref = str(row.get("standard_reference") or "")
    if numparse.value_in_text(figure, ref):
        return False
    stated = False
    for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z])", comment):
        if not numparse.value_in_text(figure, sentence):
            continue
        if _REQUIREMENT_WORDS.search(sentence) and not _ROW_STATES.search(sentence):
            return False
        if _ROW_STATES.search(sentence):
            stated = True
    return stated


def _common(proposal: dict) -> str | None:
    """The checks every type shares. The first failure is the reason."""
    if proposal.get("confidence") not in CONFIDENCES:
        return Reason.BAD_CONFIDENCE.value
    if not str(proposal.get("reason") or "").strip():
        return Reason.MISSING_FIELD.value
    if len(_words_of(proposal)) > 2 * MAX_TEXT_CHARS:
        return Reason.TOO_LONG.value
    if _has_pass_fail_word(_words_of(proposal)):
        return Reason.PASS_FAIL_WORD.value
    return None


def _check_page_and_value(
    proposal: dict, ctx: Context
) -> tuple[int | None, str | None]:
    page = _page_of(proposal, ctx)
    if page is None:
        return None, Reason.PAGE_NOT_IN_DOCUMENT.value
    value = str(proposal.get("value") or "").strip()
    if value and not numparse.value_in_text(value, ctx.pages[page]):
        return page, Reason.VALUE_NOT_ON_PAGE.value
    return page, None


def _verify_remove(proposal: dict, ctx: Context) -> Verdict:
    def no(reason: Reason) -> Verdict:
        return Verdict(False, reason.value, proposal)

    key = str(proposal.get("row_key") or "")
    row = ctx.rows.get(key)
    if row is None:
        return no(Reason.NO_SUCH_ROW)
    # An unknown or differently-cased kind is read as a Fail: the safe reading never makes a row easier to remove.
    kind = str(row.get("row_kind") or "").strip().lower() or FAIL_KIND
    if kind in PROTECTED_KINDS:
        return no(Reason.PROTECTED_ROW)
    basis = str(proposal.get("basis") or "")
    if basis not in BASES:
        return no(Reason.NO_BASIS)
    page, bad = _check_page_and_value(proposal, ctx)
    if bad:
        return Verdict(False, bad, proposal)
    if not _clause_held(proposal, ctx):
        return no(Reason.CLAUSE_NOT_VERIFIED)
    bad = _evidence_ok(proposal, ctx)
    if bad:
        return Verdict(False, bad, proposal)
    if not proposal.get("evidence") and basis != "out_of_scope":
        return no(
            Reason.NO_BASIS
        )  # a removal needs at least one verified quote, except a rulebook scope
    if not _evidence_carries_value(proposal):
        return no(Reason.EVIDENCE_NOT_ON_PAGE)
    if not _numbers_verified(proposal, ctx, ctx.pages[page], row):
        return no(Reason.NUMBER_NOT_VERIFIED)
    if kind == FAIL_KIND:
        if basis not in FAIL_REMOVING_BASES:
            return no(Reason.FAIL_KEPT)
        if basis == "misread":
            # The row states a figure that is NOT on the page, and the page shows the value the AI cites.
            value = str(proposal.get("value") or "").strip()
            if not value or not numparse.value_in_text(value, ctx.pages[page]):
                return no(Reason.FAIL_KEPT)
            # `row_value` is the figure the ROW printed for the datasheet (not the standard's requirement, not a clause
            # number). `value` is what the contractor's page shows. Both carry a unit, the same unit; the page shows `value`
            # inside a quote of at least MIN_QUOTE_CHARS; the row does not already print `value`; the page lacks `row_value`.
            shown = str(proposal.get("row_value") or "").strip()
            unit = _unit_of(value)
            if not shown or not unit or _unit_of(shown) != unit:
                return no(Reason.FAIL_KEPT)
            if not _row_printed(shown, row) or numparse.value_in_text(
                value, str(row.get("comment") or "")
            ):
                return no(Reason.FAIL_KEPT)
            if numparse.value_in_text(shown, ctx.pages[page]):
                return no(Reason.FAIL_KEPT)
            m = re.search(r"\bp\.\s*(\d+)", str(row.get("page_section") or ""))
            if m and int(m.group(1)) != page:
                return no(Reason.FAIL_KEPT)
            if not proposal.get("evidence"):
                return no(Reason.FAIL_KEPT)
        else:  # out_of_scope: the rulebook, not the AI, says the clause is outside this equipment
            ref = str(row.get("standard_reference") or "")
            names = standard_ids.cited_standards(ref)
            clause = (
                str(proposal.get("clause") or "").strip()
                or (re.search(r"cl\.\s*(\S+?)(?:\s|\(|$)", ref) or [None, ""])[1]
            )
            if not any(
                (n, clause) in ctx.out_of_scope
                or any(
                    standard_ids.same_standard(n, s) and c == clause
                    for s, c in ctx.out_of_scope
                )
                for n in names
            ):
                return no(Reason.FAIL_KEPT)
    return Verdict(True, None, proposal)


def _verify_add(proposal: dict, ctx: Context) -> Verdict:
    def no(reason: str) -> Verdict:
        return Verdict(False, reason, proposal)

    for name in ("field", "value", "text"):
        if not str(proposal.get(name) or "").strip():
            return no(Reason.MISSING_FIELD.value)
    page, bad = _check_page_and_value(proposal, ctx)
    if bad:
        return no(bad)
    clause = str(proposal.get("clause") or "").strip()
    if not clause or not _clause_held(proposal, ctx):
        return no(
            Reason.CLAUSE_NOT_VERIFIED.value
        )  # a missed comment must cite a clause that was read
    if len(str(proposal["text"])) > MAX_TEXT_CHARS:
        return no(Reason.TOO_LONG.value)
    wanted = _fold(str(proposal["field"]))
    for row in ctx.rows.values():
        if (
            wanted
            and wanted in _fold(str(row.get("page_section") or ""))
            and f"p.{page}" in str(row.get("page_section") or "")
        ):
            return no(Reason.DUPLICATE_ROW.value)
    if not _numbers_verified(proposal, ctx, ctx.pages[page], None):
        return no(Reason.NUMBER_NOT_VERIFIED.value)
    kind = ADDED_KIND
    if ctx.compare is not None:
        verdict = ctx.compare(
            str(proposal["field"]),
            str(proposal["value"]),
            str(proposal.get("standard") or ""),
            clause,
        )
        if verdict == FAIL_KIND:
            kind = FAIL_KIND  # only the code comparison may make a Fail
    return Verdict(
        True, None, proposal, row_kind=kind, final_text=str(proposal["text"]).strip()
    )


def _verify_reword(proposal: dict, ctx: Context) -> Verdict:
    row = ctx.rows.get(str(proposal.get("row_key") or ""))
    if row is None:
        return Verdict(False, Reason.NO_SUCH_ROW.value, proposal)
    text = str(proposal.get("text") or "").strip()
    if not text:
        return Verdict(False, Reason.MISSING_FIELD.value, proposal)
    refused = crs_wording.lock(text, dict(row))
    if refused:
        return Verdict(False, f"{Reason.REWORD_REFUSED.value}:{refused}", proposal)
    return Verdict(True, None, proposal, final_text=text)


def _verify_understanding(proposal: dict, ctx: Context) -> Verdict:
    note = proposal.get("understanding")
    if not isinstance(note, dict) or not note:
        return Verdict(False, Reason.MALFORMED.value, proposal)
    pages = [_fold(t) for t in ctx.pages.values()]  # one page at a time: text spanning two pages is no quote
    count = 0
    for key, value in note.items():
        if key not in UNDERSTANDING_KEYS:
            return Verdict(False, Reason.MALFORMED.value, proposal)
        for item in value if isinstance(value, list) else [value]:
            text = str(item or "").strip()
            if not text:
                continue
            count += 1
            if _has_pass_fail_word(text):
                return Verdict(False, Reason.PASS_FAIL_WORD.value, proposal)
            if len(text) < MIN_UNDERSTANDING_CHARS:
                return Verdict(False, Reason.NOT_IN_DOCUMENT.value, proposal)
            if not any(_fold(text) in page for page in pages):
                return Verdict(False, Reason.NOT_IN_DOCUMENT.value, proposal)
    if count > MAX_UNDERSTANDING_ITEMS:
        return Verdict(False, Reason.TOO_LONG.value, proposal)
    return Verdict(True, None, proposal)


def verify(proposal: object, ctx: Context) -> Verdict:
    """THE GATE. Accept a proposal only when every value, page and clause it cites is verified."""
    if not isinstance(proposal, dict):
        return Verdict(False, Reason.MALFORMED.value, {"raw": str(proposal)[:80]})
    kind = proposal.get("type")
    if kind not in TYPES:
        return Verdict(False, Reason.BAD_TYPE.value, proposal)
    if kind == "understanding":
        if proposal.get("confidence") not in CONFIDENCES:
            return Verdict(False, Reason.BAD_CONFIDENCE.value, proposal)
        return _verify_understanding(proposal, ctx)
    bad = _common(proposal)
    if bad:
        return Verdict(False, bad, proposal)
    return {"remove": _verify_remove, "add": _verify_add, "reword": _verify_reword}[
        kind
    ](proposal, ctx)


def verify_all(proposals: object, ctx: Context) -> list[Verdict]:
    """Every proposal gets a verdict, in order. More than MAX_PROPOSALS: the rest are refused, never silently dropped.
    A removal and a reword of the same row: the removal stands only if the reword was not also accepted (one change per row)."""
    if not isinstance(proposals, list):
        return [Verdict(False, Reason.MALFORMED.value, {})]
    out, touched = [], set()
    for i, item in enumerate(proposals):
        if i >= MAX_PROPOSALS:
            out.append(
                Verdict(
                    False, Reason.TOO_MANY.value, item if isinstance(item, dict) else {}
                )
            )
            continue
        verdict = verify(item, ctx)
        key = str(verdict.proposal.get("row_key") or "")
        if verdict.accepted and verdict.proposal.get("type") in ("remove", "reword"):
            if key in touched:
                verdict = Verdict(
                    False,
                    Reason.NO_SUCH_ROW.value + ":row_already_changed",
                    verdict.proposal,
                )
            else:
                touched.add(key)
        out.append(verdict)
    return out
