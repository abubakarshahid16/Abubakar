"""Mutations of the B10 review-decision rules: who signs, what is audited,
and one completeness formula."""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_b10_engineer_decisions.py"
_C = "tests/test_comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M844", phase=73, description="B10: an approval is recorded in the name the body gives",
             path=APP / "main.py", anchor='        changes["approved_by"] = scope.user_id\n',
             replacement='        changes["approved_by"] = (body.model_extra or {}).get("approved_by") or "somebody-else"\n',
             target=_T, keyword="names_the_caller or disposition_is_also_signed", tags=("audit", "critical")),
    Mutation(id="M845", phase=73, description="B10: a finding can be created already accepted",
             path=APP / "schemas.py", anchor='    approval_status: Literal["pending"] = "pending"\n',
             replacement='    approval_status: ApprovalStatus = "pending"\n',
             target=_T, keyword="created_already_accepted", tags=("audit", "critical")),
    Mutation(id="M846", phase=73, description="B10: a code decision stands when its audit row fails",
             path=APP / "comparison.py",
             anchor='        _audit(conn, "review.code_recorded", actor, review_run_id,\n',
             replacement='        (lambda *a, **k: None)(conn, "review.code_recorded", actor, review_run_id,\n',
             target=_T, keyword="audit_fails or audited_with_the_engineer", tags=("audit",)),
    Mutation(id="M847", phase=73, description="B10: the selection computes its own completeness again",
             path=APP / "applicability.py", anchor='        "completeness": run["completeness"],\n',
             replacement='        "completeness": reference_coverage if reference_coverage is not None else 1.0,\n',
             target=_C, keyword="one_completeness or unknown_page_count", tags=("honesty",)),
    Mutation(id="M848", phase=73, description="B10: a pair rejection is not audited",
             path=APP / "comparison.py", anchor='            _audit(conn, "review.pair_rejected",\n',
             replacement='            (lambda *a, **k: None)(conn, "review.pair_rejected",\n',
             target=_T, keyword="pair_rejection_is_audited", tags=("audit",)),
    Mutation(id="M849", phase=73, description="B10: the CRS passes the AI's code off as decided",
             path=APP / "main.py",
             anchor='            else crs_export_mod.CODE_NOT_YET_DECIDED if outcome.get("recommended_code")\n',
             replacement='            else crs_export_mod.CODE_DECIDED_BY_ENGINEER if outcome.get("recommended_code")\n',
             target=_T, keyword="not_yet_an_engineers_decision", tags=("honesty", "critical")),
    Mutation(id="M850", phase=73, description="B10: the CRS never says an engineer decided",
             path=APP / "main.py",
             anchor='            crs_export_mod.CODE_DECIDED_BY_ENGINEER if run.get("engineer_final_code")\n',
             replacement='            crs_export_mod.CODE_NOT_YET_DECIDED if run.get("engineer_final_code")\n',
             target=_T, keyword="engineer_decided_the_code", tags=("honesty",)),
    Mutation(id="M851", phase=73, runner="vitest", description="B10: the CRS preview hides who decided the code",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="      {preview.recommended_code && preview.recommended_code_status && (\n",
             replacement="      {false && preview.recommended_code_status && (\n",
             target="src/views/ReviewRunsView.crsPreview.test.tsx", keyword="AI's recommendation",
             tags=("honesty", "ui")),
    Mutation(id="M852", phase=73, description="B10: a machine-written finding leaves no history",
             path=APP / "comparison.py", anchor='        review._event(conn, row["id"], "created_by_review", {\n',
             replacement='        (lambda *a, **k: None)(conn, row["id"], "created_by_review", {\n',
             target=_C, keyword="starts_its_history", tags=("audit",)),
    # ---- from the safety group (2026-09-27): "issue to contractor" gated ---
    Mutation(id="M1130", phase=95,
             description="safety: the issue-to-contractor CRS export no "
                         "longer refuses a run with no engineer's final code",
             path=APP / "main.py",
             anchor='    reject_unknown_params(request, {"copy"})\n'
                    '    if copy == "issue":\n'
                    '        run = submittal_review_mod.get_review_run(\n'
                    '            review_run_id, allowed_document_ids=scope.allowed_document_ids)\n'
                    '        if run is None:\n'
                    '            raise HTTPException(status_code=404, detail=errors.safe_error(\n'
                    '                errors.NOT_FOUND, "no review run with that id"))\n'
                    '        if not run.get("engineer_final_code"):\n'
                    '            raise HTTPException(status_code=409, detail=errors.safe_error(\n'
                    '                errors.CODE_NOT_DECIDED,\n'
                    '                "an engineer must record the final code before this run can "\n'
                    '                "be issued to the contractor"))\n'
                    '    rows, meta, submittal_name, stamp = _crs_content(review_run_id, scope, copy)',
             replacement='    reject_unknown_params(request, {"copy"})\n'
                         '    rows, meta, submittal_name, stamp = _crs_content(review_run_id, scope, copy)',
             target="tests/test_crs_endpoint.py",
             keyword="issue_copy_is_refused_until_an_engineer_decides",
             tags=("safety", "critical")),
    Mutation(id="M1131", phase=95, runner="vitest",
             description="safety: the issue-to-contractor button is no "
                         "longer disabled before an engineer decides",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor='              disabled={exporting || !run.engineer_final_code}\n'
                    '              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50"\n'
                    '            >\n'
                    '              Export CRS - issue to contractor\n',
             replacement='              disabled={exporting}\n'
                        '              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50"\n'
                        '            >\n'
                        '              Export CRS - issue to contractor\n',
             target="src/views/ReviewRunsView.crsPreview.test.tsx",
             keyword="SAFETY GATE",
             tags=("safety", "ui")),
)
