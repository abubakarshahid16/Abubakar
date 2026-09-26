"""Mutations of:

    backend/app/chat.py
    backend/app/chunker.py
    backend/app/claude_spend.py
    backend/app/config.py
    backend/app/crs_export.py
    backend/app/disciplines.py
    backend/app/hooks_check.py
    backend/app/job_queue.py
    backend/app/metrics.py
    backend/app/quotes.py
    backend/run.py
    scripts/gold_pairs_score.py
    scripts/mutation_check.py
    scripts/resetdoc.py
"""

from __future__ import annotations

from ._base import (
    APP,
    BACKEND,
    REPO,
    _B38_NOOP,
    _B38_TEST,
    _LIVE_GUARD_TEST,
    _SCORERS_TEST,
    Mutation,
)


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from GATE_FALLOUT ------------------------------------------------
    #: The three defects the model tier's failed gate exposed, plus the default
    #: it was turned off by.
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
    # ---- from DISCIPLINE_CANONICAL ----------------------------------------
    #: The discipline overlay: one canonical value, the raw one kept intact.
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
    # ---- from CORPUS_QUESTIONS --------------------------------------------
    #: Document Q&A answered "there are 12 distinct standards" from three retrieved
    #: passages, of a library holding 272. Both halves of the fix, both sides.
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
    # ---- from PERSISTED_TRUNCATION ----------------------------------------
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
    # ---- from CONDITION_AND_QUOTES ----------------------------------------
    #: B24 (the condition safety gate) and B23 (evidence quote validation), plus a
    #: re-anchoring of B20's dimension guard, so all three safety gates that came out
    #: of the Phase 0.5 slice are proven by this harness rather than by an ad-hoc
    #: script in one session's scratchpad.
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
    # ---- from B38_ORPHAN_GUARD --------------------------------------------
    #: B38: record, then refuse by default, on all four paths that delete
    #: requirement rows review findings cite. A path's mutation swaps its guard
    #: call for a no-op that accepts the same arguments.
    Mutation(
        id="M329", phase=38,
        description="path 3: a re-chunk cascades cited requirements away unguarded",
        path=APP / "chunker.py",
        anchor='    orphan_guard.check(\n        "re_chunk",',
        replacement=f'    {_B38_NOOP}\n        "re_chunk",',
        target=_B38_TEST, keyword="re_chunk",
        tags=("critical",),
    ),
    # ---- from B163_EVIDENCE_TYPE_GATE -------------------------------------
    Mutation(
        id="M380", phase=49,
        description="stop colouring rows by row_kind, so a NON_COMPLIANT "
                    "defect and a NEEDS_ENGINEER_REVIEW row look identical "
                    "on the printed sheet (issue #165 criterion 4)",
        path=APP / "crs_export.py",
        anchor="            if fill is not None:\n"
               "                cell.fill = fill",
        replacement="            if False:\n"
                    "                cell.fill = fill",
        target="tests/test_crs_export.py",
        keyword="rows_of_different_kinds_get_different_fill_colours",
        tags=("honesty", "critical"),
    ),
    # ---- from B168_PIPELINE_REPAIR ----------------------------------------
    Mutation(
        id="M381", phase=50,
        description="delete the chunk_signature skip-if-unchanged guard, so "
                    "every re-chunk does a full rebuild instead of the "
                    "incremental no-op issue #168 criterion 2 claims",
        path=APP / "chunker.py",
        anchor='    if not force and existing and doc["chunk_signature"] == signature:',
        replacement='    if False:',
        target="tests/test_incremental_reindex.py",
        keyword="rechunking_unchanged_content_leaves_chunk_rows_untouched",
        tags=("honesty",),
    ),
    # ---- from B177_JOB_CLAIM_RETRY_PRIORITY -------------------------------
    Mutation(
        id="M414", phase=53,
        description="every failure poisons at once - no retry is ever "
                    "scheduled, jobs.retries has no reader again (#177 gap 2)",
        path=APP / "job_queue.py",
        anchor="    if retries < settings.job_max_retries:\n",
        replacement="    if False:\n",
        target="tests/test_job_queue_177.py",
        keyword="retried_after_a_backoff or retry_resumes or backoff_grows",
        tags=("honesty",),
    ),
    Mutation(
        id="M415", phase=53,
        description="retries never run out, so a job that always fails is "
                    "retried forever and never marked poisoned (#177 gap 2)",
        path=APP / "job_queue.py",
        anchor="    if retries < settings.job_max_retries:\n",
        replacement="    if True:\n",
        target="tests/test_job_queue_177.py",
        keyword="exhaustion or retried_then_poisoned",
        tags=("honesty",),
    ),
    Mutation(
        id="M419", phase=53,
        description="the corpus-wide queue counts are served to every "
                    "metrics caller, not only to the admin capability "
                    "(#177 visibility; audit rows 15 and 30)",
        path=APP / "metrics.py",
        anchor="        **({\"queue\": _queue()} if host else {}),",
        replacement="        **{\"queue\": _queue()},",
        target="tests/test_job_queue_177.py",
        keyword="queue_counts_reach_an_admin",
        tags=("critical",),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M469", phase=57,
        description="run.py stops marking the server, so the live API is "
                    "refused its own database on the next restart (live guard)",
        path=REPO / "backend" / "run.py",
        anchor="    live_guard.mark_server_process()\n",
        replacement="",
        target=_LIVE_GUARD_TEST, keyword="marks_the_server",
        tags=("critical",),
    ),
    Mutation(
        id="M470", phase=57,
        description="resetdoc writes a live database without the guard again - "
                    "the raw sqlite path the connection layer cannot see",
        path=REPO / "scripts" / "resetdoc.py",
        anchor="    if live_guard.is_live_shaped(path):\n"
               "        clearance = live_guard.prepare_live_write(path, reason=f\"resetdoc {args.doc_id}\")\n"
               "        print(f\"rollback point: {clearance.backup_path}\")\n",
        replacement="",
        target=_LIVE_GUARD_TEST, keyword="resetdoc",
        tags=("critical",),
    ),
    # ---- from B193_PAIRING ------------------------------------------------
    #: Master order B4, issue #193: pairing measured against gold and made
    #: precise. Phase 58.
    Mutation(
        id="M481", phase=58,
        description="the pairing scorer hands the matcher superseded facts, so "
                    "a tie hides the pairing production makes (#193, audit 52)",
        path=REPO / "scripts" / "gold_pairs_score.py",
        anchor='        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?" + current,\n',
        replacement='        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?",\n',
        target=_SCORERS_TEST, keyword="gold_pairs_score",
        tags=("honesty",),
    ),
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M534", phase=61,
        description="treat an unset core.hooksPath as fine, so a checkout "
                    "with the hooks off boots silently",
        path=BACKEND / "app" / "hooks_check.py",
        anchor="    if configured:\n",
        replacement="    if configured is None:\n        return None\n    if configured:\n",
        target="tests/test_hooks_check.py",
        keyword="unset_hooks_path_is_warned",
        tags=("safety", "live"),
    ),
    # Owner order 2026-09-25 (item 3a): client identifiers out of git. The
    # CRS company comes from configuration, and the pre-commit hook reads its
    # blocked patterns from a local, git-ignored file.
    Mutation(
        id="M540", phase=61,
        description="ignore CRS_COMPANY_NAME: the CRS company is no longer "
                    "read from settings",
        path=APP / "crs_export.py",
        anchor='    return settings.crs_company_name or ""\n',
        replacement='    return ""\n',
        target="tests/test_crs_export.py",
        keyword="default_company_comes_from_settings",
        tags=("privacy",),
    ),
    Mutation(
        id="M569", phase=61,
        description="the total cap only counts the current step",
        path=APP / "claude_spend.py",
        anchor="    step_spent, total_spent = spent(step), spent()\n",
        replacement="    step_spent, total_spent = spent(step), spent(step)\n",
        target="tests/test_claude_provider.py",
        keyword="total_cap_counts",
        tags=("safety", "budget"),
    ),
    # ---- the registry itself ----------------------------------------------
    #: The entries were split into one file per mutated module (2026-09-25);
    #: a duplicate id across two files must be refused at import.
    Mutation(
        id="M576", phase=62,
        description="the registry accepts a duplicate mutation id across two "
                    "files, making `--only` and every citation ambiguous",
        path=REPO / "scripts" / "mutation_check.py",
        anchor="            if m.id in seen:\n",
        replacement="            if False:\n",
        target="tests/test_mutation_registry.py",
        keyword="duplicate_id_across_two_modules",
        tags=("harness",),
    ),
    Mutation(
        id="M640", phase=64,
        description="B4 vision: page images are dropped from the request (text only)",
        path=APP / "reader_api.py",
        anchor='        content = [*blocks, {"type": "text", "text": prompt}]\n',
        replacement="        content = prompt\n",
        target="tests/test_b4_quality.py", keyword="images_ride_in_the_one_request_builder",
        tags=("egress",),
    ),
    Mutation(
        id="M641", phase=64,
        description="B4 vision: any media type, or an empty image, is sent",
        path=APP / "reader_api.py",
        anchor="            if media_type not in IMAGE_MEDIA_TYPES or not isinstance(data, str) or not data:\n",
        replacement="            if False:\n",
        target="tests/test_b4_quality.py", keyword="image_request_keeps_every_gate",
        tags=("egress", "critical"),
    ),
    Mutation(
        id="M644", phase=64,
        description="B4 vision: the budget check ignores image tokens",
        path=APP / "claude_spend.py",
        anchor="    tokens_in = prompt_chars // 3 + 1 + max(0, int(image_tokens))\n",
        replacement="    tokens_in = prompt_chars // 3 + 1\n",
        target="tests/test_b4_quality.py", keyword="worst_case_counts_the_image",
        tags=("budget", "critical"),
    ),
    # ---- b5-quality 2026-09-25: Message Batches (claude_spend, reader_transport)
    Mutation(
        id="M670", phase=62,
        description="a batch result is charged at the full price (the batch discount is dropped)",
        path=APP / "claude_spend.py",
        anchor="            + int(usage.get(\"cache_read_input_tokens\") or 0) * p_read) / 1_000_000\n"
               "    return full * BATCH_DISCOUNT if batch else full\n",
        replacement="            + int(usage.get(\"cache_read_input_tokens\") or 0) * p_read) / 1_000_000\n"
                    "    return full\n",
        target="tests/test_claude_provider.py",
        keyword="priced_at_half",
        tags=("budget",),
    ),
    Mutation(
        id="M671", phase=62,
        description="a batch is created without checking its worst case against the caps",
        path=APP / "reasoning_provider.py",
        anchor="            for step in steps:\n                claude_spend.ensure_affordable(step, worst)\n",
        replacement="            for step in ():\n                claude_spend.ensure_affordable(step, worst)\n",
        target="tests/test_claude_provider.py",
        keyword="refused_before_it_is_created",
        tags=("safety", "budget"),
    ),
    Mutation(
        id="M672", phase=62,
        description="the batch calls skip gate 1 (both egress flags)",
        path=APP / "reader_transport.py",
        anchor="    \"\"\"One request through the gates; returns the httpx response.\"\"\"\n    if not available():\n",
        replacement="    \"\"\"One request through the gates; returns the httpx response.\"\"\"\n    if False:\n",
        target="tests/test_reader_transport.py",
        keyword="flags_off_no_batch",
        tags=("privacy", "egress"),
    ),
    Mutation(
        id="M673", phase=62,
        description="a results_url from the provider's answer is fetched without the https/host gate",
        path=APP / "reader_transport.py",
        anchor="    if not url.startswith(\"https://\") or host not in ReaderSettings.from_env().allowed_hosts:\n"
               "        raise ReaderRefused(f\"reader transport refuses host {host!r}\")\n    sent = ",
        replacement="    if False:\n"
                    "        raise ReaderRefused(f\"reader transport refuses host {host!r}\")\n    sent = ",
        target="tests/test_reader_transport.py",
        keyword="results_url_from_the_answer",
        tags=("privacy", "egress"),
    ),
    Mutation(
        id="M765", phase=67,
        description="B6: a number inside a sentence ends the clause again (figured clauses unsearchable)",
        path=APP / "quality.py",
        anchor="            # non-word the run is already 0, so the left side needs no check).\n            continue\n",
        replacement="            # non-word the run is already 0, so the left side needs no check).\n            run = 0\n",
        target="tests/test_b6_measure_in_clause.py",
        keyword="measurement_inside_a_sentence or figured",
    ),
    Mutation(
        id="M766", phase=67,
        description="B6: any number keeps a clause going, so contents columns and table rows read as prose",
        path=APP / "quality.py",
        anchor="            and is_word(tokens[i + 1])\n            and tokens[i + 1][0].islower()\n",
        replacement="            and True\n            and True\n",
        target="tests/test_b6_measure_in_clause.py",
        keyword="not_inside_a_sentence_still_break",
    ),
    Mutation(
        id="M768", phase=67,
        description="B6: a number before a capitalised label bridges, so a joined table's rows read as a sentence",
        path=APP / "quality.py",
        anchor="            and tokens[i + 1][0].islower()\n",
        replacement="            and True\n",
        target="tests/test_b6_measure_in_clause.py",
        keyword="joined_onto_one_line",
    ),
)
