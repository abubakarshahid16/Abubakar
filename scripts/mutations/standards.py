"""Mutations of `backend/app/standards.py`."""

from __future__ import annotations

from ._base import APP, _B38_NOOP, _B38_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_3A ----------------------------------------------------
    #: Phase 3A: the Standards Library.
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
        # Re-anchored in P5: the helper no longer swallows its own failure,
        # so the try block it used to sit in is gone.
        anchor="    conn = connect()\n"
               "    with conn:\n"
               "        conn.execute(\n"
               '            """INSERT INTO audit_events',
        replacement="    return\n"
                    "    conn = connect()\n"
                    "    with conn:\n"
                    "        conn.execute(\n"
                    '            """INSERT INTO audit_events',
        target="tests/test_standards_library.py",
        keyword="supersession_is_audited",
        tags=("audit",),
    ),
    Mutation(
        id="M33", phase=3,
        description="record recommendations ('should') as requirements",
        path=APP / "standards.py",
        # Re-anchored 2026-09-24: the pattern gained a `must\s+not` branch and
        # the old anchor matched 0 times, so this mutation had silently stopped
        # being applied (the harness reported it as a harness error).
        anchor=r'    r"\b(shall|must\s+not|must|is\s+required\s+to|are\s+required\s+to"',
        replacement=r'    r"\b(shall|should|must\s+not|must|is\s+required\s+to|are\s+required\s+to"',
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
    # ---- from PHASE_3B ----------------------------------------------------
    #: Phase 3B: tables, limits, units, exceptions, conflicts, the queue.
    #: `phase=4` only because `--phase 3` already selects 3A; the ids are the
    #: stable handle and the tags say what each one is about.
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
        # Re-anchored in B11: the check-then-insert now sits under one write
        # lock, so the synchronous run goes after it, before the return.
        anchor="    _audit(\"standard.extraction_queued\", actor, document_id, detail=f\"job={job_id}\")\n    return job_id",
        replacement="    _audit(\"standard.extraction_queued\", actor, document_id, detail=f\"job={job_id}\")\n"
                    "    run_extraction_job(document_id)\n    return job_id",
        target="tests/test_standards_3b.py",
        keyword="queued_and_drained_by_the_existing_worker",
        tags=("job",),
    ),
    # ---- from DISCIPLINE --------------------------------------------------
    #: Part A of the extraction preparation: the discipline each standard's own
    #: cover page names. M84 is the one with teeth - the letter map is the rule
    #: anyone would reach for, and it is wrong for whole families of this corpus.
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
        # Re-anchored 2026-09-24 when `must\s+not` was added to the pattern:
        # "(shall|must|is" matched 0 times and "(shall|must" alone now also
        # occurs in the `\b(shall|must)\b` check, so the slice needs the
        # `must\s+not` branch to stay unique.
        anchor=r"(shall|must\s+not|must|is",
        replacement=r"(shall|should|must\s+not|must|is",
        target="tests/test_standards_library.py",
        keyword="mandatory_vocabulary_is_saudi_aramcos_own",
        tags=("honesty", "critical"),
    ),
    # ---- from EXTRACTION --------------------------------------------------
    #: Extraction quality: the unit gate, the page footer, the dedupe, the
    #: descriptive subject, and the orphaned job nobody would ever see.
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
    # ---- from STANDARDS_MODAL ---------------------------------------------
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
    # ---- from B38_ORPHAN_GUARD --------------------------------------------
    #: B38: record, then refuse by default, on all four paths that delete
    #: requirement rows review findings cite. A path's mutation swaps its guard
    #: call for a no-op that accepts the same arguments.
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
    # ---- from B175_CASCADE_AND_CONFIDENCE ---------------------------------
    #: #175: cascaded extractor (table column-scoping, reused from the parked
    #: B58 fix, renumbered M356-M358 -> M365-M367 to avoid colliding with
    #: mutation ids already added on this branch since the two diverged), OCR
    #: fallback routing, and confidence-based NEEDS_ENGINEER_REVIEW routing.
    Mutation(
        id="M372", phase=47,
        description="reimplement requirement ranking directly off the RRF "
                    "fusion helpers instead of calling the shared "
                    "search.search entrypoint, so requirement retrieval "
                    "silently forks into a second search stack",
        path=APP / "standards.py",
        anchor="    from . import search as search_mod\n"
               "    result = search_mod.search(",
        replacement="    from . import search as search_mod\n"
                    "    def _bypass(*a, **k):\n"
                    "        return {'hits': []}\n"
                    "    result = _bypass(",
        target="tests/test_standards_3b.py",
        keyword="search_requirements_reuses_the_existing_hybrid_search",
        tags=("critical",),
    ),
    Mutation(
        id="M373", phase=47,
        description="apply the structured pre-filter AFTER retrieval "
                    "instead of narrowing the id set retrieval receives, "
                    "so a filtered-out standard is still a candidate",
        path=APP / "standards.py",
        anchor="        scope = {r[\"id\"] for r in rows}\n"
               "    narrowed = frozenset(scope)",
        replacement="        pass\n"
                    "    narrowed = frozenset(scope)",
        target="tests/test_standards_3b.py",
        keyword="a_prefilter_narrows_the_scope_handed_to_retrieval_before_ranking",
        tags=("honesty", "critical"),
    ),
    # ---- from B177_JOB_CLAIM_RETRY_PRIORITY -------------------------------
    Mutation(
        id="M410", phase=53,
        description="next_extraction_job writes the claimant's name but "
                    "leaves the job 'queued', so the claim is not exclusive "
                    "and a second poller is handed the same job (#177 gap 1)",
        path=APP / "standards.py",
        anchor="            f\"\"\"UPDATE jobs SET state = 'running', claimed_by = :me,\n"
               "                       claimed_at = :now, updated_at = :now\n"
               "                WHERE id = (SELECT id FROM jobs WHERE stage = :stage",
        replacement="            f\"\"\"UPDATE jobs SET state = state, claimed_by = :me,\n"
                    "                       claimed_at = :now, updated_at = :now\n"
                    "                WHERE id = (SELECT id FROM jobs WHERE stage = :stage",
        target="tests/test_job_claiming_race.py",
        keyword="second_poller",
        tags=("critical",),
    ),
    Mutation(
        id="M411", phase=53,
        description="run_extraction_job trusts its caller again: a worker "
                    "that holds no claim runs the job anyway - the pre-#177 "
                    "unchecked-rowcount behaviour (#177 gap 1)",
        path=APP / "standards.py",
        anchor="    if job is None:\n"
               "        return {\"document_id\": document_id, \"state\": \"not_claimed\",\n"
               "                \"requirements\": 0, \"table_values\": 0}\n",
        replacement="    if job is None:\n"
                    "        job = conn.execute(\"SELECT id FROM jobs WHERE document_id = ?\"\n"
                    "            \" AND stage = ?\", (document_id, EXTRACTION_STAGE)).fetchone()\n",
        target="tests/test_job_claiming_race.py",
        keyword="someone_else_holds",
        tags=("critical",),
    ),
    Mutation(
        id="M416", phase=53,
        description="the backoff is ignored: a retrying job is claimable the "
                    "moment it fails (#177 gap 2)",
        path=APP / "standards.py",
        anchor="              \" AND next_attempt_at IS NOT NULL AND next_attempt_at <= :now))\")",
        replacement="              \" AND 1 = 1))\")",
        target="tests/test_job_queue_177.py",
        keyword="retried_after_a_backoff",
    ),
)
