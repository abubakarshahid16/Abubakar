"""Order 95 piece 1: the CRS-first Sheet's tiers, one per finding, on the server.

THE SAME RULES AS `frontend/src/components/review/crs/tiers.ts` (spec section
2, order 96 item 5), so the export, the footer and the screen read one answer.
A change to one is a change to both; `test_95_run_summary.py` pins the table.

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

import re
from dataclasses import dataclass, field

from .comparison import _pairing_unconfirmed

A, B, C = "A", "B", "C"
REMOVED = "removed"
PAGE_NOT_READ = "page not read"
NOT_IN_LIBRARY = "standard not in library"
UNSETTLED = "condition unsettled"

_TIER_C = {"NEEDS_ENGINEER_REVIEW", "CONDITIONAL"}
_CONFLICT = re.compile(r"\bvalue conflict\b|\bconflicting values?\b|\bvalues? conflict\b")
_UNIT = re.compile(r"\bunit unknown\b|\bunknown unit\b"
                   r"|\bunit (?:not|could not be) (?:read|recognised|recognized|parsed)\b")


@dataclass(frozen=True)
class RunFacts:
    """What is known about the run, as data (tiers.ts `RunFacts`)."""
    pages_not_read: frozenset[int] = frozenset()
    reader_timed_out_pages: frozenset[int] = frozenset()
    #: identifiers of cited standards the library does not hold (MISSING_LOCALLY)
    missing_standards: tuple[str, ...] = ()
    #: the standards the run compared against; None when not known - then
    #: nothing is called "not in library" on that ground alone
    library_standard_ids: frozenset[str] | None = field(default=None)


def _fold(text: str | None) -> str:
    return re.sub(r"[\s_-]+", " ", (text or "").lower()).strip()


def page_not_read(finding: dict, facts: RunFacts) -> bool:
    page = finding.get("contractor_page")
    if not isinstance(page, int) or isinstance(page, bool):
        return False
    return page in facts.pages_not_read or page in facts.reader_timed_out_pages


def missing_standard_of(finding: dict, facts: RunFacts) -> str | None:
    """The first missing standard the finding names in its sources, requirement,
    rationale or clause (tiers.ts `citesMissingStandard`), or None."""
    if not facts.missing_standards:
        return None
    parts = [*(finding.get("governing_sources") or []), finding.get("requirement"),
             finding.get("ai_rationale"), finding.get("standard_clause")]
    text = _fold(" \n ".join(str(p) for p in parts if p))
    return next((ident for ident in facts.missing_standards
                 if _fold(ident) and _fold(ident) in text), None)


def standard_in_library(finding: dict, facts: RunFacts) -> bool:
    standard = finding.get("standard_document_id")
    if not standard:
        return False
    return facts.library_standard_ids is None or standard in facts.library_standard_ids


def _conflict_word(finding: dict) -> str | None:
    why = _fold(finding.get("ai_rationale"))
    if _CONFLICT.search(why):
        return "value conflict"
    if _UNIT.search(why):
        return "unit unknown"
    return None


def safety_tick_open(finding: dict) -> bool:
    """rule_trust (#947): a safety field shown for the engineer's own tick, not ticked yet."""
    return (bool(finding.get("show_for_engineer_tick"))
            and finding.get("compliance_status") == "COMPLIANT" and not finding.get("confirmed_by"))


def _unsettled_reason(finding: dict, facts: RunFacts) -> str | None:
    """The fact, other than the status, that makes this finding Tier C, in the
    order the reason is told (tiers.ts `unsettledReason`); None when none holds."""
    if page_not_read(finding, facts):
        return PAGE_NOT_READ
    if missing_standard_of(finding, facts) is not None:
        return NOT_IN_LIBRARY
    if _pairing_unconfirmed(finding):
        return "AI guess"
    if finding.get("trust_label") == "UNPROVEN":
        return "rule not proven"
    if safety_tick_open(finding):
        return "safety field"
    return _conflict_word(finding)


def _needs_you_reason(finding: dict, facts: RunFacts) -> str:
    unsettled = _unsettled_reason(finding, facts)
    if unsettled:
        return unsettled
    if finding.get("compliance_status") == "MISSING_INFORMATION" and not standard_in_library(finding, facts):
        return NOT_IN_LIBRARY
    return UNSETTLED


def tier_of(finding: dict, facts: RunFacts = RunFacts()) -> tuple[str, str | None, str | None]:
    """(tier, label, reason) for one finding; (``REMOVED``, None, None) when an
    engineer removed it. Only a Tier C row carries a reason."""
    if finding.get("approval_status") == "rejected":
        return REMOVED, None, None
    status = finding.get("compliance_status") or ""
    if status in _TIER_C or _unsettled_reason(finding, facts) is not None:
        return C, "Needs you", _needs_you_reason(finding, facts)
    if status == "COMPLIANT":
        return A, "Met", None
    if status == "NOT_APPLICABLE":
        return A, "Not applicable", None
    if status == "NOT_IN_DOCUMENT_SCOPE":
        return A, "Another document", None
    if status == "NON_COMPLIANT":
        return B, "Comment", None
    if status == "MISSING_INFORMATION":
        if standard_in_library(finding, facts):
            return B, "Comment", None
        return C, "Needs you", NOT_IN_LIBRARY
    return C, "Needs you", UNSETTLED


_SCREEN_ORDER = {B: 0, C: 1, A: 2}


def _order(row: dict) -> tuple:
    page = row["contractor_page"]
    return (_SCREEN_ORDER[row["tier"]], page is None, page or 0, row["standard_clause"] or "")


def summarise(findings: list[dict], facts: RunFacts = RunFacts()) -> dict:
    """Headline counts (tiers.ts `countTiers`, plus removed and total) and one
    row per finding still in a tier, in screen order: Comment, Needs you, Met;
    then contractor page (no page last), then clause."""
    counts = {"met": 0, "not_applicable": 0, "another_document": 0, "comment": 0, "needs_you": 0,
              REMOVED: 0}
    rows = []
    for f in findings:
        tier, label, reason = tier_of(f, facts)
        counts[{REMOVED: REMOVED, B: "comment", C: "needs_you"}.get(tier)
               or {"Met": "met", "Another document": "another_document"}.get(label or "")
               or "not_applicable"] += 1
        if tier != REMOVED:
            rows.append({"finding_id": f["id"], "tier": tier, "label": label, "reason": reason,
                         "compliance_status": f.get("compliance_status"),
                         "standard_clause": f.get("standard_clause"),
                         "contractor_page": f.get("contractor_page"),
                         "equipment_tag": f.get("equipment_tag"),
                         "missing_standard_id": missing_standard_of(f, facts)})
    rows.sort(key=_order)
    return {"counts": {**counts, "total": len(findings)}, "rows": rows}
