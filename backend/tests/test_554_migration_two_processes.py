"""#554: two PROCESSES migrating one fresh database at the same moment.

WHAT WAS MISSING. #332/#334 closed the race between threads in one process
(`db._migration_lock`, `SchemaRetryConnection`, `_run_migration`), and
`test_migration_race.py` proves it with threads. The issue's criterion is two
processes on a fresh database - the server and a script beside it - which a
thread lock cannot cover; nothing tested it.

THE SHAPE. Each round makes a fresh database file. Two Python processes are
started, wait for a start file so they migrate in the same instant, then run
`db.init_db()` and the heaviest `ensure_schema`s. Both must exit 0, and the
schema they leave must equal the schema one process alone produces.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUNDS = 8
PROCESSES = 3

CHILD = r"""
import sys, time
from pathlib import Path
from app.config import settings
from app import db
settings.db_path = Path(sys.argv[1])
settings.data_dir = Path(sys.argv[1]).parent
go = Path(sys.argv[2])
while not go.exists():
    time.sleep(0.005)
db.init_db()
from app import deliverables, review, submittal_review, risks
for module in (review, submittal_review, deliverables, risks):
    module.ensure_schema()
db.reset_connection()
"""


def _schema(path: Path) -> list[tuple]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return [(t, tuple(r[1] for r in con.execute(f'PRAGMA table_info("{t}")'))) for t in tables]
    finally:
        con.close()


def _start(db_path: Path, go: Path) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(BACKEND), os.environ.get("PYTHONPATH", "")])}
    return subprocess.Popen([sys.executable, "-c", CHILD, str(db_path), str(go)],
                            cwd=BACKEND, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _run(db_path: Path, processes: int) -> list[tuple[int, str]]:
    go = db_path.with_suffix(".go")
    children = [_start(db_path, go) for _ in range(processes)]
    time.sleep(1.0)   # every child imported the app and is waiting
    go.touch()
    out = []
    for child in children:
        _stdout, stderr = child.communicate(timeout=120)
        out.append((child.returncode, stderr[-2000:]))
    return out


def test_two_processes_migrating_a_fresh_database_both_succeed(tmp_path):
    reference = tmp_path / "alone.sqlite"
    [(code, err)] = _run(reference, 1)
    assert code == 0, err
    expected = _schema(reference)
    assert len(expected) > 20, "the reference schema is too small to compare against"

    for round_number in range(ROUNDS):
        path = tmp_path / f"pair-{round_number}.sqlite"
        results = _run(path, PROCESSES)
        failed = [err for code, err in results if code != 0]
        assert not failed, f"round {round_number}: a process failed:\n" + "\n---\n".join(failed)
        assert _schema(path) == expected, f"round {round_number}: the schema differs from one process alone"
