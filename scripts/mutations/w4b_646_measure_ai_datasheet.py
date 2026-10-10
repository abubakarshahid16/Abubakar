"""#646: the AI datasheet measuring tool counts honestly and never runs on the
live database. M5601 onward."""
from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_w4b_646_measure_script.py"
_F = REPO / "scripts" / "measure_ai_datasheet.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M5601", phase=5601, description="an AI reading's figure is not read by code, so it can never pair",
             path=_F, anchor='            "raw_value": figures[0]["value"] if figures else None,\n',
             replacement='            "raw_value": None,\n',
             target=_T, keyword="ai_read_figure", tags=("honesty",)),
    Mutation(id="M5602", phase=5602, description="a blank field is counted as a paired value",
             path=_F, anchor='        elif fact.get("is_blank"):\n', replacement='        elif False:\n',
             target=_T, keyword="counts_once", tags=("honesty", "critical")),
    Mutation(id="M5603", phase=5603, description="prose is counted as a value requirement with no field",
             path=_F, anchor="        if not comparison.is_matchable(r):\n            out[",
             replacement="        if False:\n            out[",
             target=_T, keyword="counts_once", tags=("honesty",)),
    Mutation(id="M5604", phase=5604, description="the tool runs on a live-shaped database path",
             path=_F, anchor="    if live_guard.is_live_shaped(path):\n", replacement="    if False:\n",
             target=_T, keyword="live_shaped", tags=("safety", "critical")),
)
