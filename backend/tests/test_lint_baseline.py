"""Order 55a (#692): `ruff.toml` findings may only go down.

`scripts/check_lint_baseline.py` compares today's per-file, per-rule counts
with `eval/quality/lint_baseline.json`. These tests hold the comparison and
the version pin; CI runs the real check.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_lint_baseline", ROOT / "scripts" / "check_lint_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_new_finding_fails_and_a_fixed_one_is_only_reported():
    mod = _load()
    base = {"a.py::F401": 1, "b.py::B904": 2}
    new, fixed = mod.compare(base, {"a.py::F401": 2, "b.py::B904": 1, "c.py::E741": 1})
    assert new == ["a.py::F401: 1 -> 2", "c.py::E741: 0 -> 1"]
    assert fixed == ["b.py::B904: 2 -> 1"]
    assert mod.compare(base, {"a.py::F401": 1}) == ([], ["b.py::B904: 2 -> 0"])


def test_the_same_counts_pass():
    mod = _load()
    assert mod.compare({"a.py::F401": 3}, {"a.py::F401": 3}) == ([], [])


def test_the_baseline_is_recorded_with_the_ruff_ci_installs():
    """Counts differ between ruff versions: the baseline and CI's pin are one."""
    baseline = json.loads((ROOT / "eval" / "quality" / "lint_baseline.json").read_text())
    pins = set(re.findall(r"ruff==([\d.]+)",
                          (ROOT / ".github" / "workflows" / "tests.yml").read_text()))
    assert pins == {baseline["ruff"]}
    assert baseline["total"] == sum(baseline["counts"].values())


def test_the_formatter_report_survives_output_it_could_not_read(monkeypatch):
    """Order 133: on Windows a byte ruff printed that cp1252 could not decode
    left stdout None, and `format_report` crashed on None + str."""
    import subprocess

    mod = _load()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(
            cmd, 1, stdout=None, stderr="3 files would be reformatted"
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.format_report().endswith("3 file(s) would be reformatted")
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
