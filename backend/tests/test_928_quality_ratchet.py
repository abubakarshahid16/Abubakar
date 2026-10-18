"""#928: the code-quality ratchet. Every detector tested against INVENTED
source text, never the real codebase (a real-codebase number changes every
PR and would make this test flaky by design). The one thing proved against
the real tree is that `measure()` runs to completion and every one of the 9
rules has an entry - never a rule silently missing.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import quality_ratchet as qr  # noqa: E402, I001
import pytest  # noqa: E402

#: The real lister, kept before the fixture below replaces it for the CLI tests.
REAL_LONG_CODE = qr.long_code


@pytest.fixture(autouse=True)
def _no_real_long_code(tmp_path, monkeypatch):
    """The CLI tests below are about the 9 metrics: give `check` an empty
    long-code list and an empty tree, so the real codebase never decides them."""
    listed = tmp_path / "long_code.json"
    listed.write_text(json.dumps({"files": {}, "functions": {}}), encoding="utf-8")
    monkeypatch.setattr(qr, "DEFAULT_LONG_CODE", listed)
    monkeypatch.setattr(qr, "long_code", lambda root=None: {"files": {}, "functions": {}})


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


# ------------------------------------------- long code (order 71c, #692)

def _src(tmp_path, name, body):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path / name


def _fn(name, lines, indent=""):
    return f"{indent}def {name}():\n" + f"{indent}    x = 1\n" * (lines - 1)


def test_function_lengths_carry_class_and_outer_names(tmp_path):
    body = "class A:\n" + _fn("m", 3, "    ") + _fn("outer", 2) + "    " + _fn("inner", 2).replace("\n    x", "\n        x")
    lengths = qr._qualified_lengths(_src(tmp_path, "m.py", body))
    assert lengths["A.m"] == 3
    assert lengths["outer.inner"] == 2 and "inner" not in lengths


def test_a_name_defined_twice_keeps_its_longest(tmp_path):
    assert qr._qualified_lengths(_src(tmp_path, "m.py", _fn("f", 3) + _fn("f", 9))) == {"f": 9}


def test_only_files_and_functions_over_the_limits_are_listed(tmp_path):
    _src(tmp_path, "long.py", "x = 1\n" * (qr.FILE_LIMIT + 1))
    _src(tmp_path, "edge.py", "x = 1\n" * qr.FILE_LIMIT)
    _src(tmp_path, "funcs.py", _fn("big", qr.FUNCTION_LIMIT + 1) + _fn("edge", qr.FUNCTION_LIMIT))
    found = REAL_LONG_CODE(tmp_path)
    assert list(found["files"]) == ["long.py"]
    assert list(found["functions"]) == ["funcs.py::big"]


def test_a_new_long_function_or_a_listed_one_growing_is_blocked():
    listed = {"files": {"a.py": 900}, "functions": {"a.py::f": 100}}
    blocked, shrunk = qr.compare_long_code(
        listed, {"files": {"a.py": 901, "b.py": 801}, "functions": {"a.py::f": 100, "a.py::g": 81}})
    assert blocked == ["GREW: a.py 900 -> 901 lines (listed, may only shrink)",
                       "NEW: b.py is 801 lines (limit 800)",
                       "NEW: a.py::g is 81 lines (limit 80)"]
    assert shrunk == []


def test_a_listed_one_shrinking_or_gone_is_reported_never_blocked():
    listed = {"files": {"a.py": 900}, "functions": {"a.py::f": 100, "a.py::h": 90}}
    blocked, shrunk = qr.compare_long_code(listed, {"files": {"a.py": 850}, "functions": {"a.py::f": 100}})
    assert blocked == []
    assert shrunk == ["a.py 900 -> 850", "a.py::h 90 -> under the limit"]


def test_the_cli_blocks_a_new_long_function(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(_doc({"x": {"value": 5, "note": None}})), encoding="utf-8")
    monkeypatch.setattr(qr, "measure", lambda: _doc({"x": {"value": 5, "note": None}}))
    monkeypatch.setattr(qr, "long_code", lambda root=None: {"files": {}, "functions": {"a.py::g": 120}})
    assert qr.main(["check", "--baseline", str(baseline)]) == 1
    assert "NEW: a.py::g is 120 lines (limit 80)" in capsys.readouterr().out


def test_record_long_code_writes_the_list_and_the_limits(tmp_path, monkeypatch):
    out = tmp_path / "long.json"
    monkeypatch.setattr(qr, "long_code", lambda root=None: {"files": {"a.py": 900}, "functions": {}})
    assert qr.main(["record-long-code", "--out", str(out)]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved == {"limits": {"file": 800, "function": 80}, "files": {"a.py": 900}, "functions": {}}


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


# ------------------------------------------- order 79d: formatter, changed files only


#: The formatter tests run ruff. The Windows job installs only the backend's
#: requirements; the Linux shards and the lint job install ruff (tests.yml).
needs_ruff = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is installed by the Linux test shards and the lint job, not the Windows job",
)


def test_a_new_file_must_be_formatted_and_a_changed_one_may_not_drift_further():
    blocked, better = qr.compare_format(
        [
            ("backend/new_clean.py", None, 0),
            ("backend/new_messy.py", None, 4),
            ("backend/grew.py", 10, 12),
            ("backend/same.py", 10, 10),
            ("backend/closer.py", 10, 3),
        ]
    )
    assert blocked == [
        "NEW FILE NOT FORMATTED: backend/new_messy.py (4 lines differ; run `ruff format backend/new_messy.py`)",
        "FORMAT DRIFT GREW: backend/grew.py 10 -> 12 lines differ from `ruff format`",
    ]
    assert better == ["backend/closer.py 10 -> 3"]


@needs_ruff
def test_format_drift_counts_the_lines_the_formatter_would_change():
    assert qr.format_drift("x = 1\n", "backend/m.py") == 0
    # `x=1` -> `x = 1`: one line out, one line in
    assert qr.format_drift("x=1\n", "backend/m.py") == 2


def _git(repo, *args):
    import subprocess

    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway git repo with the real ruff.toml and one unformatted file."""
    (tmp_path / "ruff.toml").write_text(
        (REPO / "ruff.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "old.py").write_text("a=1\nb = 2\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "tag", "base")
    monkeypatch.setattr(qr, "REPO", tmp_path)
    return tmp_path


@needs_ruff
def test_the_cli_blocks_a_changed_file_that_drifts_further(repo, capsys):
    (repo / "backend" / "old.py").write_text("a=1\nb = 2\nc=3\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "grow")
    assert qr.main(["format-check", "--base", "base"]) == 1
    assert "FORMAT DRIFT GREW: backend/old.py 2 -> 4" in capsys.readouterr().out


@needs_ruff
def test_the_cli_passes_an_untidy_file_whose_new_lines_are_formatted(repo, capsys):
    (repo / "backend" / "old.py").write_text("a=1\nb = 2\nc = 3\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "tidy addition")
    assert qr.main(["format-check", "--base", "base"]) == 0
    assert "1 changed Python files checked" in capsys.readouterr().out


@needs_ruff
def test_a_renamed_untidy_file_is_not_a_new_file(repo):
    _git(repo, "mv", "backend/old.py", "backend/moved.py")
    _git(repo, "commit", "-qm", "move")
    assert qr.format_check("base") == ([], [], [], 1)


@needs_ruff
def test_a_new_untidy_file_is_blocked_and_files_outside_the_trees_are_not_read(repo):
    (repo / "backend" / "new.py").write_text("z=9\n", encoding="utf-8")
    (repo / "frontend.py").write_text("y=8\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "new")
    blocked, better, moved, checked = qr.format_check("base")
    assert (checked, better, moved) == (1, [], [])
    assert blocked == [
        "NEW FILE NOT FORMATTED: backend/new.py (2 lines differ; "
        "run `ruff format backend/new.py`)"
    ]


_UNTIDY = "".join(f"value_{i}={i}\n" for i in range(10))


@needs_ruff
def test_code_moved_out_of_another_file_keeps_its_formatting(repo):
    (repo / "backend" / "long.py").write_text(_UNTIDY + "keep=1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a long untidy file")
    _git(repo, "tag", "-f", "base")
    # a split: nine of the ten lines move verbatim into a new module
    (repo / "backend" / "long.py").write_text("value_9=9\nkeep=1\n", encoding="utf-8")
    (repo / "backend" / "part.py").write_text(
        "".join(_UNTIDY.splitlines(True)[:9]), encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "split")
    blocked, _better, moved, checked = qr.format_check("base")
    assert (blocked, checked) == ([], 2)
    assert moved == [
        "backend/part.py (100% of its lines moved from elsewhere in this PR)"
    ]


@needs_ruff
def test_new_code_beside_a_little_moved_code_must_still_be_formatted(repo):
    # one moved line and four new untidy ones: 20% moved, under the bar
    (repo / "backend" / "old.py").write_text("b = 2\n", encoding="utf-8")
    (repo / "backend" / "part.py").write_text(
        "a=1\nx=1\ny=2\nz=3\nw=4\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "new code")
    blocked, _better, moved, _checked = qr.format_check("base")
    assert moved == []
    assert blocked[0].startswith("NEW FILE NOT FORMATTED: backend/part.py")


def test_moved_share_counts_a_route_decorator_as_the_same_line():
    deleted = {'@app.get("/api/x")', "def x():"}
    assert qr.moved_share('@router.get("/api/x")\ndef x():\n\n', deleted) == 1.0
    assert qr.moved_share("", deleted) == 0.0


def test_a_missing_ruff_is_a_named_error_never_zero_drift(monkeypatch):
    # Without the module, `python -m ruff` exits 1 like "would reformat" and
    # prints no diff: that read as 0 drift, a silent pass (Windows CI, #1092).
    monkeypatch.setattr(qr.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(SystemExit, match="ruff is not installed"):
        qr.format_drift("x=1\n", "backend/m.py")
