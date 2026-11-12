"""Owner order 12 Nov 2026, point G ("less waste"): style stops are warnings
outside the verdict path. One list (`scripts/verdict_path.py`) is read by the
pre-push hook, the quality ratchet and the lint baseline; CI runs those scripts.

A too-long file off the list WARNS and exits 0 (naming the file and the number);
the same on the list STOPS. Checks that are not style are not touched here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import quality_ratchet as qr  # noqa: E402
import verdict_path as vp  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RULE_6_ZONE = [
    "comparison.py", "numparse.py", "claims.py", "datasheet_checks.py",
    "crs_mapping.py", "crs_export.py", "crs_numbers.py", "live_guard.py", "heavy_lock.py",
    "market_transport.py", "model_transport.py", "reader_transport.py", "notifications.py",
    "claude_spend.py",
]  # fmt: skip


# ---------------------------------------------------------------- the list


def test_every_listed_path_exists_and_has_a_reason():
    for path, why in vp.VERDICT_PATH:
        assert (ROOT / path).exists(), f"{path} is listed but is not in the repo"
        assert why.strip(), path


def test_the_round_4_reader_files_are_on_the_list():
    for name in (
        "crs_normal", "agent_review_two_reader", "agent_review_two_reader_absence",
        "agent_review_two_reader_other", "agent_review_equipment",
    ):  # fmt: skip
        assert vp.is_verdict_path(f"backend/app/{name}.py"), name


def test_a_new_agent_review_or_crs_ai_file_is_listed_or_off_on_purpose():
    for path in sorted((ROOT / "backend" / "app").glob("*.py")):
        if path.name.startswith(("agent_review_", "agent_general_", "crs_ai_")):
            listed = vp.is_verdict_path(f"backend/app/{path.name}")
            off = path.name in vp.OFF_ON_PURPOSE
            assert listed != off, (
                f"{path.name}: put it on VERDICT_PATH or OFF_ON_PURPOSE (with a reason), not both or neither"
            )
    for name, why in vp.OFF_ON_PURPOSE.items():
        assert (ROOT / "backend" / "app" / name).exists() and why.strip(), name


def test_the_full_review_sentence_is_the_same_in_every_home():
    sentence = "whether or not the file is on the list; the list only decides where style stops block."
    for home in (
        "CLAUDE.md",
        ".claude/skills/release-train/SKILL.md",
        ".claude/commands/review.md",
    ):
        assert sentence in (ROOT / home).read_text(encoding="utf-8"), home


def test_the_whole_rule_6_danger_zone_is_on_the_list():
    for name in RULE_6_ZONE:
        assert vp.is_verdict_path(f"backend/app/{name}"), name
    assert vp.is_verdict_path("backend/app/reference/datasheet_checks.json")
    assert vp.is_verdict_path("scripts/rehearse_requirement_reextraction.py")


def test_a_function_suffix_and_a_dot_slash_still_match_and_other_files_do_not():
    assert vp.is_verdict_path("backend/app/comparison.py::Compare.run")
    assert vp.is_verdict_path("./backend/app/numparse.py")
    assert not vp.is_verdict_path("backend/app/main.py")
    assert not vp.is_verdict_path("frontend/src/views/ReportsView.tsx")
    assert not vp.is_verdict_path("backend/app/comparison.py.bak")


def test_the_list_is_short_enough_to_be_honest():
    assert len(vp.VERDICT_PATH) <= 50  # raised on 12 Nov: the list grew with real verdict files; trim before raising again


def test_the_ratchet_the_lint_baseline_and_the_hook_read_the_one_list():
    assert qr.verdict_path is vp
    lint = _load("check_lint_baseline")
    assert lint.verdict_path.VERDICT_PATH == vp.VERDICT_PATH
    guard = (ROOT / "scripts" / "pre_push_guard.py").read_text(encoding="utf-8")
    assert "verdict_path.py" in guard and "WARNING (not a stop" in guard


def test_split_stops_a_verdict_file_warns_for_others_and_never_guesses_harmless():
    stops, warns = vp.split(
        [
            "NEW: backend/app/main.py is 900 lines (limit 800)",
            "GREW: backend/app/numparse.py 800 -> 810 lines (listed, may only shrink)",
            "something that names no file",
        ]
    )
    assert warns == ["NEW: backend/app/main.py is 900 lines (limit 800)"]
    assert len(stops) == 2 and "numparse.py" in stops[0]


# ------------------------------------------------------- the size ratchet


def _check(tmp_path, monkeypatch, long_code, metrics=None, base_metrics=None):
    base = {
        "format": qr.FORMAT,
        "rules": {},
        "metrics": base_metrics or {"x": {"value": 5, "note": None}},
    }
    now = {
        "format": qr.FORMAT,
        "rules": {},
        "metrics": metrics or {"x": {"value": 5, "note": None}},
    }
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(base), encoding="utf-8")
    listed = tmp_path / "long_code.json"
    listed.write_text(json.dumps({"files": {}, "functions": {}}), encoding="utf-8")
    monkeypatch.setattr(qr, "measure", lambda: now)
    monkeypatch.setattr(qr, "long_code", lambda root=None: long_code)
    return qr.main(["check", "--baseline", str(baseline), "--long-code", str(listed)])


def test_a_too_long_file_off_the_verdict_path_warns_and_exits_0(
    tmp_path, monkeypatch, capsys
):
    code = _check(
        tmp_path, monkeypatch, {"files": {"backend/app/main.py": 950}, "functions": {}}
    )
    out = capsys.readouterr().out
    assert code == 0
    assert (
        "WARNING (not a stop, off the verdict path): NEW: backend/app/main.py is 950 lines (limit 800)"
        in out
    )


def test_a_too_long_verdict_path_file_stops(tmp_path, monkeypatch, capsys):
    code = _check(
        tmp_path,
        monkeypatch,
        {"files": {"backend/app/numparse.py": 950}, "functions": {}},
    )
    assert code == 1
    assert (
        "NEW: backend/app/numparse.py is 950 lines (limit 800)"
        in capsys.readouterr().out
    )


def test_a_long_function_warns_off_the_path_and_stops_on_it(
    tmp_path, monkeypatch, capsys
):
    assert (
        _check(
            tmp_path,
            monkeypatch,
            {"files": {}, "functions": {"backend/app/x.py::f": 120}},
        )
        == 0
    )
    assert "backend/app/x.py::f is 120 lines" in capsys.readouterr().out
    assert (
        _check(
            tmp_path,
            monkeypatch,
            {"files": {}, "functions": {"backend/app/claims.py::f": 120}},
        )
        == 1
    )


def test_a_rise_in_a_non_style_metric_still_stops_everywhere(
    tmp_path, monkeypatch, capsys
):
    code = _check(
        tmp_path,
        monkeypatch,
        {"files": {}, "functions": {}},
        metrics={"unused_backend_modules": {"value": 1, "note": None}},
        base_metrics={"unused_backend_modules": {"value": 0, "note": None}},
    )
    assert code == 1
    assert "unused_backend_modules: was 0, now 1" in capsys.readouterr().out


def test_a_complexity_rise_stops_only_when_a_verdict_path_function_caused_it(
    tmp_path, monkeypatch, capsys
):
    metric = {"max_cyclomatic_complexity": {"value": 30, "note": None}}
    base = {"max_cyclomatic_complexity": {"value": 20, "note": None}}
    quiet = {"files": {}, "functions": {}}
    monkeypatch.setattr(
        qr,
        "complexity_over",
        lambda limit: ["backend/app/main.py::f complexity is 30 (was at most 20)"],
    )
    assert _check(tmp_path, monkeypatch, quiet, metrics=metric, base_metrics=base) == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "backend/app/main.py::f complexity is 30" in out
    monkeypatch.setattr(
        qr,
        "complexity_over",
        lambda limit: [
            "backend/app/comparison.py::f complexity is 30 (was at most 20)"
        ],
    )
    assert _check(tmp_path, monkeypatch, quiet, metrics=metric, base_metrics=base) == 1


def test_a_frontend_component_length_rise_warns(tmp_path, monkeypatch, capsys):
    metric = {"max_frontend_component_lines": {"value": 950, "note": None}}
    base = {"max_frontend_component_lines": {"value": 901, "note": None}}
    code = _check(
        tmp_path,
        monkeypatch,
        {"files": {}, "functions": {}},
        metrics=metric,
        base_metrics=base,
    )
    assert code == 0
    assert "max_frontend_component_lines: was 901, now 950" in capsys.readouterr().out


# --------------------------------------------------------- the formatter


def test_a_new_unformatted_file_warns_off_the_path_and_stops_on_it(monkeypatch, capsys):
    off = "NEW FILE NOT FORMATTED: backend/app/main_extra.py (4 lines differ; run `ruff format x`)"
    on = "FORMAT DRIFT GREW: backend/app/numparse.py 2 -> 9 lines differ from `ruff format`"
    monkeypatch.setattr(qr, "format_check", lambda base: ([off], [], [], 1))
    assert qr.main(["format-check", "--base", "b"]) == 0
    out = capsys.readouterr().out
    assert "WARNING (not a stop, off the verdict path): " + off in out
    monkeypatch.setattr(qr, "format_check", lambda base: ([off, on], [], [], 2))
    assert qr.main(["format-check", "--base", "b"]) == 1
    assert on in capsys.readouterr().out


# ---------------------------------------------------------- the lint baseline


def test_a_new_lint_finding_warns_off_the_path_and_stops_on_it(monkeypatch, capsys):
    lint = _load("check_lint_baseline")
    stored = {"ruff": "1", "total": 0, "counts": {}}
    monkeypatch.setattr(lint, "ruff_version", lambda: "1")
    monkeypatch.setattr(lint, "format_report", lambda: "formatter report")
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: json.dumps(stored))
    monkeypatch.setattr(
        lint, "current_counts", lambda: {"backend/app/main.py::B904": 1}
    )
    assert lint.main(["check"]) == 0
    assert (
        "WARNING (not a stop, off the verdict path): NEW ruff finding backend/app/main.py::B904: 0 -> 1"
        in capsys.readouterr().out
    )
    monkeypatch.setattr(
        lint, "current_counts", lambda: {"backend/app/comparison.py::B904": 1}
    )
    assert lint.main(["check"]) == 1


# ------------------------------------------------------------------ the hook


def test_the_pre_push_hook_prints_the_warnings_of_a_step_that_passed(
    monkeypatch, capsys
):
    guard = _load("pre_push_guard")
    line = "  WARNING (not a stop, off the verdict path): NEW: backend/app/main.py is 950 lines (limit 800)"
    monkeypatch.setattr(
        guard, "changed_files", lambda base, root=guard.REPO: ["backend/app/main.py"]
    )
    monkeypatch.setattr(guard, "is_behind", lambda base, root=guard.REPO: False)
    monkeypatch.setattr(guard, "find_python", lambda root=guard.REPO: "python")
    monkeypatch.setattr(
        guard,
        "plan",
        lambda files, python, root=guard.REPO: [("size", ["x"], guard.REPO, "fix")],
    )
    monkeypatch.setattr(
        guard, "_run", lambda cmd, cwd, timeout=300: (0, line + "\nOK\n")
    )
    assert guard.main([]) == 0
    out = capsys.readouterr().out
    assert "1 style warning(s), not stops" in out
    assert "backend/app/main.py is 950 lines" in out


def test_a_failing_step_still_refuses_the_push(monkeypatch, capsys):
    guard = _load("pre_push_guard")
    monkeypatch.setattr(
        guard, "changed_files", lambda base, root=guard.REPO: ["backend/app/main.py"]
    )
    monkeypatch.setattr(guard, "is_behind", lambda base, root=guard.REPO: False)
    monkeypatch.setattr(guard, "find_python", lambda root=guard.REPO: "python")
    monkeypatch.setattr(
        guard,
        "plan",
        lambda files, python, root=guard.REPO: [
            ("system map", ["x"], guard.REPO, "list it")
        ],
    )
    monkeypatch.setattr(
        guard, "_run", lambda cmd, cwd, timeout=300: (1, "module not in the map")
    )
    assert guard.main([]) == 1
    assert "REFUSED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "label",
    [
        "every module is reached",
        "flag register",
        "no test-sheet names in code",
        "no second number reader",
        "mutation anchors",
        "system map",
        "no client data added",
    ],
)
def test_the_checks_that_are_not_style_are_still_in_the_hook_plan(label):
    guard = _load("pre_push_guard")
    steps = guard.plan(["backend/app/main.py"], "python", ROOT)
    assert label in [s[0] for s in steps]
