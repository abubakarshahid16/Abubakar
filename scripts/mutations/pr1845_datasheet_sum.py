"""PR #1845 (order 14, lane A): the checklist rule kind sum_percent_of (`backend/app/datasheet_sum.py`, split out of the
datasheet_checks danger zone, CLAUDE.md rule 6). SAES-J-600 5.1.1 compares the SUM of two back pressures with 10% of the set
pressure. Each entry deletes one part of that; tests/test_o14_valve_ai_draft_checks.py must notice. Ids named after the PR
(rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_o14_valve_ai_draft_checks.py"
_K = "compares_the_sum"
_TAG = ("o14", "datasheet", "honesty")
_SUM = APP / "datasheet_sum.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1845-01", phase=1845,
             description="one part alone is compared: the second back pressure is dropped from the sum",
             path=_SUM,
             anchor='    for role in (rule["field"], rule["plus"]):\n',
             replacement='    for role in (rule["field"],):\n',
             target=_T, keyword=_K, tags=_TAG),
    Mutation(id="M1845-02", phase=1845,
             description="a part not given or marked by the contractor is skipped (taken as 0) instead of stopping the check",
             path=_SUM,
             anchor="        if stop is not None:\n            return stop\n",
             replacement="        if stop is not None:\n            continue\n",
             target=_T, keyword=_K, tags=_TAG),
    Mutation(id="M1845-03", phase=1845,
             description="the rule's comparator is ignored: a sum exactly at the limit passes 'below 10%'",
             path=_SUM,
             anchor='    ok = dc._hold(rule["op"], percent, float(rule["percent"]), dc._OPS)\n',
             replacement='    ok = dc._hold("<=", percent, float(rule["percent"]), dc._OPS)\n',
             target=_T, keyword=_K, tags=_TAG),
    Mutation(id="M1845-04", phase=1845,
             description="a part stated as a percentage of the set pressure is read as a pressure",
             path=_SUM,
             anchor="    if dc._is_percent(fact):\n",
             replacement="    if False:\n",
             target=_T, keyword=_K, tags=_TAG),
    Mutation(id="M1845-05", phase=1845,
             description="datasheet_checks no longer sends the sum kind to datasheet_sum",
             path=APP / "datasheet_checks.py",
             anchor='    if kind in ("calc", "sum_percent_of"):  # R13; a sum: datasheet_sum.sum_percent_of\n',
             replacement='    if kind == "calc":  # R13; a sum: datasheet_sum.sum_percent_of\n',
             target=_T, keyword=_K, tags=_TAG),
)
