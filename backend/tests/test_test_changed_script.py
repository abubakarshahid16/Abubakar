"""scripts/test_changed.py maps changed files to the tests worth running locally.

Checked on an invented tests/ tree: a changed test runs itself, a changed app
module runs the tests that import it, a changed script runs the tests that name
it, frontend files go to `vitest related`, and a file that maps to nothing is
reported rather than silently dropped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test_changed.py"


@pytest.fixture(scope="module")
def tc():
    spec = importlib.util.spec_from_file_location("test_changed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    t = tmp_path / "tests"
    t.mkdir()
    (t / "test_alpha.py").write_text("from app import alpha\n", encoding="utf-8")
    (t / "test_uses_beta.py").write_text("import app.beta as b\n", encoding="utf-8")
    (t / "test_gamma_rules.py").write_text("x = 1\n", encoding="utf-8")
    (t / "test_report_script.py").write_text('SCRIPT = "scripts/make_report.py"\n', encoding="utf-8")
    (t / "test_unrelated.py").write_text("y = 2\n", encoding="utf-8")
    return t


def test_a_changed_test_file_runs_itself(tc, tree):
    sel, _ = tc.backend_tests_for(["backend/tests/test_unrelated.py"], tree)
    assert sel == {"tests/test_unrelated.py"}


def test_a_changed_app_module_runs_the_tests_that_import_it(tc, tree):
    sel, _ = tc.backend_tests_for(["backend/app/alpha.py", "backend/app/beta.py"], tree)
    assert sel == {"tests/test_alpha.py", "tests/test_uses_beta.py"}


def test_a_changed_app_module_runs_tests_named_after_it(tc, tree):
    sel, _ = tc.backend_tests_for(["backend/app/gamma.py"], tree)
    assert sel == {"tests/test_gamma_rules.py"}


def test_a_changed_script_runs_the_tests_that_name_it(tc, tree):
    sel, _ = tc.backend_tests_for(["scripts/make_report.py"], tree)
    assert sel == {"tests/test_report_script.py"}


def test_a_file_mapping_to_no_test_is_reported(tc, tree):
    sel, unmapped = tc.backend_tests_for(["backend/app/delta.py"], tree)
    assert sel == set()
    assert unmapped == {"backend/app/delta.py"}


def test_frontend_sources_go_to_vitest_related(tc):
    got = tc.frontend_files(["frontend/src/views/ChatView.tsx", "frontend/package.json", "docs/x.md"])
    assert got == ["src/views/ChatView.tsx"]


def test_files_that_can_affect_any_test_are_flagged(tc):
    assert {"backend/tests/conftest.py", "backend/pytest.ini", "backend/requirements.txt"} <= tc.WHOLE_SUITE
