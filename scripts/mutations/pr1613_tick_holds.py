"""Owner on #1584 / PR 1613, the review code waits for the engineer's tick: each entry undoes one
decision of the code's one hold and of what a tick does to a stored code."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_tick_holds_code.py"
_TAG = ("pr1613", "tick_holds_code")
_R = APP / "rule_trust.py"
_C = APP / "tick_code.py"


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(
        id=f"M1613-{n:02d}",
        phase=1613,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "only the owner's label holds, with the switch on",
        _R,
        '        if (every_label or f.get("trust_label") == OWNER_APPROVED)\n',
        '        if f.get("trust_label") == OWNER_APPROVED\n',
        "any_label",
    ),
    _m(
        2,
        "the switch is ignored: every label holds with it off",
        _R,
        "    every_label = settings.tick_holds_review_code_enabled\n",
        "    every_label = True\n",
        "switch_off_an_open_tick",
    ),
    _m(
        3,
        "a ticked row still holds the code",
        _R,
        "        and not tick_done(f)\n",
        "",
        "all_ticked",
    ),
    _m(
        4,
        "an open tick overrides a proven breach",
        _R,
        '    if not still_open or result["code"] not in (codes[0], codes[1]):\n',
        "    if not still_open:\n",
        "breach_stays_rejected",
    ),
    _m(
        5,
        "a tick rewrites the recommendation beside an engineer's final code",
        _C,
        '        if run is None or run["engineer_final_code"] or run["status"] != "completed":\n',
        '        if run is None or run["status"] != "completed":\n',
        "typed_final_code",
    ),
    _m(
        6,
        "a tick touches the stored code with the switch off",
        _C,
        "        not settings.tick_holds_review_code_enabled\n        or not finding\n",
        "        not finding\n",
        "switch_off_a_tick",
    ),
    _m(
        7,
        "a change to any row works the code out again",
        _C,
        '        or not finding.get("show_for_engineer_tick")\n',
        "",
        "another_row",
    ),
    _m(
        8,
        "a tick leaving others open still rewrites the dated reason",
        _C,
        '        if result["code"] == before:\n            return None\n',
        "",
        "last_tick",
    ),
    _m(
        9,
        "the code does not change after the last tick",
        _C,
        "    after_change(finding, actor_user_id)\n",
        "",
        "last_tick",
    ),
    _m(
        11,
        "the read and the write are not one transaction",
        _C,
        '        conn.execute("BEGIN IMMEDIATE")\n',
        "",
        "one_transaction",
    ),
    _m(
        12,
        "a run being redone is written over",
        _C,
        '        if run is None or run["engineer_final_code"] or run["status"] != "completed":\n',
        '        if run is None or run["engineer_final_code"]:\n',
        "being_redone",
    ),
    _m(
        13,
        "a rejection after a tick still reads as a tick",
        APP / "crs_decider.py",
        '    if finding.get("engineer_comment") or finding.get("approval_status") == "rejected":\n',
        '    if finding.get("engineer_comment"):\n',
        "tick_then_reject",
    ),
    _m(
        10,
        "the stored gate is forgotten when the code is worked out again",
        _C,
        '            outcome.get("completeness") or {},\n',
        '            {"sufficient": True, "extraction_coverage": 1.0},\n',
        "stored_inputs_reach",
    ),
)
