"""Backlog 243.4b (PR 1351): a gross mismatch in a trailing "gpm" bracket is refused like "USGPM".
Unit reading feeds the unit checks and the comparison, so it is guarded like them (rule 6).
Ids M1351-01 onwards, phase 1351."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_243_gpm_cross_check.py"
_TAGS = ("honesty", "o243")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1351-01",
        phase=1351,
        description="a bare gpm bracket is no longer cross-checked, so '24.8 m3/h (30 gpm)' reads unchecked again",
        path=APP / "dual_unit_form.py",
        anchor="        u2 = _CHECKED_AS.get(_fold(u2), u2)\n",
        replacement="        u2 = u2\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1351-02",
        phase=1351,
        description="the gpm cross-check also reads the interleaved form, where its 2% check would refuse real imperial values",
        path=APP / "dual_unit_form.py",
        anchor="    if not interleaved:\n        u2 = _CHECKED_AS.get(_fold(u2), u2)\n",
        replacement="    u2 = _CHECKED_AS.get(_fold(u2), u2)\n",
        target=_T,
        tags=_TAGS,
    ),
)
