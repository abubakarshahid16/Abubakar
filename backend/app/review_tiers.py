"""Order 95 piece 1: the CRS-first Sheet's tiers, one per finding, on the server.

The rules' DATA lives in ONE place, `reference/review_tiers.json` (order 133):
statuses, labels, reason words and the order they are told in, the phrases,
the fold, the screen order and the count keys. This module and the screen's
`frontend/src/components/review/crs/tiers.ts` (through the generated
`contracts/generated/review_tiers.ts`) both read it; neither keeps a status,
label, reason word, order or phrase of its own. The word edge of a phrase and
the separators the fold joins are explicit data too (order 135), so both
engines read them the same way, never by their own word-boundary or white-space
class. The logic is pinned on both sides by one case table,
`contracts/fixtures/review_tier_cases.json`
(`test_133_one_truth_tiers.py` and `crs/tiers.parity.test.ts`).

  Tier A  "Met" / "Not applicable"  COMPLIANT / NOT_APPLICABLE / NOT_IN_DOCUMENT_SCOPE
          / "Another document"      (the clause names another document).
  Tier B  "Comment"                 NON_COMPLIANT; MISSING_INFORMATION when the
                                    standard IS in the library.
  Tier C  "Needs you" + a reason    NEEDS_ENGINEER_REVIEW, CONDITIONAL, a page not
                                    read into fields or timed out, a standard the
                                    library does not hold, a pairing an AI guessed
                                    and nobody confirmed ("AI guess", the backend's
                                    own `comparison._pairing_unconfirmed`), a rule
                                    not yet proven, an unconfirmed safety tick
                                    ("safety field"), a value conflict, an unknown
                                    unit, else "condition unsettled".

The facts that make any finding Tier C come first, so a "met" value on an
unread page is still shown to the engineer. A status this table does not know
is never swept quietly: it needs a person. DISPLAY ONLY: stored fields are
read, nothing is decided or written. A finding an engineer removed
(``approval_status = 'rejected'``) is in no tier; it is counted as removed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .comparison import _pairing_unconfirmed

RULES_PATH = Path(__file__).parent / "reference" / "review_tiers.json"
RULES: dict = json.loads(RULES_PATH.read_text(encoding="utf-8"))

A, B, C = RULES["tiers"]
#: the tier of a finding an engineer removed, and its count key
REMOVED = "removed"
# The reason words, in the order of `TierRow.reason` (test_133 pins the two).
(
    PAGE_NOT_READ,
    NOT_IN_LIBRARY,
    AI_GUESS,
    RULE_NOT_PROVEN,
    SAFETY_FIELD,
    UNSETTLED,
    VALUE_CONFLICT,
    UNIT_UNKNOWN,
    NO_STANDARD_LINKED,
    OUTSIDE_REVIEW,
) = RULES["reasons"]

_NEEDS_YOU = (RULES["needs_you"]["tier"], RULES["needs_you"]["label"])
_TIER_C = frozenset(RULES["tier_c_statuses"])
_STATUS_TIERS = {
    status: (row["tier"], row["label"]) for status, row in RULES["status_tiers"].items()
}
_MISSING = RULES["missing_information"]
_WORD = RULES["word_edge"]
_PHRASES = {
    word: re.compile(source.replace(_WORD["token"], _WORD["python"]))
    for word, source in RULES["phrases"].items()
}
_FOLD = re.compile(RULES["fold"]["pattern"])
_IDENT = RULES["ident_match"].replace(_WORD["token"], _WORD["python"])


@dataclass(frozen=True)
class RunFacts:
    """What is known about the run, as data (tiers.ts `RunFacts`)."""

    pages_not_read: frozenset[int] = frozenset()
    reader_timed_out_pages: frozenset[int] = frozenset()
    #: identifiers of cited standards the library does not hold (MISSING_LOCALLY)
    missing_standards: tuple[str, ...] = ()
    #: the standards INCLUDED in this review (not the whole library); None when
    #: not known - then nothing is called "outside this review" on that ground
    library_standard_ids: frozenset[str] | None = field(default=None)


def _fold(text: str | None) -> str:
    return _FOLD.sub(RULES["fold"]["replace"], (text or "").lower()).strip()


def page_not_read(finding: dict, facts: RunFacts) -> bool:
    page = finding.get("contractor_page")
    if not isinstance(page, int) or isinstance(page, bool):
        return False
    return page in facts.pages_not_read or page in facts.reader_timed_out_pages


def missing_standard_of(finding: dict, facts: RunFacts) -> str | None:
    """The first missing standard the finding names in its sources, requirement,
    rationale or clause, between word edges (tiers.ts `citesMissingStandard`),
    or None. A name is not looked for inside a longer one."""
    if not facts.missing_standards:
        return None
    parts = [
        *(finding.get("governing_sources") or []),
        finding.get("requirement"),
        finding.get("ai_rationale"),
        finding.get("standard_clause"),
    ]
    text = _fold(" \n ".join(str(p) for p in parts if p))
    return next(
        (i for i in facts.missing_standards if _fold(i) and _names(_fold(i), text)),
        None,
    )


def _names(ident: str, text: str) -> bool:
    return bool(re.search(_IDENT.replace("{ident}", re.escape(ident)), text))


def blank_reason(finding: dict, facts: RunFacts) -> str | None:
    """Why a blank (MISSING_INFORMATION) needs a person, or None when it is a
    Comment (tiers.ts `blankReason`). The tier is the same as ever: a blank
    without an included standard is Tier C. Only the word is told true: no
    standard behind it, or a standard that is not in this review's list (it may
    well be in the library). A list that failed to load claims nothing."""
    standard = finding.get("standard_document_id")
    if not standard:
        return NO_STANDARD_LINKED
    library = facts.library_standard_ids
    return None if library is None or standard in library else OUTSIDE_REVIEW


def _phrase(word: str):
    """The predicate for a reason told by a phrase in the rationale."""

    def holds(finding: dict, _facts: RunFacts) -> bool:
        return bool(_PHRASES[word].search(_fold(finding.get("ai_rationale"))))

    return holds


def safety_tick_open(finding: dict) -> bool:
    """rule_trust (#947): a safety field shown for the engineer's own tick, not ticked yet."""
    return (
        bool(finding.get("show_for_engineer_tick"))
        and finding.get("compliance_status") == RULES["safety_tick_status"]
        and not finding.get("confirmed_by")
    )


#: one predicate per reason word other than the status's own; the order they
#: are asked in is the data's `unsettled_order`
PREDICATES = {
    PAGE_NOT_READ: page_not_read,
    NOT_IN_LIBRARY: lambda f, facts: missing_standard_of(f, facts) is not None,
    AI_GUESS: lambda f, _facts: _pairing_unconfirmed(f),
    RULE_NOT_PROVEN: lambda f, _facts: (
        f.get("trust_label") == RULES["rule_not_proven_trust_label"]
    ),
    SAFETY_FIELD: lambda f, _facts: safety_tick_open(f),
    VALUE_CONFLICT: _phrase(VALUE_CONFLICT),
    UNIT_UNKNOWN: _phrase(UNIT_UNKNOWN),
}


def _unsettled_reason(finding: dict, facts: RunFacts) -> str | None:
    """The fact, other than the status, that makes this finding Tier C, in the
    order the reason is told (tiers.ts `unsettledReason`); None when none holds."""
    return next(
        (w for w in RULES["unsettled_order"] if PREDICATES[w](finding, facts)), None
    )


def _needs_you_reason(finding: dict, facts: RunFacts) -> str:
    unsettled = _unsettled_reason(finding, facts)
    if unsettled:
        return unsettled
    if finding.get("compliance_status") == _MISSING["status"]:
        return blank_reason(finding, facts) or RULES["fallback_reason"]
    return RULES["fallback_reason"]


def tier_of(
    finding: dict, facts: RunFacts = RunFacts()
) -> tuple[str, str | None, str | None]:
    """(tier, label, reason) for one finding; (``REMOVED``, None, None) when an
    engineer removed it. Only a Tier C row carries a reason."""
    if finding.get("approval_status") == RULES["removed"]["approval_status"]:
        return REMOVED, None, None
    status = finding.get("compliance_status") or ""
    if status in _TIER_C or _unsettled_reason(finding, facts) is not None:
        return (*_NEEDS_YOU, _needs_you_reason(finding, facts))
    if status in _STATUS_TIERS:
        return (*_STATUS_TIERS[status], None)
    if status == _MISSING["status"]:
        reason = blank_reason(finding, facts)
        if reason is None:
            in_library = _MISSING["in_library"]
            return in_library["tier"], in_library["label"], None
        return (*_NEEDS_YOU, reason)
    return (*_NEEDS_YOU, RULES["fallback_reason"])


_SCREEN_ORDER = {tier: i for i, tier in enumerate(RULES["screen_order"])}


def _order(row: dict) -> tuple:
    page = row["contractor_page"]
    return (
        _SCREEN_ORDER[row["tier"]],
        page is None,
        page or 0,
        row["standard_clause"] or "",
    )


def summarise(findings: list[dict], facts: RunFacts = RunFacts()) -> dict:
    """Headline counts (tiers.ts `countTiers`, plus removed and total) and one
    row per finding still in a tier, in the server's order: tier by the data's
    `screen_order` (Comment, Needs you, Met), then contractor page (no page
    last), then clause. The CRS sheet does not use this order: it keys the
    rows by finding id and lays out its own (`crsRows.ts`)."""
    counts = dict.fromkeys([*RULES["count_keys"].values(), REMOVED], 0)
    rows = []
    for f in findings:
        tier, label, reason = tier_of(f, facts)
        counts[REMOVED if tier == REMOVED else RULES["count_keys"][label]] += 1
        if tier != REMOVED:
            rows.append(
                {
                    "finding_id": f["id"],
                    "tier": tier,
                    "label": label,
                    "reason": reason,
                    "compliance_status": f.get("compliance_status"),
                    "standard_clause": f.get("standard_clause"),
                    "contractor_page": f.get("contractor_page"),
                    "equipment_tag": f.get("equipment_tag"),
                    "missing_standard_id": missing_standard_of(f, facts),
                }
            )
    rows.sort(key=_order)
    return {"counts": {**counts, "total": len(findings)}, "rows": rows}
