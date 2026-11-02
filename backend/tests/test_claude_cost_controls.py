"""Cost controls on the Claude lane (#805 plan change 6 E, #1584): USD 100 a day on every route, and spend per step
from settled ledger lines. Fake transports only: no socket, no real call, no local model.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
import re
import runpy
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import (
    access,
    claude_api,
    claude_recheck,
    claude_spend,
    claude_spend_report,
    datasheet_ai,
    db,
    match_claude,
    reader_transport,
    review_audit,
    review_audit_rows,
    submittal_review,
    vision_reader,
)
from app import reasoning_provider as rp
from app.ai import output_limits
from app.config import settings
from app.main import app

MODEL = "claude-sonnet-5-5"
ANSWER = '{"answer": "yes"}'
USAGE = {"input_tokens": 1000, "output_tokens": 500}
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "cost.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "answers")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 500.0)
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", True)
    monkeypatch.setattr(settings, "match_engine", "claude")
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _at(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(UTC)


def _write(*lines: dict) -> None:
    with Path(settings.claude_spend_log).open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _settled(usd, *, step="other-step", when=None, **kw) -> dict:
    return {
        "at": _at(when or _now()),
        "step": step,
        "model": MODEL,
        "cost_usd": usd,
        "settles": kw.pop("settles", "r-" + str(id(kw))),
        **kw,
    }


def _hold(usd, *, step="other-step", when=None, **kw) -> dict:
    return {
        "at": _at(when or _now()),
        "step": step,
        "model": MODEL,
        "cost_usd": usd,
        "estimated": True,
        "reserved": True,
        "reservation": kw.pop("reservation", "h-" + str(id(kw))),
        **kw,
    }


def _send(url, *, headers, body, timeout):
    _send.calls.append(body)
    return {
        "model": body["model"],
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": ANSWER}],
        "usage": USAGE,
    }


@pytest.fixture
def sent():
    _send.calls = []
    return _send.calls


def _settle(held, usage):
    return claude_spend.settle(held, usage=usage, finish_reason="stop")


def _packet(prompt="Is it?", **kw):
    return rp.Packet(prompt=prompt, num_ctx=4096, num_predict=200, step="a-step", **kw)


# ---------------------------------------------- one check on every route


def _lane_metered():
    call = output_limits.model_call_for(
        claude_spend.metered(_send, "a-step"), output_limits.ROUTE_MATCH
    )
    return call("which?")


def _lane_reason():
    return rp.ClaudeProvider(MODEL, transport=_send).reason(_packet())


def _lane_stream():
    def stream(url, *, headers, body, timeout, cancel=None):
        _send.calls.append(body)
        yield {"type": "message_start", "message": {"model": MODEL, "usage": USAGE}}
        yield {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        }

    provider = rp.ClaudeProvider(MODEL, stream_transport=stream)
    return provider.stream(_packet(), lambda piece: None)


class _Batches:
    def batch_create(self, url, *, headers, requests):
        _send.calls.append(requests)
        return {"id": "b1", "processing_status": "ended", "results_url": "https://x"}

    def batch_retrieve(self, url, batch_id, *, headers):
        raise AssertionError("the batch had ended")

    def batch_results(self, url, *, headers):
        return []


def _lane_batch():
    return rp.ClaudeProvider(MODEL).reason_batch([_packet()], client=_Batches())


def _lane_matcher(monkeypatch):
    monkeypatch.setattr(reader_transport, "transport", lambda: _send)
    return match_claude.ask_claude_for_a_pair("which pair?")


def _lane_datasheet_reader(monkeypatch):
    monkeypatch.setattr(reader_transport, "transport", lambda: _send)
    monkeypatch.setattr(datasheet_ai, "engine_setting", lambda: "claude")
    call, why = datasheet_ai._claude_call()
    assert why is None
    return call("read this page")


def _lane_review_route(monkeypatch):
    monkeypatch.setattr(reader_transport, "transport", lambda: _send)
    call, _transport = claude_api._model_call_or_409(claude_api.STEP_RECHECK)
    return call("agree?")


LANES = {
    "metered": lambda _m: _lane_metered(),
    "reasoning_provider": lambda _m: _lane_reason(),
    "chat_stream": lambda _m: _lane_stream(),
    "batch": lambda _m: _lane_batch(),
    "matcher": _lane_matcher,
    "datasheet_reader": _lane_datasheet_reader,
    "claude_api_review_route": _lane_review_route,
}


@pytest.mark.parametrize("lane", LANES)
def test_the_day_cap_refuses_every_route_before_anything_is_sent(
    lane, monkeypatch, sent
):
    """Spend on ANOTHER step today, so only the day cap can refuse: the step and total caps have room."""
    _write(_settled(99.9999))
    before = claude_spend.spent()
    try:
        LANES[lane](monkeypatch)
    except claude_spend.BudgetExceeded as exc:
        assert "a day" in str(exc)
    except rp.ProviderRefused as exc:
        assert "a day" in str(exc)
    assert sent == [], f"{lane} sent past the day cap"
    assert claude_spend.spent() == before, "a refused call held something"


@pytest.mark.parametrize("lane", LANES)
def test_the_day_cap_binds_every_route_with_the_report_switch_off(
    lane, monkeypatch, sent
):
    """Owner, #1584: a day cannot exceed USD 100. The switch governs the report, not the cap."""
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", False)
    _write(_settled(99.9999))
    with contextlib.suppress(claude_spend.BudgetExceeded, rp.ProviderRefused):
        LANES[lane](monkeypatch)
    assert sent == [], f"{lane} sent past the day cap"


def test_under_the_cap_the_call_goes_out(sent):
    _write(_settled(50.0))
    assert _lane_metered() == ANSWER
    assert len(sent) == 1


def test_a_stored_answer_still_answers_at_the_cap(sent):
    """It costs nothing, so the cap has nothing to stop."""
    assert _lane_metered() == ANSWER
    _write(_settled(99.9999))
    assert _lane_metered() == ANSWER
    assert len(sent) == 1


def test_a_batch_cannot_pass_one_request_at_a_time_and_cross_the_cap_together():
    _write(_settled(99.0))
    with pytest.raises(claude_spend.BudgetExceeded, match="a day"):
        claude_spend.reserve_all([("a", 0.6), ("b", 0.6)], model=MODEL)
    assert sum(1 for e in claude_spend.entries() if e.get("reserved")) == 0
    assert claude_spend.reserve_all([("a", 0.5), ("b", 0.5)], model=MODEL)


def test_the_read_only_check_says_the_same():
    _write(_settled(99.9999))
    with pytest.raises(claude_spend.BudgetExceeded, match="a day"):
        claude_spend.ensure_affordable("a-step", 0.01)


# ---------------------------------------------- what the day counts


def test_settled_replaces_its_hold_and_an_open_hold_counts_at_its_worst_case():
    """THE DEFECT THIS GUARDS: settled and reserved both counted would charge a call twice."""
    held = claude_spend.reserve("a-step", 3.71, model=MODEL)
    assert claude_spend_report.charged_today(claude_spend.entries()) == pytest.approx(
        3.71
    )
    _settle(held, {"input_tokens": 175_000, "output_tokens": 0})
    assert claude_spend_report.charged_today(claude_spend.entries()) == pytest.approx(
        0.35
    )


def test_a_released_hold_counts_nothing():
    held = claude_spend.reserve("a-step", 3.71, model=MODEL)
    claude_spend.release(held, "unbilled")
    assert claude_spend_report.charged_today(claude_spend.entries()) == 0


def test_yesterdays_settled_spend_does_not_count_today():
    yesterday = _now() - timedelta(days=1)
    _write(_settled(99.0, when=yesterday), _settled(2.0))
    assert claude_spend_report.charged_today(claude_spend.entries()) == pytest.approx(
        2.0
    )


def test_a_hold_open_across_midnight_still_counts_and_a_dead_one_stops():
    """A batch may finish up to 24 hours after its hold; older, its process died."""
    young = _hold(4.0, when=_now() - timedelta(hours=23), reservation="y")
    dead = _hold(9.0, when=_now() - timedelta(hours=25), reservation="d")
    _write(young, dead)
    assert claude_spend_report.charged_today(claude_spend.entries()) == pytest.approx(
        4.0
    )
    assert claude_spend.spent() == pytest.approx(13.0), "the total keeps both"


def test_the_day_is_the_utc_day(monkeypatch):
    noon = datetime(2026, 11, 2, 12, tzinfo=UTC)
    monkeypatch.setattr(claude_spend_report, "_now", lambda: noon)
    _write(
        _settled(1.0, when=datetime(2026, 11, 2, 0, 0, tzinfo=UTC)),
        _settled(2.0, when=datetime(2026, 11, 1, 23, 59, tzinfo=UTC)),
        _settled(4.0, when=datetime(2026, 11, 3, 0, 0, tzinfo=UTC)),
    )
    assert claude_spend_report.charged_today(claude_spend.entries()) == pytest.approx(
        1.0
    )


def test_a_torn_ledger_line_fails_closed(sent):
    with Path(settings.claude_spend_log).open("a", encoding="utf-8") as fh:
        fh.write('{"at": "2026\n')
    assert claude_spend_report.charged_today(claude_spend.entries()) == pytest.approx(
        claude_spend.total_cap()
    )


def test_the_setting_narrows_the_owners_100_and_cannot_raise_it(monkeypatch, sent):
    monkeypatch.setattr(settings, "claude_budget_usd_per_day", 10.0)
    assert claude_spend_report.day_cap() == 10.0
    monkeypatch.setattr(settings, "claude_budget_usd_per_day", 1000.0)
    assert claude_spend_report.day_cap() == 100.0
    _write(_settled(100.0))
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$100\.00 a day"):
        _lane_metered()


def test_no_existing_cap_moved():
    defaults = type(settings)(_env_file=None)
    assert defaults.claude_budget_usd_per_step == 5.0
    assert defaults.claude_budget_usd_per_standard == 25.0
    assert defaults.claude_budget_usd_per_day == 100.0
    assert defaults.claude_cost_controls_enabled is False
    assert defaults.reasoning_provider == "ollama"


# ---------------------------------------------- spend per step


def _report(**kw):
    return claude_spend_report.report(claude_spend.entries(), **kw)


def test_the_report_counts_settled_lines_never_a_hold():
    """THE PAST REPORT: holds counted as cost said USD 3.71 against a real USD 0.35."""
    with claude_spend.for_run("run-1"):
        done = claude_spend.reserve("a-step", 0.5, model=MODEL)
        _settle(done, {"input_tokens": 175_000, "output_tokens": 0})
        claude_spend.reserve("a-step", 3.36, model=MODEL)
    report = _report(run_id="run-1")
    assert report["usd"] == pytest.approx(0.35)
    assert report["calls_charged"] == 1
    assert report["held_calls"] == 1 and report["held_worst_usd"] == pytest.approx(3.36)
    assert claude_spend.spent() == pytest.approx(3.71), "the caps do count it"
    assert report["asked"] == 2


def test_the_report_gives_usd_calls_stored_and_batch_per_step_with_its_denominator():
    with claude_spend.for_run("run-1"):
        call = claude_spend.metered(_send, "a-step")
        body = {
            "model": MODEL,
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "q"}],
        }
        call("u", headers={}, body=body, timeout=1)
        claude_spend.metered(_send, "a-step")("u", headers={}, body=body, timeout=1)
        held = claude_spend.reserve("b-step", 1.0, model=MODEL, batch=True)
        _settle(held, {"input_tokens": 1000, "output_tokens": 100})
        lost = claude_spend.reserve("b-step", 1.0, model=MODEL)
        claude_spend.settle_failure(lost, RuntimeError("timed out"))
    report = _report(run_id="run-1")
    a, b = report["steps"]
    assert (a["step"], a["asked"], a["calls_charged"], a["stored_answers"]) == (
        "a-step",
        2,
        1,
        1,
    )
    assert a["usd"] == pytest.approx(claude_spend.cost_usd(MODEL, USAGE))
    assert a["saved_usd"] == pytest.approx(a["usd"])
    assert (b["step"], b["asked"], b["calls_charged"], b["batch_calls"]) == (
        "b-step",
        2,
        2,
        1,
    )
    batch_usd = claude_spend.cost_usd(
        MODEL, {"input_tokens": 1000, "output_tokens": 100}, batch=True
    )
    assert b["usd"] == pytest.approx(batch_usd + 1.0)
    assert b["usd_estimated"] == pytest.approx(1.0)
    assert b["input_tokens"] == 1000
    assert (
        report["asked"]
        == report["calls_charged"]
        + report["stored_answers"]
        + report["refused"]
        + report["held_calls"]
    )
    assert report["usd"] == pytest.approx(a["usd"] + b["usd"])
    assert "names this review run" in report["boundary"]
    assert "not the invoice" in report["boundary"]


def test_the_report_is_only_this_runs_lines():
    with claude_spend.for_run("run-1"):
        _settle(claude_spend.reserve("a-step", 1.0, model=MODEL), USAGE)
    with claude_spend.for_run("run-2"):
        _settle(claude_spend.reserve("a-step", 1.0, model=MODEL), USAGE)
    _settle(claude_spend.reserve("chat", 1.0, model=MODEL), USAGE)
    assert _report(run_id="run-1")["calls_charged"] == 1
    assert _report()["calls_charged"] == 3


def test_a_refusal_is_asked_and_counted_at_no_cost():
    _write(
        {
            "at": _at(_now()),
            "step": "a-step",
            "cost_usd": 0.0,
            "refused": "not_approved",
            "run": "run-1",
        }
    )
    report = _report(run_id="run-1")
    assert (
        report["asked"],
        report["refused"],
        report["calls_charged"],
        report["usd"],
    ) == (1, 1, 0, 0)


def test_a_reservation_settled_twice_is_one_call():
    """The batch run's known overcount: the caps err toward spent, the report says what happened."""
    _write(_settled(0.35, settles="same"), _settled(0.35, settles="same"))
    report = _report()
    assert report["calls_charged"] == 1 and report["usd"] == pytest.approx(0.35)


def test_an_unreadable_line_is_named_never_cost():
    with Path(settings.claude_spend_log).open("a", encoding="utf-8") as fh:
        fh.write('{"torn\n')
    report = _report()
    assert report["usd"] == 0 and report["unreadable_lines"] == 1


def test_a_window_and_a_step_prefix_cover_a_run_that_is_not_a_review():
    start = _now() - timedelta(hours=1)
    _write(
        _settled(1.0, step="standards_convert:X", when=start - timedelta(hours=1)),
        _settled(2.0, step="standards_convert:X", when=start + timedelta(minutes=1)),
        _settled(4.0, step="chat", when=start + timedelta(minutes=1)),
    )
    report = _report(since=_at(start), step_prefix="standards_convert:")
    assert report["usd"] == pytest.approx(2.0)
    assert (
        "standards_convert:" in report["boundary"] and _at(start) in report["boundary"]
    )
    assert "whole ledger" in _report()["boundary"]


def test_the_script_prints_the_report_and_todays_cap(capsys):
    spec = importlib.util.spec_from_file_location(
        "claude_spend_report_cli", REPO / "scripts" / "claude_spend_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _write(_settled(2.0), _hold(3.0))
    assert module.main([]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["usd"] == pytest.approx(2.0) and printed[
        "held_worst_usd"
    ] == pytest.approx(3.0)
    assert printed["today_utc"]["charged_usd"] == pytest.approx(5.0)
    assert printed["today_utc"]["cap_usd"] == 100.0


# ---------------------------------------------- the run record and the audit


def _run(run_id="run-1", outcome=None):
    conn = db.connect()
    with conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, outcome_json)"
            " VALUES (?, 'doc-1', 'done', '2026-11-02T00:00:00+00:00', '2026-11-02T00:00:00+00:00', ?)",
            (run_id, json.dumps(outcome or {"kept": 1})),
        )
    return run_id


def _outcome(run_id="run-1"):
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["outcome_json"])


def _spend_on_run(run_id="run-1"):
    with claude_spend.for_run(run_id):
        _settle(claude_spend.reserve("a-step", 1.0, model=MODEL), USAGE)


def test_the_run_record_carries_the_report_and_keeps_what_it_had():
    _run()
    _spend_on_run()
    claude_spend_report.record_run("run-1")
    outcome = _outcome()
    assert outcome["kept"] == 1
    assert outcome["claude_spend"]["calls_charged"] == 1
    assert outcome["claude_spend"]["steps"][0]["step"] == "a-step"


def test_a_run_with_no_claude_call_says_nothing(sent):
    _run()
    claude_spend_report.record_run("run-1")
    assert "claude_spend" not in _outcome()
    assert review_audit_rows.spend_figures({"id": "run-1"}) == {}


def test_with_the_switch_off_the_run_record_and_audit_say_nothing(monkeypatch):
    _run()
    _spend_on_run()
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", False)
    claude_spend_report.record_run("run-1")
    assert "claude_spend" not in _outcome()
    assert review_audit_rows.spend_figures({"id": "run-1"}) == {}


def test_an_unreadable_ledger_says_so_on_the_run_and_breaks_nothing(monkeypatch):
    _run()

    def unreadable():
        raise OSError("disk")

    monkeypatch.setattr(claude_spend, "entries", unreadable)
    claude_spend_report.record_run("run-1")
    assert _outcome()["claude_spend"] == {
        "not_recorded": claude_spend_report.LEDGER_UNREADABLE
    }
    figures = review_audit_rows.spend_figures({"id": "run-1"})
    assert "spend ledger unreadable" in review_audit_rows.spend_lines(figures)[0]


def test_the_audit_prints_spend_per_step_with_its_denominator_and_boundary():
    _spend_on_run()
    with claude_spend.for_run("run-1"):
        claude_spend.reserve("a-step", 3.36, model=MODEL)
    figures = review_audit_rows.spend_figures({"id": "run-1"})
    lines = review_audit_rows.spend_lines(figures)
    usd = claude_spend.cost_usd(MODEL, USAGE)
    assert lines[0].startswith(
        f"- Claude spend, this review run: USD {round(usd, 6)} over 2 asked: 1 charged"
    )
    assert any(
        re.match(r"  - a-step: USD .*; 2 asked; 1 charged; 0 stored; 0 batch", x)
        for x in lines
    )
    assert any(x.startswith("  - still held, not cost") and "3.36" in x for x in lines)
    assert "names this review run" in lines[-1]
    assert review_audit_rows.spend_lines({}) == []


def test_the_audit_report_shows_the_lines():
    _spend_on_run()
    figures = review_audit_rows.spend_figures({"id": "run-1"})
    audit = {
        "ai_use": {
            "steps": [],
            "totals": {"fresh": 0, "failed": 0, "reused": 0, "boundary": "b"},
            **figures,
        }
    }
    assert any(
        "Claude spend, this review run" in line for line in review_audit._md_ai(audit)
    )


def test_a_review_job_writes_its_record_even_when_it_fails(monkeypatch):
    """The wrapper round `review_jobs.run`, not the run itself: its spend was paid either way."""
    from app import local_engine_bar, review_jobs

    _run()
    conn = db.connect()
    with conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        columns = {r[1]: r for r in conn.execute("PRAGMA table_info(jobs)")}
        values = {
            name: ("x" if str(info[2]).upper().startswith("TEXT") else 0)
            for name, info in columns.items()
            if info[3] and info[4] is None
        }
        values |= {"id": "job-1", "review_run_id": "run-1"}
        conn.execute(
            f"INSERT INTO jobs ({','.join(values)}) VALUES ({','.join('?' * len(values))})",
            list(values.values()),
        )
    monkeypatch.setattr(local_engine_bar, "barring_local_engine", lambda job: job)

    def job(job_id):
        _spend_on_run_inside()
        raise ValueError("the review failed")

    def _spend_on_run_inside():
        _settle(claude_spend.reserve("a-step", 1.0, model=MODEL), USAGE)

    with pytest.raises(ValueError):
        review_jobs._review_scope(job)("job-1")
    assert _outcome()["claude_spend"]["calls_charged"] == 1


def _route_stubs(monkeypatch):
    monkeypatch.setattr(
        claude_api,
        "_run_or_404",
        lambda rid, scope: {"id": rid, "submittal_document_id": "doc-1"},
    )
    monkeypatch.setattr(reader_transport, "transport", lambda: _send)
    monkeypatch.setattr(
        claude_recheck,
        "recheck_run",
        lambda rid, call, *, allowed_document_ids: {"a": call("agree?")},
    )


def test_a_reviewers_route_charges_the_run_and_updates_its_record(monkeypatch, sent):
    _send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    _route_stubs(monkeypatch)
    _run()
    response = TestClient(app).post("/api/reviews/runs/run-1/claude/recheck")
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    settled = [e for e in claude_spend.entries() if e.get("settles")]
    assert [e["run"] for e in settled] == ["run-1"]
    assert _outcome()["claude_spend"]["steps"][0]["step"] == claude_api.STEP_RECHECK


def test_with_the_report_off_a_route_still_names_its_run_but_writes_no_record(
    monkeypatch, sent
):
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", False)
    _send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    _route_stubs(monkeypatch)
    _run()
    assert (
        TestClient(app).post("/api/reviews/runs/run-1/claude/recheck").status_code
        == 200
    )
    assert [e["run"] for e in claude_spend.entries()] == ["run-1"]
    assert "claude_spend" not in _outcome()


# ---------------------------------------------- no route escapes


#: Every file that may hold the raw transport: each wraps it in `metered`, or (the provider) reserves itself.
_RESERVES_ITSELF = {"reasoning_provider.py"}


def test_every_holder_of_the_raw_transport_meters_it():
    """`scripts/reader_score_standard.py` held the raw transport: no reservation, no ledger, no cap."""
    holders = []
    for folder in (REPO / "backend" / "app", REPO / "scripts"):
        for path in folder.rglob("*.py"):
            if "mutations" in path.parts or path.name == "reader_transport.py":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"reader_transport(_mod)?\.transport\(\)", text):
                holders.append(path.name)
                if path.name not in _RESERVES_ITSELF:
                    assert "claude_spend.metered(" in text, (
                        f"{path.name} sends unmetered"
                    )
    assert {
        "claude_api.py",
        "datasheet_ai.py",
        "match_claude.py",
        "reader_score_standard.py",
    } <= set(holders)


def test_the_day_cap_does_not_replace_the_step_cap(sent):
    """Three checks: the step, the total and the day."""
    _write(_settled(4.9999, step="a-step"))
    with pytest.raises(claude_spend.BudgetExceeded, match="per step"):
        _lane_metered()
    assert sent == []


def test_the_audit_names_unreadable_ledger_lines():
    _spend_on_run()
    with Path(settings.claude_spend_log).open("a", encoding="utf-8") as fh:
        fh.write('{"torn\n')
    lines = review_audit_rows.spend_lines(
        review_audit_rows.spend_figures({"id": "run-1"})
    )
    assert any("1 ledger lines could not be read" in line for line in lines)


def _vision_block():
    return vision_reader._local_status(0.0)


def test_the_vision_status_says_the_day_cap_is_reached(monkeypatch):
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(vision_reader, "engine_setting", lambda: "claude")
    assert _vision_block() is None
    _write(_settled(100.0))
    state = _vision_block()
    assert state["state"] == "BUDGET_REACHED" and "today (UTC)" in state["detail"]
    assert "for today" in state["reason"]
    assert "Settled spend resets at 00:00 UTC" in state["fix"]
    assert (
        "until it settles, or for up to 24 hours from when it was placed"
        in state["fix"]
    )
    assert "clears by itself" not in state["fix"], "an open hold can outlast midnight"
    assert "CLAUDE_BUDGET" not in state["fix"] and "Raise" not in state["fix"]
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", False)
    assert _vision_block()["state"] == "BUDGET_REACHED", "the day cap has no switch"


# ---------------------------------------------- rule 1: no script opens the lane without the app's gate


def _flags_on_provider_ollama(monkeypatch):
    """The state of the live app with egress flags left on: nothing may leave."""
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")

    def never():
        raise AssertionError("the transport was asked for")

    monkeypatch.setattr(reader_transport, "transport", never)


def test_the_score_script_refuses_on_ollama_before_it_reads_anything(
    monkeypatch, tmp_path, capsys
):
    _flags_on_provider_ollama(monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["reader_score_standard.py", str(tmp_path / "out")]
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(
            str(REPO / "scripts" / "reader_score_standard.py"), run_name="__main__"
        )
    assert stopped.value.code == 2
    assert "REFUSED" in capsys.readouterr().out
    assert not (tmp_path / "out").exists(), "it went on to read before refusing"


def test_the_bench_refuses_on_ollama(monkeypatch):
    _flags_on_provider_ollama(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "datasheet_bench_gate", REPO / "scripts" / "datasheet_bench.py"
    )
    bench = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bench
    try:
        spec.loader.exec_module(bench)
        with pytest.raises(bench.ReaderUnavailable, match="PROVIDER"):
            bench.build_model_call("ai-only:claude")
    finally:
        del sys.modules[spec.name]


_GATES = {"claude_unavailable", "claude_unavailable_for_task", "claude_available"}
_TRANSPORT_CALLS = {
    "transport",
    "stream",
    "batch_create",
    "batch_retrieve",
    "batch_results",
}


def _name_of(func) -> str:
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _lane_openers(tree) -> list[int]:
    """Lines that reach the Claude lane without a gate of their own: the raw transport, or a hand-built provider.
    `get_provider` and `claude_for_task` are not here: they ask the gate themselves."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
            "reader_transport"
        ):
            lines.append(node.lineno)
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        owner = getattr(getattr(func, "value", None), "id", "")
        if _name_of(func) == "ClaudeProvider" or (
            _name_of(func) in _TRANSPORT_CALLS and owner.startswith("reader_transport")
        ):
            lines.append(node.lineno)
    return lines


def _scripts_and_openers():
    for path in sorted((REPO / "scripts").rglob("*.py")):
        if "mutations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        yield path, tree, _lane_openers(tree)


def test_no_script_opens_the_claude_lane_before_the_apps_gate():
    """Rule 1: the flags alone are not the gate. The gate's call must come first in the file, in source order, so a
    new script that holds the transport or builds a provider fails here until it asks."""
    seen = set()
    for path, tree, openers in _scripts_and_openers():
        if not openers:
            continue
        seen.add(path.name)
        gates = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _name_of(n.func) in _GATES
        ]
        assert gates and min(gates) < min(openers), (
            f"{path.name}:{min(openers)} opens the lane with no gate"
        )
    assert {
        "datasheet_bench.py",
        "reader_score_standard.py",
        "convert_standards.py",
    } <= seen


def test_the_script_guard_sees_an_unguarded_script():
    """The guard itself: a script that holds the transport, or builds a provider, is found."""
    for source in (
        "from app import reader_transport\nsend = reader_transport.transport()\n",
        "from app.reasoning_provider import ClaudeProvider\nClaudeProvider()\n",
        "from app.reader_transport import transport\n",
    ):
        assert _lane_openers(ast.parse(source))


def test_the_vision_status_at_the_step_cap_keeps_its_own_words(monkeypatch):
    """Only the day cap clears by itself: the step and total caps stay the owner's to raise."""
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(vision_reader, "engine_setting", lambda: "claude")
    _write(_settled(5.0, step=vision_reader.VISION_STEP))
    state = _vision_block()
    assert state["state"] == "BUDGET_REACHED" and "CLAUDE_BUDGET" in state["fix"]
    assert "all time, no run" in state["detail"]
    with claude_spend.for_run("run-1"):
        assert _vision_block() is None, "that spend is not this run's"


# ---------------------------------------------- the step cap is per review run (owner, #1584)


def _hold_in(run, step="a-step", usd=4.0):
    with claude_spend.for_run(run):
        return claude_spend.reserve(step, usd, model=MODEL)


def test_a_step_of_one_run_cannot_exceed_5_and_another_run_has_its_own():
    _settle(_hold_in("run-1"), {"input_tokens": 1_500_000, "output_tokens": 0})
    with pytest.raises(
        claude_spend.BudgetExceeded, match="per step of this review run"
    ):
        _hold_in("run-1", usd=2.5)
    assert _hold_in("run-2", usd=4.9), "a new run id gets a new USD 5"


def test_a_re_run_of_the_same_document_is_held_by_the_day_cap():
    """The same step under ever-new run ids: each has USD 5, so the day cap is what stops them."""
    for n in range(20):
        _hold_in(f"run-{n}", usd=5.0)
    with pytest.raises(claude_spend.BudgetExceeded, match="a day"):
        _hold_in("run-20", usd=0.01)
    assert claude_spend.spent("a-step") == pytest.approx(100.0)


def test_an_open_hold_counts_on_its_run_at_its_worst_case():
    _hold_in("run-1", usd=4.0)
    with pytest.raises(claude_spend.BudgetExceeded, match="per step"):
        _hold_in("run-1", usd=1.5)


def test_a_settlement_outside_the_run_still_counts_on_the_run():
    """A batch settled later, on another thread, must not slip off its run's cap."""
    held = _hold_in("run-1", usd=4.9)
    _settle(held, {"input_tokens": 2_000_000, "output_tokens": 0})
    assert claude_spend.entries()[-1]["run"] == "run-1"
    with pytest.raises(claude_spend.BudgetExceeded, match="per step"):
        _hold_in("run-1", usd=1.5)


@pytest.mark.parametrize("step", ["chat", "b4-vision", "a-script"])
def test_a_send_with_no_run_reads_every_line_of_its_step_as_before(step):
    """Chat, a read at upload, a script, an offline job: at least as tight as today, runs' lines included."""
    _settle(
        _hold_in("run-1", step=step, usd=4.0),
        {"input_tokens": 1_500_000, "output_tokens": 0},
    )
    with pytest.raises(claude_spend.BudgetExceeded, match="per step"):
        claude_spend.reserve(step, 2.5, model=MODEL)


def test_the_no_run_words_do_not_claim_a_run():
    _write(_settled(4.9999, step="chat"))
    with pytest.raises(claude_spend.BudgetExceeded) as refused:
        claude_spend.reserve("chat", 1.0, model=MODEL)
    assert "review run" not in str(refused.value)


def test_a_standard_stays_25_whatever_the_run():
    step = claude_spend.STANDARD_STEP_PREFIX + "X"
    _write(_settled(24.9999, step=step))
    with pytest.raises(claude_spend.BudgetExceeded, match=r"cap \$25\.00"):
        _hold_in("run-1", step=step, usd=0.01)
    assert claude_spend.Caps.from_settings().for_step(step).per_step == 25.0


def test_a_batch_in_a_run_cannot_cross_its_step_cap_together():
    with claude_spend.for_run("run-1"), pytest.raises(claude_spend.BudgetExceeded):
        claude_spend.reserve_all([("a-step", 3.0), ("a-step", 3.0)], model=MODEL)
    assert claude_spend.entries() == []


def _race(worker, count):
    """`count` threads at once; each returns True when its reservation was accepted."""
    won = []
    start = threading.Barrier(count)

    def run(n):
        start.wait()
        try:
            worker(n)
        except claude_spend.BudgetExceeded:
            return
        won.append(n)

    threads = [threading.Thread(target=run, args=(n,)) for n in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return won


def test_concurrent_reservations_on_one_run_cannot_pass_5():
    won = _race(lambda n: _hold_in("run-1", usd=0.6), 20)
    assert len(won) == 8
    assert claude_spend.spent("a-step") == pytest.approx(4.8)


def test_concurrent_reservations_on_many_runs_cannot_pass_100(monkeypatch):
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", False)
    won = _race(lambda n: _hold_in(f"run-{n}", usd=4.0), 40)
    assert len(won) == 25
    assert claude_spend.spent() == pytest.approx(100.0)


def test_open_holds_fill_the_day_with_the_report_switch_off(monkeypatch):
    monkeypatch.setattr(settings, "claude_cost_controls_enabled", False)
    _write(_hold(99.5, reservation="open"))
    with pytest.raises(claude_spend.BudgetExceeded, match="a day"):
        _hold_in("run-1", usd=1.0)


def test_the_route_reports_this_runs_step_and_the_day(monkeypatch, sent):
    _send.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    _route_stubs(monkeypatch)
    _run()
    _write(_settled(4.5, step=claude_api.STEP_RECHECK))
    body = (
        TestClient(app)
        .post("/api/reviews/runs/run-1/claude/recheck")
        .json()["usd_spent"]
    )
    assert 0 < body["step_usd"] < 1, "another run's spend is not this run's"
    assert body["step_boundary"] == "this review run"
    assert body["cap_per_day_usd"] == 100.0 and body["today_usd"] > 4.5
