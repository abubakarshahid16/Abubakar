"""#1539: the bench went 'red' once (exit 1, no output file). The cause was a
crash - it imported a file another process was editing - and exit 1 also meant
'red'. A crash is now its own exit code with a clear message, never a result."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location(
        "crs_bench_script", REPO / "scripts" / "crs_bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_crash_is_exit_3_and_says_it_is_not_a_result(tmp_path, monkeypatch, capsys):
    script = _script()
    db = tmp_path / "copy.sqlite"
    sqlite3.connect(db).close()
    from tools import crs_bench

    def boom(*_a, **_k):
        raise SyntaxError("invalid syntax (spec_kit.py, line 9)")

    monkeypatch.setattr(crs_bench, "run_bench", boom)
    out = tmp_path / "bench.md"
    code = script.main(["--db", str(db), "--out", str(out)])
    assert code == script.EXIT_ERROR == 3
    err = capsys.readouterr().err
    assert "BENCH ERROR" in err and "not a result" in err and "SyntaxError" in err
    assert not out.exists()


def test_red_stays_exit_1(tmp_path, monkeypatch):
    script = _script()
    db = tmp_path / "copy.sqlite"
    sqlite3.connect(db).close()
    from tools import crs_bench

    monkeypatch.setattr(crs_bench, "run_bench", lambda *a, **k: [])
    monkeypatch.setattr(crs_bench, "render_markdown", lambda *a, **k: "table")
    monkeypatch.setattr(crs_bench, "gate", lambda *a, **k: ["worse"])
    assert script.main(["--db", str(db)]) == 1
