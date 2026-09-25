"""Shared by the harness and every registry module.

The `Mutation` type, the repository paths, and the anchors and test targets
that several entries quote - moved verbatim from `scripts/mutation_check.py`
when its entries were split into one file per mutated module (2026-09-25).
Nothing here imports the harness, so there is no import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: scripts/mutations/_base.py -> the repository root.
REPO = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO / "backend"
APP = BACKEND / "app"
TESTS = BACKEND / "tests"
FRONTEND_SRC = REPO / "frontend" / "src"


@dataclass(frozen=True)
class Mutation:
    """One deleted feature and the tests that must notice."""

    id: str
    phase: int
    description: str
    path: Path
    #: Replaced EXACTLY ONCE. Kept long enough to be unambiguous; if it ever
    #: matches twice the harness stops rather than guessing which one was meant.
    anchor: str
    replacement: str
    #: Pytest node ids or paths. Every selected test is expected to fail.
    target: str
    #: Optional `-k` expression narrowing `target`.
    keyword: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    #: Which runner proves this one. The frontend workflows are only visible
    #: through vitest, and a backend-only harness would leave every screen
    #: unproven while reporting a perfect score.
    runner: str = "pytest"


# --------------------------------------------------------------------------
# Anchors and targets shared by entries, moved verbatim.
# --------------------------------------------------------------------------

#: The guard `db.add_column_if_missing` puts round a concurrent
#: migrator, quoted once so two mutations can share it.
DUPLICATE_GUARD = (
    '        if "duplicate column" not in str(exc).lower():\n'
    "            raise")

#: Anchors whose text carries double quotes, quoted once here.
TAG_SCOPED = (
    '    return len({f.get("equipment_tag") for f in facts\n'
    '                if f.get("equipment_tag")}) >= 2')

TAG_IN_KEY = (
    '    if tag_scoped:\n'
    '        parts.append(_normalise_for_match(fact.get("equipment_tag")))')

TAG_TAIL = (
    '    tail = " ".join((match.group("tail") or "").split())\n'
    '    return tail or " ".join((value or "").split()) or None')

#: Phase 31: B34 - a standard number is a NAME, not a measurement, under a
#: CLOSED grammar; and a removed sentence is REPORTED, never silently deleted.
#: M288-M293 loosen or remove the grammar in six different ways - each must be
#: caught, and M289 and M293 are the loosenings that would let a fabricated
#: value disguised as a standard number through ("per SAES-H-150, apply 150").
_SYNTH = APP / "synthesis.py"

_B34_TEST = "tests/test_b34_standard_identifiers.py"

_B34_UI_TEST = "src/views/AnalysisModeScreen.removed.test.tsx"

#: B18: completeness dropped an UNMEASURED extraction factor and reported the
#: other half alone - 1.0 and "sufficient" with the datasheet never measured.
_B18_GUARD = ("    if extraction is None:\n"
              "        overall = 0.0 if reference_coverage == 0 else None")

#: B19: a review never read the datasheet (extract_facts had no caller).
_B19_TEST = "tests/test_b19_review_reads_the_datasheet.py"

#: B38: record, then refuse by default, on all four paths that delete
#: requirement rows review findings cite. A path's mutation swaps its guard
#: call for a no-op that accepts the same arguments.
_B38_TEST = "tests/test_b38_orphan_guard.py"

_B38_NOOP = "(lambda *a, **k: 0)("

#: B9/B22: NOT_IN_DOCUMENT_SCOPE, rule R1 - an unmatched `statement` is not
#: the contractor's omission, and must never approve a submittal either.
_REVIEW_UI = REPO / "frontend" / "src" / "components" / "review"

#: B40 -> #179: `extract_facts(replace=True)` used to DELETE unconfirmed facts
#: that findings cite by `fact_id` (B40 guarded it: count, record, refuse).
#: Since #179 it SUPERSEDES them instead - the rows stay, marked
#: `superseded_at`, and every reader of current facts leaves them out.
#: M334-M336 keep their ids, re-anchored on the supersession; M440-M444 cover
#: the readers and the record. Phase 56.
_B40_TEST = "tests/test_b40_fact_orphan_guard.py"

#: B42: the one branch that never applied the scope mask, and the permissive
#: default that would have let the next caller read the corpus by forgetting.
_B42_TEST = "tests/test_structured_search.py"

#: B49: the condition gate excused a clause using the fields under test,
#: because "is this material evidence" was a question about the field's NAME.
_B49_TEST = "tests/test_condition_gate.py"

#: B44: a file nobody could open was reported as a page that printed nothing,
#: and counted as read. M51 was NOT re-anchored - the fix sits before the page
#: loop and after the return, so `if page_written == 0:` never moved; phase 5
#: re-run 8/8 to prove it rather than assume it.
_B44_TEST = "tests/test_datasheets.py"

#: B50: a model row that fails its schema is refused, never coerced. The two
#: malformations these protect against are real - a 9B returned them on the
#: frozen packet.
_B50_TEST = "tests/test_extraction_schema.py"

#: Feature 1 section 5a + B54: one interface, and provenance that cannot be
#: omitted. Before it, nothing in the system could say which model answered.
_PROVIDER_TEST = "tests/test_reasoning_provider.py"

#: B19's other half: fact extraction wired into ingestion completion (upload
#: + watched folder), never a manually-started review run.
_INGEST_FACTS_TEST = "tests/test_ingest_fact_extraction.py"

#: B9: automated, evidence-based `equipment_type` for CONTRACTOR_SUBMITTAL,
#: wired into the same ingestion-completion point as B19's fact extraction.
_EQUIPMENT_TYPE_TEST = "tests/test_equipment_type_classification.py"

#: #175: cascaded extractor (table column-scoping, reused from the parked
#: B58 fix, renumbered M356-M358 -> M365-M367 to avoid colliding with
#: mutation ids already added on this branch since the two diverged), OCR
#: fallback routing, and confidence-based NEEDS_ENGINEER_REVIEW routing.
_B175_DATASHEET_TEST = "tests/test_datasheets.py"

#: Issue #179, second pass. Phase 52, ids M400-M409.
_EVAL = REPO / "scripts" / "eval_extraction.py"

_B176_TARGET = "tests/test_submittal_metadata_classification.py"

#: Master order B3: the page ledger, and a review that never calls an unread
#: page the contractor's omission. Phase 57.
_B3_TEST = "tests/test_b3_page_ledger.py"

_LIVE_GUARD_TEST = "tests/test_live_guard.py"

#: Master order B4, issue #193: pairing measured against gold and made
#: precise. Phase 58.
_MATCH_RULES_TEST = "tests/test_match_rules.py"

_SCORERS_TEST = "tests/test_scorers_read_current_facts.py"

#: Master order B4: the pump datasheet's layout defects. Phase 59.
_B4_TEST = "tests/test_b4_pump_layouts.py"
