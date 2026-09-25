"""Mutations of `backend/app/submittal_review.py`."""

from __future__ import annotations

from ._base import APP, _B19_TEST, _B40_TEST, _INGEST_FACTS_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_1 -----------------------------------------------------
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
        # A true WHERE, not an empty string: the line now appends
        # " AND superseded_at IS NULL" (#179), and an empty scope would make
        # the mutant a syntax error rather than the permission leak it models.
        replacement='    where, args = " WHERE 1 = 1", []\n'
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
    # ---- from REVIEW_GOVERNANCE -------------------------------------------
    #: A crashed run, and the engineer's final code (master plan section 15).
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
    # ---- from REVIEW_DASHBOARD --------------------------------------------
    #: The Dashboard's four cards (CLAUDE.md rule 10, master plan section 20).
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
    # ---- from B19_FACT_EXTRACTION -----------------------------------------
    #: B19: a review never read the datasheet (extract_facts had no caller).
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
    # ---- from B40_FACT_GUARD ----------------------------------------------
    #: B40 -> #179: `extract_facts(replace=True)` used to DELETE unconfirmed facts
    #: that findings cite by `fact_id` (B40 guarded it: count, record, refuse).
    #: Since #179 it SUPERSEDES them instead - the rows stay, marked
    #: `superseded_at`, and every reader of current facts leaves them out.
    #: M334-M336 keep their ids, re-anchored on the supersession; M440-M444 cover
    #: the readers and the record. Phase 56.
    Mutation(
        id="M441", phase=56,
        description="list_submittal_facts returns superseded rows again - the "
                    "same defect in its other home (#179)",
        path=APP / "submittal_review.py",
        anchor='    sql = "SELECT * FROM submittal_facts" + where + " AND superseded_at IS NULL"',
        replacement='    sql = "SELECT * FROM submittal_facts" + where',
        target=_B40_TEST, keyword="every_current_fact_reader",
        tags=("critical",),
    ),
    Mutation(
        id="M442", phase=56,
        description="the has-no-facts guard counts superseded rows, so a sheet "
                    "with no current fact is never read again (#179)",
        path=APP / "submittal_review.py",
        anchor='        "SELECT 1 FROM submittal_facts WHERE submittal_document_id = ?"\n'
               '        " AND superseded_at IS NULL LIMIT 1",',
        replacement='        "SELECT 1 FROM submittal_facts WHERE submittal_document_id = ?"\n'
                    '        " LIMIT 1",',
        target=_B40_TEST, keyword="has_no_facts_guard_reads_current",
        tags=("critical",),
    ),
    # ---- from INGEST_FACT_WIRING ------------------------------------------
    #: B19's other half: fact extraction wired into ingestion completion (upload
    #: + watched folder), never a manually-started review run.
    Mutation(
        id="M358", phase=45,
        description="drop the shared 'has no facts' guard as seen from the "
                    "ingestion path, so re-ingesting a submittal with facts "
                    "already extracted duplicates them",
        path=APP / "submittal_review.py",
        anchor="    if has_facts is not None:\n        return",
        replacement="    if False:\n        return",
        target=_INGEST_FACTS_TEST,
        keyword="does_not_duplicate_them",
        tags=("critical",),
    ),
)
