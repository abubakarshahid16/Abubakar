from __future__ import annotations

from ._base import APP, Mutation

TARGET = "tests/test_279_one_row_per_missing_value.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1433-01",
        phase=1433,
        description="a comparison whose own field is missing is asked for again: the fold is never applied",
        path=APP / "datasheet_checks.py",
        anchor="out = checklist_fold.fold_into_stated(out, checklist)",
        replacement="out = out",
        target=TARGET,
        keyword="folds_into_the_is_stated",
        tags=("honesty",),
    ),
    Mutation(
        id="M1433-02",
        phase=1433,
        description="the fold forgets the tag: a value missing for one valve is not folded for the other that misses it",
        path=APP / "checklist_fold.py",
        anchor='asked.setdefault((r["equipment_tag"], r["role"]), r["rule_id"])',
        replacement='asked.setdefault((None, r["role"]), r["rule_id"])',
        target=TARGET,
        keyword="per_tag",
        tags=("honesty",),
    ),
    Mutation(
        id="M1433-03",
        phase=1433,
        description="the is-stated item folds into itself: the one row the CRS keeps disappears",
        path=APP / "checklist_fold.py",
        anchor='and kind.get(r["rule_id"]) not in (None, "required")',
        replacement="and True",
        target=TARGET,
        keyword="folds_into_the_is_stated",
        tags=("honesty",),
    ),
    Mutation(
        id="M1433-04",
        phase=1433,
        description="a comparison that is not missing (an unclear question) is folded away and its row lost",
        path=APP / "checklist_fold.py",
        anchor='and r["status"] == MISSING\n            and kind',
        replacement="and kind",
        target=TARGET,
        keyword="keeps_its_status_and_row",
        tags=("honesty",),
    ),
)
