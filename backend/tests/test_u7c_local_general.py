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
    agent_review_local,
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
from app.aim_review import budget, local_model, material, paper, prompts
from app.aim_review import engine as method_engine
from app.config import settings
from app.main import app
from tests.test_aim_dry_run import PAPERS, _ledger_lines, dry  # noqa: F401 - fixture
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture

REPORTED = "invented-local:1b"
#: An answer that holds every step's answer key (the parse of the answer is the method's, not under test here).
ANY_ANSWER = json.dumps(
    {k: [] for k in sorted(set().union(*prompts.ANSWER_KEYS.values()))}
)


@pytest.fixture(autouse=True)
def unloaded(monkeypatch) -> list[str]:
    """The engine's model description (a model that does not think) and the unloads, without any engine."""
    gone: list[str] = []
    monkeypatch.setattr(
        local_model, "_show", lambda name: {"capabilities": ["completion"]}
    )
    monkeypatch.setattr(local_model, "_unload", gone.append)
    return gone


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
        # a model that does not think is not sent the thinking switch
        assert path == "/api/chat" and body["format"] == "json" and "think" not in body
        bodies.append(body)
        kw = asked.kw
        out = fake.fake_answer(kw["step"], kw.get("cached") or "", kw["prompt"])
        return {
            "model": REPORTED,
            "message": {"role": "assistant", "content": json.dumps(out)},
            # a count the whole request can have (at least its fewest tokens)
            "prompt_eval_count": 1
            + agent_review_local.lower_bound_tokens(
                "\n".join(m["content"] for m in body["messages"])
            ),
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
    monkeypatch.setattr(aim_review_jobs, "local_ready", lambda _model: None)
    paper_id = PAPERS["datasheet"][0]
    before = _ledger_lines()
    run_id = _start_local(world, paper_id)
    worker = job_queue.worker_id()
    job_id = aim_review_jobs.claim_next(worker)
    assert (
        aim_review_jobs.run(job_id, worker) == job_queue.DONE
    )  # the shipped path: the job builds the local model itself
    assert bodies, "no call reached the local engine"
    # the window is sized to hold the whole paper (no blind chunking), the same for every call of the run
    window = budget.for_paper(aim_review_jobs.paper_tokens(db.connect(), paper_id))
    assert all(
        b["options"]["num_ctx"] == window.num_ctx
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
    assert any(
        c.startswith("name: " + REPORTED) for c in cells
    )  # the model of each step
    judge = [c for c in model_calls if c["step"] == "aim_judge"]
    assert judge and all(c["note"].endswith("the whole paper") for c in judge)
    assert "The judge saw the whole paper" in page["measured"]["sentence"]


def test_a_local_run_that_is_not_ready_stops_with_the_sentence_and_loads_nothing(
    world, monkeypatch
):
    _no_claude(monkeypatch)

    def no_load(*_a, **_k):
        raise AssertionError(
            "the local engine was called although the run was not ready"
        )

    monkeypatch.setattr(model_transport, "post_json", no_load)
    monkeypatch.setattr(
        aim_review_jobs, "local_ready", lambda _model: "an invented reason"
    )
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


def _engine(
    monkeypatch,
    *,
    installed,
    loaded,
    free=60_000_000_000,
    holder=None,
    size=9_000_000_000,
):
    def get_json(path, *, timeout, required=True):
        return {
            "/api/tags": {"models": [{"name": n, "size": size} for n in installed]},
            "/api/ps": {"models": loaded},
        }[path]

    monkeypatch.setattr(model_transport, "get_json", get_json)
    monkeypatch.setattr(heavy_lock, "read", lambda path=None: holder)
    monkeypatch.setattr(local_model, "_free_bytes", lambda: free)


def test_readiness_one_model_in_memory_never_the_35b_and_its_need_plus_6_gb(
    monkeypatch,
):
    ours, other = "invented-mid:14b", "invented-other:12b"
    _engine(monkeypatch, installed=[ours], loaded=[])
    assert local_model.readiness([ours], 32_768) is None
    _engine(
        monkeypatch,
        installed=[ours],
        loaded=[{"name": ours, "size": 9_000_000_000}],
        free=1,
    )
    assert (
        local_model.readiness([ours], 32_768) is None
    )  # already in memory: nothing new is loaded
    _engine(
        monkeypatch,
        installed=[ours, other],
        loaded=[{"name": other, "size": 8_000_000_000}],
    )
    assert local_model.readiness([ours], 32_768) == local_model.OTHER_LOADED.format(
        name=other
    )
    _engine(
        monkeypatch,
        installed=[ours],
        loaded=[{"name": "invented-small:1b", "size": 1_000_000_000}],
    )
    assert (
        local_model.readiness([ours], 32_768) is None
    )  # a small helper model may stay
    # need = the 9 GB file + the window's cache (163,840 bytes x 32,768 tokens = 5.4 GB); plus 6 GB to spare = 20.4 GB
    _engine(monkeypatch, installed=[ours], loaded=[], free=20_000_000_000)
    words = local_model.readiness([ours], 32_768)
    assert (
        words.startswith("this computer has 20.0 GB of memory free")
        and "needs 14.4 GB" in words
    )
    _engine(monkeypatch, installed=[ours], loaded=[], free=20_500_000_000)
    assert local_model.readiness([ours], 32_768) is None
    _engine(monkeypatch, installed=["invented-big:35b"], loaded=[], size=23_000_000_000)
    assert local_model.readiness(["invented-big:35b"]) == local_model.TOO_LARGE.format(
        name="invented-big:35b"
    )
    _engine(monkeypatch, installed=[other], loaded=[])
    assert local_model.readiness([ours]) == local_model.NOT_INSTALLED.format(name=ours)
    _engine(
        monkeypatch,
        installed=[ours],
        loaded=[],
        holder={"kind": "tests", "started": 9e12},
    )
    monkeypatch.setattr(heavy_lock, "is_stale", lambda r, now=None: False)
    assert local_model.readiness([ours]) == local_model.LOCK_HELD.format(who="tests")

    def down(*_a, **_k):
        raise model_transport.httpx.ConnectError("invented")

    monkeypatch.setattr(heavy_lock, "read", lambda path=None: None)
    monkeypatch.setattr(model_transport, "get_json", down)
    assert local_model.readiness([ours]) == local_model.ENGINE_DOWN


def test_the_cache_per_token_is_read_from_the_engines_own_model_description():
    info = {
        "model_info": {
            "x.block_count": 40,
            "x.attention.head_count_kv": 8,
            "x.attention.key_length": 128,
        }
    }
    assert local_model.kv_bytes_per_token(info) == 40 * 8 * 128 * 4
    assert local_model.kv_bytes_per_token({}) == local_model.DEFAULT_KV_BYTES_PER_TOKEN


def test_the_window_holds_the_whole_paper_and_is_raised_never_cut():
    """Owner's standing lesson (25 Nov 2026): no blind chunking. An ordinary datasheet fits whole; a long paper gets the largest
    window, and only above it is it judged in page windows (each judge call says so)."""
    small, sheet, long = (
        budget.for_paper(6_000),
        budget.for_paper(14_000),
        budget.for_paper(90_000),
    )
    # half again for a tokenizer that counts more than the app's estimate (the 14B does)
    assert small.num_ctx == 28_672 and small.window_tokens >= 9_000
    assert sheet.num_ctx == 40_960 and sheet.window_tokens >= 21_000
    assert long.num_ctx == budget.MAX_CTX and long.window_tokens < 90_000
    pages = dict.fromkeys(
        range(1, 8), "word " * 2400
    )  # 7 pages, about 3,000 tokens each by the window count
    with budget.using(budget.for_paper(sum(len(t) // 4 for t in pages.values()) + 200)):
        assert len(paper.windows(paper.Paper(paper_id="p", pages=pages), None)) == 1


def test_each_step_may_name_its_own_local_model_and_one_model_is_in_memory_at_a_time(
    monkeypatch, unloaded
):
    monkeypatch.setattr(
        settings,
        "general_review_local_step_models",
        "judge = invented-small:9b, nonsense=x, editor=",
    )
    assert local_model.step_models() == {
        "aim_judge": "invented-small:9b",
        "aim_reference": "invented-small:9b",
        "aim_answered": "invented-small:9b",
    }
    asked = []
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, *, timeout: (
            asked.append(body["model"])
            or {
                "model": body["model"],
                "message": {"content": ANY_ANSWER},
                "prompt_eval_count": 5,
                "done_reason": "stop",
            }
        ),
    )
    m = local_model.LocalModel("invented-mid:14b")
    assert m.names() == ["invented-mid:14b", "invented-small:9b"]
    kw = {
        "model": "x",
        "system": "s",
        "cached": "c",
        "prompt": "p",
        "carries": set(),
        "max_tokens": 8,
    }
    m.ask(step="aim_identify", **kw)
    m.ask(step="aim_judge", **kw)
    m.ask(step="aim_edit", **kw)
    assert asked == ["invented-mid:14b", "invented-small:9b", "invented-mid:14b"]
    assert unloaded == [
        "invented-mid:14b",
        "invented-small:9b",
    ]  # the one loaded leaves before the next is asked
    m.unload()
    assert unloaded[-1] == "invented-mid:14b" and m.loaded is None


def test_a_thinking_model_is_told_not_to_think(monkeypatch):
    monkeypatch.setattr(
        local_model, "_show", lambda name: {"capabilities": ["completion", "thinking"]}
    )
    sent = []
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, *, timeout: (
            sent.append(body)
            or {
                "model": "m",
                "message": {"content": '{"kind": "x"}'},
                "prompt_eval_count": 5,
                "done_reason": "stop",
            }
        ),
    )
    local_model.LocalModel("invented-small:9b").ask(
        step="aim_identify",
        model="x",
        system="s",
        cached="c",
        prompt="p",
        carries=set(),
        max_tokens=8,
    )
    assert sent[0]["think"] is False


def test_the_model_socket_offers_claude_and_local_and_refuses_an_unapproved_vendor_without_any_network(
    monkeypatch,
):
    from app.aim_review import model_socket as MS

    assert MS.selectable("claude")[0] and MS.selectable("local")[0]
    assert MS.selectable("openai_compatible") == (False, MS.NOT_APPROVED)
    assert MS.selectable("anything else")[0] is False

    def no_network(*_a, **_k):
        raise AssertionError("the unapproved slot reached the network")

    monkeypatch.setattr(model_transport, "post_json", no_network)
    monkeypatch.setattr(reader_transport, "transport", no_network)
    slot = MS.model_for_run("openai_compatible")
    with pytest.raises(method_engine.StepFailed) as got:
        slot.ask(
            step="aim_identify",
            model="x",
            system="s",
            cached="c",
            prompt="p",
            carries=set(),
            max_tokens=8,
        )
    assert got.value.stops_run and MS.NOT_APPROVED in str(got.value)
    local = MS.model_for_run("local", paper_tokens=14_000)
    assert local.engine == "local" and local.budget.num_ctx == 40_960
    imported = set()
    for node in ast.walk(ast.parse(Path(MS.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            imported |= {node.module or "", *(a.name for a in node.names)}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert not imported & {
        "httpx",
        "socket",
        "requests",
        "urllib",
        "model_transport",
        "reader_transport",
    }


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


def test_a_prompt_counted_longer_than_the_estimate_is_no_cut_but_one_filling_the_window_is():
    """The 14B's tokenizer counted 8,087 tokens where the app's estimate allowed less: that is no cut. A count that reaches the
    room the window leaves, or one shorter than the text can be, is."""
    text = "word " * 400  # 2,000 characters
    assert local_model._prompt_cut(8_087, 28_672, 512, text) is False
    assert local_model._prompt_cut(28_672 - 512 - 10, 28_672, 512, text) is True
    assert local_model._prompt_cut(3, 28_672, 512, text) is True
    assert local_model._prompt_cut(None, 28_672, 512, text) is True
