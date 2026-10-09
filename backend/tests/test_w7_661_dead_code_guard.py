"""#661: new dead code fails the build.

The CI step runs `python -m vulture backend/app scripts/vulture_whitelist.py
--min-confidence 80` (an unused import, variable or unreachable branch; an
unused FUNCTION is only 60% sure and is reviewed by hand). These tests prove the
step exists with those settings, that the whitelist is honest, that the code has
no finding today, and (when vulture is installed) that the check really reports
a new unused variable.

Mutations: M4631-M4636 (scripts/mutations/w7_661_dead_code_guard.py).
"""
from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
WHITELIST = REPO / "scripts" / "vulture_whitelist.py"
APP = REPO / "backend" / "app"

#: The functions only the tests call (reset a cache, reload a data file).
TEST_HOOKS = {
    "acronyms.py": "reset_cache", "auth.py": "reset_limiter", "market_providers.py": "reset_rate_limits",
    "metrics.py": "reset_ollama_cache", "watcher.py": "reset_watcher", "front_matter.py": "reload_vocabulary",
    "standard_ids.py": "reload_vocabulary", "keyword.py": "reload_prefixes", "market.py": "reload_samples",
}
vulture_available = importlib.util.find_spec("vulture") is not None


def test_the_ci_job_runs_vulture_at_80_over_the_app_with_the_whitelist_and_a_pinned_version():
    assert ("run: python -m vulture backend/app scripts/vulture_whitelist.py --min-confidence 80"
            in WORKFLOW)
    # the lint job's installer pins it, and its cache key changes with it
    block = WORKFLOW[WORKFLOW.index("backend lint, anchors and benchmarks"):]
    block = block[:block.index("Find dead code")]
    assert "vulture==2.16" in block and "vulture2.16" in block


def test_every_whitelisted_name_is_a_real_identifier_with_its_reason_beside_it():
    text = WHITELIST.read_text(encoding="utf-8")
    lines = text.splitlines()
    names = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Name):
            comment = lines[node.lineno - 1].partition("#")[2].strip()
            assert comment, f"{node.value.id} is whitelisted with no reason beside it"
            names[node.value.id] = comment
    assert set(names) == {"mtime_ns", "mtime", "rect_num"}, names
    source = " ".join(p.read_text(encoding="utf-8") for p in APP.glob("*.py"))
    for name in names:
        assert re.search(rf"\b{name}\b", source), f"{name} is whitelisted but no longer exists"


def test_the_test_hooks_are_marked_as_such():
    for filename, name in TEST_HOOKS.items():
        text = (APP / filename).read_text(encoding="utf-8")
        assert re.search(rf"# TEST HOOK \(#661\)[^\n]*\n(?:@[^\n]*\n)*def {name}\(", text), (filename, name)


def test_the_marked_hooks_are_really_called_only_by_tests():
    for filename, name in TEST_HOOKS.items():
        calls = []
        for path in APP.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call)
                        and (getattr(node.func, "attr", None) == name or getattr(node.func, "id", None) == name)):
                    calls.append(path.name)
        # a hook may call itself or be called by a sibling hook in its own file; never from app code
        assert all(c == filename for c in calls), (name, calls)


@pytest.mark.skipif(not vulture_available, reason="vulture is installed by the CI lint job, not the test shards")
def test_the_app_has_no_dead_code_at_80_with_the_whitelist():
    done = subprocess.run([sys.executable, "-m", "vulture", str(APP), str(WHITELIST), "--min-confidence", "80"],
                          capture_output=True, text=True, cwd=REPO)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(not vulture_available, reason="vulture is installed by the CI lint job, not the test shards")
def test_the_check_reports_a_new_unused_variable_and_the_whitelist_silences_a_listed_one(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(mtime_ns, fresh_unused):\n    return 1\n", encoding="utf-8")
    plain = subprocess.run([sys.executable, "-m", "vulture", str(bad), "--min-confidence", "80"],
                           capture_output=True, text=True)
    assert plain.returncode != 0 and "fresh_unused" in plain.stdout and "mtime_ns" in plain.stdout
    listed = subprocess.run([sys.executable, "-m", "vulture", str(bad), str(WHITELIST), "--min-confidence", "80"],
                            capture_output=True, text=True)
    assert "fresh_unused" in listed.stdout and "mtime_ns" not in listed.stdout


def test_the_functions_removed_in_this_sweep_are_gone_and_nothing_imports_them():
    gone = {"absence.py": ["not_found_text", "is_unrecognised"], "access.py": ["grant_uploaded_document_to_owner"],
            "chat_answers.py": ["_engine_label"], "keyword.py": ["drop_document"], "lexical.py": ["uncovered_terms"],
            "submittal_review.py": ["_new_id"], "synthesis.py": ["_figures_with_units"],
            "answer.py": ["figure_conflict"], "extract.py": ["PageResult"], "ocr.py": ["PageOCR"],
            "schemas.py": ["KeywordSearchResult"]}
    for filename, names in gone.items():
        defined = {n.name for n in ast.parse((APP / filename).read_text(encoding="utf-8")).body
                   if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        assert not defined & set(names), (filename, defined & set(names))


def test_the_scripts_that_nothing_references_are_listed_as_tools():
    text = (REPO / "scripts" / "README.md").read_text(encoding="utf-8")
    for script in ("b4_before_after.py", "backfill_standard_metadata.py", "bench_vector_store.py",
                   "verify_crs_numbers_on_real_runs.py", "verify_geometry_ocr_guard_on_real_docs.py"):
        assert script in text and (REPO / "scripts" / script).exists()
