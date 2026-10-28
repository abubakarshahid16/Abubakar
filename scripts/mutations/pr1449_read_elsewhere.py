from __future__ import annotations

from ._base import APP, Mutation

TARGET = "tests/test_307_read_elsewhere.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1449-01",
        phase=1449,
        description="the pass is never applied: a value read for other tags is still reported as not read",
        path=APP / "datasheet_checks.py",
        anchor="results = read_elsewhere.soften(results)",
        replacement="results = results",
        target=TARGET,
        keyword="stored_finding_says",
        tags=("honesty",),
    ),
    Mutation(
        id="M1449-02",
        phase=1449,
        description="a placeholder on another tag counts as a value that was read",
        path=APP / "read_elsewhere.py",
        anchor='and r["status"] in _READ',
        replacement='and r["status"] != "X"',
        target=TARGET,
        keyword="placeholder_on_the_other_tag",
        tags=("honesty",),
    ),
    Mutation(
        id="M1449-03",
        phase=1449,
        description="a reader-gap row (its own words, no fact) is rewritten as well as a missing one",
        path=APP / "read_elsewhere.py",
        anchor='and r["status"] == MISSING',
        replacement='and r["status"] != "X"',
        target=TARGET,
        keyword="only_a_missing_row",
        tags=("honesty",),
    ),
    Mutation(
        id="M1449-04",
        phase=1449,
        description="a field missing on every tag is softened as if it had been read",
        path=APP / "read_elsewhere.py",
        anchor='pages = sorted(pages_by_role.get(r.get("role"), ()))',
        replacement="pages = [1]",
        target=TARGET,
        keyword="missing_on_every_tag",
        tags=("honesty",),
    ),
    Mutation(
        id="M1449-05",
        phase=1449,
        description="the mandatory-field check's MISSING result is rewritten as well as a checklist row",
        path=APP / "read_elsewhere.py",
        anchor='            pages\n            and r.get("checklist")\n            and r["status"] == MISSING',
        replacement='            pages\n            and r["status"] == MISSING',
        target=TARGET,
        keyword="not_a_checklist_item",
        tags=("honesty",),
    ),
)
