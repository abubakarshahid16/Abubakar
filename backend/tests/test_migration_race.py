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
