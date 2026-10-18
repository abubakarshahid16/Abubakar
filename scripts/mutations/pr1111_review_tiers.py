"""PR #1111 (order 95 piece 1): the CRS-first screen's tiers. A wrong tier puts
an unsure row out of the engineer's sight. backend/tests/test_95_run_summary.py
must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "review_tiers.py"
_T = "tests/test_95_run_summary.py"
_TAG = ("pr1111", "review_tiers")


def _m(n, desc, anchor, repl, kw):
    return Mutation(id=f"M1111-{n:02d}", phase=1111, description=desc, path=_P,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(1, "a finding with no verdict or an unknown status reads as met",
       '    return _STATUS.get(status or "", (NEEDS_YOU, "no verdict"))\n',
       '    return _STATUS.get(status or "", (MET, "meets"))\n', "unknown_status"),
    _m(2, "an unconfirmed AI finding is shown as a decided comment",
       "    if finding.get(\"origin\") in _AI_ORIGINS and not confirmed:\n",
       "    if False:\n", "ai_finding_is_a_guess"),
    _m(3, "a removed finding stays on the screen as a row",
       "    if finding.get(\"approval_status\") == \"rejected\":\n",
       "    if False:\n", "removed"),
    _m(4, "a held (unproven) rule's verdict is shown as decided",
       "    if finding.get(\"trust_label\") == \"UNPROVEN\":\n",
       "    if False:\n", "held_rule"),
    _m(5, "an engineer-review finding becomes a comment nobody is asked about",
       '        return NEEDS_YOU, _NEEDS_REVIEW_WORD.get(code or "", "engineer check")\n',
       '        return COMMENT, _NEEDS_REVIEW_WORD.get(code or "", "engineer check")\n',
       "each_status"),
    _m(6, "an unticked safety result is shown as met",
       "    if finding.get(\"show_for_engineer_tick\") and not confirmed:\n",
       "    if False:\n", "held_rule"),
)
