"""Mutations of `backend/app/main.py`."""

from __future__ import annotations

from ._base import (
    APP,
    BACKEND,
    _B38_NOOP,
    _B38_TEST,
    _B3_TEST,
    _B42_TEST,
    Mutation,
)


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_2 -----------------------------------------------------
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
    # ---- from ROLES_FIX ---------------------------------------------------
    #: Document roles: the watched folder's subfolder convention, and the bulk
    #: assignment endpoint. Not a phase - a contained fix between phases 5B and 6.
    #:
    #: M73 IS THE ONE THAT MATTERS. Every other mutation here breaks something a
    #: user would notice. M73 makes the watcher guess a role from the filename,
    #: which on this corpus is right 272 times out of 280 and would look like an
    #: improvement in a diff.
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
    # ---- from MODEL_TIER --------------------------------------------------
    #: The model tier of the matcher. It may CHOOSE, never NAME.
    Mutation(
        id="M154", phase=11,
        description="accept an anonymous confirmation, which records nothing "
                    "and answers 200",
        path=APP / "main.py",
        # B10 added a second `if scope.user_id is None:` (approvals); the
        # confirmation's own comment line keeps this anchor unique.
        anchor="        if scope.user_id is None:\n            # AN ANONYMOUS CONFIRMATION",
        replacement="        if False:\n            # AN ANONYMOUS CONFIRMATION",
        target="tests/test_model_matching.py",
        keyword="confirmation_with_no_identity",
        tags=("honesty",),
    ),
    # ---- from GATE_FALLOUT ------------------------------------------------
    #: The three defects the model tier's failed gate exposed, plus the default
    #: it was turned off by.
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
    # ---- from REVIEW_GOVERNANCE -------------------------------------------
    #: A crashed run, and the engineer's final code (master plan section 15).
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
    # ---- from REVIEW_DASHBOARD --------------------------------------------
    #: The Dashboard's four cards (CLAUDE.md rule 10, master plan section 20).
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
        id="M224", phase=19,
        description="stop putting the name on the wire, so the client is "
                    "back to rendering the id it was given",
        path=APP / "main.py",
        anchor='        "decided_by_name": run.get("decided_by_name"),',
        replacement='        "decided_by_name": None,',
        target="tests/test_review_code.py",
        keyword="not_an_admin_can_record_the_final_code",
    ),
    # ---- from ADMIN_EXPLORER ----------------------------------------------
    #: The read-only database explorer: who may look, and what they may see.
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
    # ---- from CRS_EXPORT --------------------------------------------------
    #: The CRS export: who may export, and what the file is allowed to say.
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
        # Re-anchored by B3: the call gained `unread_pages=` on the next line.
        anchor="        findings, _missing_references(submittal_id, allowed), submittal_name,\n",
        replacement="        findings, [], submittal_name,\n",
        target="tests/test_crs_endpoint.py",
        keyword="no_includable_findings_still_exports_its_gap_rows",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M240", phase=22,
        description="INVENT A TRANSMITTAL NUMBER, so the CRS lies about its "
                    "own provenance to whoever receives it",
        path=APP / "main.py",
        anchor='        "company_transmittal": "",',
        replacement='        "company_transmittal": "EOC-TRX-0001",',
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
    # ---- from B7_ANALYSIS_GENERATION --------------------------------------
    #: B7: four analysis-route tests had passed through the single-passage
    #: pass-through since 5a7a2b3's relevance floor, so they never reached
    #: generation. With two on-topic passages they do; one mutation per test
    #: proves each still guards the behaviour its name claims.
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
    # ---- from B38_ORPHAN_GUARD --------------------------------------------
    #: B38: record, then refuse by default, on all four paths that delete
    #: requirement rows review findings cite. A path's mutation swaps its guard
    #: call for a no-op that accepts the same arguments.
    Mutation(
        id="M330", phase=38,
        description="path 4: deleting a cited standard cascades unguarded",
        path=APP / "main.py",
        anchor='    orphan_guard.check(\n        "document_delete",',
        replacement=f'    {_B38_NOOP}\n        "document_delete",',
        target=_B38_TEST, keyword="deleting_a_cited_standard",
        tags=("critical",),
    ),
    # ---- from B42_STRUCTURED_SCOPE ----------------------------------------
    #: B42: the one branch that never applied the scope mask, and the permissive
    #: default that would have let the next caller read the corpus by forgetting.
    Mutation(
        id="M341", phase=40,
        description="hand the unowned rows back to every caller, not the admin "
                    "capability alone",
        path=APP / "main.py",
        anchor="        include_unowned=scope.is_admin)}",
        replacement="        include_unowned=True)}",
        target=_B42_TEST, keyword="route_gives_the_unowned_rows",
        tags=("privacy",),
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M458", phase=57,
        description="the page-ledger route stops checking the caller may read "
                    "the document (B3)",
        path=APP / "main.py",
        anchor="    reject_unknown_params(request, set())\n"
               "    require_document(document_id, scope)\n"
               "    return {\"document_id\": document_id,\n"
               "            \"pages\": page_ledger_mod.rows(document_id),",
        replacement="    reject_unknown_params(request, set())\n"
                    "    return {\"document_id\": document_id,\n"
                    "            \"pages\": page_ledger_mod.rows(document_id),",
        target=_B3_TEST, keyword="hides_a_document_outside",
        tags=("permission", "critical"),
    ),
    Mutation(
        id="M476", phase=57,
        description="the CRS export stops passing the run's stored unread "
                    "pages, so the summary names no page (B3)",
        path=APP / "main.py",
        anchor="        unread_pages=unread)\n",
        replacement="        unread_pages=[])\n",
        target=_B3_TEST, keyword="crs_names_the_unread_pages",
        tags=("honesty",),
    ),
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M535", phase=61,
        description="the boot step computes the warning but never logs it",
        path=BACKEND / "app" / "main.py",
        anchor='        logging.getLogger("uvicorn.error").warning(message)\n',
        replacement="        pass\n",
        target="tests/test_hooks_check.py",
        keyword="boot_logs_the_warning",
        tags=("safety", "live"),
    ),
    Mutation(
        id="M536", phase=61,
        description="lifespan no longer runs the hooks check",
        path=BACKEND / "app" / "main.py",
        anchor="    _log_hooks_path()\n",
        replacement="",
        target="tests/test_hooks_check.py",
        keyword="real_app_startup_logs_the_warning",
        tags=("safety", "live"),
    ),
    Mutation(
        id="M537", phase=61,
        description="the revived Claude lane's router is no longer registered (#222)",
        path=BACKEND / "app" / "main.py",
        anchor="app.include_router(claude_api_mod.router)\n",
        replacement="",
        target="tests/test_claude_api.py",
        keyword="the_four_routes_are_registered",
        tags=("gate",),
    ),
)
