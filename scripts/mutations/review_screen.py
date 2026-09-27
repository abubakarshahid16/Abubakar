"""Owner order section 3 (screen, part A): readiness strip and Edit/Reject."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_review_screen.py"
_MAIN = APP / "main.py"
_CRS = APP / "crs_mapping.py"
_REVIEW = APP / "review.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1099", phase=92, description="the last run is any run, not the last completed one",
             path=_MAIN,
             anchor='    last = next((r for r in runs if r.get("status") == "completed"), None)\n',
             replacement='    last = runs[0] if runs else None\n',
             target=_T, keyword="the_last_run_is_the_last_completed_one", tags=("honesty",)),
    Mutation(id="M1100", phase=92, description="a datasheet value read after the run is not a change",
             path=_MAIN,
             anchor='        if newer_facts:\n            changes.append(f"{newer_facts} datasheet value(s) read since the last run")\n',
             replacement='        if False:\n            changes.append(f"{newer_facts} datasheet value(s) read since the last run")\n',
             target=_T, keyword="a_value_read_after_the_run_is_a_change", tags=("honesty",)),
    Mutation(id="M1101", phase=92, description="a standard added after the run is not a change",
             path=_MAIN,
             anchor='        if newer_standards:\n',
             replacement='        if False:\n',
             target=_T, keyword="a_standard_added_after_the_run_is_a_change", tags=("honesty",)),
    Mutation(id="M1102", phase=92, description="an edited comment is not confirmed on save",
             path=_MAIN,
             anchor='    if changes.get("engineer_comment"):\n        changes["confirmed"] = True\n',
             replacement='    if False:\n        changes["confirmed"] = True\n',
             target=_T, keyword="an_edited_comment_survives_a_re_run", tags=("honesty", "critical")),
    Mutation(id="M1103", phase=92, description="the finding's own stored wording is silently replaced",
             path=_REVIEW,
             anchor='    changed = {key: value for key, value in changes.items()\n               if key in allowed and value is not None\n               and value != current.get(key)}',
             replacement='    changed = {key: value for key, value in changes.items()\n               if key in allowed and value is not None\n               and value != current.get(key)}\n    if "engineer_comment" in changed:\n        changed["finding"] = changed["engineer_comment"]',
             target=_T, keyword="edit_is_the_crs_comment_confirmed", tags=("honesty", "critical")),
    Mutation(id="M1104", phase=92, description="the edit's earlier wording is not kept in the audit",
             path=_REVIEW,
             anchor='        detail = ({**changed, "engineer_comment_before": current.get("engineer_comment")}\n                  if "engineer_comment" in changed else changed)\n',
             replacement='        detail = changed\n',
             target=_T, keyword="the_audit_keeps_both", tags=("audit",)),
    Mutation(id="M1105", phase=92, description="a rejected comment still prints on the CRS",
             path=_CRS,
             anchor='    findings = [f for f in findings if not _rejected(f)]\n',
             replacement='    findings = list(findings)\n',
             target=_T, keyword="a_rejected_comment_is_left_off_the_sheet", tags=("honesty", "critical")),
    Mutation(id="M1106", phase=92, description="the CRS prints the review's text instead of the engineer's edit",
             path=_CRS,
             anchor='    if finding.get("engineer_comment"):\n        return finding["engineer_comment"]\n',
             replacement='    if False:\n        return finding["engineer_comment"]\n',
             target=_T, keyword="edit_is_the_crs_comment", tags=("honesty", "critical")),
    # ---- from the honesty group (2026-09-27): unread pages name their reason
    Mutation(id="M1133", phase=95,
             description="honesty: the readiness payload drops the page "
                         "ledger's own reason for each unread page",
             path=_MAIN,
             anchor='        "unread_page_reasons": pages.get("not_read_reasons") or {},\n',
             replacement='        "unread_page_reasons": {},\n',
             target=_T, keyword="unread_page_carries_its_own_reason",
             tags=("honesty", "critical")),
    Mutation(id="M1134", phase=95, runner="vitest",
             description="honesty: the readiness strip stops naming why each "
                         "unread page is unread",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor='              Page {page}: {readiness.unread_page_reasons?.[String(page)]\n'
                    '                || "reason not recorded"}\n',
             replacement='              Page {page}\n',
             target="src/views/ReviewRunsView.screen.test.tsx",
             keyword="HONESTY GROUP", tags=("honesty", "ui")),
)
