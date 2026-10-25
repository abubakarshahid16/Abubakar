"""scripts/trim_test_output.py (order 145.7): a test run's output cut to what a
reader needs - the failures. It must never hide what it does not recognise: a
crash, a traceback, a collection error or output that is not a test run stays
whole. Invented output only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "trim_test_output.py"

GREEN = """============================= test session starts ==============================
collected 3 items

tests/test_a.py ...                                                      [100%]

=============================== warnings summary ===============================
tests/test_a.py::test_x
  /x/y.py:1: DeprecationWarning: nope
-- Docs: https://docs.pytest.org
no tests were skipped - the whole suite ran
============================== 3 passed in 0.12s ===============================
"""

RED = """tests/test_a.py .F.                                                      [100%]

=================================== FAILURES ===================================
___________________________ test_two ___________________________

    def test_two():
>       assert 1 == 2
E       assert 1 == 2

tests/test_a.py:5: AssertionError
=========================== short test summary info ============================
FAILED tests/test_a.py::test_two - assert 1 == 2
========================= 1 failed, 2 passed in 0.10s ==========================
"""

COLLECTION_ERROR = """==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_b.py _________________
ImportError: cannot import name 'gone'
=========================== short test summary info ============================
ERROR tests/test_b.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.30s ===============================
"""

VITEST_RED = """ RUN  v5.0.3 /repo/frontend

 ✓ src/a.test.ts (3 tests) 4ms
 \u276f src/b.test.ts (2 tests | 1 failed) 9ms
   \u00d7 b > adds 3ms
     → expected 3 to be 4
 ✓ src/c.test.ts (1 test) 2ms

 Test Files  1 failed | 2 passed (3)
      Tests  1 failed | 5 passed (6)
"""


@pytest.fixture(scope="module")
def trimmer():
    spec = importlib.util.spec_from_file_location("trim_test_output", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_green_pytest_run_is_its_summary_and_the_skipped_note(trimmer):
    got = trimmer.trim(GREEN)
    assert "3 passed in 0.12s" in got
    assert "no tests were skipped" in got
    assert "DeprecationWarning" not in got and "[100%]" not in got
    assert len(got.splitlines()) <= 3


def test_a_red_pytest_run_keeps_the_failure_whole(trimmer):
    got = trimmer.trim(RED)
    for needle in (
        "FAILURES",
        "assert 1 == 2",
        "AssertionError",
        "FAILED tests/test_a.py::test_two",
        "1 failed, 2 passed",
    ):
        assert needle in got
    assert ".F." not in got  # the progress line is gone


def test_a_collection_error_is_never_hidden(trimmer):
    got = trimmer.trim(COLLECTION_ERROR)
    assert "ImportError: cannot import name 'gone'" in got
    assert "1 error in 0.30s" in got


def test_a_vitest_run_drops_the_passing_files_and_keeps_the_failure(trimmer):
    got = trimmer.trim(VITEST_RED)
    assert "src/a.test.ts" not in got and "src/c.test.ts" not in got
    assert "expected 3 to be 4" in got and "\u00d7 b > adds" in got
    assert "1 failed | 5 passed (6)" in got


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Traceback (most recent call last):\n  File 'x.py', line 1\nBoomError: no\n",
        "just some build output\nwith lines\n",
    ],
)
def test_output_that_is_not_a_test_run_comes_back_unchanged(trimmer, text):
    assert trimmer.trim(text) == text


def test_ansi_colour_codes_do_not_hide_the_summary(trimmer):
    coloured = (
        "\x1b[31mFAILED\x1b[0m x\n\x1b[32m=== 1 failed, 2 passed in 0.10s ===\x1b[0m\n"
    )
    got = trimmer.trim(coloured)
    assert "1 failed, 2 passed" in got and "\x1b" not in got


# ----------------------------------------------------- the PostToolUse hook

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "trim_test_output.py"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("trim_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _event(command, stdout, tool="Bash", **response):
    return {
        "tool_name": tool,
        "tool_input": {"command": command},
        "tool_response": {
            "stdout": stdout,
            "stderr": "",
            "interrupted": False,
            **response,
        },
    }


def test_the_hook_replaces_only_the_stdout_of_a_test_run(hook):
    answer = hook.decide(
        _event(
            "cd backend && python -m pytest tests/test_a.py -q", GREEN, isImage=False
        )
    )
    out = answer["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    assert (
        out["updatedToolOutput"]["stdout"]
        .strip()
        .endswith("3 passed in 0.12s ===============================")
    )
    # every other key of the tool's result is carried over unchanged
    assert (
        out["updatedToolOutput"]["stderr"] == ""
        and out["updatedToolOutput"]["interrupted"] is False
    )
    assert out["updatedToolOutput"]["isImage"] is False


@pytest.mark.parametrize(
    "event",
    [
        _event("git status", GREEN),  # not a test command
        _event("pytest -q", GREEN, tool="Read"),  # not the Bash tool
        _event("npm run pytester", GREEN),  # a word that only contains pytest
        {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "tool_response": "plain text",
        },
        {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "tool_response": {"stdout": ""},
        },
        _event(
            "pytest -q", "Traceback (most recent call last):\n  boom\n"
        ),  # unrecognised: nothing to trim
    ],
)
def test_the_hook_changes_nothing_it_does_not_recognise(hook, event):
    assert hook.decide(event) is None


def test_a_broken_event_never_breaks_the_run(hook, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    assert hook.main() == 0
    assert capsys.readouterr().out == ""


def test_the_hook_is_wired_in_settings_and_the_env_denies_are_kept():
    import json

    settings = json.loads(
        (HOOK.parents[1] / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        h["command"]
        for entry in settings["hooks"]["PostToolUse"]
        if entry["matcher"] == "Bash"
        for h in entry["hooks"]
    ]
    assert any("trim_test_output.py" in c for c in commands)
    assert "Read(**/backend/.env)" in settings["permissions"]["deny"]
    assert "Edit(**/backend/.env)" in settings["permissions"]["deny"]


# ------------------------------------- what the independent review found (all kept)

HEADER_LOOKING_LINE = """=================================== FAILURES ===================================
___________________________ test_two ___________________________

    def test_two():
        print("=== step 1 ===")
>       assert state == "ok"
E       assert 'bad' == 'ok'

----------------------------- Captured stdout call -----------------------------
=== step 1 ===
state=bad
tests/a.py:3: AssertionError
=========================== short test summary info ============================
FAILED tests/a.py::test_two - assert 'bad' == 'ok'
========================= 1 failed, 2 passed in 0.10s ==========================
"""


def test_a_line_that_only_looks_like_a_section_header_does_not_end_a_failure(trimmer):
    got = trimmer.trim(HEADER_LOOKING_LINE)
    assert "=== step 1 ===" in got and "state=bad" in got
    assert "tests/a.py:3: AssertionError" in got


@pytest.mark.parametrize(
    "crash",
    [
        "INTERNALERROR> Traceback (most recent call last):\nINTERNALERROR> KeyError: 'x'",
        "Fatal Python error: Segmentation fault",
        "[gw0] node down: Not properly terminated\nreplacing crashed worker gw0",
        "stray ERROR: db connection lost",
    ],
)
def test_a_crash_printed_before_the_summary_is_never_dropped(trimmer, crash):
    text = f"tests/test_a.py ...  [100%]\n{crash}\n============ 3 passed in 0.50s ============\n"
    got = trimmer.trim(text)
    assert crash.splitlines()[0] in got and "3 passed in 0.50s" in got


def test_one_output_holding_a_pytest_and_a_vitest_run_is_left_whole(trimmer):
    both = (
        "============ 1 failed, 2 passed in 0.10s ============\n"
        " FAIL  src/a.test.ts > x\nAssertionError: nope\n\n Test Files  1 failed (1)\n"
    )
    assert trimmer.trim(both) == both


def test_the_warnings_and_durations_sections_are_dropped_but_the_summary_stays(trimmer):
    text = (
        "=============================== warnings summary ===============================\n"
        "tests/a.py::t\n  /x.py:1: DeprecationWarning: old\n"
        "============================ slowest 3 durations ===============================\n"
        "2.15s call     tests/a.py::t\n"
        "============================== 3 passed in 0.12s ===============================\n"
    )
    got = trimmer.trim(text)
    assert "DeprecationWarning" not in got and "2.15s call" not in got
    assert "3 passed in 0.12s" in got


def test_a_banner_printed_after_the_warnings_is_not_swallowed_with_them(trimmer):
    text = (
        "=============================== warnings summary ===============================\n"
        "tests/a.py::t\n  /x.py:1: DeprecationWarning: old\n"
        "-- Docs: https://docs.pytest.org\n"
        "======================= 2 SKIPPED - these proved nothing =======================\n"
        "  tests/a.py::test_x\n      reason: needs a client file\n"
        "============================== 3 passed, 2 skipped in 0.12s ====================\n"
    )
    got = trimmer.trim(text)
    assert (
        "2 SKIPPED - these proved nothing" in got
        and "reason: needs a client file" in got
    )
    assert "DeprecationWarning" not in got
