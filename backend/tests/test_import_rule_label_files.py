"""The command-line import of the two label files, with the server stopped (order 12, N3 part B). Invented data only."""

from __future__ import annotations

import importlib.util
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

from app import db, live_guard, rule_equipment
from tests import rule_label_support as s
from tests.test_rule_equipment import row as equipment_row
from tests.test_rule_label_import import _label_file

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("import_rule_label_files", REPO / "scripts" / "import_rule_label_files.py")
cli = importlib.util.module_from_spec(_spec)
sys.modules["import_rule_label_files"] = cli
_spec.loader.exec_module(cli)


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    s.switch(monkeypatch)
    s.patch_pages(monkeypatch)
    monkeypatch.delenv(live_guard.SERVER_ENV, raising=False)
    monkeypatch.setattr(live_guard, "known_live_files", lambda: ())
    live_guard.revoke_all()
    db.reset_connection()
    yield
    live_guard.revoke_all()
    db.reset_connection()


def _setup(tmp_path, monkeypatch, *, db_rel="server.sqlite"):
    data = tmp_path / "data"
    (data / "labels").mkdir(parents=True)
    path = s.make_db(data / db_rel if "/" not in db_rel else _mk(data / db_rel), with_book=True)
    labels = _label_file(tmp_path, monkeypatch, name="x.json")
    (data / "labels" / "rule-labels.json").write_bytes(labels.read_bytes())
    rule_equipment.write_file([equipment_row("r1"), equipment_row("r2"), equipment_row("r3", equip_state="bogus")],
                              data / "labels" / "rule-equipment.json")
    return data, Path(path)


def _mk(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _args(data, path, port, *extra):
    return ["--labels", str(data / "labels" / "rule-labels.json"), "--equipment", str(data / "labels" / "rule-equipment.json"),
            "--db", str(path), "--data-dir", str(data), "--port", str(port), *extra]


def _count(path, table):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


def test_both_files_are_loaded_with_the_routes_counts_and_a_second_run_changes_nothing(tmp_path, monkeypatch, capsys):
    data, path = _setup(tmp_path, monkeypatch)
    args = _args(data, path, _free_port(), "--expect-labels-stored", "2", "--expect-equipment-stored", "2")
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert '"stored": 2' in out and '"refused": 1' in out  # the bogus equipment row is refused, as by the route
    assert _count(path, "rule_label") == 2 and _count(path, "rule_equipment_label") == 2
    events = _count(path, "rule_label_event")
    assert cli.main(args) == 0  # idempotent: nothing duplicated, no new event
    assert _count(path, "rule_label") == 2 and _count(path, "rule_equipment_label") == 2
    assert _count(path, "rule_label_event") == events


def test_the_switch_off_reads_and_writes_nothing(tmp_path, monkeypatch, capsys):
    data, path = _setup(tmp_path, monkeypatch)
    s.switch(monkeypatch, on=False)
    assert cli.main(_args(data, path, _free_port())) == 1
    assert "REFUSED" in capsys.readouterr().out
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert "rule_label" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master")}


def test_a_running_server_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    data, path = _setup(tmp_path, monkeypatch)
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        assert cli.main(_args(data, path, srv.getsockname()[1])) == 1
    assert "stop the server" in capsys.readouterr().out
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert "rule_label" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master")}


def test_a_file_outside_the_data_directory_is_refused_like_the_route(tmp_path, monkeypatch, capsys):
    data, path = _setup(tmp_path, monkeypatch)
    outside = tmp_path / "elsewhere.json"
    outside.write_bytes((data / "labels" / "rule-labels.json").read_bytes())
    argv = _args(data, path, _free_port())
    argv[1] = str(outside)
    assert cli.main(argv) == 1
    assert "outside_the_data_directory" in capsys.readouterr().out
    assert _count(path, "standard_requirements") == 2  # untouched; no label table made


def test_a_wrong_stored_count_is_exit_3_and_the_rows_stay(tmp_path, monkeypatch, capsys):
    data, path = _setup(tmp_path, monkeypatch)
    assert cli.main(_args(data, path, _free_port(), "--expect-labels-stored", "99")) == 3
    assert "labels stored 2, expected 99" in capsys.readouterr().out
    assert _count(path, "rule_label") == 2


def test_a_live_shaped_database_is_written_only_after_the_verified_backup(tmp_path, monkeypatch, capsys):
    data = tmp_path / "checkout" / "backend" / "data"
    (data / "labels").mkdir(parents=True)
    path = s.make_db(data / "rag_intelligence.sqlite", with_book=True)
    labels = _label_file(tmp_path, monkeypatch, name="x.json")
    (data / "labels" / "rule-labels.json").write_bytes(labels.read_bytes())
    rule_equipment.write_file([equipment_row("r1")], data / "labels" / "rule-equipment.json")
    assert live_guard.is_live_shaped(path)
    (tmp_path / "checkout-backups").mkdir()
    assert cli.main(_args(data, path, _free_port())) == 0
    assert "verified before the write: True" in capsys.readouterr().out
    backups = list((tmp_path / "checkout-backups").glob("*.sqlite"))
    assert backups and _count(path, "rule_label") == 2
    # the backup was taken BEFORE the write: it holds no label table
    assert "rule_label" not in {r[0] for r in sqlite3.connect(f"file:{backups[0]}?mode=ro", uri=True).execute(
        "SELECT name FROM sqlite_master")}


def test_a_live_shaped_database_whose_backup_cannot_be_made_is_not_written(tmp_path, monkeypatch, capsys):
    data = tmp_path / "checkout" / "backend" / "data"
    (data / "labels").mkdir(parents=True)
    path = s.make_db(data / "rag_intelligence.sqlite", with_book=True)
    labels = _label_file(tmp_path, monkeypatch, name="x.json")
    (data / "labels" / "rule-labels.json").write_bytes(labels.read_bytes())
    rule_equipment.write_file([equipment_row("r1")], data / "labels" / "rule-equipment.json")

    def refuse(*_a, **_k):
        raise live_guard.LiveWriteRefused("backup step failed: invented")

    monkeypatch.setattr(live_guard, "prepare_live_write", refuse)
    assert cli.main(_args(data, path, _free_port())) == 1
    assert "live guard" in capsys.readouterr().out
    assert "rule_label" not in {r[0] for r in sqlite3.connect(f"file:{path}?mode=ro", uri=True).execute(
        "SELECT name FROM sqlite_master")}
