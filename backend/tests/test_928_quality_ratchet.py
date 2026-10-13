"""#928: the code-quality ratchet. Every detector tested against INVENTED
source text, never the real codebase (a real-codebase number changes every
PR and would make this test flaky by design). The one thing proved against
the real tree is that `measure()` runs to completion and every one of the 9
rules has an entry - never a rule silently missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import quality_ratchet as qr  # noqa: E402


# ------------------------------------------------------- duplicate detector

def test_a_name_defined_twice_at_module_level_counts_one_extra(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f():\n    return 1\n\n\ndef f():\n    return 2\n", encoding="utf-8")
    assert qr.duplicate_definitions(tmp_path / "m.py") == 1


def test_a_name_defined_three_times_counts_two_extra(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n" * 1 + "\n".join(
        [f"def f():\n    return {n}\n" for n in range(3)]), encoding="utf-8")
    assert qr.duplicate_definitions(tmp_path / "m.py") == 2


def test_a_class_field_defined_twice_counts_one_extra(tmp_path):
    (tmp_path / "m.py").write_text(
        "class Settings:\n    watch_folder: str = ''\n    watch_folder: str = ''\n",
        encoding="utf-8")
    assert qr.duplicate_definitions(tmp_path / "m.py") == 1


def test_every_name_unique_counts_zero(tmp_path):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n",
                                   encoding="utf-8")
    assert qr.duplicate_definitions(tmp_path / "m.py") == 0


def test_two_functions_of_the_same_name_in_different_classes_are_not_duplicates(tmp_path):
    (tmp_path / "m.py").write_text(
        "class A:\n    def ensure_schema(self): return 1\n\n"
        "class B:\n    def ensure_schema(self): return 2\n", encoding="utf-8")
    assert qr.duplicate_definitions(tmp_path / "m.py") == 0


def test_a_file_that_does_not_parse_counts_zero_never_guessed(tmp_path):
    (tmp_path / "m.py").write_text("def f(:\n", encoding="utf-8")
    assert qr.duplicate_definitions(tmp_path / "m.py") == 0


# -------------------------------------------------------- broad except

def test_a_bare_except_that_swallows_silently_is_counted(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        g()\n    except:\n        pass\n", encoding="utf-8")
    assert qr.broad_unaccounted_excepts(tmp_path / "m.py") == 1


def test_except_exception_that_logs_is_not_counted(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        g()\n    except Exception as exc:\n"
        "        log.warning('failed: %s', exc)\n        return None\n", encoding="utf-8")
    assert qr.broad_unaccounted_excepts(tmp_path / "m.py") == 0


def test_except_exception_that_raises_is_not_counted(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        g()\n    except Exception:\n        raise\n", encoding="utf-8")
    assert qr.broad_unaccounted_excepts(tmp_path / "m.py") == 0


def test_except_a_named_error_type_is_never_counted_as_broad(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        g()\n    except ValueError:\n        pass\n", encoding="utf-8")
    assert qr.broad_unaccounted_excepts(tmp_path / "m.py") == 0


# ------------------------------------------------------ length / lines

def test_function_length_is_counted_by_line_span(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def f():\n" + "    x = 1\n" * 10, encoding="utf-8")
    lengths = qr._function_lengths(path)
    assert lengths == [("f", 11)]


# ------------------------------------------------------------- comparing

def _doc(metrics: dict) -> dict:
    return {"format": qr.FORMAT, "rules": qr.RULES, "metrics": metrics}


def test_a_higher_count_than_the_baseline_is_a_regression():
    baseline = _doc({"dups": {"value": 2, "note": None}})
    current = _doc({"dups": {"value": 3, "note": None}})
    assert qr.compare(baseline, current) == ["dups: was 2, now 3"]


def test_an_equal_or_lower_count_is_not_a_regression():
    baseline = _doc({"dups": {"value": 2, "note": None}})
    assert qr.compare(baseline, _doc({"dups": {"value": 2, "note": None}})) == []
    assert qr.compare(baseline, _doc({"dups": {"value": 1, "note": None}})) == []


def test_a_metric_null_on_either_side_is_never_compared_never_a_silent_pass_or_fail():
    baseline = _doc({"coverage": {"value": None, "note": "not measured: no tool"}})
    current = _doc({"coverage": {"value": 95, "note": None}})
    assert qr.compare(baseline, current) == []
    # and the reverse
    baseline2 = _doc({"coverage": {"value": 95, "note": None}})
    current2 = _doc({"coverage": {"value": None, "note": "not measured: tool crashed"}})
    assert qr.compare(baseline2, current2) == []


def test_a_rule_missing_from_todays_run_is_never_silently_treated_as_improved():
    baseline = _doc({"dups": {"value": 2, "note": None}})
    current = _doc({})  # today's run produced nothing for this metric
    assert qr.compare(baseline, current) == []  # not compared, not a pass


# -------------------------------------------------------------- the CLI

def test_the_cli_exits_1_and_names_the_regression(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(_doc({"duplicate_definitions_in_backend_app":
                                        {"value": 0, "note": None}})), encoding="utf-8")
    monkeypatch.setattr(qr, "measure", lambda: _doc(
        {"duplicate_definitions_in_backend_app": {"value": 1, "note": None}}))
    code = qr.main(["check", "--baseline", str(baseline)])
    assert code == 1
    assert "duplicate_definitions_in_backend_app: was 0, now 1" in capsys.readouterr().out


def test_the_cli_passes_when_nothing_measured_is_worse(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(_doc({"x": {"value": 5, "note": None}})), encoding="utf-8")
    monkeypatch.setattr(qr, "measure", lambda: _doc({"x": {"value": 5, "note": None}}))
    assert qr.main(["check", "--baseline", str(baseline)]) == 0


def test_record_baseline_writes_every_rules_metrics(tmp_path, monkeypatch):
    out = tmp_path / "baseline.json"
    monkeypatch.setattr(qr, "measure", lambda: _doc({"x": {"value": 1, "note": None}}))
    assert qr.main(["record-baseline", "--out", str(out)]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["format"] == qr.FORMAT and saved["metrics"]["x"]["value"] == 1


# -------------------------------------------------------- against the real tree

def test_measure_covers_all_nine_rules_and_never_fabricates_a_value_with_no_note():
    """The one check run against the REAL codebase: every rule has at least
    one metric, and every null value carries why - proved here so a future
    detector cannot silently drop a rule or guess a number."""
    data = qr.measure()
    assert set(data["rules"]) == set(range(1, 10))
    for name, entry in data["metrics"].items():
        if entry["value"] is None:
            assert entry["note"], f"{name} is null with no note"
        else:
            assert isinstance(entry["value"], int) and entry["value"] >= 0
