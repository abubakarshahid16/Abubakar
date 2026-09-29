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
    Mutation(id="M1362", phase=1362, description="migrations run without the process lock (issue #325)",
             path=APP / "db.py",
             anchor="        with _migration_lock:\n",
             replacement="        if True:\n",
             target="tests/test_migration_race.py", keyword="only_one_thread_runs_a_migration",
             tags=("reliability",)),
    Mutation(id="M1363", phase=1362, description="the memo is not re-checked under the migration lock",
             path=APP / "db.py",
             anchor="            if _schema_memo.get(key) == _schema_version(conn):\n                return None\n            result",
             replacement="            result",
             target="tests/test_migration_race.py", keyword="only_one_thread_runs_a_migration",
             tags=("reliability",)),
    Mutation(id="M1364", phase=1362, description="'schema has changed' from any migration statement is raised, not re-run",
             path=APP / "db.py",
             anchor='            if "schema has changed" not in str(exc).lower():\n                raise\n            last = exc\n',
             replacement="            raise\n",
             target="tests/test_migration_race.py", keyword="reruns_the_whole_migration",
             tags=("reliability",)),
    Mutation(id="M1365", phase=1362, description="the whole-migration retry swallows every OperationalError",
             path=APP / "db.py",
             anchor='            if "schema has changed" not in str(exc).lower():\n                raise\n            last = exc\n',
             replacement="            last = exc\n",
             target="tests/test_migration_race.py", keyword="other_migration_errors_are_not_retried",
             tags=("reliability",)),
)
