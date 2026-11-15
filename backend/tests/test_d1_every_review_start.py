"""D1 (R50f N1): every place that can queue a review or an AI review is listed here, with the guard it carries. A new caller of the two
enqueue functions fails this test until it is added with its guard (the list of what will leave is shown first, or it is local only)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, review_engine
from app.config import settings
from app.main import app
from tests.test_b1_review_engine import open_facts
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

APP = Path(__file__).resolve().parents[1] / "app"
ENQUEUE_MODULES = {
    "review_jobs",
    "review_jobs_mod",
    "agent_review_jobs",
    "agent_review_jobs_mod",
}

#: (file, function) -> the text its body must carry: what makes that start show the list or stay local.
EXPECTED = {
    (
        "review_engine_start.py",
        "start",
    ): "LIST_NOT_SHOWN",  # POST /api/reviews/start: the list is required when text would leave
    (
        "review_engine_start.py",
        "_enqueue_ai",
    ): "shown_ids",  # the AI run after the rule check inherits the run's stored list
    (
        "main.py",
        "start_review_run",
    ): "legacy_start_blocked",  # POST /api/reviews/run: local only (refused on an open Claude lane)
    (
        "api/agent_review.py",
        "start_agent_run",
    ): "legacy_start_blocked",  # POST /api/reviews/agent-run: the same
}


def _enqueue_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(the local names that stand for the two review job modules, the local names that stand for their `enqueue` function), whatever
    the import: `from . import review_jobs as rj`, `import app.review_jobs as rj`, `from .review_jobs import enqueue as go`."""
    modules, functions = set(ENQUEUE_MODULES), set()
    short = {m.removesuffix("_mod") for m in ENQUEUE_MODULES}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in short:
                    modules.add(alias.asname or alias.name)
                if (node.module or "").split(".")[
                    -1
                ] in short and alias.name == "enqueue":
                    functions.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in short:
                    modules.add(alias.asname or alias.name.split(".")[-1])
    return modules, functions


def _callers() -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for path in sorted(APP.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        source = text.splitlines()
        modules, functions = _enqueue_names(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                f = getattr(call, "func", None)
                via_module = (
                    isinstance(f, ast.Attribute)
                    and f.attr == "enqueue"
                    and isinstance(f.value, ast.Name)
                    and f.value.id in modules
                )
                bare = isinstance(f, ast.Name) and f.id in functions
                if via_module or bare:
                    found[(str(path.relative_to(APP)), fn.name)] = "\n".join(
                        source[fn.lineno - 1 : fn.end_lineno]
                    )
    return found


def test_every_caller_of_the_review_enqueue_functions_is_known_and_carries_its_guard():
    callers = _callers()
    assert set(callers) == set(EXPECTED), (
        f"a new way to queue a review: {sorted(set(callers) ^ set(EXPECTED))}"
    )
    for key, token in EXPECTED.items():
        assert token in callers[key], f"{key} no longer carries {token}"


def test_the_scan_sees_an_aliased_module_a_bare_import_and_a_module_import():
    """The scan itself is not blind: each of these ways of calling `enqueue` is found."""
    for code in (
        "from . import review_jobs as rj\ndef f():\n    rj.enqueue(1)\n",
        "from .review_jobs import enqueue\ndef f():\n    enqueue(1)\n",
        "from .agent_review_jobs import enqueue as go\ndef f():\n    go(1)\n",
        "import app.agent_review_jobs as aj\ndef f():\n    aj.enqueue(1)\n",
    ):
        modules, functions = _enqueue_names(ast.parse(code))
        hits = [
            c
            for c in ast.walk(ast.parse(code))
            if isinstance(c, ast.Call)
            and (
                (
                    isinstance(c.func, ast.Attribute)
                    and c.func.attr == "enqueue"
                    and isinstance(c.func.value, ast.Name)
                    and c.func.value.id in modules
                )
                or (isinstance(c.func, ast.Name) and c.func.id in functions)
            )
        ]
        assert hits, code


def test_only_the_two_enqueue_modules_insert_review_jobs():
    from app import agent_review_jobs, review_jobs

    stages = {review_jobs.STAGE, agent_review_jobs.STAGE}
    for name in ("review_jobs.py", "agent_review_jobs.py"):
        assert "INSERT INTO jobs" in (APP / name).read_text(encoding="utf-8")
    others = []
    for p in APP.rglob("*.py"):
        if p.name in {"review_jobs.py", "agent_review_jobs.py"}:
            continue
        text = p.read_text(encoding="utf-8")
        if "INSERT INTO jobs" in text and (
            any(f'"{st}"' in text or f"'{st}'" in text for st in stages)
            or "review_jobs.STAGE" in text
            or "agent_review_jobs.STAGE" in text
        ):
            others.append(str(p.relative_to(APP)))
    assert others == [], f"a raw job insert that may queue a review: {others}"


def test_the_agent_run_route_is_refused_on_an_open_claude_lane_with_one_plain_sentence(
    world, monkeypatch
):  # noqa: F811
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    before = db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    r = TestClient(app).post(
        "/api/reviews/agent-run",
        json={"submittal_document_id": world["sub"]},
        headers=world["admin"],
    )
    assert (
        r.status_code == 409
        and "start from the review page: it shows what will be sent" in r.text
    )
    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == before


def test_the_agent_run_route_still_serves_a_run_when_nothing_can_leave(
    world, monkeypatch
):  # noqa: F811
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(lane_open=False), None)
    )
    r = TestClient(app).post(
        "/api/reviews/agent-run",
        json={"submittal_document_id": world["sub"]},
        headers=world["admin"],
    )
    assert r.status_code != 409 or "start from the review page" not in r.text
