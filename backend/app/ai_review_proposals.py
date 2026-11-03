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
  * a removal of a Fail row, EVER (any case or spelling of the kind): a Fail stays on the CRS. For a suspected misread the AI may only
    FLAG the row (`flag`): the flag text is built by CODE from a verified page quote, the Fail stays and the engineer decides.
    A removal of any other removable row must cite verified evidence quotes; "different tags with different values" is such a basis;
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

TYPES = ("remove", "add", "reword", "understanding", "flag")
CONFIDENCES = ("low", "medium")  # never "high"
MAX_PROPOSALS = 30
MAX_TEXT_CHARS = 600
#: Rows an AI may never remove, whatever it says.
PROTECTED_KINDS = ("safety_tick", "pages_not_readable")
#: The ONLY row kinds an AI may remove: machine-drafted comments and the AI's own suggestions. Anything else (an engineer's
#: comment, a carried-forward row, a kind this list does not know, a row with no kind) is never removable.
REMOVABLE_KINDS = ("needs_engineer_review", "ai_engineering_check")
#: A datasheet self-check row is removable only when the result it carries is explicitly one of these (never a Fail).
DATASHEET_CHECK_NON_FAIL = ("needs_engineer_review",)
FAIL_SEVERITIES = ("critical", "major")
FAIL_KIND = "non_compliant"
#: The kind of a row the pass ADDS. Chosen by code. There is no conforming kind to choose.
ADDED_KIND = "needs_engineer_review"
BASES = ("tag_difference", "context")
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
    "in line with",
    "in line",
    "consistent with",
    "is consistent",
    "in accordance with",
    "in agreement with",
    "in conformity",
    "agrees with the standard",
    "consistent with the standard",
    "within limits",
    "within the limit",
    "within limit",
    "within range",
    "within spec",
    "within specification",
    "as required by",
    "ok",
    "okay",
    "correct",
    "good",
    "fine",
    "compliance",
    "non-conformity",
    "nonconformity",
    "per the standard",
    "per standard",
)


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


def _plain(text: str) -> str:
    """Hyphens, dashes, underscores and runs of spaces read as one space: "in-line  with" is "in line with"."""
    return re.sub(r"\s+", " ", re.sub(r"[-\u2010-\u2015_]+", " ", _fold(text))).strip()


def _has_pass_fail_word(text: str) -> bool:
    plain = _plain(text)
    return any(
        _contains(plain, _plain(word))
        for word in (*PASS_FAIL_WORDS, *EXTRA_VERDICT_WORDS)
    )


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


def _kind(row: Mapping) -> str:
    return re.sub(r"[\s\-]+", "_", str(row.get("row_kind") or "").strip().lower())


def is_fail_word(text: object) -> bool:
    """A Fail in any case or spelling ("non_compliant", "Non-Compliant", "NONCOMPLIANT", "fail")."""
    squeezed = re.sub(r"[^a-z]", "", str(text or "").lower())
    return (
        squeezed in ("fail", "failed", "fails")
        or "noncompliant" in squeezed
        or "nonconform" in squeezed
    )


def is_fail_row(row: Mapping) -> bool:
    """A row is a Fail when its kind OR the result it carries is one, or it is a datasheet self-check of major or critical
    severity (a failed requirement is never filed minor). The row's own kind alone is not trusted: a datasheet check that
    FAILED has the kind `datasheet_check`."""
    kind = _kind(row)
    return (
        is_fail_word(kind)
        or is_fail_word(row.get("compliance_status"))
        or (
            kind == "datasheet_check"
            and str(row.get("severity") or "").strip().lower() in FAIL_SEVERITIES
        )
    )


def _removable(row: Mapping) -> bool:
    kind = _kind(row)
    if kind == "datasheet_check":
        status = re.sub(
            r"[\s\-]+", "_", str(row.get("compliance_status") or "").strip().lower()
        )
        return status in DATASHEET_CHECK_NON_FAIL
    return kind in REMOVABLE_KINDS


FLAG_PREFIX = "AI suspects the datasheet value was misread: "


def _verify_flag(proposal: dict, ctx: Context) -> Verdict:
    """The only thing the AI may do about a suspected misread: put an internal flag on the row. The Fail stays. The flag
    text is built HERE from the first verified page quote; none of the AI's own words are shown in it."""

    def no(reason: Reason) -> Verdict:
        return Verdict(False, reason.value, proposal)

    if str(proposal.get("row_key") or "") not in ctx.rows:
        return no(Reason.NO_SUCH_ROW)
    page, bad = _check_page_and_value(proposal, ctx)
    if bad:
        return Verdict(False, bad, proposal)
    if not str(proposal.get("value") or "").strip() or not proposal.get("evidence"):
        return no(Reason.NO_BASIS)
    bad = _evidence_ok(proposal, ctx)
    if bad:
        return Verdict(False, bad, proposal)
    if not _evidence_carries_value(proposal):
        return no(Reason.EVIDENCE_NOT_ON_PAGE)
    quote = (
        next(
            str(e["quote"]).strip()
            for e in proposal["evidence"]
            if e.get("page") == page
        )
        if any(e.get("page") == page for e in proposal["evidence"])
        else None
    )
    if quote is None:
        return no(Reason.EVIDENCE_NOT_ON_PAGE)
    return Verdict(
        True,
        None,
        proposal,
        final_text=f'{FLAG_PREFIX}page {page} shows "{quote}"',
    )


def _verify_remove(proposal: dict, ctx: Context) -> Verdict:
    def no(reason: Reason) -> Verdict:
        return Verdict(False, reason.value, proposal)

    key = str(proposal.get("row_key") or "")
    row = ctx.rows.get(key)
    if row is None:
        return no(Reason.NO_SUCH_ROW)
    kind = _kind(row)
    if is_fail_row(row):  # a Fail is never removed by the AI, whatever the basis
        return no(Reason.FAIL_KEPT)
    if kind in PROTECTED_KINDS or not _removable(row):
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
    if not proposal.get("evidence"):
        return no(Reason.NO_BASIS)  # a removal needs at least one verified quote
    if not _evidence_carries_value(proposal):
        return no(Reason.EVIDENCE_NOT_ON_PAGE)
    if not _numbers_verified(proposal, ctx, ctx.pages[page], row):
        return no(Reason.NUMBER_NOT_VERIFIED)
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
    pages = [
        _fold(t) for t in ctx.pages.values()
    ]  # one page at a time: text spanning two pages is no quote
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
    return {
        "remove": _verify_remove,
        "add": _verify_add,
        "reword": _verify_reword,
        "flag": _verify_flag,
    }[kind](proposal, ctx)


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
        if verdict.accepted and verdict.proposal.get("type") in (
            "remove",
            "reword",
            "flag",
        ):
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
