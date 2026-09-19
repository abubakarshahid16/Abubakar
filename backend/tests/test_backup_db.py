"""The backup captures the WAL, stands alone, and survives a live writer."""
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from backup_db import backup, verify  # noqa: E402


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
