"""Order 261.2 (PR 1393): a degraded AI reading holds every checklist pass. M1393-01 onward."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_261_degraded_read.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1393-01",
        phase=1393,
        description="a read where most answers were refused is not called degraded",
        path=APP / "degraded_read.py",
        anchor="    if refused > agreed:\n",
        replacement="    if refused > agreed + 10_000:\n",
        target=_T,
        keyword="refused_than_agreed or whole_review or broken_read",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-02",
        phase=1393,
        description="a page that timed out does not make the read degraded",
        path=APP / "degraded_read.py",
        anchor="    if timed_out:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="timeout",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-03",
        phase=1393,
        description="a degraded read holds no checklist pass",
        path=APP / "degraded_read.py",
        anchor='        if r["status"] == "COMPLIANT" and r.get("checklist"):\n',
        replacement="        if False:\n",
        target=_T,
        keyword="broken_read or only_checklist or whole_review",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-04",
        phase=1393,
        description="a degraded read also rewrites a failure or a missing value as a hold",
        path=APP / "degraded_read.py",
        anchor='        if r["status"] == "COMPLIANT" and r.get("checklist"):\n',
        replacement='        if r.get("checklist"):\n',
        target=_T,
        keyword="only_checklist",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-05",
        phase=1393,
        description="the stored checklist results skip the degraded-read hold",
        path=APP / "datasheet_checks.py",
        anchor=(
            "    for r in (x for x in degraded_read.hold(results, submittal_id)"
            ' if x["status"] not in (NOT_APPLICABLE, NOT_CALCULATED)'
        ),
        replacement=(
            "    for r in (x for x in results"
            ' if x["status"] not in (NOT_APPLICABLE, NOT_CALCULATED)'
        ),
        target=_T,
        keyword="whole_review",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-06",
        phase=1393,
        description="the run does not record that the read was degraded",
        path=APP / "comparison.py",
        anchor="    split = degraded_read.with_reader(split, submittal_id)\n",
        replacement="    split = split\n",
        target=_T,
        keyword="whole_review",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-07",
        phase=1393,
        description="the CRS banner does not mention a degraded read",
        path=APP / "absence.py",
        anchor="    if degraded:  # order 261.2: a degraded AI read is a part that could not be trusted\n",
        replacement="    if False:\n",
        target=_T,
        keyword="banner",
        tags=_TAGS,
    ),
)
