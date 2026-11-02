"""#1574: an old --out file must not outlive a bench that refused or crashed, or
a later reader takes it for this run (twelve benches once printed old GREENs)."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from tools import crs_bench

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "crs_bench.py"
OLD = "Gate: GREEN\n"


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("crs_bench_script_1574", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def old_out(tmp_path):
    path = tmp_path / "bench-off.md"
    path.write_text(OLD)
    return path


def test_a_database_copy_deleted_on_purpose_leaves_no_old_result(
    script, old_out, tmp_path, capsys
):
    copy = tmp_path / "copy.sqlite"
    sqlite3.connect(copy).close()
    copy.unlink()

    assert script.main(["--db", str(copy), "--out", str(old_out)]) == 2
    assert "refused" in capsys.readouterr().out
    assert not old_out.exists()


def test_the_refused_live_database_leaves_no_old_result(script, old_out):
    assert script.main(["--db", str(script.LIVE), "--out", str(old_out)]) == 2
    assert not old_out.exists()


def test_a_crash_inside_the_bench_leaves_no_old_result(
    script, old_out, tmp_path, monkeypatch
):
    def crash(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(crs_bench, "run_bench", crash)
    copy = tmp_path / "copy.sqlite"
    sqlite3.connect(copy).close()

    assert script.main(["--db", str(copy), "--out", str(old_out)]) == script.EXIT_ERROR
    assert not old_out.exists()


def test_a_wrong_command_line_leaves_no_old_result(script, old_out):
    with pytest.raises(SystemExit) as stop:
        script.main(["--out", str(old_out)])  # no --db
    assert stop.value.code == 2
    assert not old_out.exists()


def test_a_bench_that_cannot_even_import_leaves_no_old_result(old_out, tmp_path):
    """A file half-edited in the checkout (#1539): a failure, never the old table."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "backend" / "tools").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "crs_bench.py")
    (tmp_path / "backend" / "tools" / "crs_bench.py").write_text("def broken(:\n")

    done = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "crs_bench.py"),
            "--db",
            str(tmp_path / "copy.sqlite"),
            "--out",
            str(old_out),
        ],
        capture_output=True,
        text=True,
    )

    assert done.returncode == 3
    assert "BENCH ERROR" in done.stderr
    assert not old_out.exists()


def test_a_failure_after_the_replay_writes_no_table(
    script, old_out, tmp_path, monkeypatch
):
    """The exit code and the table must agree: exit 3 means no table at all."""
    monkeypatch.setattr(crs_bench, "run_bench", lambda *_a, **_k: [])
    copy = tmp_path / "copy.sqlite"
    sqlite3.connect(copy).close()
    save = tmp_path / "no-such-folder" / "numbers.json"

    code = script.main(["--db", str(copy), "--out", str(old_out), "--save", str(save)])

    assert code == script.EXIT_ERROR
    assert not old_out.exists()


def test_a_good_run_still_writes_its_table(script, old_out, tmp_path, monkeypatch):
    monkeypatch.setattr(crs_bench, "run_bench", lambda *_a, **_k: [])
    copy = tmp_path / "copy.sqlite"
    sqlite3.connect(copy).close()

    assert script.main(["--db", str(copy), "--out", str(old_out)]) == 0
    assert old_out.read_text() != OLD
    assert "Gate: GREEN" in old_out.read_text()


@pytest.mark.parametrize("flag", ["--db", "--baseline", "--truth"])
def test_out_pointing_at_an_input_is_refused_and_the_input_is_kept(
    script, tmp_path, flag
):
    """Clearing --out at the start must never delete what the run reads."""
    target = tmp_path / "input.json"
    target.write_text("{}")
    args = ["--db", str(tmp_path / "copy.sqlite"), "--out", str(target)]
    if flag != "--db":
        args += [flag, str(target)]
    else:
        args[1] = str(target)

    assert script.main(args) == 2
    assert target.read_text() == "{}"


def test_out_pointing_at_a_database_is_refused_and_the_file_is_kept(script, tmp_path):
    live_shaped = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live_shaped.parent.mkdir(parents=True)
    live_shaped.write_text("data")
    args = ["--db", str(tmp_path / "copy.sqlite"), "--out", str(live_shaped)]

    assert script.main(args) == 2
    assert live_shaped.read_text() == "data"


def test_an_out_that_is_not_a_regular_file_is_never_deleted(script, tmp_path):
    """#1578 deleted --out first, so `--out /dev/null` failed with PermissionError and
    the board's bench stopped. A pipe stands in: deleting one needs no special rights."""
    pipe = tmp_path / "table.pipe"
    os.mkfifo(pipe)
    assert script._clear_old_out(["--out", str(pipe)]) is None
    assert pipe.is_fifo()
