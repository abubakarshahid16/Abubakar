"""#711: the guarded --live mode of the #599 re-extraction script.

Everything runs on a TEMP database placed at a live-shaped path
(`<tmp>/backend/data/rag_intelligence.sqlite`) with the script's notion of
"this checkout's live file" pointed at it. INVENTED standard. The real live
database is never touched.

Mutations: M6001-M6014, `python scripts/mutation_check.py --phase 6001`;
#738 (the check never hangs): M7301-M7306.
"""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
import threading
import time
import types
import uuid
from pathlib import Path

import pytest

from app import db, live_guard, submittal_review
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
NOW = "2026-10-09T00:00:00Z"
SENTENCE = "The casing shall be painted by the vendor before dispatch to the site."


def _script():
    spec = importlib.util.spec_from_file_location(
        "rehearse_live", REPO / "scripts" / "rehearse_requirement_reextraction.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A live-shaped database holding one standard, with a verified backup."""
    work = tmp_path / "work.sqlite"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", work)
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    std = str(uuid.uuid4())
    confirmed = str(uuid.uuid4())
    stale = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'s.pdf','ready',1,?)", (std, "s.pdf", f"sha-{std}", NOW))
        conn.execute("INSERT INTO document_classification (document_id, suggested_by, document_role)"
                     " VALUES (?, 'test', 'COMPANY_STANDARD')", (std,))
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
            "token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'5.1 General','prose',?,12,?,1)",
            (f"c-{std}", std, "s.pdf", SENTENCE, f"h-{std}"))
        user = str(uuid.uuid4())
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,created_at)"
                     " VALUES (?,?,'E','x',?)", (user, f"{user}@example.test", NOW))
        for rid, text, by in ((confirmed, "A confirmed requirement the extractor will not reproduce.", user),
                              (stale, "An old unconfirmed requirement the extractor will not reproduce.", None)):
            conn.execute(
                "INSERT INTO standard_requirements (id, standard_document_id, clause, page, chunk_id,"
                " requirement_text, source_text, confirmed_by, created_at, updated_at)"
                " VALUES (?,?,?,1,?,?,?,?,?,?)",
                (rid, std, "5.1", f"c-{std}", text, text, by, NOW, NOW))
    db.reset_connection()
    live = tmp_path / "checkout" / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    src, dst = sqlite3.connect(work), sqlite3.connect(live)
    src.backup(dst); src.close(); dst.close()
    backups = live_guard.default_backup_dir(live)
    backups.mkdir()
    from importlib import util
    spec = util.spec_from_file_location("backup_db", REPO / "scripts" / "backup_db.py")
    tool = util.module_from_spec(spec); spec.loader.exec_module(tool)
    backup = Path(tool.backup(str(live), str(backups)))
    script = _script()
    monkeypatch.setattr(script, "LIVE", live)
    monkeypatch.setattr(script, "backend_running", lambda p: None)
    live_guard.revoke_all()
    yield types.SimpleNamespace(script=script, live=live, backup=backup, std=std,
                                confirmed=confirmed, stale=stale, tmp=tmp_path, tool=tool)
    live_guard.revoke_all()
    db.reset_connection()


def _rows(live):
    conn = sqlite3.connect(f"{Path(live).as_uri()}?mode=ro", uri=True)
    try:
        return {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT id, superseded_at, confirmed_by FROM standard_requirements")}
    finally:
        conn.close()


def _argv(w, *extra, backup=True):
    out = ["--live", "--db", str(w.live)]
    if backup:
        out += ["--i-have-a-backup", str(w.backup)]
    return out + list(extra)


# ----------------------------------------------------------------- the refusals

def test_live_without_a_backup_is_refused_and_nothing_is_written(world):
    before = _rows(world.live)
    with pytest.raises(SystemExit) as exc:
        world.script.main(_argv(world, backup=False))
    assert "needs --i-have-a-backup" in str(exc.value)
    assert _rows(world.live) == before


def test_a_backup_without_live_is_refused(world):
    with pytest.raises(SystemExit) as exc:
        world.script.main(["--db", str(world.tmp / "work.sqlite"), "--i-have-a-backup", str(world.backup)])
    assert "only for --live" in str(exc.value)


def test_live_on_a_copy_is_refused_it_is_only_for_this_checkouts_live_file(world):
    with pytest.raises(SystemExit) as exc:
        world.script.main(["--live", "--db", str(world.tmp / "work.sqlite"),
                           "--i-have-a-backup", str(world.backup)])
    assert "not this checkout's live database" in str(exc.value)


def test_live_on_another_checkouts_live_shaped_file_is_refused(world):
    other = world.tmp / "worktree" / "backend" / "data" / "rag_intelligence.sqlite"
    other.parent.mkdir(parents=True)
    shutil.copy2(world.live, other)
    with pytest.raises(SystemExit) as exc:
        world.script.main(["--live", "--db", str(other), "--i-have-a-backup", str(world.backup)])
    assert "not this checkout's live database" in str(exc.value)


def test_live_is_refused_while_the_backend_is_running(world, monkeypatch):
    monkeypatch.setattr(world.script, "backend_running", lambda p: "process 4242 has the database file open")
    before = _rows(world.live)
    with pytest.raises(SystemExit) as exc:
        world.script.main(_argv(world))
    assert "backend may be running" in str(exc.value) and "4242" in str(exc.value)
    assert _rows(world.live) == before


def test_a_missing_backup_file_is_refused(world):
    with pytest.raises(SystemExit) as exc:
        world.script.main(["--live", "--db", str(world.live), "--i-have-a-backup", str(world.tmp / "none.sqlite")])
    assert "no backup file" in str(exc.value)


def test_a_backup_that_fails_its_integrity_check_is_refused(world):
    bad = world.tmp / "bad.sqlite"
    bad.write_bytes(b"this is not a database")
    with pytest.raises(SystemExit) as exc:
        world.script.main(["--live", "--db", str(world.live), "--i-have-a-backup", str(bad)])
    assert "cannot be read" in str(exc.value) or "integrity check" in str(exc.value)


def test_a_backup_the_tool_reports_as_not_ok_is_refused(world, monkeypatch):
    tool = types.SimpleNamespace(verify=lambda path: {"ok": False, "integrity": "page 3 corrupt", "tables": {}})
    monkeypatch.setattr(world.script, "_backup_tool", lambda: tool)
    with pytest.raises(SystemExit) as exc:
        world.script.main(_argv(world))
    assert "fails its integrity check" in str(exc.value)


def test_a_backup_of_a_different_state_is_refused(world):
    conn = sqlite3.connect(world.live)           # the live file moved on after the backup
    conn.execute("INSERT INTO audit_events (at, actor_username, action, resource_type, outcome)"
                 " VALUES (?, 'x', 'test.after_backup', 'document', 'ok')", (NOW,))
    conn.commit(); conn.close()
    before = _rows(world.live)
    with pytest.raises(SystemExit) as exc:
        world.script.main(_argv(world))
    assert "table counts differ" in str(exc.value)
    assert _rows(world.live) == before


def test_a_failed_live_guard_refuses_and_writes_nothing(world, monkeypatch):
    def refuse(*a, **k):
        raise live_guard.LiveWriteRefused("restore drill failed")
    monkeypatch.setattr(live_guard, "prepare_live_write", refuse)
    before = _rows(world.live)
    with pytest.raises(SystemExit) as exc:
        world.script.main(_argv(world))
    assert "prepare_live_write failed" in str(exc.value)
    assert _rows(world.live) == before


def test_the_default_mode_still_refuses_the_live_database(world):
    with pytest.raises(SystemExit) as exc:
        world.script.rehearse(world.live)
    assert "refusing" in str(exc.value)


# -------------------------------------------------------------- the live run

def test_a_live_run_supersedes_and_deletes_nothing_and_leaves_confirmed_rows_alone(world, capsys):
    before = _rows(world.live)
    code = world.script.main(_argv(world))
    out = capsys.readouterr().out
    after = _rows(world.live)
    assert code == 0 and "SAFE" in out
    assert set(before) <= set(after), "a requirement row was deleted"
    assert len(after) > len(before)                                  # the sentence was extracted
    assert after[world.stale][0] is not None                         # superseded, not deleted
    assert after[world.confirmed] == before[world.confirmed]         # confirmed: untouched
    assert after[world.confirmed][0] is None


def test_a_live_run_takes_its_own_verified_backup_and_ends_with_no_clearance(world):
    world.script.main(_argv(world))
    backups = list(live_guard.default_backup_dir(world.live).glob("*.sqlite"))
    assert len(backups) >= 2                       # the owner's backup plus live_guard's own
    assert live_guard._cleared == {}               # the process is not left cleared


def test_a_run_that_lost_rows_would_not_be_called_safe(world, monkeypatch, capsys):
    real = world.script.rehearse

    def deleting(db_path, only=None, *, live=False):
        summary = real(db_path, only, live=live)
        summary["after"] = {**summary["after"], "requirements_total": summary["before"]["requirements_total"] - 1}
        return summary
    monkeypatch.setattr(world.script, "rehearse", deleting)
    assert world.script.main(_argv(world)) == 1
    assert "NOT SAFE" in capsys.readouterr().out


# ----------------------------------------------- how "backend running" is decided

def _fake_psutil(monkeypatch, *, open_path=None, listen_port=None, deny=False, procs=None):
    class Denied(Exception):
        pass

    class Gone(Exception):
        pass

    fake = types.SimpleNamespace(AccessDenied=Denied, NoSuchProcess=Gone, CONN_LISTEN="LISTEN")
    fake.process_iter = lambda attrs=None: procs if procs is not None else [
        _Proc(1, ["/x/other"]), _Proc(4242, [open_path] if open_path else [])]

    def net_connections(kind="inet"):
        if deny:
            raise Denied()
        return [types.SimpleNamespace(status="LISTEN", laddr=types.SimpleNamespace(port=listen_port))] \
            if listen_port else []
    fake.net_connections = net_connections
    monkeypatch.setitem(sys.modules, "psutil", fake)
    return fake


class _Proc:
    def __init__(self, pid, paths=(), name="python.exe", open_files=None):
        self.info, self._paths, self._open_files = {"pid": pid, "name": name}, list(paths), open_files

    def open_files(self):
        if self._open_files is not None:
            return self._open_files()
        return [types.SimpleNamespace(path=p) for p in self._paths]


def test_another_process_holding_the_file_open_means_running(world, monkeypatch):
    script = _script()                      # the unpatched detector
    _fake_psutil(monkeypatch, open_path=str(world.live))
    assert "4242" in script.backend_running(world.live)


def test_something_listening_on_the_api_port_means_running(world, monkeypatch):
    script = _script()
    _fake_psutil(monkeypatch, listen_port=settings.port)
    assert str(settings.port) in script.backend_running(world.live)


def test_a_check_that_cannot_be_made_counts_as_running(world, monkeypatch):
    script = _script()
    _fake_psutil(monkeypatch, deny=True)
    assert "could not check" in script.backend_running(world.live)


def test_nothing_open_and_nothing_listening_means_stopped(world, monkeypatch):
    script = _script()
    _fake_psutil(monkeypatch)
    assert script.backend_running(world.live) is None


# ----------------------------------------------- #738: the check never hangs

@pytest.fixture
def hang():
    """An `open_files` that blocks until the test ends (as on Windows, #738)."""
    release = threading.Event()
    yield lambda: release.wait(60) and []
    release.set()


def test_a_process_whose_open_files_hangs_refuses_within_seconds(world, monkeypatch, hang):
    """THE MUTATION TARGET (#738): it hung for ever with the backend stopped."""
    script = _script()
    _fake_psutil(monkeypatch, procs=[_Proc(4242, open_files=hang)])
    started = time.monotonic()
    reason = script.backend_running(world.live)
    assert time.monotonic() - started < script.PROCESS_CHECK_TIMEOUT + 3
    assert reason and "could not check" in reason and "4242" in reason


def test_a_hanging_check_refuses_the_live_run_and_writes_nothing(world, monkeypatch, hang):
    script = _script()
    _fake_psutil(monkeypatch, procs=[_Proc(4242, open_files=hang)])
    monkeypatch.setattr(world.script, "backend_running", script.backend_running)
    before = _rows(world.live)
    with pytest.raises(world.script.LiveRunRefused, match="backend may be running"):
        world.script.main(_argv(world))
    assert _rows(world.live) == before


def test_a_process_that_denies_the_check_refuses(world, monkeypatch):
    script = _script()
    fake = _fake_psutil(monkeypatch, procs=[])

    def denied():
        raise fake.AccessDenied()
    fake.process_iter = lambda attrs=None: [_Proc(4242, open_files=denied)]
    assert "could not check" in script.backend_running(world.live)


def test_a_process_that_exited_meanwhile_holds_nothing(world, monkeypatch):
    script = _script()
    fake = _fake_psutil(monkeypatch, procs=[])

    def gone():
        raise fake.NoSuchProcess()
    fake.process_iter = lambda attrs=None: [_Proc(4242, open_files=gone)]
    assert script.backend_running(world.live) is None


def test_only_python_processes_are_asked(world, monkeypatch, hang):
    """A non-Python process is never asked for its open files, so it cannot hang the check."""
    script = _script()
    _fake_psutil(monkeypatch, procs=[_Proc(7, name="explorer.exe", open_files=hang),
                                     _Proc(8, [str(world.live)], name="sqlite3.exe")])
    started = time.monotonic()
    assert script.backend_running(world.live) is None
    assert time.monotonic() - started < 1
    _fake_psutil(monkeypatch, procs=[_Proc(9, [str(world.live)], name="Python3.12")])
    assert "process 9" in script.backend_running(world.live)


def test_a_listener_on_the_api_port_refuses_before_any_process_is_asked(world, monkeypatch, hang):
    script = _script()
    _fake_psutil(monkeypatch, listen_port=settings.port, procs=[_Proc(4242, open_files=hang)])
    started = time.monotonic()
    assert str(settings.port) in script.backend_running(world.live)
    assert time.monotonic() - started < 1
