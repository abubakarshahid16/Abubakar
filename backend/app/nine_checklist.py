"""Role 5, the checklist: today's batch path, asked only for the required items the reviewer did not mention (builder B4).

One list of REQUIRED items, three sources, all existing:

  * the rules chosen for this paper (the plan's `R-` items);
  * the approved checklist of the equipment type: the plan's `S-` items (the code-decided `C-` lines are the calculator's, not asked);
  * the fields a sheet of this kind must carry (`agent_review_absence.carried_roles`) against the fact sheet.

COVERAGE (SPEC D). An item is "mentioned" and skipped ONLY when:
  * it is a rule item (`R-<id>`) and a finding matched ITS OWN rule id (`nine_match`), the finding's clause quote was verified in the book,
    and the finding is not a contradiction and not "cannot tell". (A finding that could not stand on its quotes, or that says nothing,
    does not cover the item: the run is never weaker than today's.)
  * An `S-` item is NEVER skipped in v1 (few items; the same field is not the same requirement).
  * When the reviewer returned nothing, or failed, or was stopped, EVERY item is asked: the run is exactly today's review.
A carried field with no fact on the sheet becomes a Query "required item not stated: <field>; pages searched 1 to N" (a `Q-` item, made
by code, passed through the same exit as any line; the absence PROOF stays off in v1).

This module decides what is NOT asked, so it only ever REMOVES items from the ask when a verified finding stands for them; it never
adds a verdict. Pure on its inputs; no model, no network.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from . import agent_review_verdict as verdict
from .nine_contract import Finding, RequiredItem
from .nine_findings import ANSWER_OF, Built

REQUIRED_NOT_STATED = "required item not stated"
SRC_RULE = "rule chosen for this paper"
SRC_CHECKLIST = "approved checklist"
SRC_FIELD = "field this kind of sheet must carry"


@dataclass
class Coverage:
    required: tuple[RequiredItem, ...]
    to_ask: list[dict]  # the plan's items that go to today's batch path
    skipped: dict[str, str] = field(
        default_factory=dict
    )  # item id -> the finding id that covers it
    stated_missing: list[str] = field(
        default_factory=list
    )  # carried field roles with no fact (their Q- lines)


def _rule_id(item: Mapping) -> str | None:
    iid = str(item.get("item_id") or "")
    return iid if iid.startswith("R-") else None


def covers(finding: Finding, item: Mapping) -> bool:
    """A finding covers a rule item only when it matched THAT rule, its clause quote was verified, and it is a plain statement."""
    rid = _rule_id(item)
    return (
        rid is not None
        and finding.matched_rule_id is not None
        and f"R-{finding.matched_rule_id}" == rid
        and finding.clause_page is not None
        and not finding.contradiction
        and finding.ai_verdict != "cannot_tell"
    )


def plan(
    items: Iterable[dict],
    findings: Iterable[Finding],
    *,
    reviewer_ok: bool = True,
    carried: frozenset[str] | None = None,
    fact_roles: frozenset[str] = frozenset(),
) -> Coverage:
    """The coverage of one run. `reviewer_ok` False (the reviewer failed, was stopped or read nothing) or no finding at all: every item is
    asked. `carried`: the sheet's field list (None = none for this kind); `fact_roles`: the registry roles the fact sheet holds."""
    items = list(items)
    found = [f for f in findings if f.origin == "reviewer"]
    skipped: dict[str, str] = {}
    to_ask: list[dict] = []
    for it in items:
        cover = (
            next((f for f in found if covers(f, it)), None)
            if (reviewer_ok and found)
            else None
        )
        if cover is not None:
            skipped[str(it["item_id"])] = cover.finding_id
        else:
            to_ask.append(it)
    required: list[RequiredItem] = []
    for it in items:
        iid = str(it.get("item_id"))
        source = SRC_RULE if iid.startswith("R-") else SRC_CHECKLIST
        required.append(
            RequiredItem(item_id=iid, source=source, mentioned_by=skipped.get(iid))
        )  # type: ignore[arg-type]
    missing = sorted(carried - fact_roles) if carried else []
    for role in missing:
        required.append(
            RequiredItem(item_id=f"Q-{role}", source=SRC_FIELD, mentioned_by=None)
        )  # type: ignore[arg-type]
    return Coverage(tuple(required), to_ask, skipped, missing)


def not_stated_lines(roles: Iterable[str], total_pages: int) -> list[Built]:
    """For each carried field with no fact: the item and the first-reader answer of a Query "required item not stated: <field>; pages searched
    1 to N". Made by code, not by a model; the runner's exit judges it like any line (a Query, never a decision)."""
    out: list[Built] = []
    for role in roles:
        label = role.replace("_", " ")
        text = f"{REQUIRED_NOT_STATED}: {label}; pages searched 1 to {total_pages}"
        iid = f"Q-{role}"
        item = {
            "item_id": iid, "source": "rule", "rule_version_id": None, "standard": None, "standard_document_id": None, "clause": None,
            "clause_page": None, "rule_kind": None, "rule_row_found": False, "field_roles": [role], "question": text, "page_hint": [],
            "page_hint_source": "nine checklist", "clause_quote_ref": None, "rule_quote_ref": None,
            "rule_tier": verdict.RULE_NOT_APPROVED, "rule_unapproved_why": "required by the kind of sheet; no rule row behind it",
        }  # fmt: skip
        word, _code = ANSWER_OF["cannot_tell"]
        answer = {
            "item_id": iid, "field_label": label, "paper_page": None, "paper_quote": "", "clause_quote": "", "reasoning": text, "comment": text,
            "verdict": word, "reason_code": "sheet_silent",
        }  # fmt: skip
        finding = Finding(
            finding_id=iid, item_id=iid, origin="checklist", book_id=None, clause=None, clause_page=None, clause_where=None, clause_scanned=False, field_label=label, field_roles=(role,),
            tag=None, paper_page=None, paper_quote=None, clause_quote=None, ai_verdict="not_stated", matched_rule_id=None, rule_tier=None,
            members=(), contradiction=False, read_refs=(),
        )  # fmt: skip
        out.append(Built(finding, item, answer, {}))
    return out
