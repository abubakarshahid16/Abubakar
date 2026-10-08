"""#633 "the remaining absence paths": each entry deletes one fix;
backend/tests/test_w3_633_absence_rest.py (or the named test) must notice."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w3_633_absence_rest.py"
_TAG = ("w3_633", "honesty")


def _m(i, desc, path, anchor, repl, kw=None, target=_T):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=target, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(3401, "a run that did not complete is no longer listed as unchecked",
       "absence.py", '    if run_status != "completed":\n', "    if False:\n", "unchecked_parts_names"),
    _m(3402, "standards-table values not compared are no longer listed as unchecked",
       "absence.py", "    if cells:\n", "    if False:\n", "unchecked_parts_names"),
    _m(3403, "the incomplete-review notice is always empty",
       "absence.py", '    if not parts:\n        return ""\n    return (f"REVIEW INCOMPLETE',
       '    if True:\n        return ""\n    return (f"REVIEW INCOMPLETE', "unchecked_parts_names"),
    _m(3404, "the workbook does not print the incomplete notice",
       "crs_export.py", '    if view["incomplete_notice"]:\n', "    if False:\n", "workbook_prints"),
    _m(3405, "the CRS meta carries no incomplete notice",
       "main.py", '"incomplete_notice": absence_mod.notice_for(unchecked),', '"incomplete_notice": "",',
       "partial_and_the_crs"),
    _m(3406, "the unchecked parts are not added to the internal review notes",
       "main.py", '            for part in unchecked],', '            for part in []],', "partial_and_the_crs"),
    _m(3407, "findings written before a failure are not marked partial",
       "review_jobs.py", "                                             if written else {})}), _now(), run_id))",
       "                                             if False else {})}), _now(), run_id))",
       "partial_and_the_crs"),
    _m(3408, "an AI check that raised leaves no record on the run",
       "review_jobs.py", '        _record_check_failure(run_id, "ai_check_status", "AI engineering check", exc)\n',
       "        pass\n", "ai_check_that_raised"),
    _m(3409, "a web check that raised leaves no record on the run",
       "review_jobs.py", '        _record_check_failure(run_id, "web_check_status", "Web standards check", exc)\n',
       "        pass\n", "web_check_that_raised"),
    _m(3410, "an AI check that could not run leaves no record on the run",
       "ai_engineering_check.py", "        _store_status(review_run_id, absence.check_failed_status(\n",
       "        (lambda *a: None)(review_run_id, absence.check_failed_status(\n", "ai_check_that_raised"),
    _m(3411, "large unchecked parts no longer stop an approval",
       "comparison.py", "    if (share is not None and share >= absence.UNCHECKED_SHARE_LIMIT\n",
       "    if (False and share is not None and share >= absence.UNCHECKED_SHARE_LIMIT\n", "large_unchecked"),
    _m(3412, "'approved with comments' is not stopped by large unchecked parts",
       "comparison.py", '            and result["code"] in (codes[0], codes[1])):',
       '            and result["code"] in (codes[0],)):', "large_unchecked"),
    _m(3413, "the run no longer hands its unchecked counts to the review code",
       "comparison.py", '                                        "checked": len(requirements)})',
       '                                        "checked": len(requirements)} if False else None)',
       "hands_its_unchecked_counts"),
    _m(3414, "a revision-block check that could not run is silent again",
       "datasheet_checks.py", '    if not page_texts:\n        return "no page text was read for this datasheet"\n',
       '    if not page_texts:\n        return None\n', "revision_block_check_that_could_not_run"),
    _m(3415, "a consistency pair that cannot be compared is silent again",
       "datasheet_checks.py", '                out.append(_result(rule["id"], NEEDS_ENGINEER_REVIEW, rule["text"],\n                                   _sentence(\n                                       "the two values are not numbers',
       '                out.append(_result(rule["id"], COMPLIANT, rule["text"],\n                                   _sentence(\n                                       "the two values are not numbers',
       None, target="tests/test_datasheet_checks.py"),
    _m(3416, "a missing revision block is the contractor's omission while pages are unread",
       "datasheet_checks.py", '        if r["rule_id"] in ("DS-M1", "DS-R1") and status == MISSING_INFORMATION:',
       '        if r["rule_id"] == "DS-M1" and status == MISSING_INFORMATION:', "revision_block_is_not"),
    _m(3417, "an engineer-to-check self-check says 'None.' as the action",
       "datasheet_checks.py", '                                else "Engineer to check." if status == NEEDS_ENGINEER_REVIEW',
       '                                else "None." if status == NEEDS_ENGINEER_REVIEW', "revision_block_is_not"),
    _m(3418, "the PDF cuts a long finding off at a fixed box again",
       "review.py", "        height = min(700, max(150, int(wrapped_lines * 8.5 * 1.25) + 24))",
       "        height = 150", "pdf"),
    _m(3419, "an empty PDF report no longer says it is not a pass",
       "review.py", '"This is NOT a statement that the document was reviewed and found acceptable."',
       '""', "pdf"),
    _m(3420, "a named document that cannot be read is no longer listed",
       "analysis.py", "        if not named_document_ids(scope, [name]):\n", "        if False:\n", "named_document"),
    Mutation(id="M3421", phase=3421, runner="vitest",
             description="the run card does not show a web check that could not be checked",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="{run.web_check_status && !run.web_check_status.complete && (",
             replacement="{false && (",
             target="src/views/ReviewRunsView.test.tsx", keyword="could not check everything",
             tags=_TAG),
    Mutation(id="M3422", phase=3422, runner="vitest",
             description="the run card does not show that findings are only partial",
             path=FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
             anchor="{(run.partial_findings ?? 0) > 0 && (",
             replacement="{false && (",
             target="src/views/ReviewRunsView.test.tsx", keyword="could not check everything",
             tags=_TAG),
)

_S = "tests/test_w3_633_silent_excepts.py"
_SILENT = (
    (3423, "telemetry.py", '        _log.warning("a stage timing for %r was not recorded (%s)", stage, type(exc).__name__)', "stage_timing"),
    (3424, "progress.py", '            _log.warning("a progress listener failed at stage %r (%s)", name, type(exc).__name__)', "progress_listener"),
    (3425, "scope_records.py", '        _log.warning("the scope search for %s failed; only the other sources were used (%s)",\n                     document_id, type(exc).__name__)', "scope_search"),
    (3426, "rule_eval.py", '            _log.warning("the ruled table on page %s of %s could not be re-read (%s)",\n                         page, requirement.get("standard_document_id"), type(exc).__name__)', "re_read"),
    (3427, "classification.py", '        _log.warning("the equipment-type audit event for %s was not written (%s)",\n                     document_id, type(exc).__name__)', "audit_write"),
    (3428, "classification.py", '        _log.warning("the field-reclassified audit event for %s was not written (%s)",\n                     document_id, type(exc).__name__)', "no_broad_except"),
    (3429, "ingest.py", '        _log.warning("the stall diagnosis for %s could not be worked out (%s)",\n                     doc_id, type(exc).__name__)', "stall_diagnosis"),
    (3430, "main.py", '        _logging.getLogger("uvicorn.error").warning("the sweep for review runs left running by a dead process failed (%s); "\n                          "such a run may still look busy", type(exc).__name__)', "no_broad_except"),
    (3431, "main.py", '        _logging.getLogger("uvicorn.error").warning("the recovery of stale extraction and review jobs failed (%s); "\n                          "such a job may stay queued", type(exc).__name__)', "no_broad_except"),
)
MUTATIONS = MUTATIONS + tuple(
    _m(i, "an exception is swallowed with no trace again (" + path + ")", path, anchor,
       anchor.split("\n")[0][: len(anchor.split("\n")[0]) - len(anchor.split("\n")[0].lstrip())] + "pass",
       kw, target=_S)
    for i, path, anchor, kw in _SILENT)
