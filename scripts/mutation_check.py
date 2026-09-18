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
        anchor='    where, args = _scope_clause(allowed_document_ids, "submittal_document_id")\n'
               '    sql = "SELECT * FROM review_runs" + where',
        replacement='    where, args = "", []\n'
                    '    sql = "SELECT * FROM review_runs" + where',
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
        anchor="        if page_written == 0:\n            unparsed.append({",
        replacement="        if False:\n            unparsed.append({",
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

ALL: tuple[Mutation, ...] = (
    PHASE_1 + PHASE_2 + PHASE_2_XLSX + PHASE_2_UI + PHASE_3A + PHASE_3A_UI
    + PHASE_3B + PHASE_4 + PHASE_5A
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
    cmd = [_python(), "-m", "pytest", mutation.target, "-q", "--no-header",
           "-p", "no:cacheprovider"]
    if mutation.keyword:
        cmd += ["-k", mutation.keyword]
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True,
                          timeout=900)
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode, (lines[-1] if lines else "(no output)")


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
    failures = [r for r in results if r[1] != "DETECTED"]
    print(f"{len(results) - len(failures)}/{len(results)} mutations detected")
    if failures:
        print("\nNOT DETECTED - the tests do not observe these features:")
        for m, verdict, summary in failures:
            print(f"  {m.id} [{verdict}] {m.description}")
            print(f"       {summary}")
        print("\nA mutation that is not detected means the test is VACUOUS.")
        print("Record it per CLAUDE.md rule 7 and fix the test, not the harness.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
