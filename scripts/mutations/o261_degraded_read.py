"""Order 261.2 (PR 1393): a failed AI reading holds the passes of the fields it did not read.
M1393-01 onward."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_261_degraded_read.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1393-01",
        phase=1393,
        description="a page with an unusable engine answer does not flag the read",
        path=APP / "degraded_read.py",
        anchor="    if failed:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="banner",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-02",
        phase=1393,
        description="a page that timed out does not flag the read",
        path=APP / "degraded_read.py",
        anchor="    if timed_out:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="banner",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-03",
        phase=1393,
        description="a checklist pass on a field the AI did not read is not held",
        path=APP / "degraded_read.py",
        anchor='            and r.get("role") in missing\n',
        replacement="            and False\n",
        target=_T,
        keyword="fields_whose_ai or fewer_meets or whole_review or broken_read",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-04",
        phase=1393,
        description="a degraded read holds the passes of fields the AI DID read too",
        path=APP / "degraded_read.py",
        anchor='            and r.get("role") in missing\n',
        replacement="            and True\n",
        target=_T,
        keyword="fields_whose_ai",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-05",
        phase=1393,
        description="a failed quote or value check counts as a missing AI reading",
        path=APP / "degraded_read.py",
        anchor="        if reason in ERROR_REASONS:\n",
        replacement="        if reason:\n",
        target=_T,
        keyword="many_gate_refusals",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-06",
        phase=1393,
        description="the stored checklist results skip the missing-reading hold",
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
        id="M1393-07",
        phase=1393,
        description="the run does not record that the read looked incomplete",
        path=APP / "comparison.py",
        anchor="    split = degraded_read.with_reader(split, submittal_id)\n",
        replacement="    split = split\n",
        target=_T,
        keyword="whole_review",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-08",
        phase=1393,
        description="the CRS banner does not mention a page the AI could not read",
        path=APP / "absence.py",
        anchor="    if degraded and degraded_read.is_part(degraded):",
        replacement="    if False:",
        target=_T,
        keyword="banner",
        tags=_TAGS,
    ),
    Mutation(
        id="M1393-09",
        phase=1393,
        description="a low agreed share alone puts REVIEW INCOMPLETE on the sheet",
        path=APP / "degraded_read.py",
        anchor='    return any(\n        w in ("failed_pages", "timed_out", "stopped", "unavailable")\n        for w in record["why"]\n    )\n',
        replacement="    return True\n",
        target=_T,
        keyword="banner",
        tags=_TAGS,
    ),
)
