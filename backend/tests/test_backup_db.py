"""The backup captures the WAL, stands alone, and survives a live writer."""
import datetime
import pathlib
import sqlite3
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import backup_db
from backup_db import backup, verify


def test_backup_captures_rows_still_sitting_in_the_wal(tmp_path):
    live = str(tmp_path / "live.sqlite")
    conn = sqlite3.connect(live)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE docs (id INTEGER)")
    conn.executemany("INSERT INTO docs VALUES (?)",
                     [(i,) for i in range(50)])
    conn.commit()  # committed, but living in -wal rather than the main file
    assert (tmp_path / "live.sqlite-wal").exists(), "precondition: WAL in use"
    out = backup(live, str(tmp_path))
    report = verify(out)
    assert report["ok"] and report["tables"]["docs"] == 50
    conn.close()


def test_backup_is_a_single_self_contained_file(tmp_path):
    """THE TEST THAT CAUGHT THE FIRST VERSION: the copy inherited WAL mode
    and grew its own sidecar, recreating the three-file trap."""
    live = str(tmp_path / "live.sqlite")
    c = sqlite3.connect(live)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    out = backup(live, str(tmp_path))
    assert not pathlib.Path(out + "-wal").exists()
    assert verify(out)["tables"]["t"] == 1
    c.close()


def test_backup_while_a_writer_holds_the_db(tmp_path):
    live = str(tmp_path / "live.sqlite")
    writer = sqlite3.connect(live)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE t (x)")
    writer.execute("INSERT INTO t VALUES (1)")
    writer.commit()
    out = backup(live, str(tmp_path))  # writer connection still open
    assert verify(out)["ok"]
    writer.close()


def test_verify_reports_counts_with_names(tmp_path):
    live = str(tmp_path / "live.sqlite")
    c = sqlite3.connect(live)
    c.execute("CREATE TABLE a (x)")
    c.execute("CREATE TABLE b (x)")
    c.executemany("INSERT INTO a VALUES (?)", [(1,), (2,)])
    c.commit()
    c.close()
    out = backup(live, str(tmp_path))
    assert verify(out)["tables"] == {"a": 2, "b": 0}


# ============================================ found by running it, 2026-09-19
#
# Two ways the first version lost data WITHOUT AN ERROR, both reproduced on
# this machine before they were fixed. For a backup tool, "succeeded" on the
# wrong contents is the worst available failure: the one moment anybody reads
# a backup is the moment the original is already gone.


def test_a_missing_source_is_refused_rather_than_created(tmp_path):
    """A ONE-LETTER TYPO BACKED UP NOTHING AND CALLED IT VERIFIED.
    `sqlite3.connect` CREATES a database at a path that does not exist, so
    `backup("rag_inteligence.sqlite", ...)` made an empty file at the typo,
    copied it, and `verify` reported ok=True with zero tables."""
    typo = tmp_path / "rag_inteligence.sqlite"

    with pytest.raises((FileNotFoundError, sqlite3.OperationalError)):
        backup(str(typo), str(tmp_path))

    assert not typo.exists(), "the backup CREATED the file it was asked to copy"


def test_a_source_with_no_tables_is_refused(tmp_path):
    """An empty database is never what a backup of this system should hold,
    and `integrity_check` passes on an empty file - so `verify`'s ok=True
    cannot be the only guard."""
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()

    with pytest.raises(RuntimeError, match="no tables"):
        backup(str(empty), str(tmp_path))


def test_two_backups_in_the_same_second_never_overwrite_each_other(tmp_path):
    """THE FILENAME HAD ONE-SECOND RESOLUTION, and the second backup opened
    the first's file and wrote over it: A's 10 rows became B's 3. Reproduced
    before it was fixed."""
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    for path, rows in ((a, 10), (b, 3)):
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE t (x)")
        c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
        c.commit()
        c.close()

    out_a = backup(str(a), str(tmp_path))
    out_b = backup(str(b), str(tmp_path))

    assert out_a != out_b
    assert verify(out_a)["tables"]["t"] == 10, "the first backup was overwritten"
    assert verify(out_b)["tables"]["t"] == 3


def _db(path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (x)")
    c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    c.commit()
    c.close()
    return str(path)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Every backup gets the SAME microsecond stamp: the Windows clock tie
    behind B30, made certain instead of left to chance."""
    fixed = datetime.datetime(2026, 9, 22, 12, 0, 0, 123456)
    monkeypatch.setattr(backup_db, "_dt", types.SimpleNamespace(
        datetime=types.SimpleNamespace(now=lambda: fixed)))
    return fixed.strftime("%Y%m%d-%H%M%S-%f")


def test_a_clock_tie_takes_the_next_name_and_every_backup_survives(tmp_path, frozen_clock):
    """B30: a second backup on the same stamp CRASHED with FileExistsError.
    It must take a free name instead, and still overwrite nothing."""
    sources = [_db(tmp_path / f"s{rows}.sqlite", rows) for rows in (10, 3, 7)]
    out = [backup(s, str(tmp_path)) for s in sources]

    assert [pathlib.Path(p).name for p in out] == [
        f"rag_intelligence-{frozen_clock}.sqlite",
        f"rag_intelligence-{frozen_clock}-1.sqlite",
        f"rag_intelligence-{frozen_clock}-2.sqlite",
    ]
    assert [verify(p)["tables"]["t"] for p in out] == [10, 3, 7], \
        "a tied backup was written over"


def test_a_name_already_taken_is_never_written_over(tmp_path, frozen_clock):
    """Whatever already holds the name - here, not even a database - is
    skipped untouched, byte for byte."""
    taken = tmp_path / f"rag_intelligence-{frozen_clock}.sqlite"
    taken.write_bytes(b"someone else's file")

    out = backup(_db(tmp_path / "live.sqlite", 4), str(tmp_path))

    assert taken.read_bytes() == b"someone else's file"
    assert pathlib.Path(out) != taken
    assert verify(out)["tables"]["t"] == 4


def test_running_out_of_names_fails_loudly_rather_than_looping(tmp_path, frozen_clock, monkeypatch):
    monkeypatch.setattr(backup_db, "NAME_ATTEMPTS", 2)
    for name in (f"rag_intelligence-{frozen_clock}.sqlite",
                 f"rag_intelligence-{frozen_clock}-1.sqlite"):
        (tmp_path / name).write_bytes(b"taken")

    with pytest.raises(FileExistsError, match="no free backup name"):
        backup(_db(tmp_path / "live.sqlite", 1), str(tmp_path))
    assert sorted(p.read_bytes() for p in tmp_path.glob("rag_intelligence-*")) \
        == [b"taken", b"taken"]


def test_a_backup_directory_that_does_not_exist_is_refused_by_name(tmp_path):
    """B41. It used to die inside `_reserve_name` with a bare
    FileNotFoundError naming a FILE nobody asked for - at exactly the moment
    a safety backup was being taken, before a destructive change. The refusal
    names the DIRECTORY, and the tool creates nothing on its own."""
    live = _db(tmp_path / "live.sqlite", 5)
    missing = tmp_path / "not_created_yet" / "nested"

    with pytest.raises(FileNotFoundError, match="no backup directory at"):
        backup(live, str(missing))

    assert str(missing) in _refusal(live, missing)
    assert not missing.exists(), "the tool created the directory it refused"


def test_the_refusal_comes_before_the_source_is_opened(tmp_path):
    """No sqlite handle is opened for a backup that is going to be refused:
    the destination is checked first, so nothing leaks on the failure path."""
    live = _db(tmp_path / "live.sqlite", 5)
    opened: list[str] = []
    real = sqlite3.connect

    def watched(*args, **kwargs):
        opened.append(str(args[0]))
        return real(*args, **kwargs)

    import backup_db
    backup_db.sqlite3.connect = watched
    try:
        with pytest.raises(FileNotFoundError):
            backup(live, str(tmp_path / "absent"))
    finally:
        backup_db.sqlite3.connect = real
    assert opened == [], f"a connection was opened before refusing: {opened}"


def _refusal(live: str, missing) -> str:
    try:
        backup(live, str(missing))
    except FileNotFoundError as exc:
        return str(exc)
    raise AssertionError("it did not refuse")


def test_the_source_is_never_written(tmp_path):
    """The live database is opened READ-ONLY. A backup tool holding a write
    handle on the thing it protects is one bug away from damaging it."""
    live = tmp_path / "live.sqlite"
    c = sqlite3.connect(live)
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    before = live.read_bytes()

    backup(str(live), str(tmp_path))

    assert live.read_bytes() == before
