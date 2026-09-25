"""Mutations of `backend/app/db.py`."""

from __future__ import annotations

from ._base import APP, DUPLICATE_GUARD, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_1 -----------------------------------------------------
    Mutation(
        id="M6", phase=1,
        description="remove the document_classification column migration",
        path=APP / "db.py",
        anchor="    if classification_cols:\n        for _column in (",
        replacement="    if False:\n        for _column in (",
        target="tests/test_submittal_review_foundation.py",
        keyword="existing_documents_remain_readable or equipment_tags",
        tags=("migration",),
    ),
    # ---- from MIGRATION_RACE ----------------------------------------------
    #: The check-then-ALTER race that every ensure_schema carried.
    Mutation(
        id="M196", phase=15,
        description="NEVER SWALLOW THE DUPLICATE COLUMN, restoring the race "
                    "that killed one request in three when two threads "
                    "migrated the same database at once",
        path=APP / "db.py",
        anchor=DUPLICATE_GUARD,
        replacement="        if True:\n            raise",
        target="tests/test_migration_race.py",
        keyword="two_threads_can_migrate",
        tags=("critical",),
    ),
    # M197 WAS WITHDRAWN, NOT SOLVED. It removed the message test - swallow
    # EVERY OperationalError, not just the duplicate - and no test could see
    # it, because the check that follows catches the same cases: an unrelated
    # error means the ALTER did not happen, so the column is still missing and
    # `if column not in columns_of(...)` re-raises. The message test is kept
    # because it states WHICH failure is expected and keeps the swallow
    # narrow, but it changes no output today and an assertion claiming
    # otherwise would be the vacuous kind. Third instance of this shape; see
    # entry 39 of docs/status-honesty-audit.md.
    Mutation(
        id="M198", phase=15,
        description="ALTER a table that does not exist, inventing a shape "
                    "whose creator never agreed to it",
        path=APP / "db.py",
        anchor="    if not existing or column in existing:",
        replacement="    if column in existing:",
        target="tests/test_migration_race.py",
        keyword="missing_table_is_not_this_functions_business",
    ),
    # ---- from DISCIPLINE_CANONICAL ----------------------------------------
    #: The discipline overlay: one canonical value, the raw one kept intact.
    # M243 AS FIRST WRITTEN WAS WITHDRAWN, and the reason is kept here.
    # It deleted `discipline_canonical TEXT,` from the CREATE TABLE and was
    # NOT DETECTED - correctly. On a fresh database the migration loop adds
    # the column too, so the two creators are redundant and deleting either
    # one alone changes nothing observable (audit entry 39: first ask whether
    # the OUTPUT can distinguish the versions at all). It now targets the one
    # creator that CAN be observed: the migration, on an old-shape database.
    Mutation(
        id="M243", phase=21,
        description="drop the MIGRATION, so a database that predates the "
                    "column never gains it and every classification write fails",
        path=APP / "db.py",
        anchor='            "discipline_canonical",\n',
        replacement="",
        target="tests/test_discipline_canonical.py",
        keyword="existing_database_gains_the_column_through_the_migration",
        tags=("critical",),
    ),
)
