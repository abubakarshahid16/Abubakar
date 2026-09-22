"""Mutation harness: delete a feature, prove its tests fail, restore it.

WHY THIS FILE EXISTS

CLAUDE.md rule 6 says every new test must fail when its feature is deleted, and
`docs/status-honesty-audit.md` records vacuous tests as this project's recurring
defect - now at instance 6, which was a pair of MIGRATION tests that passed with
the migration deleted because the fixture built the table from the current
schema. That pair was caught by running this harness and by nothing else.

A harness that lives in one session's scratchpad proves a claim once and cannot
be re-run by a reviewer. Section 14 of `docs/AI_SUBMITTAL_REVIEW_HANDOFF.md`
tells a reviewer to verify "permission tests are mutation-proven" by deleting
the filter and re-running. This script is that instruction, executable.

HOW IT WORKS

Each mutation names a file, an exact anchor string to replace, a replacement,
and the tests that must then FAIL. For every mutation the harness:

  1. copies the file to `<file>.mutbak`,
  2. refuses to continue if the anchor is not found EXACTLY once - an anchor
     that silently stops matching turns a mutation into a no-op, and a no-op
     mutation reports "tests passed" and looks like a vacuous test,
  3. applies the replacement, runs the selected tests,
  4. restores the file in a `finally` block, so an exception, a timeout or a
     Ctrl-C cannot leave the working tree patched.

A mutation whose tests still PASS is a failure of this harness, not a success:
it means the tests do not observe the feature.

USAGE

    python scripts/mutation_check.py                 # every mutation
    python scripts/mutation_check.py --list          # ids and descriptions
    python scripts/mutation_check.py --only M1 M4    # a subset
    python scripts/mutation_check.py --phase 1       # one phase's set

Run it from the repository root, with the Python 3.12 environment the backend
suite uses. Exit code 0 means every mutation was detected; 1 means at least one
was not, and the summary names it.

SAFETY

This script EDITS SOURCE FILES IN PLACE and restores them. Run it on a clean
working tree so that `git status` after a run is the proof it restored
everything. It never touches the database and never runs the full suite.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
APP = BACKEND / "app"
TESTS = BACKEND / "tests"
FRONTEND_SRC = REPO / "frontend" / "src"

#: The interpreter that runs the suite. The project venv first, because
#: `run.py` refuses anything but 3.12 and a 3.10 on PATH would fail every
#: mutation for the wrong reason - which reads exactly like a detected
#: mutation and would be a false green.
_VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"
_VENV_PY_POSIX = REPO / ".venv" / "bin" / "python"


def _python() -> str:
    for candidate in (_VENV_PY, _VENV_PY_POSIX):
        if candidate.exists():
            return str(candidate)
    return sys.executable


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


PHASE_1 = (
    Mutation(
        id="M1", phase=1,
        description="delete the scope filter from list_review_runs",
        path=APP / "submittal_review.py",
        # RE-ANCHORED 2026-09-19. Phase 7's step 0a replaced
        # `"SELECT * FROM review_runs"` with the `_RUN_SELECT` join, and this
        # anchor stopped matching. The harness reported it as a HARNESS ERROR
        # rather than a pass - which is the three-bucket verdict doing its
        # job - but it went unrun for three phases because only the new
        # mutations were run after that change, never the whole harness.
        # A permission mutation, silently inert. See the phase 8 progress
        # entry.
        anchor='    where, args = _scope_clause(allowed_document_ids, "submittal_document_id")\n'
               '    sql = _RUN_SELECT + where',
        replacement='    where, args = "", []\n'
                    '    sql = _RUN_SELECT + where',
        target="tests/test_submittal_review_foundation.py",
        keyword="unauthorised_user_cannot_read_another_users_review_run or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M2", phase=1,
        description="delete the scope filter from list_submittal_facts",
        path=APP / "submittal_review.py",
        anchor='    where, args = _scope_clause(allowed_document_ids, "submittal_document_id")\n'
               '    sql = "SELECT * FROM submittal_facts" + where',
        replacement='    where, args = "", []\n'
                    '    sql = "SELECT * FROM submittal_facts" + where',
        target="tests/test_submittal_review_foundation.py",
        keyword="submittal_facts or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M3", phase=1,
        description="make an EMPTY grant set mean everything (the deliverables.py defect)",
        path=APP / "submittal_review.py",
        anchor='    if not allowed_document_ids:\n        return " WHERE 1 = 0", []',
        replacement='    if not allowed_document_ids:\n        return "", []',
        target="tests/test_submittal_review_foundation.py",
        keyword="empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M4", phase=1,
        description="drop the standards-side filter in list_applicable_standards",
        path=APP / "submittal_review.py",
        anchor='    where, args = _scope_clause(allowed_document_ids, "standard_document_id")\n'
               '    sql = "SELECT * FROM review_applicable_standards" + where',
        replacement='    where, args = " WHERE 1 = 1", []\n'
                    '    sql = "SELECT * FROM review_applicable_standards" + where',
        target="tests/test_submittal_review_foundation.py",
        keyword="standard_the_caller_cannot_read",
        tags=("permission",),
    ),
    Mutation(
        id="M5", phase=1,
        description="give a read path a DEFAULT scope, so forgetting the filter is silent",
        path=APP / "submittal_review.py",
        anchor="def list_review_runs(\n    *, allowed_document_ids: frozenset[str],",
        replacement="def list_review_runs(\n    *, allowed_document_ids: frozenset[str] = frozenset(),",
        target="tests/test_submittal_review_foundation.py",
        keyword="forgets_the_filter",
        tags=("permission",),
    ),
    Mutation(
        id="M6", phase=1,
        description="remove the document_classification column migration",
        path=APP / "db.py",
        anchor="    if classification_cols:\n        for _column in (",
        replacement="    if False:\n        for _column in (",
        target="tests/test_submittal_review_foundation.py",
        keyword="existing_documents_remain_readable or equipment_tags",
        tags=("migration",),
    ),
    Mutation(
        id="M7", phase=1,
        description="remove the review_findings compliance column migration",
        path=APP / "review.py",
        anchor='            "review_run_id": "TEXT",\n            "compliance_status": "TEXT",',
        replacement='            # "review_run_id": "TEXT",\n            # "compliance_status": "TEXT",',
        target="tests/test_submittal_review_foundation.py",
        keyword="existing_review_findings or guided_review",
        tags=("migration",),
    ),
    Mutation(
        id="M8", phase=1,
        description="widen DocumentRole to a free string",
        path=APP / "schemas.py",
        anchor='DocumentRole = Literal[\n    "CONTRACTOR_SUBMITTAL",',
        replacement='DocumentRole = str\n_UNUSED_DocumentRole = Literal[\n    "CONTRACTOR_SUBMITTAL",',
        target="tests/test_submittal_review_foundation.py",
        keyword="invalid_document_role",
        tags=("validation",),
    ),
    Mutation(
        id="M9", phase=1,
        description="widen ComplianceStatus to a free string",
        path=APP / "schemas.py",
        anchor='ComplianceStatus = Literal[\n    "COMPLIANT",',
        replacement='ComplianceStatus = str\n_UNUSED_ComplianceStatus = Literal[\n    "COMPLIANT",',
        target="tests/test_submittal_review_foundation.py",
        keyword="invalid_compliance_status",
        tags=("validation",),
    ),
    Mutation(
        id="M10", phase=1,
        description="give a finding's standard_document_id a CASCADE foreign key",
        path=APP / "review.py",
        anchor="                standard_document_id TEXT,",
        replacement="                standard_document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,",
        target="tests/test_submittal_review_foundation.py",
        keyword="deleting_a_standard_does_not_erase",
        tags=("foreign-key",),
    ),
)

PHASE_2 = (
    Mutation(
        id="M11", phase=2,
        description="make the metadata filter UNION with the caller's scope instead of intersecting",
        path=APP / "classification.py",
        anchor="    return frozenset(matched & set(scope.allowed_document_ids)), True",
        replacement="    return frozenset(matched | set(scope.allowed_document_ids)), True",
        target="tests/test_document_metadata_filters.py",
        keyword="intersect or narrow or cannot_widen",
        tags=("permission",),
    ),
    Mutation(
        id="M12", phase=2,
        description="let an unknown document_role through the update boundary",
        path=APP / "schemas.py",
        anchor="    document_role: DocumentRole | None = None\n"
               "    document_number: str | None = None\n"
               "    title: str | None = None",
        replacement="    document_role: str | None = None\n"
                    "    document_number: str | None = None\n"
                    "    title: str | None = None",
        target="tests/test_document_metadata_filters.py",
        keyword="invalid_role_is_rejected",
        tags=("validation",),
    ),
    Mutation(
        id="M13", phase=2,
        description="drop the scope check from the original-file download",
        path=APP / "main.py",
        # Disambiguated by the line that follows: `document_workbook` opens with
        # the same two lines, and the harness refuses an ambiguous anchor rather
        # than guessing which route was meant.
        anchor='    doc = require_document(document_id, scope)\n'
               '    stored = Path(doc["stored_path"])\n'
               '    if not stored.exists():',
        # A REAL unscoped read, not a call to a function that does not exist.
        # A NameError would fail the test for the wrong reason and still report
        # DETECTED - a mutation has to reproduce the DEFECT (serving a document
        # the caller holds no grant for), not merely break the route.
        replacement='    doc = connect().execute(\n'
                    '        "SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()\n'
                    '    stored = Path(doc["stored_path"])\n'
                    '    if not stored.exists():',
        target="tests/test_document_original_file.py",
        keyword="cannot_download",
        tags=("permission",),
    ),
    Mutation(
        id="M14", phase=2,
        description="make the metadata filter fall back to the whole corpus when it matches nothing",
        path=APP / "classification.py",
        anchor="    if wanted.is_empty:\n        return scope.allowed_document_ids, False",
        replacement="    if True:\n        return scope.allowed_document_ids, False",
        target="tests/test_document_metadata_filters.py",
        keyword="matches_nothing or narrow",
        tags=("permission",),
    ),
    Mutation(
        id="M15", phase=2,
        description="let the upload route overwrite an existing stored original",
        path=APP / "upload.py",
        anchor="    if final_path.exists():",
        replacement="    if False:",
        target="tests/test_document_original_file.py",
        keyword="never_rewrites or guards_the_stored_path",
        tags=("immutability",),
    ),
)

#: Phase 2 continued: the workbook upload path.
PHASE_2_XLSX = (
    Mutation(
        id="M16", phase=2,
        description="accept any zip as a workbook (drop the xl/workbook.xml proof)",
        path=APP / "upload.py",
        anchor="            if _XLSX_REQUIRED_ENTRY not in names:",
        replacement="            if False:",
        target="tests/test_xlsx_upload.py",
        keyword="not_a_workbook or docx",
        tags=("validation", "upload"),
    ),
    Mutation(
        id="M17", phase=2,
        description="remove the decompression-bomb ceiling",
        path=APP / "upload.py",
        anchor="            if declared > MAX_XLSX_UNCOMPRESSED_BYTES:",
        replacement="            if False:",
        target="tests/test_xlsx_upload.py",
        keyword="decompression_bomb",
        tags=("validation", "upload"),
    ),
    Mutation(
        id="M18", phase=2,
        description="queue a workbook for indexing like a PDF",
        path=APP / "upload.py",
        anchor="    indexed = kind != KIND_XLSX",
        replacement="    indexed = True",
        target="tests/test_xlsx_upload.py",
        keyword="terminal_state or worker_never_selects",
        tags=("pipeline", "upload"),
    ),
    Mutation(
        id="M19", phase=2,
        description="hardcode the stored suffix back to .pdf, so an xlsx "
                    "overwrites or misses the immutability guard",
        path=APP / "upload.py",
        anchor='    final_path = settings.upload_dir / f"{sha256}{_SUFFIX_FOR_KIND[kind]}"',
        replacement='    final_path = settings.upload_dir / f"{sha256}.pdf"',
        target="tests/test_xlsx_upload.py",
        keyword="never_rewrites or suffix_comes_from_the_bytes",
        tags=("immutability", "upload"),
    ),
    Mutation(
        id="M20", phase=2,
        description="accept macro-enabled workbooks",
        path=APP / "upload.py",
        anchor='            if any(n.lower().startswith("xl/vbaproject") for n in names):',
        replacement="            if False:",
        target="tests/test_xlsx_upload.py",
        keyword="macros",
        tags=("validation", "upload"),
    ),
)

#: Phase 2 frontend: the visible workflows. Proven with vitest.
PHASE_2_UI = (
    Mutation(
        id="M21", phase=2, runner="vitest",
        description="open the page viewer at page 1, ignoring the cited page",
        path=FRONTEND_SRC / "components" / "PageImageViewer.tsx",
        anchor="  const [selected, setSelected] = useState(Math.max(1, initialPage ?? 1));",
        replacement="  const [selected, setSelected] = useState(1);",
        target="src/components/PageImageViewer.citation.test.tsx",
        keyword="opens at the cited page",
        tags=("citation", "ui"),
    ),
    Mutation(
        id="M22", phase=2, runner="vitest",
        description="stop clearing blank metadata fields, so a value cannot be removed",
        path=FRONTEND_SRC / "components" / "classification" / "MetadataEditor.tsx",
        anchor="      body[field] = text[field]?.trim() ? text[field].trim() : null;",
        replacement="      if (text[field]?.trim()) body[field] = text[field].trim();",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="sends every field",
        tags=("metadata", "ui"),
    ),
    Mutation(
        id="M23", phase=2, runner="vitest",
        description="send the human role label instead of its contract value",
        path=FRONTEND_SRC / "components" / "classification" / "MetadataEditor.tsx",
        anchor="      document_role: role === \"\" ? null : role,",
        replacement="      document_role: role === \"\" ? null : String(role).toLowerCase(),",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="sends the role the engineer chose",
        tags=("validation", "ui"),
    ),
    Mutation(
        id="M24", phase=2, runner="vitest",
        description="show the metadata form to a non-admin",
        path=FRONTEND_SRC / "components" / "classification" / "MetadataEditor.tsx",
        anchor="  if (!canEdit) {",
        replacement="  if (false) {",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="does not offer the controls to a non-admin",
        tags=("permission", "ui"),
    ),
    Mutation(
        id="M25", phase=2, runner="vitest",
        description="render a workbook's empty cells instead of populated ones",
        path=FRONTEND_SRC / "components" / "DocumentPreview.tsx",
        anchor="  const rows = sheet.rows.filter((row) => row.some((cell) => cell !== \"\"));",
        replacement="  const rows: string[][] = [];",
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="shows a workbook as sheets",
        tags=("preview", "ui"),
    ),
    Mutation(
        id="M26", phase=2, runner="vitest",
        description="render 'Unknown' for a field that was never recorded",
        path=FRONTEND_SRC / "components" / "DocumentTechnicalDetails.tsx",
        anchor='  if (value === null || value === undefined || value === "") return null;',
        replacement='  if (value === null || value === undefined || value === "") value = "Unknown";',
        target="src/components/DocumentWorkflows.test.tsx",
        keyword="renders nothing at all",
        tags=("honesty", "ui"),
    ),
)

#: Phase 3A: the Standards Library.
PHASE_3A = (
    Mutation(
        id="M27", phase=3,
        description="write a requirement whose citation does not resolve",
        path=APP / "standards.py",
        anchor="    if chunk is None:\n"
               "        raise RequirementError(f\"no chunk {chunk_id!r}: the citation does not resolve\")\n"
               "    if chunk[\"document_id\"] != standard_document_id:",
        replacement="    if chunk is None:\n"
                    "        chunk = {\"document_id\": standard_document_id, \"page_start\": 1, \"page_end\": 9999}\n"
                    "    if False:",
        target="tests/test_standards_library.py",
        keyword="without_a_resolving_citation",
        tags=("honesty", "citation"),
    ),
    Mutation(
        id="M28", phase=3,
        description="guess an unnumbered section into the preceding clause "
                    "instead of marking it low-confidence",
        path=APP / "standards.py",
        anchor="    score = 0.9\n    if clause is None:",
        replacement="    score = 0.9\n    if False:",
        target="tests/test_standards_library.py",
        keyword="could_not_identify_is_marked_for_verification",
        tags=("honesty", "confidence"),
    ),
    Mutation(
        id="M29", phase=3,
        description="keep selecting a superseded standard for new reviews",
        path=APP / "standards.py",
        anchor=" AND c.document_role = ? AND c.superseded_by IS NULL\",",
        replacement=" AND c.document_role = ?\",",
        target="tests/test_standards_library.py",
        keyword="superseded_standard_is_excluded_from_selection",
        tags=("supersession",),
    ),
    Mutation(
        id="M30", phase=3,
        description="drop the scope filter from the Standards Library list",
        path=APP / "standards.py",
        anchor='    where, args = _scope_clause(allowed_document_ids, "d.id")\n'
               "    sql = (",
        replacement='    where, args = " WHERE 1 = 1", []\n'
                    "    sql = (",
        target="tests/test_standards_library.py",
        keyword="unauthorised_user_sees_no_standard or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M31", phase=3,
        description="drop the scope filter from the requirements read",
        path=APP / "standards.py",
        # Disambiguated by the SELECT that follows: `verification_queue` opens
        # with the same _scope_clause line, and the harness refuses an
        # ambiguous anchor rather than guessing which read path was meant.
        anchor='    where, args = _scope_clause(allowed_document_ids, "r.standard_document_id")\n'
               "    rows = connect().execute(\n"
               '        "SELECT r.*, c.page_start AS chunk_page, c.section AS chunk_section"',
        replacement='    where, args = " WHERE 1 = 1", []\n'
                    "    rows = connect().execute(\n"
                    '        "SELECT r.*, c.page_start AS chunk_page, c.section AS chunk_section"',
        target="tests/test_standards_library.py",
        keyword="unauthorised_user_sees_no_standard or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M32", phase=3,
        description="stop auditing the supersede action",
        path=APP / "standards.py",
        # Disables the audit WITHOUT raising. Calling a name that does not
        # exist would fail the test with a NameError - the right verdict for
        # the wrong reason, and indistinguishable from a real detection. The
        # mutation has to reproduce the DEFECT: the action happens and no
        # record of it is written.
        anchor="    conn = connect()\n"
               "    try:\n"
               "        with conn:\n"
               "            conn.execute(\n"
               '                """INSERT INTO audit_events',
        replacement="    return\n"
                    "    conn = connect()\n"
                    "    try:\n"
                    "        with conn:\n"
                    "            conn.execute(\n"
                    '                """INSERT INTO audit_events',
        target="tests/test_standards_library.py",
        keyword="supersession_is_audited",
        tags=("audit",),
    ),
    Mutation(
        id="M33", phase=3,
        description="record recommendations ('should') as requirements",
        path=APP / "standards.py",
        anchor=r'    r"\b(shall|must|is\s+required\s+to|are\s+required\s+to|is\s+to\s+be"',
        replacement=r'    r"\b(shall|must|should|is\s+required\s+to|are\s+required\s+to|is\s+to\s+be"',
        target="tests/test_standards_library.py",
        keyword="recommendations_are_not_recorded",
        tags=("honesty",),
    ),
    Mutation(
        id="M34", phase=3,
        description="let re-extraction delete a human-confirmed requirement",
        path=APP / "standards.py",
        anchor='                " WHERE standard_document_id = ? AND confirmed_by IS NULL",',
        replacement='                " WHERE standard_document_id = ?",',
        target="tests/test_standards_library.py",
        keyword="never_discards_a_confirmed",
        tags=("data-loss",),
    ),
)

#: Phase 3A frontend: what the Standards Library refuses to say.
PHASE_3A_UI = (
    Mutation(
        id="M35", phase=3, runner="vitest",
        description="render '0 requirements' instead of 'none extracted yet'",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor='        {standard.requirement_count === 0\n'
               '          ? "No requirements extracted yet"',
        replacement='        {false\n'
                    '          ? "No requirements extracted yet"',
        target="src/views/StandardsView.test.tsx",
        keyword="no requirements have been extracted",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M36", phase=3, runner="vitest",
        description="guess a clause number when the parser could not identify one",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor='                  {row.clause ?? "Clause not identified"}',
        replacement='                  {row.clause ?? "1.1"}',
        target="src/views/StandardsView.test.tsx",
        keyword="clause could not be identified",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M37", phase=3, runner="vitest",
        description="stop labelling an extracted requirement as unconfirmed",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor='                {row.extraction_method === "extracted" && !row.confirmed_by && (',
        replacement="                {false && (",
        target="src/views/StandardsView.test.tsx",
        keyword="labels an extracted requirement",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M38", phase=3, runner="vitest",
        description="show the supersede control to a non-admin",
        path=FRONTEND_SRC / "views" / "StandardsView.tsx",
        anchor="      {isAdmin && (\n"
               '        <div className="flex flex-col gap-2 border-t border-white/10 pt-2">',
        replacement="      {true && (\n"
                    '        <div className="flex flex-col gap-2 border-t border-white/10 pt-2">',
        target="src/views/StandardsView.test.tsx",
        keyword="does not offer the supersede control",
        tags=("permission", "ui"),
    ),
)

#: Phase 3B: tables, limits, units, exceptions, conflicts, the queue.
#: `phase=4` only because `--phase 3` already selects 3A; the ids are the
#: stable handle and the tags say what each one is about.
PHASE_3B = (
    Mutation(
        id="M39", phase=4,
        description="stop reading the unit out of a table header",
        path=APP / "requirements_3b.py",
        anchor="    match = _HEADER_UNIT.search(header or \"\")\n    if not match:",
        replacement="    match = None\n    if not match:",
        target="tests/test_standards_3b.py",
        keyword="numeric_value_is_extracted_from_a_real_table",
        tags=("table", "unit"),
    ),
    Mutation(
        id="M40", phase=4,
        description="coerce an unknown unit to 0 instead of leaving it None",
        path=APP / "requirements_3b.py",
        anchor="    return claims.normalise(raw_value, raw_unit or \"\")",
        replacement="    m = claims.normalise(raw_value, raw_unit or \"\")\n"
                    "    from dataclasses import replace as _r\n"
                    "    return _r(m, normalized_value=m.normalized_value or 0.0)",
        target="tests/test_standards_3b.py",
        keyword="unknown_unit_yields_none",
        tags=("honesty", "unit"),
    ),
    Mutation(
        id="M41", phase=4,
        description="report an unparsed table as parsed, so completeness lies",
        path=APP / "tables.py",
        anchor='                unparsed_reason="no recoverable table geometry on this page",',
        replacement="                unparsed_reason=None,",
        target="tests/test_standards_3b.py",
        keyword="unparsed_table_lowers_completeness",
        tags=("honesty", "table"),
    ),
    Mutation(
        id="M42", phase=4,
        description="drop the exception clause, turning a compliant PSV into a finding",
        path=APP / "requirements_3b.py",
        anchor="    match = _EXCEPTION.search(sentence)\n    if not match:\n        return []",
        replacement="    match = None\n    if not match:\n        return []",
        target="tests/test_standards_3b.py",
        keyword="psv_exception_is_preserved or exception_is_stored",
        tags=("honesty", "exception"),
    ),
    Mutation(
        id="M43", phase=4,
        description="silently resolve a conflict by keeping only the first limit",
        path=APP / "requirements_3b.py",
        anchor="        if len(distinct) < 2:\n            continue",
        replacement="        if True:\n            continue",
        target="tests/test_standards_3b.py",
        keyword="limiting_the_same_field_differently_is_a_conflict",
        tags=("honesty", "conflict"),
    ),
    Mutation(
        id="M44", phase=4,
        description="leave extraction_method as 'extracted' after a human correction",
        path=APP / "standards.py",
        anchor='        "extraction_method": "human",',
        replacement='        "extraction_method": "extracted",',
        target="tests/test_standards_3b.py",
        keyword="correction_flips_extraction_method",
        tags=("honesty", "provenance"),
    ),
    Mutation(
        id="M45", phase=4,
        description="drop the scope filter from the verification queue",
        path=APP / "standards.py",
        anchor='    where, args = _scope_clause(allowed_document_ids, "r.standard_document_id")\n'
               '    rows = connect().execute(\n'
               '        "SELECT r.*, c.page_start AS chunk_page FROM standard_requirements r"\n'
               '        " LEFT JOIN chunks c ON c.id = r.chunk_id" + where +\n'
               '        " AND r.confirmed_by IS NULL"',
        replacement='    where, args = " WHERE 1 = 1", []\n'
                    '    rows = connect().execute(\n'
                    '        "SELECT r.*, c.page_start AS chunk_page FROM standard_requirements r"\n'
                    '        " LEFT JOIN chunks c ON c.id = r.chunk_id" + where +\n'
                    '        " AND r.confirmed_by IS NULL"',
        target="tests/test_standards_3b.py",
        keyword="unauthorised_user_sees_no_requirement or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M46", phase=4,
        description="make queuing extract synchronously, blocking the request",
        path=APP / "standards.py",
        anchor="    if existing is not None:\n        return existing[\"id\"]",
        replacement="    if existing is not None:\n        return existing[\"id\"]\n"
                    "    run_extraction_job(document_id)",
        target="tests/test_standards_3b.py",
        keyword="queued_and_drained_by_the_existing_worker",
        tags=("job",),
    ),
    Mutation(
        id="M47", phase=4,
        description="accept character fragmentation as a real table",
        path=APP / "tables.py",
        anchor="                if width > MAX_COLUMNS or _is_fragmented(rows):",
        replacement="                if False:",
        target="tests/test_standards_3b.py",
        keyword="character_fragmentation_is_not_accepted",
        tags=("table", "honesty"),
    ),
    Mutation(
        id="M48", phase=4,
        description="record a cross-reference cell ('see 5.2') as a numeric value",
        path=APP / "requirements_3b.py",
        anchor="    if not cell or not _CELL_VALUE.match(cell):\n        return None",
        replacement="    if not cell:\n        return None",
        target="tests/test_standards_3b.py",
        keyword="not_a_number_is_not_recorded",
        tags=("table", "honesty"),
    ),
)

#: Phase 4: datasheet intelligence. `phase=5` because --phase 4 already
#: selects 3B; the ids are the stable handle.
PHASE_4 = (
    Mutation(
        id="M49", phase=5,
        description="stop reading the unit off a datasheet value",
        path=APP / "datasheets.py",
        anchor='    unit = (match.group("unit") or "").strip() or None',
        replacement="    unit = None",
        target="tests/test_datasheets.py",
        keyword="value_with_its_unit_is_extracted",
        tags=("datasheet", "unit"),
    ),
    Mutation(
        id="M50", phase=5,
        description="treat a By Contractor field as a filled value, not a blank",
        path=APP / "datasheets.py",
        anchor="    marker = _BLANK_MARKERS.search(text)\n    if marker:",
        replacement="    marker = _BLANK_MARKERS.search(text)\n    if False:",
        target="tests/test_datasheets.py",
        keyword="by_contractor_field_is_recorded_as_blank",
        tags=("honesty", "missing-information"),
    ),
    Mutation(
        id="M51", phase=5,
        description="report a page that yielded nothing as parsed anyway",
        path=APP / "datasheets.py",
        # Re-anchored by B19: the write loop moved inside one transaction, +4.
        anchor="            if page_written == 0:\n                unparsed.append({",
        replacement="            if False:\n                unparsed.append({",
        target="tests/test_datasheets.py",
        keyword="unparsed_page_lowers_completeness",
        tags=("honesty", "completeness"),
    ),
    Mutation(
        id="M52", phase=5,
        description="stop detecting standards referenced by the datasheet",
        path=APP / "datasheets.py",
        anchor="    for match in _REFERENCED_STANDARD.finditer(text or \"\"):",
        replacement="    for match in _REFERENCED_STANDARD.finditer(\"\"):",
        target="tests/test_datasheets.py",
        keyword="referenced_standard_named_in_the_datasheet",
        tags=("datasheet",),
    ),
    Mutation(
        id="M53", phase=5,
        description="refuse same-unit comparison again, re-blocking the dB(A) case",
        path=APP / "claims.py",
        anchor="    if (a.normalized_value is None or b.normalized_value is None) and same_unit(a, b):",
        replacement="    if False:",
        target="tests/test_datasheets.py",
        keyword="same_unit_dba_values_compare",
        tags=("comparison", "unit"),
    ),
    Mutation(
        id="M54", phase=5,
        description="compare across different units, breaking ScaleMismatch",
        path=APP / "claims.py",
        anchor='    ua, ub = _fold_unit(a.raw_unit or ""), _fold_unit(b.raw_unit or "")\n    return bool(ua) and ua == ub',
        replacement='    ua, ub = _fold_unit(a.raw_unit or ""), _fold_unit(b.raw_unit or "")\n    return True',
        target="tests/test_datasheets.py",
        keyword="different_units_still_refuse",
        tags=("comparison", "honesty"),
    ),
    Mutation(
        id="M55", phase=5,
        description="drop the scope filter from the datasheet facts read",
        path=APP / "datasheets.py",
        anchor='    where, args = _scope_clause(allowed_document_ids, "f.submittal_document_id")',
        replacement='    where, args = " WHERE 1 = 1", []',
        target="tests/test_datasheets.py",
        keyword="unauthorised_user_sees_no_facts or empty_grant_set",
        tags=("permission",),
    ),
    Mutation(
        id="M56", phase=5,
        description="promote a value into a field label, inventing blank fields",
        path=APP / "datasheets.py",
        anchor="        if not is_field_label(label):\n            continue",
        replacement="        if False:\n            continue",
        target="tests/test_datasheets.py",
        keyword="value_is_never_promoted_into_a_field_label",
        tags=("honesty", "datasheet"),
    ),
)

#: Phase 5A: applicability selection. `phase=6` because --phase 5 already
#: selects phase 4; the ids are the stable handle.
PHASE_5A = (
    Mutation(
        id="M57", phase=6,
        description="stop matching standards the datasheet explicitly names",
        path=APP / "applicability.py",
        anchor="        if entry is not None:\n            out[entry[\"id\"]] = {",
        replacement="        if False:\n            out[entry[\"id\"]] = {",
        target="tests/test_applicability.py",
        keyword="named_in_the_datasheet_is_selected or citation_of_a_part",
        tags=("selection",),
    ),
    Mutation(
        id="M58", phase=6,
        description="silently drop a referenced standard the library lacks",
        path=APP / "applicability.py",
        anchor="        if normalise_identifier(identifier) not in matched_keys",
        replacement="        if False",
        target="tests/test_applicability.py",
        keyword="absent_from_the_library_is_reported_missing",
        tags=("honesty", "missing"),
    ),
    Mutation(
        id="M59", phase=6,
        description="let a semantically retrieved standard satisfy a missing "
                    "reference - THE failure this phase exists to prevent",
        path=APP / "applicability.py",
        anchor="    selected, missing = _semantic_cannot_cover_a_missing_reference(selected, missing)",
        replacement="    missing = [m for m in missing if not selected]",
        target="tests/test_applicability.py",
        keyword="semantically_retrieved_standard_does_not_satisfy",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M60", phase=6,
        description="select superseded standards again",
        path=APP / "applicability.py",
        anchor="    ids = standards.selectable_standard_ids(allowed_document_ids=allowed_document_ids)",
        replacement="    ids = frozenset(r[0] for r in connect().execute(\"SELECT document_id FROM document_classification WHERE document_role = 'COMPANY_STANDARD'\"))",
        target="tests/test_applicability.py",
        keyword="superseded_standard_is_not_selected",
        tags=("supersession",),
    ),
    Mutation(
        id="M61", phase=6,
        description="stop recording standards considered and ruled out",
        path=APP / "applicability.py",
        anchor="        if entry[\"id\"] in selected:\n            continue",
        replacement="        if True:\n            continue",
        target="tests/test_applicability.py",
        keyword="keeps_its_exclusion_reason",
        tags=("audit",),
    ),
    Mutation(
        id="M62", phase=6,
        description="stop auditing an engineer override",
        path=APP / "applicability.py",
        # Disables the audit WITHOUT raising. Calling a name that does not
        # exist fails the test with a NameError - the right verdict for the
        # wrong reason, and indistinguishable from a real detection. That is
        # honesty-audit entries 10 and 12, and this is the third time the
        # same shortcut has been reached for, so the reasoning lives here at
        # the mutation rather than only in the audit file.
        anchor='    """Durable record of a selection decision. Ids and counts only."""\n'
               '    conn = connect()',
        replacement='    """Durable record of a selection decision. Ids and counts only."""\n'
                    '    return\n'
                    '    conn = connect()',
        target="tests/test_applicability.py",
        keyword="override_writes_an_audit_row",
        tags=("audit",),
    ),
    Mutation(
        id="M63", phase=6,
        description="drop the confidence ceiling, allowing a high confidence",
        path=APP / "applicability.py",
        anchor="    confidence = min(float(confidence), ceiling)",
        replacement="    confidence = float(confidence)",
        target="tests/test_applicability.py",
        keyword="confidence_is_never_high",
        tags=("honesty",),
    ),
)

#: Phase 5B: the compliance comparison engine. `phase=7` because the lower
#: numbers are taken; the ids are the stable handle.
PHASE_5B = (
    Mutation(
        id="M64", phase=7,
        description="stop comparing numbers, so a breach is never caught",
        path=APP / "comparison.py",
        anchor="    verdict = claims._compatible(observed, limit)",
        replacement="    verdict = True",
        target="tests/test_comparison.py",
        keyword="numeric_breach_is_caught",
        tags=("deterministic",),
    ),
    Mutation(
        id="M65", phase=7,
        description="drop the exception, reporting a false breach against a "
                    "compliant PSV",
        path=APP / "comparison.py",
        anchor="    exception = _applicable_exception(requirement, subject)",
        replacement="    exception = None",
        target="tests/test_comparison.py",
        keyword="psv_at_108_db_is_compliant",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M66", phase=7,
        description="turn a blank By-Contractor field into NON_COMPLIANT",
        path=APP / "comparison.py",
        anchor='            "status": MISSING_INFORMATION,\n            "rationale": f"the submittal leaves this field to be provided ({marker})",',
        replacement='            "status": NON_COMPLIANT,\n            "rationale": f"the submittal leaves this field to be provided ({marker})",',
        target="tests/test_comparison.py",
        keyword="blank_by_contractor_field_is_missing_information",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M67", phase=7,
        description="store a finding whose citations do not resolve",
        path=APP / "comparison.py",
        anchor="    if unresolved:\n        status = NEEDS_ENGINEER_REVIEW",
        replacement="    if False:\n        status = NEEDS_ENGINEER_REVIEW",
        target="tests/test_comparison.py",
        keyword="citation_does_not_resolve or another_document",
        tags=("citation",),
    ),
    Mutation(
        id="M68", phase=7,
        description="guess a comparison when the units cannot be compared",
        path=APP / "comparison.py",
        anchor="    if verdict is None:\n        return {\n            \"status\": NEEDS_ENGINEER_REVIEW,",
        replacement="    if verdict is None:\n        verdict = True\n    if False:\n        return {\n            \"status\": NEEDS_ENGINEER_REVIEW,",
        target="tests/test_comparison.py",
        keyword="unknown_unit_yields_no_comparison",
        tags=("honesty", "unit"),
    ),
    Mutation(
        id="M69", phase=7,
        description="let the model overrule the deterministic comparison",
        path=APP / "comparison.py",
        anchor="    if not model_opinion or model_opinion == deterministic:\n        return deterministic, None\n    return deterministic, (",
        replacement="    if not model_opinion or model_opinion == deterministic:\n        return deterministic, None\n    return model_opinion, (",
        target="tests/test_comparison.py",
        keyword="model_disagreeing_does_not_change",
        tags=("section14", "critical"),
    ),
    Mutation(
        id="M70", phase=7,
        description="approve a review that examined a fraction of the fields",
        path=APP / "comparison.py",
        anchor='    if not completeness.get("sufficient"):',
        replacement="    if False:",
        target="tests/test_comparison.py",
        keyword="low_completeness_forces_manual_review",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M71", phase=7,
        description="allow a code override with no reason",
        path=APP / "comparison.py",
        anchor='    if recommended and code != recommended and not (override_reason or "").strip():',
        replacement="    if False:",
        target="tests/test_comparison.py",
        keyword="overriding_without_a_reason",
        tags=("audit",),
    ),
    Mutation(
        id="M72", phase=7,
        description="let completeness average instead of taking the weakest link",
        path=APP / "comparison.py",
        anchor="    overall = round(min(parts), 3) if parts else None",
        replacement="    overall = round(sum(parts) / len(parts), 3) if parts else None",
        target="tests/test_comparison.py",
        keyword="weakest_link_not_the_average",
        tags=("honesty",),
    ),
)

#: Document roles: the watched folder's subfolder convention, and the bulk
#: assignment endpoint. Not a phase - a contained fix between phases 5B and 6.
#:
#: M73 IS THE ONE THAT MATTERS. Every other mutation here breaks something a
#: user would notice. M73 makes the watcher guess a role from the filename,
#: which on this corpus is right 272 times out of 280 and would look like an
#: improvement in a diff.
ROLES_FIX = (
    Mutation(
        id="M73", phase=8,
        description="guess the role from the filename instead of the subfolder",
        path=APP / "watcher.py",
        # PATCHED ABOVE THE `len(parts) != 1` GUARD, not below it. The first
        # version of this mutation replaced the final return, which a file in
        # the ROOT never reaches - so it changed nothing for the only case the
        # test is about and reported NOT DETECTED against a test that was
        # standing exactly where it should. A mutation that cannot reach the
        # code path is a broken mutation, not a vacuous test, and the harness
        # saying so is the harness working.
        anchor="    parts = relative.parts",
        replacement='    if path.name.upper().startswith("SAES-"):\n'
                    '        return "COMPANY_STANDARD"\n'
                    "    parts = relative.parts",
        target="tests/test_document_roles.py",
        keyword="root_gets_no_role_even_when_it_looks_like_a_standard",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M74", phase=8,
        description="ingest from a role subfolder without applying the role",
        path=APP / "watcher.py",
        anchor="        tagged = self._apply_role(row[\"id\"], role, path.name, source, sha256,\n"
               "                                  only_if_unset=False)",
        replacement="        tagged = False",
        target="tests/test_document_roles.py",
        keyword="dropped_in_standards_is_ingested_as_a_company_standard",
    ),
    Mutation(
        id="M75", phase=8,
        description="skip the role on a duplicate, so an already-ingested "
                    "library can never be tagged by moving it",
        path=APP / "watcher.py",
        anchor='            tagged = self._apply_role(existing["id"], role, path.name, source, sha256)',
        replacement="            tagged = False",
        target="tests/test_document_roles.py",
        keyword="duplicate_dropped_into_standards_tags_the_document",
        tags=("critical",),
    ),
    Mutation(
        id="M76", phase=8,
        description="let a file in a folder overwrite a role a person set",
        path=APP / "watcher.py",
        anchor="source: str, sha256: str, *, only_if_unset: bool = True) -> bool:",
        replacement="source: str, sha256: str, *, only_if_unset: bool = False) -> bool:",
        target="tests/test_document_roles.py",
        keyword="never_overwrites_a_role_a_person_already_set",
        tags=("honesty",),
    ),
    Mutation(
        id="M77", phase=8,
        description="key watched files by bare filename again, so the same "
                    "name in two subfolders collides",
        path=APP / "watcher.py",
        anchor="        return path.resolve().relative_to(folder.resolve()).as_posix()",
        replacement="        return path.name",
        target="tests/test_document_roles.py",
        keyword="same_filename_in_two_subfolders",
    ),
    Mutation(
        id="M78", phase=8,
        description="DROP THE ADMIN GATE FROM THE BULK ROUTE, so any signed-in "
                    "caller can re-tag the corpus",
        path=APP / "main.py",
        anchor="    scope: access.AccessScope = Depends(access.current_scope),\n"
               "    actor: dict | None = Depends(admin_mod.current_admin),\n"
               "):\n"
               '    """Set one role on many documents. THE SAME PERMISSION, N TIMES.',
        replacement="    scope: access.AccessScope = Depends(access.current_scope),\n"
                    "    actor: dict | None = None,\n"
                    "):\n"
                    '    """Set one role on many documents. THE SAME PERMISSION, N TIMES.',
        target="tests/test_document_roles.py",
        keyword="non_admin_cannot_bulk_set_roles",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M79", phase=8,
        description="stop re-asking scope inside the bulk loop",
        path=APP / "main.py",
        anchor="            require_document(document_id, scope)\n"
               "        except HTTPException:",
        replacement="            pass\n"
                    "        except HTTPException:",
        target="tests/test_document_roles.py",
        keyword="outside_the_callers_scope_is_not_written",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M80", phase=8,
        description="report bulk failures as a silent count instead of by id",
        path=APP / "main.py",
        anchor='            failed.append({"document_id": document_id, "reason": "not_found"})',
        replacement="            pass",
        target="tests/test_document_roles.py",
        keyword="names_every_one_that_failed",
        tags=("honesty",),
    ),
    Mutation(
        id="M81", phase=8,
        description="let set_role report a change when the value is identical",
        path=APP / "classification.py",
        # RE-ANCHORED after `set_role` and `set_discipline` were refactored
        # onto one writer, which turned the column name into an f-string hole.
        # The old anchor stopped matching and the harness said "anchor matched
        # 0 times" instead of reporting a pass - the guard working, and the
        # reason an anchor must match EXACTLY once rather than at least once.
        anchor='            f" WHERE document_classification.{column}"\n'
               '            f" IS NOT excluded.{column}{guard}",',
        replacement='            f" WHERE 1 = 1{guard}",',
        target="tests/test_document_roles.py",
        keyword="separates_documents_it_changed or reports_whether_it_changed",
        tags=("honesty",),
    ),
    Mutation(
        id="M82", phase=8, runner="vitest",
        description="show the bulk selection to a non-admin, whose every "
                    "apply would 404",
        path=FRONTEND_SRC / "views" / "DocumentsView.tsx",
        anchor="                                selected={isAdmin ? selectedIds.includes(doc.id) : undefined}\n"
               "                                onToggleSelected={isAdmin ? toggleSelected : undefined}",
        replacement="                                selected={selectedIds.includes(doc.id)}\n"
                    "                                onToggleSelected={toggleSelected}",
        target="src/views/DocumentsView.bulkRole.test.tsx",
        keyword="no selection at all to a non-admin",
        tags=("permission",),
    ),
    Mutation(
        id="M83", phase=8, runner="vitest",
        description="report a partial bulk write as an unqualified success",
        path=FRONTEND_SRC / "views" / "DocumentsView.tsx",
        anchor="        failed.length\n"
               "          ? `${failed.length} could not be updated and were left unchanged`\n"
               "          : null,",
        replacement="        null,",
        target="src/views/DocumentsView.bulkRole.test.tsx",
        keyword="says which documents were not updated",
        tags=("honesty", "critical"),
    ),
)

#: Part A of the extraction preparation: the discipline each standard's own
#: cover page names. M84 is the one with teeth - the letter map is the rule
#: anyone would reach for, and it is wrong for whole families of this corpus.
DISCIPLINE = (
    Mutation(
        id="M84", phase=8,
        description="READ THE SUPERSEDED COMMITTEE out of revision-history "
                    "prose instead of requiring the header's colon",
        path=APP / "standards.py",
        anchor=r'    r"Document\s+Responsibility\s*:\s*(?P<window>[^:]{0,140})", re.IGNORECASE | re.DOTALL)',
        replacement=r'    r"Document\s+Responsibility\s*:?\s*(?:from\s+the\s+)?(?P<window>[^:]{0,140})", re.IGNORECASE | re.DOTALL)',
        target="tests/test_standard_discipline.py",
        keyword="revision_history_prose_is_never_parsed",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M85", phase=8,
        description="stop at the newline, losing every wrapped committee name",
        path=APP / "standards.py",
        anchor='_COMMITTEE = re.compile(r"^(?P<value>.{3,90}?Committee)\\b", re.IGNORECASE | re.DOTALL)',
        replacement='_COMMITTEE = re.compile(r"^(?P<value>.{3,90}?Committee)\\b", re.IGNORECASE)',
        target="tests/test_standard_discipline.py",
        keyword="wrapped_across_a_line_break",
    ),
    Mutation(
        id="M86", phase=8,
        description="store a value that ran into the issue date",
        path=APP / "standards.py",
        # Anchored at the CALL SITE, not at the pattern. The pattern literal
        # contains a quote, a backslash and a brace, and every attempt to write
        # it as an anchor produced a string that did not match the file - which
        # the harness correctly reported as "anchor matched 0 times" rather
        # than pretending to have mutated anything.
        anchor="        if _PLAIN_VALUE.match(head):",
        replacement="        if head:",
        target="tests/test_standard_discipline.py",
        keyword="ran_into_the_issue_date",
    ),
    Mutation(
        id="M87", phase=8,
        description="take the first header rather than the most frequent, so "
                    "one garbled page decides for the standard",
        path=APP / "standards.py",
        anchor="    ranked = sorted(counts.items(), key=lambda kv: -kv[1])",
        replacement="    ranked = list(counts.items())",
        target="tests/test_standard_discipline.py",
        keyword="most_frequent_header_wins",
    ),
    Mutation(
        id="M88", phase=8,
        description="resolve a tie by picking one instead of answering NULL",
        path=APP / "standards.py",
        anchor="    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:\n        return None",
        replacement="    if False:\n        return None",
        target="tests/test_standard_discipline.py",
        keyword="equally_often_yields_nothing",
        tags=("honesty",),
    ),
    Mutation(
        id="M89", phase=8,
        description="let the backfill overwrite a discipline a person set",
        path=APP / "standards.py",
        anchor="def backfill_disciplines(*, only_if_unset: bool = True) -> dict:",
        replacement="def backfill_disciplines(*, only_if_unset: bool = False) -> dict:",
        target="tests/test_standard_discipline.py",
        keyword="never_overwrites_a_discipline_a_person_set",
        tags=("honesty",),
    ),
    Mutation(
        id="M90", phase=8,
        description="report the unreadable documents as a count, not by name",
        path=APP / "standards.py",
        anchor='            result["without"].append(row["filename"])',
        replacement="            pass",
        target="tests/test_standard_discipline.py",
        keyword="names_what_it_could_not",
        tags=("honesty",),
    ),
    Mutation(
        id="M92", phase=8,
        description="ADD `should` TO THE MANDATORY VOCABULARY, recording "
                    "recommendations as obligations",
        path=APP / "standards.py",
        # A BACKSLASH-FREE SLICE of the pattern, on purpose. The full literal
        # is a raw regex full of `\b` and `\s+`, and three attempts to quote it
        # as an anchor produced strings that did not match the file - each
        # reported honestly by the harness as "anchor matched 0 times" rather
        # than as a passing mutation. This slice occurs exactly once in
        # standards.py (checked), which is all an anchor has to be.
        anchor="(shall|must|is",
        replacement="(shall|should|must|is",
        target="tests/test_standards_library.py",
        keyword="mandatory_vocabulary_is_saudi_aramcos_own",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M91", phase=8,
        description="accept a blank discipline, which reads as classified and "
                    "matches nothing",
        path=APP / "classification.py",
        anchor='        raise ValueError("discipline must not be blank; leave it NULL instead")',
        replacement="        pass",
        target="tests/test_standard_discipline.py",
        keyword="refuses_a_blank_value",
    ),
)

#: Extraction quality: the unit gate, the page footer, the dedupe, the
#: descriptive subject, and the orphaned job nobody would ever see.
EXTRACTION = (
    Mutation(
        id="M93", phase=8,
        description="keep any word after a number as a unit, so 'locations' "
                    "becomes a unit again",
        path=APP / "requirements_3b.py",
        anchor="    return cleaned if claims.is_unit(cleaned) else None",
        replacement="    return cleaned",
        target="tests/test_extraction_quality.py",
        keyword="not_a_unit_is_not_stored_as_one",
        tags=("honesty",),
    ),
    Mutation(
        id="M94", phase=8,
        description="stop stripping trailing punctuation, restoring the 'g/L.' "
                    "defect that broke the product's worked example",
        path=APP / "requirements_3b.py",
        anchor='    cleaned = text.rstrip(".,;:")',
        replacement="    cleaned = text",
        target="tests/test_extraction_quality.py",
        keyword="full_stop_is_not_part_of_the_unit",
        tags=("critical",),
    ),
    Mutation(
        id="M95", phase=8,
        description="STRIP THE BRACKET OFF dB(A), reopening the phase 5B "
                    "defect from the standards side",
        path=APP / "requirements_3b.py",
        anchor='and cleaned.count("(") < cleaned.count(")"):',
        replacement=":",
        target="tests/test_extraction_quality.py",
        keyword="db_a_survives_the_unit_gate",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M96", phase=8,
        description="stop stripping the page footer, putting it back inside "
                    "quoted requirement text",
        path=APP / "standards.py",
        anchor="claims.split_sentences(strip_page_furniture(chunk",
        replacement="claims.split_sentences((chunk",
        target="tests/test_extraction_quality.py",
        keyword="footer_is_removed_before_the_sentence_is_read",
        tags=("honesty",),
    ),
    Mutation(
        id="M97", phase=8,
        description="write the duplicate rows again",
        path=APP / "standards.py",
        anchor="            if key in seen:",
        replacement="            if False:",
        target="tests/test_extraction_quality.py",
        keyword="repeated_across_chunks_is_stored_once or second_copy_of_a_confirmed_row",
    ),
    Mutation(
        id="M98", phase=8,
        description="dedupe on text alone, dropping a citation when one "
                    "sentence appears under two clauses",
        path=APP / "standards.py",
        anchor="            key = (clause, sentence)",
        replacement="            key = (None, sentence)",
        target="tests/test_extraction_quality.py",
        keyword="different_clause_is_kept",
    ),
    Mutation(
        id="M99", phase=8,
        description="PUT THE DESCRIPTIVE SUBJECT INTO `field`, making the join "
                    "column read as populated while matching nothing",
        path=APP / "standards.py",
        anchor='                "subject": subject_of(sentence),',
        replacement='                "subject": subject_of(sentence),\n'
                    '                "field": subject_of(sentence),',
        target="tests/test_extraction_quality.py",
        keyword="field_stays_null",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M100", phase=8,
        description="never recover an orphaned running job",
        path=APP / "standards.py",
        anchor="AND state = 'running' AND updated_at < ?",
        replacement="AND state = 'nonesuch' AND updated_at < ?",
        target="tests/test_extraction_quality.py",
        keyword="left_running_by_a_dead_process",
    ),
    Mutation(
        id="M101", phase=8,
        description="recover jobs of ANY age, re-queueing work a live worker "
                    "is still doing",
        path=APP / "standards.py",
        anchor="    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)",
        replacement="    cutoff = (datetime.now(timezone.utc) + timedelta(days=3650)",
        target="tests/test_extraction_quality.py",
        keyword="started_moments_ago_is_left_alone",
    ),
)

#: The datasheet side: which strings are citations, where a unit lives, and
#: what is not a fact at all.
DATASHEET = (
    Mutation(
        id="M102", phase=8,
        description="MATCH A BARE ASME FAMILY LETTER again, reporting "
                    "'ASME B' as a missing reference nobody can look up",
        path=APP / "datasheets.py",
        anchor=r'    r"|ASME\s*B\d{1,2}\.\d{1,3}(?:\.\d{1,3})?"',
        replacement=r'    r"|ASME\s*[IVXB]+(?:\.\d+)?"',
        target="tests/test_reference_identifiers.py",
        keyword="bare_asme_family_letter",
        tags=("honesty",),
    ),
    Mutation(
        id="M103", phase=8,
        description="drop the SAMSS alternative, making ten citations invisible",
        path=APP / "datasheets.py",
        anchor=r'    r"|\d{2}-SAMSS-\d{3}"',
        replacement=r'    r"|(?!x)x-SAMSS-\d{3}"',
        target="tests/test_reference_identifiers.py",
        keyword="citation_shape_is_read_whole",
    ),
    Mutation(
        id="M104", phase=8,
        description="stop zero-padding the library filename, so a standard "
                    "cannot be matched to itself",
        path=APP / "applicability.py",
        anchor='    return f"{match.group(1).upper()}-{match.group(2).upper()}-{int(match.group(3)):03d}"',
        replacement='    return f"{match.group(1).upper()}-{match.group(2).upper()}-{match.group(3)}"',
        target="tests/test_reference_identifiers.py",
        keyword="padded_number or matches_the_citation_key",
    ),
    Mutation(
        id="M105", phase=8,
        description="stop absorbing the unit column, orphaning it as a field "
                    "named after a unit",
        path=APP / "datasheets.py",
        anchor="            if index < len(parts) and _is_numeric_cell(value):",
        replacement="            if False:",
        target="tests/test_datasheet_unit_layouts.py",
        keyword="unit_in_its_own_column",
        tags=("critical",),
    ),
    Mutation(
        id="M106", phase=8,
        description="stop taking the unit out of the label, losing it with no "
                    "trace that it existed",
        path=APP / "datasheets.py",
        anchor="        label, carried = _unit_in_label(label)",
        replacement="        label, carried = label, None",
        target="tests/test_datasheet_unit_layouts.py",
        keyword="unit_inside_the_label",
        tags=("critical",),
    ),
    Mutation(
        id="M107", phase=8,
        description="STRIP THE PARENTHETICAL OFF ANY UNIT, turning dB(A) into "
                    "decibels-absolute and reopening the phase 5B defect",
        path=APP / "claims.py",
        anchor="    if folded in _RECOGNISED_UNITS:\n        return text, None",
        replacement="    if False:\n        return text, None",
        target="tests/test_fact_gates.py",
        keyword="db_a_is_never_split",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M108", phase=8,
        description="lose the gauge reference, comparing a gauge pressure "
                    "against an absolute limit",
        path=APP / "datasheets.py",
        anchor="    base_unit, unit_reference = claims.split_reference(unit)",
        replacement="    base_unit, unit_reference = unit, None",
        target="tests/test_fact_gates.py",
        keyword="reference_is_stored_on_the_fact_row",
        tags=("critical",),
    ),
    Mutation(
        id="M109", phase=8,
        description="call a label furniture after ONE page, deleting real "
                    "fields to remove a header",
        path=APP / "datasheets.py",
        anchor="FURNITURE_PAGE_THRESHOLD = 3",
        replacement="FURNITURE_PAGE_THRESHOLD = 1",
        target="tests/test_fact_gates.py",
        keyword="two_pages_is_kept or repeated_many_times_on_one_page",
    ),
    Mutation(
        id="M110", phase=8,
        description="open the categorical list, letting a signature block back "
                    "in as a fact",
        path=APP / "datasheets.py",
        anchor='    return " ".join((value or "").strip().lower().split()) in _CATEGORICAL_VALUES',
        replacement='    return bool((value or "").strip())',
        target="tests/test_fact_gates.py",
        keyword="free_text_is_not_a_categorical_answer",
        tags=("honesty",),
    ),
    Mutation(
        id="M111", phase=8,
        description="store the chunk's heading as the section even when it is "
                    "another column's value",
        path=APP / "datasheets.py",
        anchor="    return text if is_field_label(text) else None",
        replacement="    return text",
        target="tests/test_fact_gates.py",
        keyword="section_that_is_not_a_label_is_null",
        tags=("honesty",),
    ),
)

#: The containment matcher and the last of the datasheet recall fixes.
MATCHER = (
    Mutation(
        id="M112", phase=8,
        description="MATCH ON A SUBSTRING instead of whole words, so "
                    "'design pressure' matches inside 'redesign pressure'",
        path=APP / "comparison.py",
        anchor=r'    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None',
        replacement="    return needle in haystack",
        target="tests/test_containment_match.py",
        keyword="whole_words",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M113", phase=8,
        description="pick a candidate arbitrarily when two fields tie, instead "
                    "of refusing the match",
        path=APP / "comparison.py",
        anchor='    if len(best) > 1:',
        replacement="    if False:",
        target="tests/test_containment_match.py",
        keyword="genuine_tie_returns_no_match",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M114", phase=8,
        description="take the SHORTEST field name, pairing a requirement with "
                    "the least specific field named in it",
        path=APP / "comparison.py",
        # Re-anchored 2026-09-21: the match_rules integration (ba73a8c) now
        # takes the longest over the hits its rules ALLOWED, and the old
        # anchor on `hits` matched nothing - silently disarming this mutation.
        anchor='    longest = max(len(h["name"]) for h in allowed)',
        replacement='    longest = min(len(h["name"]) for h in allowed)',
        target="tests/test_containment_match.py",
        keyword="longest_field_name_wins",
    ),
    Mutation(
        id="M115", phase=8,
        description="let a CATEGORICAL fact match, reviving the insulation "
                    "false friend",
        path=APP / "comparison.py",
        anchor="        if not fact_has_number(fact):\n            continue",
        replacement="        if False:\n            continue",
        target="tests/test_containment_match.py",
        keyword="categorical_fact_never_matches",
        tags=("honesty",),
    ),
    Mutation(
        id="M116", phase=8,
        description="scope the matcher on the NORMALISED value, silently "
                    "excluding every unconvertible unit including dB(A)",
        path=APP / "comparison.py",
        anchor='    if requirement.get("raw_value") in (None, ""):\n        return none',
        replacement='    if requirement.get("value") is None:\n        return none',
        target="tests/test_containment_match.py",
        keyword="unit_cannot_be_converted_is_still_matched",
        tags=("critical",),
    ),
    Mutation(
        id="M117", phase=8,
        description="treat a small integer followed by a unit as a line "
                    "number again, discarding most numeric rows on a page",
        path=APP / "datasheets.py",
        anchor=("        if re.fullmatch(r" + chr(34) + chr(92) + "d{1,3}" + chr(34) + ", value) and not _unit_follows(parts, index + 2):"),
        replacement=("        if re.fullmatch(r" + chr(34) + chr(92) + "d{1,3}" + chr(34) + ", value):"),
        target="tests/test_fact_gates.py",
        keyword="line_number or followed_by_a_unit",
        tags=("critical",),
    ),
    Mutation(
        id="M118", phase=8,
        description="record a date as a measurement, so a signature block "
                    "becomes a numeric fact",
        path=APP / "datasheets.py",
        # ANCHORED ON THE PREDICATE, not on the call site in extract_facts.
        # The first version mutated the gate, which only runs inside a full PDF
        # extraction that these fixtures do not drive - so it reported NOT
        # DETECTED against tests that cover the rule perfectly well at the
        # level they can reach. The wiring itself is evidenced by the measured
        # end-to-end run, where the signature fact disappeared.
        anchor="    return bool(_DATE_VALUE.match(value or \"\"))",
        replacement="    return False",
        target="tests/test_fact_gates.py",
        keyword="a_date_is_not_a_quantity",
        tags=("honesty",),
    ),
)

#: Table rows, the dimension-aware unit guard, and the identifier rule.
TABLE_AND_UNITS = (
    Mutation(
        id="M119", phase=8,
        description="STOP CLASSIFYING TABLE ROWS, restoring a limit of "
                    "<= 6,900 kPa that the standard never states",
        path=APP / "requirements_3b.py",
        anchor="    if is_table_row(sentence):\n        return TABLE_ROW",
        replacement="    if False:\n        return TABLE_ROW",
        target="tests/test_table_row_requirements.py",
        keyword="classify_prefers_table_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M120", phase=8,
        description="classify a real limit as a table row, so a requirement "
                    "that states its own number stops being checked",
        path=APP / "requirements_3b.py",
        anchor="    if _COMPARATOR_PRESENT.search(text):\n        return False",
        replacement="    if False:\n        return False",
        target="tests/test_table_row_requirements.py",
        keyword="states_its_own_limit_stays_a_numeric_limit or cites_a_table_is_still_a_limit",
        tags=("critical",),
    ),
    Mutation(
        id="M121", phase=8,
        description="let compare() treat a table row as a limit again",
        path=APP / "comparison.py",
        # ANCHORED ON THE SECOND LINE of the condition. The first ends in a
        # backslash continuation, and every attempt to carry that through a
        # string literal produced an anchor that did not match the file -
        # which the harness reported as "matched 0 times" rather than as a
        # pass. Disabling the fact half disables the branch just as well.
        # NOW ALSO CARRYING THE TYPE, because the relative-limit branch added
        # in the next task repeats this line verbatim and the anchor started
        # matching twice - reported as a harness error, which is what it was:
        # the mutation did not run and proved nothing either way.
        anchor=('    if requirement.get("requirement_type") == '
                'requirements_3b.TABLE_ROW \\\n'
                '            and fact is not None and not fact.get("is_blank"):'),
        replacement="    if False:",
        target="tests/test_table_row_requirements.py",
        keyword="compare_refuses_a_table_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M122", phase=8,
        description="drop the row text from the finding, leaving a verdict "
                    "with no way to see the table",
        path=APP / "comparison.py",
        anchor='                f"The row reads: {fragment}"),',
        replacement='                ""),',
        target="tests/test_table_row_requirements.py",
        keyword="quotes_the_row",
    ),
    Mutation(
        id="M123", phase=8,
        description="compare units by SPELLING only, refusing a kPa rule "
                    "against a bar value the engine can convert",
        path=APP / "comparison.py",
        anchor="    if both_normalised:",
        replacement="    if False:",
        target="tests/test_table_row_requirements.py",
        keyword="kpa_rule_and_a_bar_value",
    ),
    Mutation(
        id="M124", phase=8,
        description="compare units by DIMENSION always, so dB(A) and dB - "
                    "which share no dimension - are treated as the same unit",
        path=APP / "comparison.py",
        anchor="    return claims.same_unit(requirement_unit, fact_unit)",
        replacement="    return True",
        target="tests/test_table_row_requirements.py",
        keyword="weighted_unit_and_an_unweighted_one or unconvertible_pair",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M126", phase=8,
        description="accept an equipment tag as a unit again",
        path=APP / "datasheets.py",
        anchor="    return digits >= 2 and letters >= 3",
        replacement="    return False",
        target="tests/test_datasheet_unit_layouts.py",
        keyword="equipment_tag_is_still_refused or no_longer_reads_a_tag_number",
        tags=("honesty",),
    ),
    Mutation(
        id="M127", phase=8,
        description="present the nominal field denominator as a measured count",
        path=APP / "comparison.py",
        anchor='                f"NOMINAL ESTIMATE of {total} ({pages} pages x "',
        replacement='                f"{total} ({pages} pages x "',
        target="tests/test_comparison.py",
        keyword="denominator",
        tags=("honesty",),
    ),
)

#: Findings a reviewer can reach, keep and correct.
REACHABLE = (
    Mutation(
        id="M128", phase=8,
        description="drop the review_run_id filter, so one run's findings can "
                    "only be found by fetching every finding ever written",
        path=APP / "review.py",
        anchor='        clauses.append("review_run_id = ?")',
        replacement='        clauses.append("1 = 1 OR ? IS NULL")',
        target="tests/test_findings_reachable.py",
        keyword="run_filter_returns_only_that_run",
    ),
    Mutation(
        id="M129", phase=8,
        description="LET A RUN ID REACH PAST THE GRANT TABLES, returning "
                    "findings for a submittal the caller may not read",
        path=APP / "review.py",
        anchor="    if allowed_document_ids is not None:\n        if not allowed_document_ids:\n            return []",
        replacement="    if allowed_document_ids is not None:\n        if not allowed_document_ids:\n            allowed_document_ids = None",
        target="tests/test_findings_reachable.py",
        keyword="cannot_reach_a_document_the_caller_may_not_read",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M130", phase=8,
        description="DELETE CONFIRMED FINDINGS ON RE-RUN, destroying an "
                    "engineer's decision with a routine maintenance action",
        path=APP / "comparison.py",
        anchor='                "DELETE FROM review_findings WHERE review_run_id = ?"\n                " AND confirmed_by IS NULL",',
        replacement='                "DELETE FROM review_findings WHERE review_run_id = ?",',
        target="tests/test_comparison.py",
        keyword="confirmed",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M131", phase=8,
        description="re-propose a pairing a human already rejected",
        path=APP / "comparison.py",
        anchor="    rejected = _rejected_keys_for(requirement)",
        replacement="    rejected = set()",
        target="tests/test_findings_reachable.py",
        keyword="rejected_pair_is_never_proposed_again",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M132", phase=8,
        description="let a rejection block every fact for that requirement, "
                    "not just the pair",
        path=APP / "comparison.py",
        # The FIRST version of this mutation broadened the SQL, which returns
        # more rejection ROWS without blocking more facts - the tests passed
        # and were right to. This one implements what the description claims.
        anchor='        if fact_key(fact, tag_scoped=tag_scoped) in rejected:',
        replacement="        if rejected:",
        target="tests/test_findings_reachable.py",
        keyword="does_not_block_another_fact",
    ),
    Mutation(
        id="M133", phase=8,
        description="overwrite an existing rejection, losing who refused the "
                    "pairing and why",
        path=APP / "comparison.py",
        anchor='            "INSERT OR IGNORE INTO review_pair_rejections"',
        replacement='            "INSERT OR REPLACE INTO review_pair_rejections"',
        target="tests/test_findings_reachable.py",
        keyword="keeps_the_first_decision",
    ),
    Mutation(
        id="M134", phase=8,
        description="KEY A REJECTION ON THE ROW ID, so an engineer's "
                    "correction stops applying at the next re-extraction",
        path=APP / "comparison.py",
        # A single-line, backslash-free slice. The function body contains
        # escaped quotes and a blank line, and carrying either through a
        # literal broke the file twice.
        anchor='        str(requirement.get("standard_document_id") or ""),',
        replacement='        str(requirement.get("id") or ""),',
        target="tests/test_comparison.py",
        keyword="survives_re_extraction",
        tags=("honesty", "critical"),
    ),
)

#: The model tier of the matcher. It may CHOOSE, never NAME.
MODEL_TIER = (
    Mutation(
        id="M135", phase=11,
        description="SHOW THE MODEL THE NUMBERS, so it can be pulled toward "
                    "whichever pairing makes the arithmetic come out",
        path=APP / "comparison.py",
        anchor="""        lines.append(f"{index}. {fact.get('field_name')}   (section: {section})")""",
        replacement="""        lines.append(f"{index}. {fact.get('field_name')} = {fact.get('raw_value')} {fact.get('raw_unit')}   (section: {section})")""",
        target="tests/test_model_matching.py",
        keyword="prompt_carries_no_value",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M158", phase=11,
        description="LET THE THINKING MODEL THINK, so Ollama answers into "
                    "`thinking` and every call reads as model_malformed",
        path=APP / "comparison.py",
        anchor='        "think": False,',
        replacement='        "think": True,',
        target="tests/test_model_matching.py",
        keyword="turns_thinking_off",
        tags=("critical",),
    ),
    Mutation(
        id="M136", phase=11,
        description="send the whole clause instead of 400 characters",
        path=APP / "comparison.py",
        anchor='        or requirement.get("requirement_text") or "").split())[:400]',
        replacement='        or requirement.get("requirement_text") or "").split())',
        target="tests/test_model_matching.py",
        keyword="capped_at_four_hundred",
    ),
    Mutation(
        id="M137", phase=11,
        description="OFFER CATEGORICAL AND BLANK FACTS as candidates, which is "
                    "how the insulation false friend reaches a model",
        path=APP / "comparison.py",
        anchor='        if not fact_has_number(fact) or fact.get("is_blank"):\n            continue\n        if not _units_comparable(',
        replacement='        if False:\n            continue\n        if not _units_comparable(',
        target="tests/test_model_matching.py",
        keyword="categorical_fact_never_enters or blank_fact_never_enters",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M138", phase=11,
        description="offer facts in ANY unit, so a length can be paired with a "
                    "pressure limit",
        path=APP / "comparison.py",
        anchor="        if not _units_comparable(requirement, fact,\n                                 requirement_unit, _unit_measure(fact)):\n            continue",
        replacement="        if False:\n            continue",
        target="tests/test_model_matching.py",
        keyword="another_dimension_never_enters",
        tags=("critical",),
    ),
    Mutation(
        id="M139", phase=11,
        description="compare unit SPELLINGS in the pre-filter, dropping the "
                    "kPa-against-bar pairing the engine can evaluate exactly",
        path=APP / "comparison.py",
        anchor='    if both_normalised:\n        left = claims.unit_dimension(requirement_unit.raw_unit or "")',
        replacement='    if False:\n        left = claims.unit_dimension(requirement_unit.raw_unit or "")',
        target="tests/test_model_matching.py",
        keyword="another_spelling_is_still_a_candidate",
    ),
    Mutation(
        id="M140", phase=11,
        description="let a pairing an engineer refused back into the model's "
                    "shortlist",
        path=APP / "comparison.py",
        anchor="    refused = _rejected_keys_for(requirement)",
        replacement="    refused = set()",
        target="tests/test_model_matching.py",
        keyword="rejected_pair_never_enters",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M141", phase=11,
        description="remove the candidate cap, so one prompt can carry every "
                    "numeric field on the sheet",
        path=APP / "comparison.py",
        anchor="    return out[:MAX_CANDIDATES]",
        replacement="    return out",
        target="tests/test_model_matching.py",
        keyword="capped_at_twelve",
    ),
    Mutation(
        id="M142", phase=11,
        description="PAIR A LONE CANDIDATE WITHOUT ASKING, turning 'only one "
                    "field was eligible' into a finding about the contractor",
        path=APP / "comparison.py",
        anchor="    candidates = candidate_facts(requirement, facts)\n    if not candidates:",
        replacement=(
            "    candidates = candidate_facts(requirement, facts)\n"
            "    if len(candidates) == 1:\n"
            "        only = candidates[0]\n"
            '        return {"fact": only, "matched_phrase": only.get("field_name"),\n'
            '                "method": METHOD_MODEL_CHOICE, "reason": "only candidate",\n'
            '                "candidates": []}\n'
            "    if not candidates:"),
        target="tests/test_model_matching.py",
        keyword="one_candidate_is_still_asked",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M143", phase=11,
        description="ACCEPT AN INDEX OUTSIDE THE SHORTLIST, letting a model "
                    "reach a fact that was never offered to it",
        path=APP / "comparison.py",
        anchor="    if choice.choice is not None and not 0 <= choice.choice < len(candidates):",
        replacement="    if choice.choice is not None and choice.choice >= len(candidates):",
        target="tests/test_model_matching.py",
        keyword="negative_index",
        tags=("critical",),
    ),
    Mutation(
        id="M144", phase=11,
        description="trust the index when the model's own sentence names a "
                    "DIFFERENT field - it may choose, never name",
        path=APP / "comparison.py",
        anchor="                return None, MODEL_NAMED_OTHER",
        replacement="                pass",
        target="tests/test_model_matching.py",
        keyword="naming_a_different_candidate",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M145", phase=11,
        description="ASK ONCE INSTEAD OF TWICE, so a coin toss becomes a finding",
        path=APP / "comparison.py",
        anchor="    second, reason = _ask_model_once(requirement, candidates)",
        replacement="    second, reason = first, None",
        target="tests/test_model_matching.py",
        keyword="disagree_make_no_pairing",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M146", phase=11,
        description="drop the per-run budget, so a pre-filter defect becomes "
                    "an unbounded number of model calls",
        path=APP / "comparison.py",
        anchor="    if budget is not None and budget.exhausted():\n        return _none_match(MODEL_BUDGET)\n    if budget is not None:\n        budget.spend()\n    first, reason",
        replacement="    if budget is not None:\n        budget.spend()\n    first, reason",
        target="tests/test_model_matching.py",
        keyword="budget",
    ),
    Mutation(
        id="M147", phase=11,
        description="ASK THE MODEL EVEN WHERE CONTAINMENT ALREADY DECIDED, "
                    "replacing evidence with a guess",
        path=APP / "comparison.py",
        anchor='        if (fact is None and match["reason"] != AMBIGUOUS_MATCH',
        replacement='        if (match["reason"] != AMBIGUOUS_MATCH',
        target="tests/test_model_matching.py",
        keyword="containment_takes_precedence",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M148", phase=11,
        description="HAND A TIE TO THE MODEL, replacing 'we could not tell' "
                    "with an answer nobody checked",
        path=APP / "comparison.py",
        anchor='and match["reason"] != AMBIGUOUS_MATCH\n',
        replacement='and match["reason"] != "no tie ever"\n',
        target="tests/test_model_matching.py",
        keyword="tie_never_reaches_the_model",
        tags=("honesty", "critical"),
    ),
    # M149 WAS WITHDRAWN, NOT SOLVED. It flipped a model-paired finding from
    # CONFIDENCE_MODEL_ASSISTED (0.5) to CONFIDENCE_DETERMINISTIC (0.9) and no
    # test could see it: `_confidence_label` has two bands and "high" is
    # forbidden, so 0.5 and 0.9 both print "medium", and the label is the only
    # confidence a finding stores. The design's §11 item - "confidence 0.5 and
    # label medium" - is therefore only half observable. What actually
    # distinguishes a model pairing on screen is `match_method` and the
    # rationale prefix, and those are M147 and M150. Recorded in
    # docs/status-honesty-audit.md rather than proved by a vacuous assertion.
    Mutation(
        id="M150", phase=11,
        description="drop the 'paired by model' prefix, so a guessed pairing "
                    "and a derived one read alike",
        path=APP / "comparison.py",
        anchor="""                f"{MODEL_PAIR_PREFIX}{match.get('reason') or ''}. \"""",
        replacement="""                f"{match.get('reason') or ''}. \"""",
        target="tests/test_model_matching.py",
        keyword="says_who_paired_it",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M151", phase=11,
        description="say nothing on the finding when the tier was off or the "
                    "model could not answer",
        path=APP / "comparison.py",
        anchor="        elif model_reason:",
        replacement="        elif False:",
        target="tests/test_model_matching.py",
        keyword="turned_off or unavailable_model_says_so or declined_pairing",
        tags=("honesty",),
    ),
    Mutation(
        id="M152", phase=11,
        description="IGNORE match_enabled, so the off switch does nothing",
        path=APP / "comparison.py",
        anchor="            if not settings.match_enabled:",
        replacement="            if False:",
        target="tests/test_model_matching.py",
        keyword="turned_off",
    ),
    Mutation(
        id="M153", phase=11,
        description="TAKE THE CONFIRMER FROM THE REQUEST BODY, so one person "
                    "can sign a pairing in another's name",
        # THE PROTECTION IS THE SCHEMA, so that is what this mutates. The
        # route cannot read a confirmer out of a field that does not exist;
        # mutating the route alone proved nothing, because `getattr` on an
        # absent field is None whatever the client sent.
        path=APP / "schemas.py",
        anchor="    approved_at: str | None = None\n    #: CONFIRM THE PAIRING.",
        replacement="    approved_at: str | None = None\n    confirmed_by: str | None = None\n    #: CONFIRM THE PAIRING.",
        target="tests/test_model_matching.py",
        keyword="body_naming_a_confirmer",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M154", phase=11,
        description="accept an anonymous confirmation, which records nothing "
                    "and answers 200",
        path=APP / "main.py",
        anchor="        if scope.user_id is None:",
        replacement="        if False:",
        target="tests/test_model_matching.py",
        keyword="confirmation_with_no_identity",
        tags=("honesty",),
    ),
    Mutation(
        id="M155", phase=11,
        description="LET AN OUT-OF-SCOPE CALLER REJECT A PAIRING, and learn "
                    "the finding exists by the answer",
        # THE DENY IS LAYERED: the finding, the requirement and the fact are
        # each scoped, so neutralising one alone changes no answer - which is
        # the point of writing it three times. This mutates the deny itself,
        # where an empty grant set stops meaning nothing and starts meaning
        # everything (the deliverables.py defect, in this file).
        path=APP / "comparison.py",
        anchor='    if not allowed_document_ids:\n        return " WHERE 1 = 0", []',
        replacement='    if not allowed_document_ids:\n        return " WHERE 1 = 1", []',
        target="tests/test_model_matching.py",
        keyword="out_of_scope_caller",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M156", phase=11,
        description="record a rejection against a finding with no pairing, "
                    "which matches no pair and is never applied",
        path=APP / "comparison.py",
        anchor='    if not finding.get("requirement_id") or not finding.get("fact_id"):',
        replacement="    if False:",
        target="tests/test_model_matching.py",
        keyword="no_pairing_is_refused",
    ),
    Mutation(
        id="M157", phase=11,
        description="stop the rejection reaching the rejection writer, so the "
                    "correction loop is broken end to end",
        path=APP / "comparison.py",
        anchor="    return reject_pair(dict(requirement), dict(fact),",
        replacement="    return dict(finding) or reject_pair(dict(requirement), dict(fact),",
        target="tests/test_model_matching.py",
        keyword="stops_it_being_proposed_again",
    ),
)


#: The three defects the model tier's failed gate exposed, plus the default
#: it was turned off by.
GATE_FALLOUT = (
    Mutation(
        id="M159", phase=12,
        description="SHIP THE MODEL TIER ON AGAIN, after it failed its hard "
                    "gate with six false pairings in seven",
        path=APP / "config.py",
        anchor="    match_enabled: bool = False",
        replacement="    match_enabled: bool = True",
        target="tests/test_model_matching.py",
        keyword="shipped_default_is_off",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M160", phase=12,
        description="print the same startup line whatever the tier's state, "
                    "so an operator cannot tell whether it ran",
        path=APP / "main.py",
        anchor="    if settings.match_enabled:",
        replacement="    if False:",
        target="tests/test_model_matching.py",
        keyword="startup_line_names_the_tier",
        tags=("honesty",),
    ),
    Mutation(
        id="M161", phase=12,
        description="TREAT AN APPLICABILITY TRIGGER AS A LIMIT - the "
                    "SAES-D-001 9.2.5 defect, reinstated",
        path=APP / "requirements_3b.py",
        anchor="    if is_applicability_trigger(sentence):\n        return APPLICABILITY_TRIGGER",
        replacement="    if False:\n        return APPLICABILITY_TRIGGER",
        target="tests/test_trigger_and_relative.py",
        keyword="defers_to_another_document_is_a_trigger",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M162", phase=12,
        description="let the trigger check swallow a sentence that states its "
                    "OWN quantity, deleting real requirements",
        path=APP / "requirements_3b.py",
        anchor="    without_documents = _DOCUMENT_REF.sub(\" \", remainder)\n    return not _BARE_NUMBER.search(without_documents)",
        replacement="    return True",
        target="tests/test_trigger_and_relative.py",
        keyword="states_its_own_quantity_is_not_a_trigger",
        tags=("critical",),
    ),
    Mutation(
        id="M163", phase=12,
        description="let the trigger check swallow a table deferral, undoing "
                    "the table_row work",
        path=APP / "requirements_3b.py",
        anchor="    if _TABLE_REFERENCE.search(remainder):\n        # A table is not another document.",
        replacement="    if False:\n        # A table is not another document.",
        target="tests/test_trigger_and_relative.py",
        keyword="predicate_itself_refuses_a_deferral_to_a_table",
    ),
    Mutation(
        id="M164", phase=12,
        description="call a sentence a trigger although it names no document",
        path=APP / "requirements_3b.py",
        anchor="    if not _DOCUMENT_REF.search(remainder):\n        return False",
        replacement="    if False:\n        return False",
        target="tests/test_trigger_and_relative.py",
        keyword="states_its_own_quantity_is_not_a_trigger",
    ),
    Mutation(
        id="M165", phase=12,
        description="PAIR AN APPLICABILITY TRIGGER, so its threshold is "
                    "compared as though it were a limit",
        path=APP / "comparison.py",
        anchor='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT})',
        replacement='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT,\n    requirements_3b.APPLICABILITY_TRIGGER})',
        target="tests/test_trigger_and_relative.py",
        keyword="outside_the_matcher",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M166", phase=12,
        description="TREAT A MARGIN AS AN ABSOLUTE LIMIT - the SAES-D-001 "
                    "14.3 defect, reinstated",
        path=APP / "requirements_3b.py",
        anchor="    if is_relative_limit(sentence):\n        return RELATIVE_LIMIT",
        replacement="    if False:\n        return RELATIVE_LIMIT",
        target="tests/test_trigger_and_relative.py",
        keyword="margin_from_a_reference",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M167", phase=12,
        description="search the whole sentence for the relative phrase instead "
                    "of anchoring it at the parsed limit, deleting a real one",
        path=APP / "requirements_3b.py",
        anchor="    return bool(_RELATIVE_TAIL.match(text[match.start(\"value\"):]))",
        replacement="    return bool(_RELATIVE_TAIL.search(text))",
        target="tests/test_trigger_and_relative.py",
        keyword="comparative_phrase_before_the_limit",
        tags=("critical",),
    ),
    Mutation(
        id="M168", phase=12,
        description="COMPARE A RELATIVE LIMIT, producing arithmetic against a "
                    "number that is a margin and not a value",
        path=APP / "comparison.py",
        anchor="    if requirement.get(\"requirement_type\") == requirements_3b.RELATIVE_LIMIT \\\n            and fact is not None and not fact.get(\"is_blank\"):",
        replacement="    if False:",
        target="tests/test_trigger_and_relative.py",
        keyword="compare_refuses_a_relative_limit",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M169", phase=12,
        description="drop relative limits from the matcher, leaving the "
                    "refusal branch dead and every one of them missing "
                    "information",
        path=APP / "comparison.py",
        anchor='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT})',
        replacement='MATCHABLE_TYPES = frozenset({\n    "numeric_limit", requirements_3b.TABLE_ROW})',
        target="tests/test_trigger_and_relative.py",
        keyword="relative_limit_is_matchable",
    ),
    Mutation(
        id="M170", phase=12,
        description="LET A BRACKET-ONLY LINE BECOME A FIELD OF ITS OWN - the "
                    "`material 2` defect, reinstated",
        path=APP / "datasheets.py",
        anchor="        if out and out[-1] and _PARENTHETICAL_ONLY.fullmatch(part):",
        replacement="        if False:",
        target="tests/test_field_name_truncation.py",
        keyword="bracket_only",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M171", phase=12,
        description="let a cross-reference cell take the label position, so "
                    "the real label becomes its value",
        path=APP / "datasheets.py",
        anchor="        if _CROSS_REFERENCE.fullmatch(part):\n            index += 1\n            continue",
        replacement="        if False:\n            index += 1\n            continue",
        target="tests/test_field_name_truncation.py",
        keyword="cross_reference or dotted_clause or bracket_only_line",
        tags=("critical",),
    ),
    # M172 WAS WITHDRAWN, NOT SOLVED. It relaxed the clause-reference rule
    # from two dots to one, so `1.6` would be skipped as a pointer - and no
    # test could see it, because `is_field_label` already refuses a bare
    # number at the label position. Skipping the cell and pairing it into a
    # rejected pair emit the same nothing. The two-dot bound is kept because
    # the rule should be TRUE and not merely harmless, but it changes no
    # output today, and an assertion that claimed otherwise would be the
    # vacuous kind. Recorded in docs/status-honesty-audit.md.
    Mutation(
        id="M173", phase=12,
        description="widen the cross-reference rule until it swallows fields "
                    "whose names merely contain the word",
        path=APP / "datasheets.py",
        anchor=r'    r"\s*[-:]?\s*[A-Za-z0-9]{1,4}(?:\s+of\s+\d{1,3})?"',
        replacement=r'    r".*"',
        target="tests/test_field_name_truncation.py",
        keyword="merely_contains_a_reference_word",
    ),
)


#: A form repeated on every page is not a title block, and the diagnostic
#: that used to hide it.
REPEATED_FORM = (
    Mutation(
        id="M174", phase=13,
        description="COUNT PAGES ALONE AGAIN, so a form repeated on every "
                    "page is stripped as a header - EF1975-DAS-I-06 back to "
                    "zero facts from 162 rows",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = False",
        target="tests/test_repeated_form.py",
        keyword="repeated_form_with_per_page_values",
        tags=("critical",),
    ),
    Mutation(
        id="M175", phase=13,
        description="drop condition 1, so a title block with constant text is "
                    "promoted to a field",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = answered * 2 > len(pages)",
        target="tests/test_repeated_form.py",
        keyword="title_block or both_conditions or one_answer_throughout",
        tags=("critical",),
    ),
    Mutation(
        id="M176", phase=13,
        description="DROP CONDITION 2, so a mostly-empty title block that "
                    "caught two stray fragments files them as facts - the "
                    "`al khafji onshore facility` row returning",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = distinct >= 2",
        target="tests/test_repeated_form.py",
        keyword="mostly_empty_label or both_conditions",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M177", phase=13,
        description="answered on exactly half the pages counts as a field, "
                    "an off-by-one on the boundary",
        path=APP / "datasheets.py",
        anchor="        is_field = distinct >= 2 and answered * 2 > len(pages)",
        replacement="        is_field = distinct >= 2 and answered * 2 >= len(pages)",
        target="tests/test_repeated_form.py",
        keyword="exactly_half",
    ),
    Mutation(
        id="M178", phase=13,
        description="count an EMPTY cell as an answer, which makes every "
                    "header look answered on every page",
        path=APP / "datasheets.py",
        anchor="            if answer:\n                answered_pages[name].add(page)",
        replacement="            if True:\n                answered_pages[name].add(page)",
        target="tests/test_repeated_form.py",
        keyword="mostly_empty_label or title_block",
        tags=("critical",),
    ),
    Mutation(
        id="M179", phase=13,
        description="SAY 'no label-value pairs recovered' WHATEVER HAPPENED, "
                    "so a page whose pairs were all filtered reads like a "
                    "page that could not be parsed",
        path=APP / "datasheets.py",
        anchor="    if not pairs:\n        return \"no label-value pairs recovered from this page\"",
        replacement="    if True:\n        return \"no label-value pairs recovered from this page\"",
        target="tests/test_repeated_form.py",
        keyword="names_the_filters or never_claims",
        tags=("honesty",),
    ),
    Mutation(
        id="M180", phase=13,
        description="report the filter counts in any order, so the biggest "
                    "cause no longer reads first",
        path=APP / "datasheets.py",
        anchor="                               key=lambda kv: (-kv[1], kv[0]))",
        replacement="                               key=lambda kv: (kv[1], kv[0]))",
        target="tests/test_repeated_form.py",
        keyword="ordered_by_size",
    ),
)


#: Two numbers in one cell, and two fields in one label.
RANGES_AND_COMPOUNDS = (
    Mutation(
        id="M181", phase=14,
        description="stop splitting compound labels, so Design/Operating "
                    "pressure stays one unusable field",
        path=APP / "datasheets.py",
        anchor="    parts = compound_label_parts(label)\n    if parts is None:",
        replacement="    parts = None\n    if parts is None:",
        target="tests/test_ranges_and_compounds.py",
        keyword="compound_label_with_a_matching_value",
        tags=("critical",),
    ),
    Mutation(
        id="M182", phase=14,
        description="SPLIT A COMPOUND LABEL WHOSE VALUE DID NOT SPLIT, "
                    "attaching one number to a field that is half wrong",
        path=APP / "datasheets.py",
        anchor="    if len(values) != len(names) or not all(values):",
        replacement="    if False:",
        target="tests/test_ranges_and_compounds.py",
        keyword="mismatched_separator_count",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M183", phase=14,
        description="parse the value of a compound label that never split, "
                    "recording a number against two fields at once",
        path=APP / "datasheets.py",
        anchor="    if not blank and compound_label_parts(field_label) is not None:",
        replacement="    if False:",
        target="tests/test_ranges_and_compounds.py",
        keyword="did_not_split_stores_no_parsed_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M184", phase=14,
        description="DISTRIBUTE A UNIT ONTO A HALF THAT HAS ITS OWN, "
                    "inventing psig onto a number already in psig",
        path=APP / "datasheets.py",
        anchor="    if units[-1] and not any(units[:-1]):",
        replacement="    if units[-1]:",
        target="tests/test_ranges_and_compounds.py",
        keyword="never_added_to_a_half",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M185", phase=14,
        description="split on a separator inside brackets, so (Cp/Cv) tears "
                    "a real value in half",
        path=APP / "datasheets.py",
        anchor="    masked = _outside_brackets(text)",
        replacement="    masked = text",
        target="tests/test_ranges_and_compounds.py",
        keyword="not_compound_is_left_alone",
    ),
    Mutation(
        id="M186", phase=14,
        description="let `&` split a tight word, so P&ID Reference becomes a "
                    "field called P",
        path=APP / "datasheets.py",
        anchor='_COMPOUND_SEPARATORS = (("/", r"\\s*/\\s*"), ("&", r"\\s+&\\s+"))',
        replacement='_COMPOUND_SEPARATORS = (("/", r"\\s*/\\s*"), ("&", r"\\s*&\\s*"))',
        target="tests/test_ranges_and_compounds.py",
        keyword="not_compound_is_left_alone",
    ),
    Mutation(
        id="M187", phase=14,
        description="READ A UNITLESS PAIR AS A RANGE, so the drum sheet's "
                    "table of contents becomes two facts",
        path=APP / "datasheets.py",
        anchor="    if range_unit is None:\n        return None",
        replacement="    if False:\n        return None",
        target="tests/test_ranges_and_compounds.py",
        keyword="unitless_range",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M188", phase=14,
        description="drop the low-above-high guard, so 10-05 reads as a "
                    "range from ten to five",
        path=APP / "datasheets.py",
        anchor="    if left is None or right is None or left > right:",
        replacement="    if left is None or right is None:",
        target="tests/test_ranges_and_compounds.py",
        keyword="descending_pair_is_refused",
    ),
    Mutation(
        id="M189", phase=14,
        description="accept a range with prose after it, so a P&ID reference "
                    "becomes a quantity",
        path=APP / "datasheets.py",
        anchor='    if rest and not rest.startswith("("):\n        return None',
        replacement="    if False:\n        return None",
        target="tests/test_ranges_and_compounds.py",
        keyword="prose_after_a_range_refuses_it",
        tags=("critical",),
    ),
    Mutation(
        id="M190", phase=14,
        description="REWRITE THE DEGREE GLYPH ANYWHERE, turning any word "
                    "ending in oc into a temperature",
        path=APP / "datasheets.py",
        anchor=r'_DEGREE_GLYPH = re.compile(r"(?<=\d)[Oo]([CF])\b")',
        replacement=r'_DEGREE_GLYPH = re.compile(r"[Oo]([CF])\b")',
        target="tests/test_ranges_and_compounds.py",
        keyword="word_ending_in_oc",
        tags=("critical",),
    ),
    Mutation(
        id="M191", phase=14,
        description="COMPARE A RANGE AT ITS MEAN, inventing a number the "
                    "document does not state",
        path=APP / "comparison.py",
        anchor='        chosen = spread[1] if side == "max" else spread[0]',
        replacement="        chosen = (spread[0] + spread[1]) / 2",
        target="tests/test_ranges_and_compounds.py",
        keyword="mean_of_a_range or upper_limit or lower_limit",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M192", phase=14,
        description="swap the ends, so an upper limit is judged against the "
                    "bottom of the band",
        path=APP / "comparison.py",
        anchor='    if operator in ("<=", "<"):\n        return "max"',
        replacement='    if operator in ("<=", "<"):\n        return "min"',
        target="tests/test_ranges_and_compounds.py",
        keyword="upper_limit_is_compared",
        tags=("critical",),
    ),
    Mutation(
        id="M193", phase=14,
        description="give an exact-equality rule an end of the range to "
                    "compare, answering a question nobody can answer",
        path=APP / "comparison.py",
        anchor='    if operator in (">=", ">"):\n        return "min"\n    return None',
        replacement='    if operator in (">=", ">"):\n        return "min"\n    return "max"',
        target="tests/test_ranges_and_compounds.py",
        keyword="exact_equality_rule",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M194", phase=14,
        description="let the matcher skip a range fact, leaving every range "
                    "unpaired and the comparison code dead",
        path=APP / "comparison.py",
        anchor='    return (fact.get("raw_value") not in (None, "")\n            or fact_range(fact) is not None)',
        replacement='    return fact.get("raw_value") not in (None, "")',
        target="tests/test_ranges_and_compounds.py",
        keyword="range_fact_can_be_matched",
        tags=("critical",),
    ),
    Mutation(
        id="M195", phase=14,
        description="drop the range from the value gate, so every range is "
                    "discarded as free text before it reaches create_fact",
        path=APP / "datasheets.py",
        anchor="            if parsed_value is None and parse_range(value) is not None:",
        replacement="            if False:",
        target="tests/test_ranges_and_compounds.py",
        keyword="survives_the_value_gate",
        tags=("critical",),
    ),
)


#: The guard `db.add_column_if_missing` puts round a concurrent
#: migrator, quoted once so two mutations can share it.
DUPLICATE_GUARD = (
    '        if "duplicate column" not in str(exc).lower():\n'
    "            raise")



#: The check-then-ALTER race that every ensure_schema carried.
MIGRATION_RACE = (
    Mutation(
        id="M196", phase=15,
        description="NEVER SWALLOW THE DUPLICATE COLUMN, restoring the race "
                    "that killed one request in three when two threads "
                    "migrated the same database at once",
        path=APP / "db.py",
        anchor=DUPLICATE_GUARD,
        replacement="        if True:\n            raise",
        target="tests/test_migration_race.py",
        keyword="two_threads_can_migrate",
        tags=("critical",),
    ),
    # M197 WAS WITHDRAWN, NOT SOLVED. It removed the message test - swallow
    # EVERY OperationalError, not just the duplicate - and no test could see
    # it, because the check that follows catches the same cases: an unrelated
    # error means the ALTER did not happen, so the column is still missing and
    # `if column not in columns_of(...)` re-raises. The message test is kept
    # because it states WHICH failure is expected and keeps the swallow
    # narrow, but it changes no output today and an assertion claiming
    # otherwise would be the vacuous kind. Third instance of this shape; see
    # entry 39 of docs/status-honesty-audit.md.
    Mutation(
        id="M198", phase=15,
        description="ALTER a table that does not exist, inventing a shape "
                    "whose creator never agreed to it",
        path=APP / "db.py",
        anchor="    if not existing or column in existing:",
        replacement="    if column in existing:",
        target="tests/test_migration_race.py",
        keyword="missing_table_is_not_this_functions_business",
    ),
)


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



#: Which equipment a fact describes.
EQUIPMENT_TAG = (
    Mutation(
        id="M199", phase=16,
        description="read the tag only from the VALUE, so the PSV sheet - "
                    "which puts the key and the tag in one cell - yields no "
                    "tag on any page",
        path=APP / "datasheets.py",
        anchor=TAG_TAIL,
        replacement='    return " ".join((value or "").split()) or None',
        target="tests/test_equipment_tag.py",
        keyword="tag_row_yields_its_tag_verbatim",
        tags=("critical",),
    ),
    Mutation(
        id="M200", phase=16,
        description="TIDY THE TAG, producing an identifier that matches "
                    "nothing anybody searches for",
        path=APP / "datasheets.py",
        anchor='    return tail or " ".join((value or "").split()) or None',
        replacement='    return (tail.split("(")[0].strip() or '
                    '" ".join((value or "").split()) or None)',
        target="tests/test_equipment_tag.py",
        keyword="tag_is_not_tidied",
        tags=("honesty",),
    ),
    Mutation(
        id="M201", phase=16,
        description="let `Tag description` name the equipment, so a fact is "
                    "stamped with what the equipment IS rather than which "
                    "one it is",
        path=APP / "datasheets.py",
        anchor=r'    r"^\s*(?:tag\s*(?:no\.?|number)|item\s*no\.?)\s*[.:\-]*\s*(?P<tail>.*)$",',
        replacement=r'    r"^\s*(?:tag|item)\s*\w*\s*[.:\-]*\s*(?P<tail>.*)$",',
        target="tests/test_equipment_tag.py",
        keyword="what_is_not_a_tag_row",
    ),
    Mutation(
        id="M202", phase=16,
        description="STOP STAMPING A ONE-TAG DOCUMENT'S OTHER PAGES, so the "
                    "drum's facts lose the vessel they describe",
        path=APP / "datasheets.py",
        anchor="    if len(mentioned) == 1:",
        replacement="    if False:",
        target="tests/test_equipment_tag.py",
        keyword="one_tag_in_a_document_stamps_every_page",
        tags=("critical",),
    ),
    Mutation(
        id="M203", phase=16,
        description="INHERIT A TAG ACROSS PAGES THAT NAME DIFFERENT "
                    "EQUIPMENT, filing one valve's numbers against another",
        path=APP / "datasheets.py",
        anchor="    return {page: tags.get(page) for page in pairs_by_page}",
        replacement="    return {page: (tags.get(page) or next(iter(mentioned), None))\n"
                    "            for page in pairs_by_page}",
        target="tests/test_equipment_tag.py",
        keyword="multi_tag_document_keeps_each_page or several_tags_stay",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M204", phase=16,
        description="PUT THE TAG IN EVERY FACT KEY, retiring every rejection "
                    "ever recorded against a single-tag datasheet",
        path=APP / "comparison.py",
        anchor=TAG_SCOPED,
        replacement="    return True",
        target="tests/test_equipment_tag.py",
        keyword="single_tag_document_keeps_todays_key or survives_re_extraction",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M205", phase=16,
        description="leave the tag out of the key on a MULTI-tag sheet, so "
                    "rejecting one valve's field suppresses every valve's",
        path=APP / "comparison.py",
        anchor=TAG_IN_KEY,
        replacement="    if False:\n        parts.append(None)",
        target="tests/test_equipment_tag.py",
        keyword="rejecting_one_tag_does_not_suppress",
        tags=("critical",),
    ),
    Mutation(
        id="M206", phase=16,
        description="stamp a finding with a tag when there is no fact, "
                    "claiming the sheet said something it did not",
        path=APP / "comparison.py",
        anchor='        "equipment_tag": (fact or {}).get("equipment_tag"),',
        replacement='        "equipment_tag": (fact or {}).get("equipment_tag") or "unknown",',
        target="tests/test_equipment_tag.py",
        keyword="no_fact_names_no_equipment",
        tags=("honesty",),
    ),
    Mutation(
        id="M207", phase=16,
        description="let the tag row become a fact, so a matcher can pair a "
                    "requirement with an equipment identifier",
        path=APP / "datasheets.py",
        anchor="            if tag_from_pair(label, value) is not None:",
        replacement="            if False:",
        target="tests/test_equipment_tag.py",
        keyword="tag_row_never_becomes_a_fact",
    ),
)


#: A crashed run, and the engineer's final code (master plan section 15).
REVIEW_GOVERNANCE = (
    Mutation(
        id="M208", phase=17,
        description="DELETE the orphaned run instead of marking it failed, "
                    "erasing the only record that anybody ever started it",
        path=APP / "submittal_review.py",
        anchor='            "UPDATE review_runs SET status = \'failed\', refusal_reason = ?,"\n'
               '            " updated_at = ? WHERE status = \'running\'",',
        replacement='            "DELETE FROM review_runs WHERE ? IS NOT NULL"\n'
                    '            " AND ? IS NOT NULL AND status = \'running\'",',
        target="tests/test_orphaned_review_runs.py",
        keyword="kept_because_a_crashed_run_is_history",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M209", phase=17,
        description="sweep every run, not only the running ones, rewriting "
                    "the outcome of every review ever done at each startup",
        path=APP / "submittal_review.py",
        anchor='            " updated_at = ? WHERE status = \'running\'",',
        replacement='            " updated_at = ? WHERE 1 = 1 OR status = \'running\'",',
        target="tests/test_orphaned_review_runs.py",
        keyword="not_running_is_left_alone or completed_runs_outcome_survives",
        tags=("critical",),
    ),
    Mutation(
        id="M210", phase=17,
        description="never call the sweep at startup, so the orphan stays "
                    "`running` and locks its submittal out of the product",
        path=APP / "main.py",
        anchor="        submittal_review_mod.fail_orphaned_review_runs()",
        replacement="        pass",
        target="tests/test_orphaned_review_runs.py",
        keyword="sweep_is_called_at_startup",
    ),
    Mutation(
        id="M211", phase=18,
        description="LET AN ENGINEER OVERRIDE THE RECOMMENDATION WITH NO "
                    "REASON, which is the whole of section 15's governance",
        path=APP / "comparison.py",
        anchor='    if recommended and code != recommended and not (override_reason or "").strip():',
        replacement="    if False:",
        target="tests/test_review_code.py",
        keyword="overriding_the_recommendation_requires_a_reason",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M212", phase=18,
        description="OVERWRITE THE RECOMMENDATION WITH THE DECISION, so no "
                    "reader can ever see what the machine itself said",
        path=APP / "comparison.py",
        anchor='            "UPDATE review_runs SET engineer_final_code = ?,"',
        replacement='            "UPDATE review_runs SET refusal_reason = NULL,"\n'
                    '            " engineer_final_code = ?,"',
        target="tests/test_review_code.py",
        keyword="recommendation_survives_the_decision",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M213", phase=18,
        description="accept any string at all as a review code",
        path=APP / "comparison.py",
        anchor="    if code not in DEFAULT_CODES:",
        replacement="    if False:",
        target="tests/test_review_code.py",
        keyword="not_a_review_code_is_refused",
    ),
    Mutation(
        id="M214", phase=18,
        description="RE-RUN A DECIDED RUN, leaving the engineer's code "
                    "attached to findings it was never made about",
        path=APP / "comparison.py",
        anchor='    if replace and run.get("engineer_final_code"):',
        replacement="    if False:",
        target="tests/test_review_code.py",
        keyword="re_running_a_decided_run_is_refused",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M215", phase=18,
        description="block EVERY re-run, not only a decided one, so no fix "
                    "can ever reach an existing run again",
        path=APP / "comparison.py",
        anchor='    if replace and run.get("engineer_final_code"):',
        replacement="    if replace:",
        target="tests/test_review_code.py",
        keyword="without_a_decision_still_re_runs or never_blocked_by_another_runs_decision",
    ),
    Mutation(
        id="M221", phase=18,
        description="GATE THE ENGINEER'S OWN ACTION ON BEING AN ADMIN, which "
                    "answers every other engineer with the admin 404",
        path=APP / "main.py",
        anchor="    actor = _actor_from_scope(scope)",
        replacement="    actor = admin_mod.current_admin(request)",
        target="tests/test_review_code.py",
        keyword="not_an_admin_can_record_the_final_code",
        tags=("critical",),
    ),
)


#: The Dashboard's four cards (CLAUDE.md rule 10, master plan section 20).
REVIEW_DASHBOARD = (
    Mutation(
        id="M216", phase=19,
        description="COUNT EVERY DOCUMENT ON THE MACHINE in the dashboard's "
                    "tiles, so a tile reveals what the caller may not read",
        path=APP / "main.py",
        anchor="    where, args = _document_scope(allowed)\n\n    submittals = [",
        replacement='    where, args = " WHERE 1 = 1", []\n\n    submittals = [',
        target="tests/test_review_dashboard.py",
        keyword="outside_the_grant_set or empty_grant_set_counts_nothing",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M217", phase=19,
        description="call every completed run awaiting a decision, so a run "
                    "an engineer has already signed keeps asking to be signed",
        path=APP / "main.py",
        anchor='                   and not run.get("engineer_final_code"))',
        replacement="                   )",
        target="tests/test_review_dashboard.py",
        keyword="takes_the_run_off_the_waiting_list",
    ),
    Mutation(
        id="M218", phase=19,
        description="SHOW THE NEEDS-ATTENTION NUMBER WITH NO BREAKDOWN, "
                    "which is a count a reader can only trust, not check",
        path=APP / "main.py",
        anchor='        "needs_attention_reasons": reasons,',
        replacement='        "needs_attention_reasons": {},',
        target="tests/test_review_dashboard.py",
        keyword="says_why_and_the_reasons_sum",
        tags=("honesty",),
    ),
    Mutation(
        id="M219", phase=19,
        description="count a review still RUNNING as one that is done, "
                    "reporting work that has not happened yet",
        path=APP / "main.py",
        anchor='    reviewed = {run["submittal_document_id"] for run in runs\n'
               '                if (run.get("status") or "") == "completed"}',
        replacement='    reviewed = {run["submittal_document_id"] for run in runs}',
        target="tests/test_review_dashboard.py",
        keyword="still_running_does_not_count_as_reviewed or "
                "no_completed_run_is_awaiting_review",
        tags=("honesty",),
    ),
    Mutation(
        id="M220", phase=19,
        description="put every run ever done in the Recent Reviews table, "
                    "which is the metrics dump rule 10 forbids",
        path=APP / "main.py",
        anchor="    recent = [_run_summary(run, scope) for run in runs[:5]]",
        replacement="    recent = [_run_summary(run, scope) for run in runs]",
        target="tests/test_review_dashboard.py",
        keyword="recent_table_stays_compact",
    ),
    Mutation(
        id="M222", phase=19,
        description="drop the name from the run's join, leaving a screen to "
                    "print the engineer's primary key at them",
        path=APP / "submittal_review.py",
        anchor='    "SELECT r.*, u.display_name AS decided_by_name"',
        replacement='    "SELECT r.*, NULL AS decided_by_name"',
        target="tests/test_review_code.py",
        keyword="carries_the_name_and_not_only_the_id or "
                "arrives_with_the_run_rather_than_a_lookup_per_row",
    ),
    Mutation(
        id="M223", phase=19,
        description="INNER-join the decider, so a run signed by a departed "
                    "engineer disappears along with them",
        path=APP / "submittal_review.py",
        anchor=" FROM review_runs r LEFT JOIN users u ON u.id = r.decided_by",
        replacement=" FROM review_runs r JOIN users u ON u.id = r.decided_by",
        target="tests/test_review_code.py",
        keyword="outlives_the_engineer_who_made_it or "
                "undecided_run_has_no_name_rather_than_a_placeholder",
        tags=("critical",),
    ),
    Mutation(
        id="M224", phase=19,
        description="stop putting the name on the wire, so the client is "
                    "back to rendering the id it was given",
        path=APP / "main.py",
        anchor='        "decided_by_name": run.get("decided_by_name"),',
        replacement='        "decided_by_name": None,',
        target="tests/test_review_code.py",
        keyword="not_an_admin_can_record_the_final_code",
    ),
)


#: The read-only database explorer: who may look, and what they may see.
ADMIN_EXPLORER = (
    Mutation(
        id="M225", phase=20,
        description="OPEN THE TABLE LIST TO ANY SIGNED-IN CALLER, which hands "
                    "every table name in the system to a non-admin",
        path=APP / "main.py",
        anchor="def admin_db_tables(request: Request,\n"
               "                    actor: dict | None = Depends(admin_mod.current_admin)):",
        replacement="def admin_db_tables(request: Request,\n"
                    "                    actor: dict | None = None):",
        target="tests/test_admin_db_routes.py",
        keyword="real_non_admin_with_a_real_token or unauthenticated_caller",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M226", phase=20,
        description="open the ROW reader to any caller - the same hole one "
                    "route further in, where the data actually is",
        path=APP / "main.py",
        anchor="    limit: int = Query(50, ge=1, description=\"rows to return; capped server-side\"),\n"
               "    offset: int = Query(0, ge=0, description=\"rows to skip\"),\n"
               "    actor: dict | None = Depends(admin_mod.current_admin),",
        replacement="    limit: int = Query(50, ge=1, description=\"rows to return; capped server-side\"),\n"
                    "    offset: int = Query(0, ge=0, description=\"rows to skip\"),\n"
                    "    actor: dict | None = None,",
        target="tests/test_admin_db_routes.py",
        keyword="real_non_admin_with_a_real_token or unauthenticated_caller",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M227", phase=20,
        description="STOP MASKING ENTIRELY, putting every stored password "
                    "hash on the wire",
        path=APP / "admin_explorer.py",
        anchor="    rows = [mask_row(columns, list(r)) for r in cur.fetchall()]",
        replacement="    rows = [list(r) for r in cur.fetchall()]",
        target="tests/test_admin_db_routes.py",
        keyword="password_hash_never_reaches_the_wire",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M228", phase=20,
        description="narrow the rule to EQUALITY, so `password_hash` and "
                    "`setup_token_sha256` sail through unmasked",
        path=APP / "admin_explorer.py",
        anchor="    return any(part in name for part in SENSITIVE_NAME_PARTS)",
        replacement="    return name in SENSITIVE_NAME_PARTS",
        target="tests/test_admin_explorer.py",
        keyword="credential_shaped_name_is_masked",
        tags=("critical",),
    ),
    Mutation(
        id="M229", phase=20,
        description="let the token_count exemption match as a SUBSTRING, a "
                    "hole shaped like a naming convention",
        path=APP / "admin_explorer.py",
        anchor="    if name in NOT_CREDENTIALS:",
        replacement="    if any(x in name for x in NOT_CREDENTIALS):",
        target="tests/test_admin_explorer.py",
        keyword="exemption_is_by_exact_name_and_does_not_spread",
    ),
    Mutation(
        id="M230", phase=20,
        description="mask a NULL too, claiming a secret is stored where none "
                    "is - itself a disclosure about the row",
        path=APP / "admin_explorer.py",
        anchor="        MASK if (is_sensitive(name) and value is not None) else value",
        replacement="        MASK if is_sensitive(name) else value",
        target="tests/test_admin_explorer.py",
        keyword="null_stays_null_rather_than_becoming_a_mask",
        tags=("honesty",),
    ),
    Mutation(
        id="M231", phase=20,
        description="DROP the sensitive column from the listing instead of "
                    "masking it, so the explorer misreports the table's shape",
        path=APP / "admin_explorer.py",
        anchor='            "pk": bool(r[5]), "sensitive": is_sensitive(r[1])}\n'
               '            for r in conn.execute(f\'PRAGMA table_info("{table}")\')]',
        replacement='            "pk": bool(r[5]), "sensitive": is_sensitive(r[1])}\n'
                    '            for r in conn.execute(f\'PRAGMA table_info("{table}")\')\n'
                    '            if not is_sensitive(r[1])]',
        target="tests/test_admin_explorer.py",
        keyword="marks_the_column_without_hiding_it",
        tags=("honesty",),
    ),
)


#: The discipline overlay: one canonical value, the raw one kept intact.
DISCIPLINE_CANONICAL = (
    Mutation(
        id="M232", phase=21,
        description="NULL an unmapped spelling instead of copying it through, "
                    "turning 'nobody reviewed this' into 'has no discipline'",
        path=APP / "disciplines.py",
        anchor="    return aliases().get(text, text)",
        replacement="    return aliases().get(text)",
        target="tests/test_discipline_canonical.py",
        keyword="absent_from_the_mapping_copies_through or "
                "unmapped_spelling_survives_the_backfill",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M233", phase=21,
        description="OVERWRITE THE RAW SPELLING with the canonical one, "
                    "destroying the only record of what the document said",
        path=APP / "disciplines.py",
        anchor='                "UPDATE document_classification SET discipline_canonical = ?"\n'
               '                " WHERE document_id = ?", (value, row["document_id"]))',
        replacement='                "UPDATE document_classification SET discipline_canonical = ?,"\n'
                    '                " discipline = ? WHERE document_id = ?",\n'
                    '                (value, value, row["document_id"]))',
        target="tests/test_discipline_canonical.py",
        keyword="leaves_raw_BYTE_UNTOUCHED or "
                "two_spellings_become_one_value",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M234", phase=21,
        description="filter on the RAW column again, so the same question "
                    "asked two ways gets two different answers",
        path=APP / "classification.py",
        anchor='            f"COALESCE(c.discipline_canonical, c.discipline) IN ({marks})")',
        replacement='            f"c.discipline IN ({marks})")',
        target="tests/test_discipline_canonical.py",
        keyword="finds_both_spellings_whichever_one_is_asked_for",
    ),
    Mutation(
        id="M235", phase=21,
        description="stop canonicalising the REQUESTED value, so an alias "
                    "spelling in the query matches nothing at all",
        path=APP / "classification.py",
        anchor="        wantedcanon = [disciplines_mod.canonical(d) or d\n"
               "                       for d in wanted.disciplines]",
        replacement="        wantedcanon = list(wanted.disciplines)",
        target="tests/test_discipline_canonical.py",
        keyword="finds_both_spellings_whichever_one_is_asked_for",
    ),
    Mutation(
        id="M236", phase=21,
        description="drop the COALESCE, so a row written before the column "
                    "existed vanishes from every filtered result",
        path=APP / "classification.py",
        anchor='            f"COALESCE(c.discipline_canonical, c.discipline) IN ({marks})")',
        replacement='            f"c.discipline_canonical IN ({marks})")',
        target="tests/test_discipline_canonical.py",
        keyword="written_before_the_column_existed_is_still_findable",
    ),
    Mutation(
        id="M242", phase=21,
        description="DROP A VALUE from the suggestion INSERT - the exact "
                    "defect that would have failed every document ingest",
        path=APP / "classification.py",
        anchor='            " VALUES (?,?,?,?,?,?,?,NULL,NULL)"',
        replacement='            " VALUES (?,?,?,?,?,?,NULL,NULL)"',
        target="tests/test_discipline_canonical.py",
        keyword="suggestion_is_written_with_its_canonical_beside_it",
        tags=("critical",),
    ),
    # M243 AS FIRST WRITTEN WAS WITHDRAWN, and the reason is kept here.
    # It deleted `discipline_canonical TEXT,` from the CREATE TABLE and was
    # NOT DETECTED - correctly. On a fresh database the migration loop adds
    # the column too, so the two creators are redundant and deleting either
    # one alone changes nothing observable (audit entry 39: first ask whether
    # the OUTPUT can distinguish the versions at all). It now targets the one
    # creator that CAN be observed: the migration, on an old-shape database.
    Mutation(
        id="M243", phase=21,
        description="drop the MIGRATION, so a database that predates the "
                    "column never gains it and every classification write fails",
        path=APP / "db.py",
        anchor='            "discipline_canonical",\n',
        replacement="",
        target="tests/test_discipline_canonical.py",
        keyword="existing_database_gains_the_column_through_the_migration",
        tags=("critical",),
    ),
)


#: The CRS export: who may export, and what the file is allowed to say.
CRS_EXPORT = (
    Mutation(
        id="M237", phase=22,
        description="EXPORT A RUN THE CALLER MAY NOT READ, handing a whole "
                    "submittal's findings to anybody who guesses a run id",
        path=APP / "main.py",
        anchor="    run = submittal_review_mod.get_review_run(\n"
               "        review_run_id, allowed_document_ids=allowed)\n"
               "    if run is None:\n"
               "        raise HTTPException(status_code=404, detail=errors.safe_error(\n"
               '            errors.NOT_FOUND, "no review run with that id"))',
        replacement="    run = submittal_review_mod.get_review_run(\n"
                    "        review_run_id,\n"
                    "        allowed_document_ids=frozenset(\n"
                    '            r["id"] for r in connect().execute('
                    '"SELECT id FROM documents")))\n'
                    "    if run is None:\n"
                    "        raise HTTPException(status_code=404, detail=errors.safe_error(\n"
                    '            errors.NOT_FOUND, "no review run with that id"))',
        target="tests/test_crs_endpoint.py",
        keyword="cannot_read_is_not_found or reads_exactly_the_same",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M238", phase=22,
        description="drop the GAP ROWS, so a run that found no breach exports "
                    "an empty sheet reading 'nothing to report'",
        path=APP / "main.py",
        anchor="        findings, _missing_references(submittal_id, allowed), submittal_name)",
        replacement="        findings, [], submittal_name)",
        target="tests/test_crs_endpoint.py",
        keyword="no_includable_findings_still_exports_its_gap_rows",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M239", phase=22,
        description="print the NORMALISED key, so a contractor reads "
                    "'32SAMSS004' and has to guess what was meant",
        # RE-ANCHORED IN THE SAME CHANGE THAT MOVED ITS LINE (audit entry 43
        # was a mutation going silently inert under exactly such a move). The
        # rule now lives in applicability.missing_references.
        path=APP / "applicability.py",
        anchor="            missing.append(name.strip())",
        replacement="            missing.append(key)",
        target="tests/test_crs_endpoint.py",
        keyword="keeps_the_spelling_the_submittal_used",
    ),
    Mutation(
        id="M240", phase=22,
        description="INVENT A TRANSMITTAL NUMBER, so the CRS lies about its "
                    "own provenance to whoever receives it",
        path=APP / "main.py",
        anchor='        "company_transmittal": "",',
        replacement='        "company_transmittal": "KJO-TRX-0001",',
        target="tests/test_crs_endpoint.py",
        keyword="transmittal_numbers_are_blank_rather_than_invented",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M241", phase=22,
        description="write the standard's ID instead of its filename, asking "
                    "an engineer to recognise a hash in a client document",
        path=APP / "main.py",
        anchor='        finding["standard_name"] = names.get(finding.get("standard_document_id"))',
        replacement='        finding["standard_name"] = None',
        target="tests/test_crs_endpoint.py",
        keyword="becomes_a_row_with_its_citation_and_both_texts",
    ),
)


#: The WAL-safe backup: every way it used to succeed on the wrong contents.
#: THE GUARDS COME IN REDUNDANT PAIRS - an existence check AND a read-only
#: open; microseconds in the name AND an exclusive create. Deleting one half
#: of a pair is not observable (audit entry 39), so each mutation below
#: removes a whole guard, or removes one half to prove the other half turns
#: a silent failure into a loud one.
BACKUP = (
    Mutation(
        id="M244", phase=23,
        description="BACK UP A MISTYPED PATH: drop the existence check AND "
                    "the read-only open, so sqlite creates an empty database "
                    "at the typo and verify calls it ok",
        path=REPO / "scripts" / "backup_db.py",
        anchor="    if not source.is_file():\n"
               '        raise FileNotFoundError(f"no database at {live_path}")\n'
               '    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)',
        replacement="    src = sqlite3.connect(live_path)",
        target="tests/test_backup_db.py",
        keyword="missing_source_is_refused_rather_than_created",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M245", phase=23,
        description="back up a database with NO TABLES and report it verified",
        path=REPO / "scripts" / "backup_db.py",
        anchor="    if tables == 0:",
        replacement="    if False:",
        target="tests/test_backup_db.py",
        keyword="source_with_no_tables_is_refused",
        tags=("honesty",),
    ),
    # M246 and M247 were re-anchored by B30. M246 used to drop the microseconds
    # and expect the exclusive create to make the tie a LOUD failure - the very
    # crash B30 removes, so it would now read NOT DETECTED against correct
    # code. Both now mutate `_reserve_name`, and the clock tie is forced by a
    # frozen clock instead of hoped for.
    Mutation(
        id="M246", phase=23,
        description="PUT B30 BACK: a clock tie raises FileExistsError instead "
                    "of taking the next free name",
        path=REPO / "scripts" / "backup_db.py",
        anchor="        except FileExistsError:\n            continue",
        replacement="        except FileExistsError:\n            raise",
        target="tests/test_backup_db.py",
        keyword="clock_tie",
    ),
    Mutation(
        id="M247", phase=23,
        description="SILENTLY OVERWRITE THE EARLIER BACKUP: open the name for "
                    "writing instead of creating it exclusively",
        path=REPO / "scripts" / "backup_db.py",
        anchor='            with open(candidate, "xb"):',
        replacement='            with open(candidate, "wb"):',
        target="tests/test_backup_db.py",
        keyword="clock_tie or never_written_over",
        tags=("critical",),
    ),
    Mutation(
        id="M303", phase=23,
        description="B30: the retry tries the SAME name every time, so a tie "
                    "still fails after a hundred attempts",
        path=REPO / "scripts" / "backup_db.py",
        anchor='        suffix = f"-{attempt}" if attempt else ""',
        replacement='        suffix = ""',
        target="tests/test_backup_db.py",
        keyword="clock_tie",
    ),
    Mutation(
        id="M304", phase=23,
        description="B30: with every name taken, hand back a taken one and let "
                    "sqlite write over it instead of failing loudly",
        path=REPO / "scripts" / "backup_db.py",
        anchor="    raise FileExistsError(\n"
               '        f"no free backup name for stamp {stamp} in {backup_dir} "',
        replacement="    return candidate\n    raise FileExistsError(\n"
                    '        f"no free backup name for stamp {stamp} in {backup_dir} "',
        target="tests/test_backup_db.py",
        keyword="running_out_of_names",
        tags=("critical",),
    ),
)


#: A gap row must be TRUE, not just present. The dashboard and the CRS both
#: reported every cited standard missing, because their check compared an
#: identifier against a dict keyed by document id.
MISSING_REFERENCES = (
    Mutation(
        id="M248", phase=24,
        description="PUT THE DEFECT BACK: call every cited standard missing, "
                    "so the CRS tells a contractor held standards are absent",
        path=APP / "applicability.py",
        anchor="        if not _match_referenced(library, [name]):",
        replacement="        if True:",
        target="tests/test_crs_endpoint.py",
        keyword="library_holds_gets_no_gap_row",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M249", phase=24,
        description="the same defect, seen from the Dashboard tile that read "
                    "'21 of 21 cited standards are not in the library'",
        path=APP / "applicability.py",
        anchor="        if not _match_referenced(library, [name]):",
        replacement="        if True:",
        target="tests/test_review_dashboard.py",
        keyword="library_holds_is_not_counted_missing",
        tags=("honesty",),
    ),
    Mutation(
        id="M250", phase=24,
        description="read identifiers back out of ONE combined match, keyed "
                    "by document - so two spellings of a held standard collide "
                    "and the loser is reported missing",
        path=APP / "applicability.py",
        anchor="        if not _match_referenced(library, [name]):\n"
               "            missing.append(name.strip())",
        replacement="        held = {normalise_identifier(v[\"identifier\"])\n"
                    "                for v in _match_referenced(library, referenced).values()}\n"
                    "        if key not in held:\n"
                    "            missing.append(name.strip())",
        target="tests/test_applicability.py",
        keyword="two_spellings_of_one_held_standard",
    ),
)


#: Document Q&A answered "there are 12 distinct standards" from three retrieved
#: passages, of a library holding 272. Both halves of the fix, both sides.
CORPUS_QUESTIONS = (
    # ----------------------------------------- part 1: the count is bounded
    Mutation(
        id="M251", phase=25,
        description="PUT THE DEFECT BACK: drop the guard on generated text, so "
                    "'there are 12 distinct standards' reaches the reader as a "
                    "fact about the library",
        path=APP / "answer.py",
        anchor="    text, counts_bounded = corpus_mod.bound_counts(text, len(passages))",
        replacement="    counts_bounded = 0",
        target="tests/test_corpus_questions.py",
        keyword="counting_question_names_its_boundary",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M252", phase=25,
        description="the guard finds the count and bounds nothing - the rule "
                    "itself, not only its wiring",
        path=APP / "corpus.py",
        anchor="        if match is None or _BOUNDED.search(sentence):",
        replacement="        if match is None or True:",
        target="tests/test_corpus_questions.py",
        keyword="every_unbounded_count_of_documents_is_bounded",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M253", phase=25,
        description="stop honouring 'retrieved', rewriting a model that had "
                    "ALREADY named its boundary",
        path=APP / "corpus.py",
        anchor="        if match is None or _BOUNDED.search(sentence):",
        replacement="        if match is None:",
        target="tests/test_corpus_questions.py",
        keyword="already_names_its_boundary or bounded_by_their_citation",
    ),
    # --------------------------------- part 2: the library answers itself
    Mutation(
        id="M254", phase=25,
        description="SEND A LIBRARY QUESTION TO RETRIEVAL AGAIN - the routing "
                    "that let three passages answer for 272 standards",
        path=APP / "answer.py",
        anchor="    corpus_q = corpus_mod.classify(question) if document_id is None else None",
        replacement="    corpus_q = None",
        target="tests/test_corpus_questions.py",
        keyword="answered_without_searching",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M255", phase=25,
        description="COUNT DOCUMENTS OUTSIDE THE GRANT SET, so a corpus "
                    "answer reveals how many standards you may not read",
        path=APP / "corpus.py",
        anchor="            WHERE d.id IN ({marks})",
        replacement="            WHERE 1 = 1 OR d.id IN ({marks})",
        target="tests/test_corpus_questions.py",
        keyword="outside_the_grant_set",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M256", phase=25,
        description="call a standard still being processed 'loaded'",
        path=APP / "corpus.py",
        anchor='        slot["loaded" if r["status"] in _LOADED else "not_loaded"] += r["n"]',
        replacement='        slot["loaded"] += r["n"]',
        target="tests/test_corpus_questions.py",
        keyword="still_processing_is_not_counted_as_loaded",
        tags=("honesty",),
    ),
    Mutation(
        id="M257", phase=25,
        description="answer a question about BOTH with the library alone, so "
                    "'how many standards cover hydrotesting' never searches",
        path=APP / "corpus.py",
        anchor="    return CorpusQuestion(kind=kind, role=role, qualified=bool(content),",
        replacement="    return CorpusQuestion(kind=kind, role=role, qualified=False,",
        target="tests/test_corpus_questions.py",
        keyword="gets_both_in_separate_fields or marked_for_both",
    ),
    Mutation(
        id="M258", phase=25,
        description="consult the library for a question scoped to ONE "
                    "document, where 'how many standards' means what it cites",
        path=APP / "answer.py",
        anchor="    corpus_q = corpus_mod.classify(question) if document_id is None else None",
        replacement="    corpus_q = corpus_mod.classify(question)",
        target="tests/test_corpus_questions.py",
        keyword="scoped_to_one_document",
    ),
    Mutation(
        id="M259", phase=25,
        description="drop `corpus` from the persisted payload - which the "
                    "screen renders LIVE as well as on replay",
        path=APP / "chat.py",
        anchor='    "corpus", "counts_bounded",',
        replacement='    "counts_bounded",',
        target="tests/test_corpus_questions.py",
        keyword="keeps_it_on_replay",
    ),
    # ------------------------------------------------ on screen, vitest
    Mutation(
        id="M260", phase=25, runner="vitest",
        description="HIDE THE LIBRARY'S HALF of a two-part answer, leaving "
                    "the documents' answer to stand for both",
        path=FRONTEND_SRC / "components" / "chat" / "AnswerCardView.tsx",
        anchor='  const twoPart = view.corpus != null && view.answer_type !== "metadata";',
        replacement="  const twoPart = false;",
        target="src/components/chat/corpusAnswer.test.tsx",
        keyword="two labelled parts",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M261", phase=25, runner="vitest",
        description="wrap a metadata answer in a second library block, "
                    "saying the same sentence twice",
        path=FRONTEND_SRC / "components" / "chat" / "AnswerCardView.tsx",
        anchor='  const twoPart = view.corpus != null && view.answer_type !== "metadata";',
        replacement="  const twoPart = view.corpus != null;",
        target="src/components/chat/corpusAnswer.test.tsx",
        keyword="once, not twice",
        tags=("ui",),
    ),
    Mutation(
        id="M262", phase=25, runner="vitest",
        description="lose `corpus` between the persisted message and the view",
        path=FRONTEND_SRC / "components" / "chat" / "AnswerCardContent.tsx",
        anchor="    corpus: p.corpus ?? null,",
        replacement="    corpus: null,",
        target="src/components/chat/corpusAnswer.test.tsx",
        keyword="carries both fields",
        tags=("ui",),
    ),
    Mutation(
        id="M263", phase=25,
        description="let Markdown around the number hide the count again - "
                    "the REAL model's '**five** distinct standards' slipped "
                    "past the first version of the guard",
        path=APP / "corpus.py",
        anchor='COUNT_CLAIM = re.compile(r"(?<![A-Za-z0-9])" + _NUMBER + _MD + r"\\s+" + _MD',
        replacement='COUNT_CLAIM = re.compile(r"(?<![A-Za-z0-9])" + _NUMBER + r"\\s+" + _MD',
        target="tests/test_corpus_questions.py",
        keyword="real_models_own_words or markdown_around_the_count",
        tags=("honesty",),
    ),
)


PERSISTED_TRUNCATION = (
    Mutation(
        id="M264", phase=26,
        description="drop the truncated state before persisting an answer, so "
                    "a cut-off reply reopens looking complete",
        path=APP / "chat.py",
        anchor='    "corpus", "counts_bounded", "truncated",',
        replacement='    "corpus", "counts_bounded",',
        target="tests/test_chat.py",
        keyword="reopened_conversation_preserves_whether_the_answer_was_truncated",
        tags=("honesty", "critical"),
    ),
)


DEMO_POLISH = (
    Mutation(
        id="M265", phase=27, runner="vitest",
        description="restore the duplicate nominal-estimate completeness line "
                    "when the recommendation already states it",
        path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
        anchor="      {completeness && !reasonStatesDenominator && (",
        replacement="      {completeness && (",
        target="src/views/ReviewRunsView.test.tsx",
        keyword="exactly once",
        tags=("honesty", "ui"),
    ),
)


STANDARDS_MODAL = (
    Mutation(
        id="M266", phase=28,
        description="drop 'may not exceed' from the requirement gate, so a "
                    "numeric prohibition disappears before parsing",
        path=APP / "standards.py",
        anchor=(
            '    r"|is\\s+to\\s+be|are\\s+to\\s+be|may\\s+not\\s+exceed\\s+[-+]?\\d)",\n'
        ),
        replacement='    r"|is\\s+to\\s+be|are\\s+to\\s+be)",\n',
        target="tests/test_standards_3b.py",
        keyword="may_not_exceed_is_a_numeric_prohibition_with_no_space_before_unit",
        tags=("honesty", "critical"),
    ),
)


#: B24 (the condition safety gate) and B23 (evidence quote validation), plus a
#: re-anchoring of B20's dimension guard, so all three safety gates that came out
#: of the Phase 0.5 slice are proven by this harness rather than by an ad-hoc
#: script in one session's scratchpad.
CONDITION_AND_QUOTES = (
    Mutation(
        id="M267", phase=29,
        description="remove the B24 condition gate, so a conditional "
                    "requirement reaches a verdict with its condition "
                    "unevaluated - the Phase 0.5 defect exactly",
        path=APP / "comparison.py",
        anchor="    condition = conditions.evaluate(requirement, submittal_facts)",
        replacement="    condition = None  # MUTANT: B24 gate removed",
        target="tests/test_condition_gate.py",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M268", phase=29,
        description="never read the facts that DO state a material, so no "
                    "condition is ever SATISFIED - a gate that always refuses "
                    "is as useless as one that never does",
        path=APP / "conditions.py",
        anchor="    for fact in stated:",
        replacement="    for fact in []:  # MUTANT: stated facts never examined",
        target="tests/test_condition_gate.py",
        tags=("honesty",),
    ),
    Mutation(
        id="M269", phase=29,
        description="treat 'N/A' as a stated value, collapsing UNKNOWN into "
                    "NOT_APPLICABLE - excusing a requirement on absent evidence",
        path=APP / "conditions.py",
        anchor='    stated = [f for f in candidates if not _is_empty(f.get("field_value"))]',
        replacement="    stated = list(candidates)  # MUTANT: N/A treated as a value",
        target="tests/test_condition_gate.py",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M270", phase=29,
        description="remove the requirement_type scoping, so the gate fires on "
                    "the 4,246 table_value rows whose condition column holds a "
                    "table ROW LABEL like 'Arsenic' or '100'",
        path=APP / "conditions.py",
        anchor='    if (requirement or {}).get("requirement_type") != GATED_TYPE:\n'
               "        return None",
        replacement="    if False:  # MUTANT: type scoping removed\n"
                    "        return None",
        target="tests/test_condition_gate.py",
        tags=("critical",),
    ),
    Mutation(
        id="M271", phase=29,
        description="widen B23's closed normalisation list to fold case and "
                    "strip decimal points, so 1.6 would match 16",
        path=APP / "quotes.py",
        anchor='    return " ".join(s.split())',
        replacement='    return " ".join(s.lower().replace(".", "").split())  # MUTANT',
        target="tests/test_quote_validation.py",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M272", phase=29,
        description="make the quote validator accept everything, so an invented "
                    "quote passes as verbatim - the Phase 0.5 run's rewritten "
                    "inch mark with nothing checking it",
        path=APP / "quotes.py",
        anchor="    return (needle in haystack, OK if needle in haystack else NOT_FOUND)",
        replacement="    return (True, OK)  # MUTANT: every quote accepted",
        target="tests/test_quote_validation.py",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M273", phase=29,
        description="remove B20's dimension guard, so a length is compared "
                    "against a temperature and yields NON_COMPLIANT",
        path=APP / "claims.py",
        anchor="    dim_a, dim_b = a.dimension, b.dimension\n"
               "    if dim_a is not None and dim_b is not None and dim_a != dim_b:\n"
               "        return None",
        replacement="    # MUTANT: B20 dimension guard removed",
        target="tests/test_dimension_guard.py",
        tags=("honesty", "critical"),
    ),
)


#: Phase 31: B34 - a standard number is a NAME, not a measurement, under a
#: CLOSED grammar; and a removed sentence is REPORTED, never silently deleted.
#: M288-M293 loosen or remove the grammar in six different ways - each must be
#: caught, and M289 and M293 are the loosenings that would let a fabricated
#: value disguised as a standard number through ("per SAES-H-150, apply 150").
_SYNTH = APP / "synthesis.py"
_B34_TEST = "tests/test_b34_standard_identifiers.py"
_B34_UI_TEST = "src/views/AnalysisModeScreen.removed.test.tsx"
B34_STANDARD_IDS = (
    Mutation(
        id="M288", phase=31,
        description="remove the grammar from the stripper - the original bug: SAES-H-004 read as the quantity 4",
        path=_SYNTH,
        anchor='    return _STANDARD_IDENTIFIER.sub(" ", _REFERENCE_NUMERAL.sub(" ", sentence))',
        replacement='    return _REFERENCE_NUMERAL.sub(" ", sentence)',
        target=_B34_TEST, keyword="naming_a_real_standard_survives",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M289", phase=31,
        description="LOOSEN BY VALUE: exempt the identifier's digits wherever they appear - lets 'per SAES-H-150, apply 150' through",
        path=_SYNTH,
        anchor='    return _STANDARD_IDENTIFIER.sub(" ", _REFERENCE_NUMERAL.sub(" ", sentence))',
        replacement=(
            '    stripped = _STANDARD_IDENTIFIER.sub(" ", _REFERENCE_NUMERAL.sub(" ", sentence))\n'
            '    for ident in _STANDARD_IDENTIFIER.findall(sentence):\n'
            '        for digits in re.findall(r"\\d+", ident):\n'
            '            stripped = re.sub(r"(?<![\\d.])" + digits + r"(?![\\d.])", " ", stripped)\n'
            '    return stripped'),
        target=_B34_TEST, keyword="disguised",
        tags=("honesty", "critical", "answer_path"),
    ),
    Mutation(
        id="M290", phase=31,
        description="LOOSEN THE PREFIX: any letters-hyphen-digits shape counts as a standard number",
        path=_SYNTH,
        anchor='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?"',
        replacement='    r"[A-Za-z]+-[A-Za-z]?-?\\d{1,5}[A-Z]?"',
        target=_B34_TEST, keyword="lookalike",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M291", phase=31,
        description="LOOSEN THE DIGITS: SAES takes any number of digits, so SAES-H-15000 is exempt",
        path=_SYNTH,
        anchor='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?"',
        replacement='    r"SAES-[A-Z]-\\d+[A-Z]?"',
        target=_B34_TEST, keyword="15000",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M292", phase=31,
        description="LOOSEN THE CASE: ignore case, so 'saes-h-150' is exempt",
        path=_SYNTH,
        anchor='    r")(?![\\w-])"\n)',
        replacement='    r")(?![\\w-])",\n    re.IGNORECASE,\n)',
        target=_B34_TEST, keyword="lookalike",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M293", phase=31,
        description="LOOSEN THE END: let an identifier swallow the text after it - 'SAES-H-150, apply 150' taken whole",
        path=_SYNTH,
        anchor='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?"',
        replacement='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?(?:[^\\[]*?\\d+)?"',
        target=_B34_TEST, keyword="disguised",
        tags=("honesty", "critical", "answer_path"),
    ),
    Mutation(
        id="M294", phase=31,
        description="disable the numeric guard altogether (the order: do not disable it)",
        path=_SYNTH,
        anchor="        if unsupported:\n            # Named as the reader sees it",
        replacement="        if False:\n            # Named as the reader sees it",
        target=_B34_TEST, keyword="disguised",
        tags=("honesty", "critical", "answer_path"),
    ),
    Mutation(
        id="M295", phase=31,
        description="regress the reason wording - the reader no longer sees 'value 300 not in cited passage'",
        path=_SYNTH,
        anchor='            dropped.append((sentence, f"value {value} not in cited passage"))',
        replacement='            dropped.append((sentence, f"carries a number no cited span contains: {value}"))',
        target=_B34_TEST, keyword="reported_and_excluded",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M296", phase=31,
        description="the summary API drops the removed list - silent deletion again",
        path=_SYNTH,
        anchor='            {"sentence": s, "reason": r} for s, r in summary.dropped_sentences\n        ],',
        replacement='            {"sentence": s, "reason": r} for s, r in ()\n        ],',
        target=_B34_TEST, keyword="reported_and_excluded",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M297", phase=31,
        description="the recommendation discards what it removed - the one silent path B34 closed",
        path=_SYNTH,
        anchor="        removed_out.extend(dropped)",
        replacement="        pass",
        target=_B34_TEST, keyword="recommendation_reports or recommendation_keeps",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M298", phase=31, runner="vitest",
        description="hide the removed sentences from the reader",
        path=REPO / "frontend" / "src" / "components" / "analysis" / "RemovedSentences.tsx",
        anchor='      {shown.length > 0 && <ul className="mt-2 space-y-1.5">{shown.map((s, i) => (',
        replacement='      {false && <ul className="mt-2 space-y-1.5">{shown.map((s, i) => (',
        target=_B34_UI_TEST, keyword="WITHOUT any click",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M299", phase=31, runner="vitest",
        description="stop greying removed sentences, so they read like the answer",
        path=REPO / "frontend" / "src" / "components" / "analysis" / "RemovedSentences.tsx",
        anchor='          className="text-xs text-slateish-500 opacity-70"',
        replacement='          className="text-xs text-slateish-300"',
        target=_B34_UI_TEST, keyword="WITHOUT any click",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M300", phase=31, runner="vitest",
        description="do not render what was removed from a recommendation",
        path=REPO / "frontend" / "src" / "views" / "analysis" / "AnalysisResultSections.tsx",
        anchor='      <RemovedSentences removed={d.removed} what="recommendation" />\n',
        replacement="",
        target=_B34_UI_TEST, keyword="even when none survived",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M301", phase=31, runner="vitest",
        description="let an all-removed recommendation read as 'nothing was generated'",
        path=REPO / "frontend" / "src" / "views" / "analysis" / "analysisStore.ts",
        anchor="&& refusal === null && removed.length === 0) return null;",
        replacement="&& refusal === null) return null;",
        target=_B34_UI_TEST, keyword="even when none survived",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M302", phase=31, runner="vitest",
        description="put the removed value back into the answer's reach: render removed sentences as plain answer text",
        path=REPO / "frontend" / "src" / "components" / "analysis" / "RemovedSentences.tsx",
        anchor='  if (removed.length === 0) return null;',
        replacement='  if (removed.length >= 0) return <p>{removed.map((s) => s.sentence).join(" ")}</p>;',
        target=_B34_UI_TEST, keyword="ONLY in the removed region",
        tags=("honesty", "ui"),
    ),
)


#: B14: the glossary-phrase pass had no test that could fail - the existing one
#: passed with the pass deleted, because two chunks can crowd nothing out.
B14_GLOSSARY_PHRASE = (
    Mutation(
        id="M305", phase=32,
        description="delete the exact-phrase pass, so a glossary definition is "
                    "crowded out of the candidate list by scattered-word matches",
        path=APP / "keyword.py",
        anchor="    phrase = build_phrase_query(question)",
        replacement='    phrase = ""',
        target="tests/test_keyword.py",
        keyword="survives_a_crowd",
    ),
)


#: B12: a spelling correction named a word found only in a document the caller
#: may not read, because fts5vocab is one term list for the whole index.
B12_SCOPED_CORRECTIONS = (
    Mutation(
        id="M306", phase=33,
        description="offer the closest corpus-wide word without checking the "
                    "caller's scope - the presence oracle B12 closed",
        path=APP / "keyword.py",
        anchor="        if term_occurrences(\n"
               "            candidate, document_id, allowed_document_ids=allowed_document_ids\n"
               "        ) > 0:",
        replacement="        if True:",
        target="tests/test_keyword.py",
        keyword="unreadable_document or closer_word",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M307", phase=33,
        description="scope REFUSES instead of filtering: an out-of-scope best "
                    "match hides the in-scope word the caller may be offered",
        path=APP / "keyword.py",
        anchor="        ) > 0:\n            return candidate\n    return None",
        replacement="        ) > 0:\n            return candidate\n        break\n    return None",
        target="tests/test_keyword.py",
        keyword="closer_word",
        tags=("permission",),
    ),
)


#: B7: four analysis-route tests had passed through the single-passage
#: pass-through since 5a7a2b3's relevance floor, so they never reached
#: generation. With two on-topic passages they do; one mutation per test
#: proves each still guards the behaviour its name claims.
B7_ANALYSIS_GENERATION = (
    Mutation(
        id="M308", phase=34,
        description="the route stops translating an unreachable model into a "
                    "503, so it surfaces as a crash",
        path=APP / "main.py",
        anchor="    except analysis_mod.ModelUnavailable as exc:",
        replacement="    except ZeroDivisionError as exc:",
        target="tests/test_analysis_routes.py",
        keyword="unreachable_model",
        tags=("honesty",),
    ),
    Mutation(
        id="M309", phase=34,
        description="a sentence whose number is in no cited span is kept, so "
                    "an unsupported number reaches the reader",
        path=APP / "synthesis.py",
        anchor="        if unsupported:\n            # Named as the reader sees it",
        replacement="        if False:\n            # Named as the reader sees it",
        target="tests/test_analysis_routes.py",
        keyword="number_is_in_no_cited_span",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M310", phase=34,
        description="an uncited sentence is kept in the prose",
        path=APP / "synthesis.py",
        anchor='        if not cited:\n            dropped.append((sentence, "cites no supplied source"))',
        replacement='        if False:\n            dropped.append((sentence, "cites no supplied source"))',
        target="tests/test_analysis_routes.py",
        keyword="uncited_sentence",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M311", phase=34,
        description="the recommendation states a confidence with no checks "
                    "behind it",
        path=APP / "synthesis.py",
        anchor='        "checks": [{"label": c.label, "fired": c.fired} for c in recommendation.checks],',
        replacement='        "checks": [],',
        target="tests/test_analysis_routes.py",
        keyword="confidence_is_never_high",
        tags=("honesty",),
    ),
)


#: B18: completeness dropped an UNMEASURED extraction factor and reported the
#: other half alone - 1.0 and "sufficient" with the datasheet never measured.
_B18_GUARD = ("    if extraction is None:\n"
              "        overall = 0.0 if reference_coverage == 0 else None")
B18_UNMEASURED_FACTOR = (
    Mutation(
        id="M312", phase=35,
        description="comparison: drop the unmeasured extraction and score the "
                    "run on references alone - 1.0 and sufficient again",
        path=APP / "comparison.py",
        anchor=_B18_GUARD,
        replacement="    if False:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="unmeasured_extraction",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M313", phase=35,
        description="applicability: the same, in the other home",
        path=APP / "applicability.py",
        anchor=_B18_GUARD,
        replacement="    if False:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="extraction_was_never_measured",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M314", phase=35,
        description="comparison: hide a measured 0 behind None because the "
                    "other factor is unknown",
        path=APP / "comparison.py",
        anchor=_B18_GUARD,
        replacement="    if extraction is None:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="measured_zero_stays",
        tags=("honesty",),
    ),
    Mutation(
        id="M315", phase=35,
        description="applicability: hide M-03's determinate 0.0 behind None",
        path=APP / "applicability.py",
        anchor=_B18_GUARD,
        replacement="    if extraction is None:\n        overall = None",
        target="tests/test_comparison.py",
        keyword="keeps_m03",
        tags=("honesty",),
    ),
)


#: B19: a review never read the datasheet (extract_facts had no caller).
_B19_TEST = "tests/test_b19_review_reads_the_datasheet.py"
B19_FACT_EXTRACTION = (
    Mutation(
        id="M316", phase=36,
        description="drop the 'has no facts' guard: every review re-reads the "
                    "sheet and, with replace=False, duplicates it",
        path=APP / "submittal_review.py",
        anchor="    if has_facts is not None:\n        return",
        replacement="    if False:\n        return",
        target=_B19_TEST,
        keyword="second_review or confirmed_fact",
        tags=("critical",),
    ),
    Mutation(
        id="M317", phase=36,
        description="PUT B19 BACK: the review never reads the datasheet",
        path=APP / "submittal_review.py",
        anchor="    _extract_facts_if_none(run_id, submittal_document_id, "
               "allowed_document_ids)\n    return run_id",
        replacement="    return run_id",
        target=_B19_TEST,
        keyword="reads_the_datasheet",
        tags=("critical",),
    ),
    Mutation(
        id="M318", phase=36,
        description="commit each fact on its own again, so a failure mid-sheet "
                    "leaves a partial set the guard mistakes for a finished one",
        path=APP / "datasheets.py",
        anchor="                        commit=False,\n",
        replacement="",
        target=_B19_TEST,
        keyword="failed_extraction or failed_re_extraction",
        tags=("critical",),
    ),
    Mutation(
        id="M319", phase=36,
        description="a run whose extraction failed is left saying 'running'",
        path=APP / "submittal_review.py",
        anchor="                \"UPDATE review_runs SET status = 'failed', refusal_reason = ?,\"\n"
               "                \" updated_at = ? WHERE id = ?\",\n"
               "                (json.dumps({\"error\": f\"fact extraction failed: {exc}\"}),",
        replacement="                \"UPDATE review_runs SET status = 'running', refusal_reason = ?,\"\n"
                    "                \" updated_at = ? WHERE id = ?\",\n"
                    "                (json.dumps({\"error\": f\"fact extraction failed: {exc}\"}),",
        target=_B19_TEST,
        keyword="failed_extraction",
    ),
)


#: B38: record, then refuse by default, on all four paths that delete
#: requirement rows review findings cite. A path's mutation swaps its guard
#: call for a no-op that accepts the same arguments.
_B38_TEST = "tests/test_b38_orphan_guard.py"
_B38_NOOP = "(lambda *a, **k: 0)("
B38_ORPHAN_GUARD = (
    Mutation(
        id="M326", phase=38,
        description="the guard records but never refuses - orphaning by default again",
        path=APP / "orphan_guard.py",
        anchor="    if not acknowledge:\n        raise OrphaningRefused",
        replacement="    if False:\n        raise OrphaningRefused",
        target=_B38_TEST, keyword="refused or 409",
        tags=("critical",),
    ),
    Mutation(
        id="M327", phase=38,
        description="path 1: re-extraction deletes cited rows unguarded",
        path=APP / "standards.py",
        anchor='        orphan_guard.check(\n            "re_extraction",',
        replacement=f'        {_B38_NOOP}\n            "re_extraction",',
        target=_B38_TEST, keyword="re_extraction",
        tags=("critical",),
    ),
    Mutation(
        id="M328", phase=38,
        description="path 2: rejecting a cited requirement is unguarded",
        path=APP / "standards.py",
        anchor='        orphan_guard.check(\n            "reject",',
        replacement=f'        {_B38_NOOP}\n            "reject",',
        target=_B38_TEST, keyword="rejecting",
    ),
    Mutation(
        id="M329", phase=38,
        description="path 3: a re-chunk cascades cited requirements away unguarded",
        path=APP / "chunker.py",
        anchor='    orphan_guard.check(\n        "re_chunk",',
        replacement=f'    {_B38_NOOP}\n        "re_chunk",',
        target=_B38_TEST, keyword="re_chunk",
        tags=("critical",),
    ),
    Mutation(
        id="M330", phase=38,
        description="path 4: deleting a cited standard cascades unguarded",
        path=APP / "main.py",
        anchor='    orphan_guard.check(\n        "document_delete",',
        replacement=f'    {_B38_NOOP}\n        "document_delete",',
        target=_B38_TEST, keyword="deleting_a_cited_standard",
        tags=("critical",),
    ),
    Mutation(
        id="M331", phase=38,
        description="refuse or proceed WITHOUT a record - the only trace of "
                    "the destroyed evidence is gone",
        path=APP / "orphan_guard.py",
        anchor="    _record(action, document_id, orphaned, actor,",
        replacement="    (lambda *a, **k: None)(action, document_id, orphaned, actor,",
        target=_B38_TEST, keyword="recorded or 409",
        tags=("honesty",),
    ),
)


#: B9/B22: NOT_IN_DOCUMENT_SCOPE, rule R1 - an unmatched `statement` is not
#: the contractor's omission, and must never approve a submittal either.
_REVIEW_UI = REPO / "frontend" / "src" / "components" / "review"
B9_NOT_IN_DOCUMENT_SCOPE = (
    Mutation(
        id="M320", phase=37,
        description="PUT B9 BACK: an unmatched statement is the contractor's "
                    "MISSING_INFORMATION again",
        path=APP / "comparison.py",
        anchor="        if requirement.get(\"requirement_type\") == requirements_3b.STATEMENT:",
        replacement="        if False:",
        target="tests/test_comparison.py",
        keyword="not_in_document_scope_not_missing",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M321", phase=37,
        description="an out-of-scope-only run falls through to APPROVED",
        path=APP / "comparison.py",
        anchor="    if out_of_scope:\n        return {\n            # NOT AN APPROVAL.",
        replacement="    if False:\n        return {\n            # NOT AN APPROVAL.",
        target="tests/test_comparison.py",
        keyword="never_approve",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M322", phase=37,
        description="count out-of-scope as the contractor's missing fields",
        path=APP / "comparison.py",
        anchor="    missing = [s for s in statuses if s == MISSING_INFORMATION]\n"
               "    # B9: counted APART",
        replacement="    missing = [s for s in statuses if s in (MISSING_INFORMATION, "
                    "NOT_IN_DOCUMENT_SCOPE)]\n    # B9: counted APART",
        target="tests/test_comparison.py",
        keyword="never_counted_as_the_contractors_omission",
        tags=("honesty",),
    ),
    Mutation(
        id="M325", phase=37,
        description="a generic manual flag instead of saying WHY: the reader "
                    "cannot tell other documents are needed",
        path=APP / "comparison.py",
        anchor='            "reason": (f"Manual review: {len(out_of_scope)} requirement"',
        replacement='            "reason": ("Manual review required"',
        target="tests/test_comparison.py",
        keyword="never_approve",
        tags=("honesty",),
    ),
    Mutation(
        id="M323", phase=37, runner="vitest",
        description="fold out-of-scope rows into the 'no evidence' count",
        path=_REVIEW_UI / "FindingsTable.tsx",
        anchor="  const missing = filtered.filter((f) => f.compliance_status === MISSING);",
        replacement="  const missing = filtered.filter((f) => f.compliance_status === MISSING"
                    " || f.compliance_status === OUT_OF_SCOPE);",
        target="src/components/review/FindingsTable.test.tsx",
        keyword="OWN count",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M332", phase=37, runner="vitest",
        description="an out-of-scope row stops showing its page, so an engineer "
                    "cannot find and catch a misclassified one (owner's merge "
                    "condition 1a)",
        path=_REVIEW_UI / "FindingsTable.tsx",
        anchor="          {finding.standard_page ? ` · p${finding.standard_page}` : \"\"}",
        replacement="          {\"\"}",
        target="src/components/review/FindingsTable.test.tsx",
        keyword="clause, page and text",
        tags=("honesty", "ui"),
    ),
    Mutation(
        id="M324", phase=37, runner="vitest",
        description="word it as missing evidence on screen",
        path=_REVIEW_UI / "reviewFormat.ts",
        anchor='    "Requires another document - not answerable from this submittal type",',
        replacement='    "No evidence submitted",',
        target="src/components/review/reviewFormat.test.ts",
        keyword="approved wording",
        tags=("honesty", "ui"),
    ),
)


ALL: tuple[Mutation, ...] = (
    PHASE_1 + PHASE_2 + PHASE_2_XLSX + PHASE_2_UI + PHASE_3A + PHASE_3A_UI
    + PHASE_3B + PHASE_4 + PHASE_5A + PHASE_5B + ROLES_FIX + DISCIPLINE
    + EXTRACTION + DATASHEET + MATCHER + TABLE_AND_UNITS + REACHABLE
    + MODEL_TIER + GATE_FALLOUT + REPEATED_FORM
    + RANGES_AND_COMPOUNDS + MIGRATION_RACE + EQUIPMENT_TAG
    + REVIEW_GOVERNANCE + REVIEW_DASHBOARD + ADMIN_EXPLORER
    + DISCIPLINE_CANONICAL + CRS_EXPORT + BACKUP
    + MISSING_REFERENCES + CORPUS_QUESTIONS + PERSISTED_TRUNCATION
    + DEMO_POLISH + STANDARDS_MODAL + CONDITION_AND_QUOTES
    + B34_STANDARD_IDS + B14_GLOSSARY_PHRASE + B12_SCOPED_CORRECTIONS
    + B7_ANALYSIS_GENERATION + B18_UNMEASURED_FACTOR + B19_FACT_EXTRACTION
    + B38_ORPHAN_GUARD + B9_NOT_IN_DOCUMENT_SCOPE
)


FRONTEND = REPO / "frontend"
#: The vitest binary as npm installed it. Called directly rather than through
#: `npx`, which on this project's Windows checkout can reach for a network
#: install; the local binary is the one the suite already runs.
_VITEST = FRONTEND / "node_modules" / ".bin" / (
    "vitest.cmd" if os.name == "nt" else "vitest")


def _ascii(text: str) -> str:
    """Printable on any console. A report that cannot be printed is no report."""
    return text.encode("ascii", "replace").decode("ascii")


def _run_tests(mutation: Mutation) -> tuple[int, str]:
    if mutation.runner == "vitest":
        cmd = [str(_VITEST), "run", mutation.target]
        if mutation.keyword:
            cmd += ["-t", mutation.keyword]
        # encoding/errors are NOT optional here. vitest prints box-drawing and
        # tick characters; on a Windows console defaulting to cp1252 the
        # decode raises, the harness treats the exception as a non-zero exit,
        # and EVERY mutation reports DETECTED whether or not the test noticed
        # anything. A harness that cannot read its runner's output is a harness
        # that reports a perfect score by accident - the exact failure this
        # file exists to catch.
        proc = subprocess.run(cmd, cwd=FRONTEND, capture_output=True, text=True,
                              timeout=900, shell=False,
                              encoding="utf-8", errors="replace")
        out = f"{proc.stdout}\n{proc.stderr}"
        # The counts line ("Tests  1 failed | 3 passed (4)"), not the "Failed
        # Tests" banner that also contains the word.
        counts = re.compile(r"Tests\s+\d+\s+(?:failed|passed)")
        summary = next(
            (ln.strip() for ln in reversed(out.splitlines()) if counts.search(ln)),
            "(no counts line)")
        # Flattened to ASCII before it is ever printed. vitest's summary
        # carries box-drawing and tick characters, and a Windows console at
        # cp1252 raises on ENCODE as readily as it did on decode - killing the
        # harness mid-run, after the mutation was applied but before the
        # `finally` had printed anything useful.
        return proc.returncode, _ascii(summary)
    # STALE BYTECODE CAN HAND ONE MUTATION ANOTHER'S VERDICT. Python reuses a
    # cached .pyc when the source's size and whole-second mtime match the
    # cache. Two consecutive mutations that change a file by the same number
    # of characters inside one second therefore ran the FIRST one's code for
    # the second: found 2026-09-22, when M296 and M297 each shortened
    # synthesis.py by exactly 23 characters and M297 reported NOT DETECTED -
    # its tests had executed M296's mutant. So: never write bytecode during a
    # mutation run (`-B`), and delete any cached copy of the mutated module
    # first, so the run can only ever compile the source as it now stands.
    for stale in (mutation.path.parent / "__pycache__").glob(f"{mutation.path.stem}.*.pyc"):
        stale.unlink(missing_ok=True)
    cmd = [_python(), "-B", "-m", "pytest", mutation.target, "-q", "--no-header",
           "-p", "no:cacheprovider"]
    if mutation.keyword:
        cmd += ["-k", mutation.keyword]
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True,
                          timeout=900)
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode, (lines[-1] if lines else "(no output)")


#: How many tests a run actually executed, out of its summary line. `None` when
#: the line cannot be read at all, which is itself a harness failure.
#: Words that mean a test RAN. `deselected` and `skipped` deliberately absent:
#: a deselected test was never collected and a skipped one never executed, so
#: neither is evidence that the mutation was observed by anything.
_PYTEST_COUNTS = re.compile(r"(\d+)\s+(passed|failed|error|errors|xfailed|xpassed)")
#: The same idea for pytest's "no tests ran" shapes, which carry only words
#: that mean nothing executed. Matched so the verdict can say so precisely
#: rather than "could not read a count".
_PYTEST_NOTHING = re.compile(r"\b\d+\s+(?:deselected|skipped)\b|no tests ran")
_VITEST_COUNTS = re.compile(r"(\d+)\s+(failed|passed)")


def _tests_collected(runner: str, summary: str) -> int | None:
    """The number of tests the run executed, from its own summary.

    THE HARNESS MUST NOT TRUST THE EXIT CODE ALONE. pytest exits 5 when it
    collects NOTHING - a `-k` expression that matches no test - and 5 is
    non-zero, which this file used to read as "the tests failed", which is what
    DETECTED means. Two mutations passed that way having executed no test at
    all, printing "49 deselected" with no pass or fail count, and were
    indistinguishable from the hundred that proved something.

    So the verdict now needs evidence that tests RAN. This reads the count out
    of the runner's own summary line; a summary with no counts in it returns
    None and the run is a harness error, not a result.
    """
    text = summary or ""
    if runner == "vitest":
        if "Tests" not in text:
            return None
        found = _VITEST_COUNTS.findall(text)
        return sum(int(n) for n, _word in found) if found else 0
    found = _PYTEST_COUNTS.findall(text)
    if found:
        # "1 failed, 20 deselected" counts the 1 and not the 20, which is the
        # whole point: deselected tests did not run.
        return sum(int(n) for n, _word in found)
    # Nothing executed, said in pytest's own words.
    return 0 if _PYTEST_NOTHING.search(text) else None


def run(mutation: Mutation) -> tuple[str, str]:
    """Apply, test, restore. Returns `(verdict, summary)`."""
    path = mutation.path
    if not path.exists():
        return "ERROR", f"file not found: {path}"
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(mutation.anchor)
    if occurrences != 1:
        # NOT a pass. An anchor that stopped matching means the mutation never
        # ran, and a mutation that never ran cannot detect anything.
        return "ERROR", (f"anchor matched {occurrences} times, expected exactly 1 "
                         f"- the mutation was NOT applied")
    backup = path.with_suffix(path.suffix + ".mutbak")
    shutil.copyfile(path, backup)
    try:
        path.write_text(source.replace(mutation.anchor, mutation.replacement, 1),
                        encoding="utf-8")
        code, summary = _run_tests(mutation)
    finally:
        shutil.copyfile(backup, path)
        os.remove(backup)
    # A VERDICT NEEDS TESTS TO HAVE RUN. Checked before the exit code is read,
    # because a run that executed nothing has no verdict to give - whatever it
    # exited with.
    ran = _tests_collected(mutation.runner, summary)
    if ran is None:
        return "HARNESS_ERROR", f"could not read a test count from: {summary}"
    if ran == 0:
        return "HARNESS_ERROR", (
            f"the run executed NO tests ({summary}) - the target or keyword "
            f"selects nothing, so this mutation proves nothing")
    return ("DETECTED" if code != 0 else "NOT DETECTED"), summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list mutations and exit")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run these ids only")
    parser.add_argument("--phase", type=int, help="run one phase's mutations")
    args = parser.parse_args()

    selected = list(ALL)
    if args.phase is not None:
        selected = [m for m in selected if m.phase == args.phase]
    if args.only:
        wanted = {i.upper() for i in args.only}
        selected = [m for m in selected if m.id.upper() in wanted]
        missing = wanted - {m.id.upper() for m in selected}
        if missing:
            print(f"unknown mutation id(s): {', '.join(sorted(missing))}")
            return 2

    if args.list:
        for m in selected:
            print(f"{m.id:>4}  phase {m.phase}  [{','.join(m.tags) or '-'}]  {m.description}")
        return 0

    if not selected:
        print("no mutations selected")
        return 2

    print(f"python: {_python()}")
    print(f"running {len(selected)} mutation(s)\n")
    results = []
    for m in selected:
        print(f"  {m.id} ... ", end="", flush=True)
        verdict, summary = run(m)
        print(f"{verdict}  ({summary})")
        results.append((m, verdict, summary))

    print("\n" + "=" * 78)
    detected = [r for r in results if r[1] == "DETECTED"]
    harness = [r for r in results if r[1] in ("HARNESS_ERROR", "ERROR")]
    vacuous = [r for r in results if r[1] == "NOT DETECTED"]
    print(f"{len(detected)}/{len(results)} mutations detected"
          f"  |  {len(vacuous)} not detected  |  {len(harness)} harness error")
    if harness:
        # REPORTED SEPARATELY AND FIRST. A harness error is not a result in
        # either direction: the mutation did not run, or ran nothing, so it
        # says nothing about the tests. Counting it as detected is how two
        # mutations came to pass while executing no tests at all.
        print("\nHARNESS ERROR - these mutations produced no evidence:")
        for m, verdict, summary in harness:
            print(f"  {m.id} [{verdict}] {m.description}")
            print(f"       {summary}")
    if vacuous:
        print("\nNOT DETECTED - the tests do not observe these features:")
        for m, verdict, summary in vacuous:
            print(f"  {m.id} [{verdict}] {m.description}")
            print(f"       {summary}")
        print("\nA mutation that is not detected means the test is VACUOUS.")
        print("Record it per CLAUDE.md rule 7 and fix the test, not the harness.")
    return 1 if (harness or vacuous) else 0


if __name__ == "__main__":
    raise SystemExit(main())
