"""Builder C (planner 25 Nov 2026 22:35): Local only runs the GENERAL review on the local model. A loopback stand-in answers for
the local engine (no model is loaded, nothing leaves the machine); the Claude lane is wired to fail the test if it is ever reached.
Invented papers and values only (the dry-run library of `test_aim_dry_run`)."""

from __future__ import annotations

import ast
import io
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import (
    agent_claude,
    aim_review_gate,
    aim_review_jobs,
    aim_review_store,
    db,
    heavy_lock,
    job_queue,
    model_transport,
    reader_transport,
    reasoning_provider,
    review_engine,
)
from app.aim_review import budget, local_model, material, paper
from app.aim_review import engine as method_engine
from app.main import app
from tests.test_aim_dry_run import PAPERS, _ledger_lines, dry  # noqa: F401 - fixture
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture

REPORTED = "invented-local:1b"


@pytest.fixture
def world(dry):  # noqa: F811 - the dry-run library and its signed-in admin
    return dry


def _no_claude(monkeypatch) -> None:
    def opened(*_a, **_k):
        raise AssertionError("a Local only run reached the Claude lane")

    monkeypatch.setattr(reader_transport, "transport", opened)
    monkeypatch.setattr(agent_claude, "_send_once", opened)
    monkeypatch.setattr(agent_claude, "_request", opened)


def _stand_in_engine(monkeypatch, kind: str) -> list[dict]:
    """The local engine, answered by the method's fake answers for the step being asked (no model)."""
    fake = method_engine.FakeModel(kind=kind, subject_key=f"local_{kind}")
    asked = threading.local()
    real_ask = local_model.LocalModel.ask
    bodies: list[dict] = []

    def ask(self, **kw):
        asked.kw = kw
        return real_ask(self, **kw)

    def post_json(path, body, *, timeout):
        # inside the run: barred from Claude, and the lane itself says so
        assert review_engine.claude_barred()
        assert (
            reasoning_provider._lane_unavailable()[0]
            == reasoning_provider.UNAVAILABLE_RUN_LOCAL
        )
        assert (
            path == "/api/chat" and body["format"] == "json" and body["think"] is False
        )
        bodies.append(body)
        kw = asked.kw
        out = fake.fake_answer(kw["step"], kw.get("cached") or "", kw["prompt"])
        return {
            "model": REPORTED,
            "message": {"role": "assistant", "content": json.dumps(out)},
            "prompt_eval_count": 50,
            "eval_count": 5,
            "done_reason": "stop",
        }

    monkeypatch.setattr(local_model.LocalModel, "ask", ask)
    monkeypatch.setattr(model_transport, "post_json", post_json)
    return bodies


def _start_local(w, paper_id: str) -> str:
    client = TestClient(app)
    plan = client.get(
        "/api/reviews/plan",
        params={"submittal_document_id": paper_id, "engine": "local"},
        headers=w["headers"],
    ).json()
    assert plan["refused"] is None and plan["text_leaves"] is False
    assert (
        plan["documents"]["leaving"] == []
        and aim_review_gate.LOCAL_PLAN_WORDS in plan["sentence"]
    )
    r = client.post(
        "/api/reviews/start",
        json={
            "submittal_document_id": paper_id,
            "engine": "local",
            "shown_document_ids": [],
        },
        headers=w["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()["review_run_id"]


def test_a_local_only_general_review_runs_on_the_local_model_and_opens_no_claude_path(
    world, monkeypatch
):
    _no_claude(monkeypatch)
    bodies = _stand_in_engine(monkeypatch, "datasheet")
    monkeypatch.setattr(aim_review_jobs, "local_ready", lambda: None)
    paper_id = PAPERS["datasheet"][0]
    before = _ledger_lines()
    run_id = _start_local(world, paper_id)
    worker = job_queue.worker_id()
    job_id = aim_review_jobs.claim_next(worker)
    assert (
        aim_review_jobs.run(job_id, worker) == job_queue.DONE
    )  # the shipped path: the job builds the local model itself
    assert bodies, "no call reached the local engine"
    assert all(
        b["options"]["num_ctx"] == budget.LOCAL.num_ctx
        and b["options"]["num_predict"] <= budget.LOCAL.max_tokens
        for b in bodies
    )
    run = _run_row(run_id)
    calls = [
        c
        for c in json.loads(run["calls_json"])
        if c.get("step") not in ("read", "ledger")
    ]
    model_calls = [c for c in calls if "engine" in c]
    assert model_calls and all(
        c["engine"] == "local" and c["model"] == REPORTED and c["usd"] == 0
        for c in model_calls
    )
    assert run["usd"] == 0 and _ledger_lines() == before  # USD 0: not one spend line
    assert aim_review_store.lines(db.connect(), run_id)  # the same method's points
    saved = (
        db.connect()
        .execute(f"SELECT COUNT(*) FROM {aim_review_store.CHECKLISTS}")
        .fetchone()[0]
    )
    assert (
        saved == 0
    )  # a checklist the local model wrote is used for this run only, never saved for later Claude runs
    client = TestClient(app)
    page = client.get(
        f"/api/reviews/papers/{paper_id}/general", headers=world["headers"]
    ).json()
    assert page["engine"]["local"] is True and page["engine"]["models"] == [
        REPORTED
    ]  # from the run, never the setting
    assert (
        aim_review_gate.LOCAL_NOT_SCORED in page["measured"]["sentence"]
        and page["measured"]["found"] is None
    )
    sheet = client.get(
        f"/api/reviews/papers/{paper_id}/general/sheet", headers=world["headers"]
    )
    wb = load_workbook(io.BytesIO(sheet.content), read_only=True)
    cells = [
        str(v)
        for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for v in row
        if v
    ]
    assert any(REPORTED in c and aim_review_gate.LOCAL_NOT_SCORED in c for c in cells)


def test_a_local_run_that_is_not_ready_stops_with_the_sentence_and_loads_nothing(
    world, monkeypatch
):
    _no_claude(monkeypatch)

    def no_load(*_a, **_k):
        raise AssertionError(
            "the local engine was called although the run was not ready"
        )

    monkeypatch.setattr(model_transport, "post_json", no_load)
    monkeypatch.setattr(aim_review_jobs, "local_ready", lambda: "an invented reason")
    paper_id = PAPERS["datasheet"][0]
    run_id = _start_local(world, paper_id)
    worker = job_queue.worker_id()
    assert (
        aim_review_jobs.run(aim_review_jobs.claim_next(worker), worker)
        == job_queue.DONE
    )
    run = _run_row(run_id)
    assert (
        run["status"] == "stopped"
        and run["stop_reason"] == "local_not_ready: an invented reason"
    )
    page = (
        TestClient(app)
        .get(f"/api/reviews/papers/{paper_id}/general", headers=world["headers"])
        .json()
    )
    assert page["engine"]["local"] is True and page["engine"]["models"] == []


def test_the_local_class_never_imports_the_claude_lane():
    src = Path(local_model.__file__).read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            names |= {a.name for a in node.names} | {node.module or ""}
        elif isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
    assert not names & {
        "reader_transport",
        "agent_claude",
        "claude_spend",
        "claude_approved",
        "app.reader_transport",
    }
    assert "model_transport" in names


def _engine(monkeypatch, *, installed, loaded, free=40_000_000_000, holder=None):
    def get_json(path, *, timeout, required=True):
        return {
            "/api/tags": {"models": [{"name": n} for n in installed]},
            "/api/ps": {"models": loaded},
        }[path]

    monkeypatch.setattr(model_transport, "get_json", get_json)
    monkeypatch.setattr(heavy_lock, "read", lambda path=None: holder)
    monkeypatch.setattr(local_model, "_free_bytes", lambda: free)


def test_readiness_one_large_model_at_a_time_and_enough_memory_to_load(monkeypatch):
    ours, other = "invented-big:35b", "invented-other:30b"
    _engine(monkeypatch, installed=[ours], loaded=[])
    assert local_model.readiness(ours) is None
    _engine(
        monkeypatch,
        installed=[ours],
        loaded=[{"name": ours, "size": 24_000_000_000}],
        free=1,
    )
    assert (
        local_model.readiness(ours) is None
    )  # already in memory: nothing new is loaded
    _engine(
        monkeypatch,
        installed=[ours, other],
        loaded=[{"name": other, "size": 20_000_000_000}],
    )
    assert local_model.readiness(ours) == local_model.OTHER_LARGE.format(name=other)
    _engine(
        monkeypatch,
        installed=[ours],
        loaded=[{"name": "invented-small:1b", "size": 1_000_000_000}],
    )
    assert local_model.readiness(ours) is None  # a small model is not a large one
    _engine(monkeypatch, installed=[ours], loaded=[], free=8_000_000_000)
    assert local_model.readiness(ours).startswith(
        "this computer has 8.0 GB of memory free"
    )
    # a smaller model needs half its own file size and a margin free (here 8 GB in all: 4 GB to start)
    tags = {"models": [{"name": "invented-mid:9b", "size": 6_000_000_000}]}
    answers = {"/api/tags": tags, "/api/ps": {"models": []}}
    monkeypatch.setattr(model_transport, "get_json", lambda p, **_k: answers[p])
    monkeypatch.setattr(local_model, "_free_bytes", lambda: 5_000_000_000)
    assert local_model.readiness("invented-mid:9b") is None
    monkeypatch.setattr(local_model, "_free_bytes", lambda: 3_000_000_000)
    assert "at least 4.0 GB" in local_model.readiness("invented-mid:9b")
    _engine(monkeypatch, installed=[other], loaded=[])
    assert local_model.readiness(ours) == local_model.NOT_INSTALLED.format(name=ours)
    _engine(
        monkeypatch,
        installed=[ours],
        loaded=[],
        holder={"kind": "tests", "started": 9e12},
    )
    monkeypatch.setattr(heavy_lock, "is_stale", lambda r, now=None: False)
    assert local_model.readiness(ours) == local_model.LOCK_HELD.format(who="tests")

    def down(*_a, **_k):
        raise model_transport.httpx.ConnectError("invented")

    monkeypatch.setattr(heavy_lock, "read", lambda path=None: None)
    monkeypatch.setattr(model_transport, "get_json", down)
    assert local_model.readiness(ours) == local_model.ENGINE_DOWN


def test_a_prompt_that_does_not_fit_is_never_sent_and_a_cut_prompt_is_never_used(
    monkeypatch,
):
    sent = []
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, *, timeout: sent.append(body) or {},
    )
    tiny = budget.Budget(**{**budget.LOCAL.__dict__, "num_ctx": 600})
    m = local_model.LocalModel("invented-big:35b", budget=tiny)
    with pytest.raises(method_engine.StepFailed, match="local_too_long"):
        m.ask(
            step="aim_identify",
            model="x",
            system="s",
            cached="word " * 400,
            prompt="p",
            carries=set(),
            max_tokens=64,
        )
    assert sent == []  # never sent
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, *, timeout: {
            "model": REPORTED,
            "message": {"content": '{"kind": "datasheet"}'},
        },
    )
    with pytest.raises(
        method_engine.StepFailed, match="local_cut"
    ):  # the engine did not say how much it read
        local_model.LocalModel("invented-big:35b").ask(
            step="aim_identify",
            model="x",
            system="s",
            cached="c",
            prompt="p",
            carries=set(),
            max_tokens=64,
        )


def test_an_engine_that_is_down_stops_the_run_and_a_timeout_fails_one_step(monkeypatch):
    def down(path, body, *, timeout):
        raise model_transport.httpx.ConnectError("invented")

    monkeypatch.setattr(model_transport, "post_json", down)
    with pytest.raises(method_engine.StepFailed) as got:
        local_model.LocalModel("m").ask(
            step="s1",
            model="x",
            system="s",
            cached="c",
            prompt="p",
            carries=set(),
            max_tokens=8,
        )
    assert got.value.stops_run

    def slow(path, body, *, timeout):
        raise model_transport.httpx.ReadTimeout("invented")

    monkeypatch.setattr(model_transport, "post_json", slow)
    with pytest.raises(method_engine.StepFailed) as got:
        local_model.LocalModel("m").ask(
            step="s1",
            model="x",
            system="s",
            cached="c",
            prompt="p",
            carries=set(),
            max_tokens=8,
        )
    assert not got.value.stops_run and "local_timeout" in str(got.value)


def test_the_local_sizes_are_smaller_and_a_claude_run_keeps_the_methods_own_sizes():
    assert (
        budget.cap(material.BATCH_CHARS, "batch_chars") == material.BATCH_CHARS
    )  # no profile: unchanged
    rows = [
        {"page_of": "B1", "book_id": "b", "page": n, "page_text": "x" * 9_000}
        for n in range(12)
    ]
    claude_batches = material._batches(rows)
    many = paper.Paper(paper_id="p", pages=dict.fromkeys(range(1, 13), "word " * 3000))
    claude_windows = paper.windows(many, None)
    with budget.using(budget.LOCAL):
        assert (
            budget.is_local()
            and budget.cap(material.BATCH_CHARS, "batch_chars")
            == budget.LOCAL.batch_chars
        )
        local_batches = material._batches(rows)
        assert len(paper.windows(many, None)) > len(claude_windows)
        assert (
            method_engine.gate_checker()("any book") is None
        )  # nothing is sent: no book is held back for the send gate
    assert len(local_batches) > len(claude_batches)
    assert not budget.is_local()
    assert (
        "engine"
        not in method_engine.CallRecord(step="s", model="m", prompt_chars=1).as_dict()
    )  # Claude calls unchanged


def _run_row(run_id: str) -> dict:
    row = (
        db.connect()
        .execute(f"SELECT * FROM {aim_review_store.RUNS} WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    return dict(row)


def test_swap_growing_more_than_one_gb_during_the_run_stops_it(monkeypatch):
    """The owner's memory rule: measured from the run's first call; the lines already judged are kept by the method."""
    swap = [2_000_000_000]
    monkeypatch.setattr(local_model, "_swap_bytes", lambda: swap[0])
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, *, timeout: {
            "model": REPORTED,
            "message": {"content": '{"kind": "datasheet"}'},
            "prompt_eval_count": 5,
            "done_reason": "stop",
        },
    )
    m = local_model.LocalModel("invented-big:35b")
    ask = {
        "step": "aim_identify",
        "model": "x",
        "system": "s",
        "cached": "c",
        "prompt": "p",
        "carries": set(),
        "max_tokens": 64,
    }
    assert m.ask(**ask) == {"kind": "datasheet"}
    swap[0] += 900_000_000
    assert m.ask(**ask) == {"kind": "datasheet"}  # under 1 GB more: goes on
    swap[0] += 200_000_000
    with pytest.raises(method_engine.StepFailed) as got:
        m.ask(**ask)
    assert got.value.stops_run and "local_swap" in str(got.value)
