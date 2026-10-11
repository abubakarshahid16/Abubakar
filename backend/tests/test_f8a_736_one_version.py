"""#725 F8a (#736): no unused app modules, and a system map with one module per job.

`scripts/check_unused_modules.py` walks the import graph from the app's entry
point; `scripts/check_system_map.py` holds `docs/system-map.md` to the modules
that exist. Both run in CI. These tests prove each check fails on the case it
exists for, and that the repository passes both today.

Mutations: M6801-M6806 (scripts/mutations/f8a_736_one_version.py).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


unused = _load("check_unused_modules")
system_map = _load("check_system_map")


def test_every_app_module_is_reached_from_the_app():
    """THE MUTATION TARGET: 0 unused modules in backend/app."""
    assert unused.unused() == []
    assert "main" in unused.reachable()


def test_the_removed_modules_are_gone_from_the_app():
    app = REPO / "backend" / "app"
    for name in ("ai_datasheet", "extraction_schema", "quotes", "worker", "datasheet_offline",
                 "review_score", "blind_test", "ai_requirements", "scope_records"):
        assert not (app / f"{name}.py").exists(), name
    for name in ("datasheet_offline", "review_score", "blind_test", "ai_requirements",
                 "scope_records", "worker"):
        assert (REPO / "backend" / "tools" / f"{name}.py").exists(), name


def test_lazy_and_relative_imports_are_followed(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("from . import alpha, beta as b\nfrom .gamma import x\nimport app.delta\n"
                   "def f():\n    from app import epsilon\n    from app.zeta import y\n", encoding="utf-8")
    known = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "other"}
    assert unused.imports_of(src, known) == known - {"other"}


def test_a_module_nothing_imports_is_reported(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("from . import used\n", encoding="utf-8")
    (app / "used.py").write_text("x = 1\n", encoding="utf-8")
    (app / "orphan.py").write_text("y = 2\n", encoding="utf-8")
    monkeypatch.setattr(unused, "APP", app)
    monkeypatch.setattr(unused, "REPO", tmp_path)
    assert unused.unused() == ["orphan"]
    assert unused.main() == 1


def test_the_system_map_matches_the_modules():
    assert system_map.problems() == []


def test_a_module_missing_from_the_map_is_reported():
    text = system_map.MAP.read_text(encoding="utf-8")
    without = "\n".join(l for l in text.splitlines() if not l.startswith("| `absence` |"))
    assert any("absence.py is not in docs/system-map.md" in p for p in system_map.problems(without))


def test_a_listed_module_that_does_not_exist_is_reported():
    text = system_map.MAP.read_text(encoding="utf-8") + "| `no_such_module` | A job |\n"
    assert any("no_such_module" in p for p in system_map.problems(text))


def test_an_unrecorded_second_module_for_one_job_is_reported():
    text = system_map.MAP.read_text(encoding="utf-8").replace(
        "| `keyword` | SQLite FTS5 keyword index |", "| `keyword` | Hybrid retrieval: FTS5 + dense vectors, fused with RRF, then reranked |")
    found = system_map.problems(text)
    assert any("keyword" in p and "not a recorded duplicate" in p for p in found)


def test_a_module_listed_twice_is_reported():
    text = system_map.MAP.read_text(encoding="utf-8") + "| `absence` | again |\n"
    assert any("absence is listed twice" in p for p in system_map.problems(text))
