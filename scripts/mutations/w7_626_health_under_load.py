"""#626: the health-under-load measuring tool. M5961 onward."""
from __future__ import annotations

from ._base import REPO, Mutation

_T = "tests/test_w7_626_health_under_load_tool.py"
_F = REPO / "scripts" / "measure_health_under_load.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M5961", phase=5961, description="a failed health call is timed as a success",
             path=_F, anchor="        if status == 200:\n", replacement="        if True:\n",
             target=_T, keyword="failed_call_is_counted", tags=("honesty", "critical")),
    Mutation(id="M5962", phase=5962, description="a job that failed is reported as fine",
             path=_F, anchor='            failed.append(type(exc).__name__)\n', replacement="            pass\n",
             target=_T, keyword="failed_call_is_counted", tags=("honesty",)),
    Mutation(id="M5963", phase=5963, description="the slowest call is left out of the summary",
             path=_F, anchor='"p95_s": round(p95, 4), "max_s": round(ordered[-1], 4)}',
             replacement='"p95_s": round(p95, 4), "max_s": round(ordered[-2 if len(ordered) > 1 else -1], 4)}',
             target=_T, keyword="median_p95", tags=("honesty",)),
    Mutation(id="M5964", phase=5964, description="the tool runs on a live-shaped database path",
             path=_F, anchor="    if live_guard.is_live_shaped(path):\n", replacement="    if False:\n",
             target=_T, keyword="live_shaped", tags=("safety", "critical")),
)
