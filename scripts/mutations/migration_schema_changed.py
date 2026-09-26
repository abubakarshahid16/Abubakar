"""A migration race's loser told "database schema has changed" (CI, 2026-09-26)."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1055", phase=87, description="a 'schema has changed' answer during a migration is raised, not retried",
             path=APP / "db.py",
             anchor='            if "schema has changed" in message:\n                continue\n',
             replacement="",
             target="tests/test_migration_race.py", keyword="schema_changed_answer_is_retried",
             tags=("reliability",)),
)
