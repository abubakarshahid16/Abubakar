"""Two requests reaching the same migration at the same moment.

THE DEFECT, CAUGHT IN THE SUITE AND THEN MEASURED. Every `ensure_schema`
migrates with check-then-ALTER, and every one of them is called from ordinary
read paths - `submittal_review.ensure_schema` alone from twenty-one. Two
threads both read `PRAGMA table_info`, both see a column missing, both issue
the `ALTER`, and the loser dies:

    sqlite3.OperationalError: duplicate column name: raw_value

`tests/test_access_routes.py` failed **3 runs in 10** on exactly that, on a
tree that was otherwise green - so a passing suite was never evidence the race
was absent, only that it had not fired that time.

WHY THIS TEST IS SHAPED THIS WAY. A race needs both threads inside the window
together, so they wait on a `Barrier` and start the migration in the same
instant, and the whole thing repeats: one attempt proves nothing about a
failure that appeared three times in ten. Run against the unfixed code these
tests fail almost every time; the mutation in `scripts/mutation_check.py`
(M196) is what keeps that true.

The fix is `db.add_column_if_missing`: the duplicate error is caught, the
column is re-read to confirm it really is there, and only then is the failure
treated as benign.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from app import db, deliverables, review, submittal_review
from app.config import settings

#: Enough repetitions that a failure appearing 3 times in 10 would be seen
#: many times over. Each round is a fresh database, so every round re-runs
#: every ALTER rather than finding the work already done.
ROUNDS = 12


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "race.sqlite")
    db.reset_connection()
    yield tmp_path
    db.reset_connection()


def _race(target, rounds: int, threads: int = 2) -> list[BaseException]:
    """Run `target` from `threads` threads at once, `rounds` times."""
    failures: list[BaseException] = []
    for round_number in range(rounds):
        settings.db_path = settings.data_dir / f"race-{round_number}.sqlite"
        db.reset_connection()
        db.init_db()
        db.reset_connection()
        barrier = threading.Barrier(threads)
        lock = threading.Lock()

        def worker():
            # EVERY THREAD GETS ITS OWN CONNECTION, which is what `db.connect`
            # gives a thread anyway. Sharing one would serialise the two and
            # the race could not happen.
            db.reset_connection()
            try:
                barrier.wait(timeout=30)
                target()
            except BaseException as exc:  # noqa: BLE001 - recorded, not raised
                with lock:
                    failures.append(exc)

        workers = [threading.Thread(target=worker) for _ in range(threads)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(timeout=60)
    return failures


@pytest.mark.parametrize("name,migrate", [
    ("submittal_review", submittal_review.ensure_schema),
    ("review", review.ensure_schema),
    ("deliverables", deliverables.ensure_schema),
])
def test_two_threads_can_migrate_the_same_database(fresh_db, name, migrate):
    """THE ONE THAT FAILED IN PRODUCTION CODE.

    `submittal_review` is where the suite caught it; `review` and
    `deliverables` carry the same shape and are reached from the same kind of
    read path, so all three are proved rather than the one that happened to
    be observed.
    """
    failures = _race(migrate, ROUNDS)

    assert not failures, (
        f"{name}.ensure_schema is not safe against a concurrent migrator: "
        f"{len(failures)} of {ROUNDS * 2} calls raised, first was "
        f"{failures[0]!r}")


def test_the_columns_really_are_there_after_a_race(fresh_db):
    """A SWALLOWED ERROR MUST NOT MEAN A MISSING COLUMN.

    Catching `duplicate column name` is only safe if the column is genuinely
    present afterwards. An except branch that swallowed the error without
    checking would turn a loud crash into a schema quietly short of a column,
    which is the worse failure because nothing reports it.
    """
    _race(submittal_review.ensure_schema, 3)

    columns = db.columns_of(db.connect(), "submittal_facts")
    for required in ("raw_value", "raw_unit", "value_min", "value_max",
                     "is_blank", "unit_reference"):
        assert required in columns, f"{required} is missing after the race"


def test_the_helper_is_idempotent_on_its_own():
    """Called twice it adds once, and says so. The return value is what a
    caller uses to tell "I added it" from "it was already there"."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id TEXT)")

    assert db.add_column_if_missing(conn, "t", "extra", "TEXT") is True
    assert db.add_column_if_missing(conn, "t", "extra", "TEXT") is False
    assert db.columns_of(conn, "t") == {"id", "extra"}


def test_a_missing_table_is_not_this_functions_business():
    """Whoever creates a table owns its shape. Adding a column to a table
    that does not exist is a different error and is not silently invented."""
    conn = sqlite3.connect(":memory:")

    assert db.add_column_if_missing(conn, "nope", "extra", "TEXT") is False


def test_an_unrelated_operational_error_still_raises():
    """ONLY THE DUPLICATE IS SWALLOWED. A syntax error in a definition is a
    bug in the migration and must be loud, not absorbed by the guard that
    exists for a different problem."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id TEXT)")

    with pytest.raises(sqlite3.OperationalError):
        db.add_column_if_missing(conn, "t", "extra", "NOT A REAL TYPE(")


class _SchemaChangedOnce:
    """A connection whose first ALTER fails as SQLite fails it when another
    connection changed the schema between prepare and step."""

    def __init__(self, conn, failures: int = 1):
        self._conn, self.failures = conn, failures

    def execute(self, sql, *args):
        if sql.startswith("ALTER TABLE") and self.failures:
            self.failures -= 1
            raise sqlite3.OperationalError("database schema has changed")
        return self._conn.execute(sql, *args)


def test_a_schema_changed_answer_is_retried_not_raised(fresh_db):
    """THE MUTATION TARGET (M1055). Seen once in CI (2026-09-26): the race's
    loser can be told "database schema has changed" rather than "duplicate
    column". It re-reads and retries; the column ends up there."""
    db.init_db()
    conn = db.connect()
    conn.execute("CREATE TABLE t_race (id TEXT)")
    assert db.add_column_if_missing(_SchemaChangedOnce(conn), "t_race", "extra", "TEXT") is True
    assert "extra" in db.columns_of(conn, "t_race")


def test_a_schema_that_never_settles_still_fails_loudly(fresh_db):
    """Bounded: a schema that keeps changing is an error, never a silent pass."""
    db.init_db()
    conn = db.connect()
    conn.execute("CREATE TABLE t_race2 (id TEXT)")
    with pytest.raises(sqlite3.OperationalError, match="kept changing"):
        db.add_column_if_missing(_SchemaChangedOnce(conn, failures=99), "t_race2", "extra", "TEXT")
    assert "extra" not in db.columns_of(conn, "t_race2")


class _SchemaVersionChangedOnce:
    """A connection whose first PRAGMA schema_version read fails as SQLite
    fails it when another connection's ALTER lands between this statement's
    prepare and its step."""

    def __init__(self, conn, failures: int = 1):
        self._conn, self.failures = conn, failures

    def execute(self, sql, *args):
        if sql.startswith("PRAGMA schema_version") and self.failures:
            self.failures -= 1
            raise sqlite3.OperationalError("database schema has changed")
        return self._conn.execute(sql, *args)


def test_schema_version_itself_is_retried_not_raised(fresh_db):
    """THE MUTATION TARGET (M1056). Found 2026-09-28: `schema_once` reads
    `db._schema_version` around every migration it memoises, at a call site
    `add_column_if_missing`'s own retry does not cover - the exact race
    M1055 already fixed, at a new call site. `test_two_threads_can_migrate_
    the_same_database` and `test_access_routes` both failed on this in CI
    before the fix."""
    db.init_db()
    conn = db.connect()
    assert db._schema_version(_SchemaVersionChangedOnce(conn)) == db._schema_version(conn)


def test_schema_version_that_never_settles_still_fails_loudly(fresh_db):
    """Bounded here too: never an infinite retry, never a silent wrong answer."""
    db.init_db()
    conn = db.connect()
    with pytest.raises(sqlite3.OperationalError, match="kept changing"):
        db._schema_version(_SchemaVersionChangedOnce(conn, failures=99))



# ---------------------------------------------------------------------------
# ISSUE #325: ONE MIGRATOR AT A TIME, AND A WHOLE-MIGRATION RETRY.
#
# Each retry above guards ONE statement, and the race kept moving to the next
# one: on 2026-09-29 CI failed on a plain `CREATE TABLE IF NOT EXISTS` inside
# `review.ensure_schema` (1, then 2, of 24 calls). Reproduced here with
# `sys.setswitchinterval(1e-6)` and 150 rounds: 1 failure in 300 calls, three
# runs out of three, on main. With the lock: 0 in 1,500. The two tests below
# pin the two halves of the fix deterministically, because the race itself
# only fires under a scheduler that interleaves at the wrong instant.


def test_only_one_thread_runs_a_migration_and_the_second_finds_it_done(fresh_db):
    """Two threads miss the memo together. Without the lock both run the
    migration at the same time - exactly the concurrent DDL that makes SQLite
    answer 'schema has changed'. With it, one runs and the other, re-checking
    under the lock, finds the work done and runs nothing."""
    import time

    db.init_db()
    db.reset_schema_memo()
    state = {"active": 0, "most": 0, "runs": 0}
    guard = threading.Lock()

    @db.schema_once
    def migrate():
        with guard:
            state["active"] += 1
            state["runs"] += 1
            state["most"] = max(state["most"], state["active"])
        time.sleep(0.2)
        db.connect().execute("CREATE TABLE IF NOT EXISTS t_once (id TEXT)")
        with guard:
            state["active"] -= 1

    failures = _race(migrate, rounds=1)

    assert not failures
    assert state["most"] == 1, "two threads ran the same migration at once"
    assert state["runs"] == 1, "the second thread re-ran a migration already done"


def test_schema_changed_from_any_statement_reruns_the_whole_migration(fresh_db):
    """Not only the ALTER: any statement in a migration can be told the schema
    changed (a second PROCESS is not stopped by the lock). The migration is
    idempotent, so it is run again - bounded, and never swallowed."""
    db.init_db()
    db.reset_schema_memo()
    calls = {"n": 0}

    @db.schema_once
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database schema has changed")
        db.connect().execute("CREATE TABLE IF NOT EXISTS t_rerun (id TEXT)")
        return "done"

    assert flaky() == "done"
    assert calls["n"] == 2
    assert "id" in db.columns_of(db.connect(), "t_rerun")


def test_a_migration_whose_schema_never_settles_fails_loudly(fresh_db):
    db.init_db()
    db.reset_schema_memo()

    @db.schema_once
    def never():
        raise sqlite3.OperationalError("database schema has changed")

    with pytest.raises(sqlite3.OperationalError, match="kept changing while running"):
        never()


def test_other_migration_errors_are_not_retried(fresh_db):
    db.init_db()
    db.reset_schema_memo()
    calls = {"n": 0}

    @db.schema_once
    def broken():
        calls["n"] += 1
        raise sqlite3.OperationalError("near \"TABEL\": syntax error")

    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        broken()
    assert calls["n"] == 1
