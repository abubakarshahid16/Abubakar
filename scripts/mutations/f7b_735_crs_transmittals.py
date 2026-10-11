"""#725 F7 (#735) part 2: editable CRS transmittal numbers; review CRSs on the Reports page. Ids M7201-M7207."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_f7b_735_crs_transmittals.py"
_F = "src/views/ReviewCrsList.test.tsx"
_TAG = ("f7", "crs")


def _m(i, desc, path, anchor, repl, kw=None, target=_T, runner=None):
    extra = {"runner": runner} if runner else {}
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=target, keyword=kw, tags=_TAG, **extra)


MUTATIONS: tuple[Mutation, ...] = (
    _m(7201, "the sheet ignores the entered company transmittal", APP / "main.py",
       '        "company_transmittal": run.get("crs_company_transmittal") or "",',
       '        "company_transmittal": "",', "printed_on_the_sheet"),
    _m(7202, "the route stores nothing", APP / "submittal_review.py",
       '        conn.execute("UPDATE review_runs SET crs_company_transmittal = ?, crs_contractor_transmittal = ?"\n'
       '                     " WHERE id = ?", (clean(company), clean(contractor), review_run_id))',
       "        pass", "printed_on_the_sheet or clears_a_number"),
    _m(7203, "a run outside the grants can be changed", APP / "submittal_review.py",
       "    run = get_review_run(review_run_id, allowed_document_ids=allowed_document_ids)\n    if run is None:\n        return None\n    clean",
       "    run = {}\n    clean", "may_not_read"),
    _m(7204, "an unnamed caller may enter one", APP / "main.py",
       '    _require_named_reviewer(scope, "entering a transmittal number")\n', "", "unnamed_caller"),
    _m(7205, "spaces are kept and an empty value is stored as text", APP / "submittal_review.py",
       '    clean = lambda v: (" ".join(v.split()) or None) if isinstance(v, str) else None  # noqa: E731',
       "    clean = lambda v: v  # noqa: E731", "printed_on_the_sheet or clears_a_number"),
    _m(7206, "the Reports page list renders nothing", FRONTEND_SRC / "views" / "ReviewCrsList.tsx",
       "      {runs !== null && runs.length > 0 && (", "      {false && (", "lists each run",
       target=_F, runner="vitest"),
    _m(7207, "the transmittal form does not save", FRONTEND_SRC / "views" / "ReviewRunsView.tsx",
       "    const res = await reviewsApi.setCrsTransmittals(runId, {\n      company_transmittal: company, contractor_transmittal: contractor,\n    });",
       "    const res = { ok: false as const, error: { message: \"no\" } };", "saves what was typed",
       target=_F, runner="vitest"),
)
