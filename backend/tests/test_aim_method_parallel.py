"""Judge calls side by side (the owner's order, 18 Nov 2026): the merged lines equal the one-at-a-time lines; money first (the
run meter counts the worst case of every call in flight; every hold, on the run meter and in the spend ledger, is closed on
success, failure and cancel); the run id travels into every worker; no document text in a log line. Invented papers; no paid
call, no socket."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from app import aim_review
from app.aim_review import engine as E
from app.aim_review import parallel
from app.aim_review import steps as S
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    PAPER_PAGES,
    MemoryStore,
    open_aim_db,
)

LISTED = frozenset({BOOK_A, BOOK_B})
MODEL = "claude-sonnet-5-5"


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


@pytest.fixture
def lane(monkeypatch):
    """The Claude lane with a fake socket (as `test_aim_method_request.lane`): what each send saw is kept."""
    import json

    from app import agent_claude, claude_approved, claude_spend, reader_transport

    seen: list[dict] = []
    fake = E.FakeModel(kind="datasheet", subject_key="test_item")

    def send(url, *, headers, body, timeout):
        prompt = body["messages"][0]["content"][0]["text"]
        step = _step_of(prompt)
        cached = "".join(
            b["text"] for b in body.get("system") or [] if isinstance(b, dict)
        )
        seen.append(
            {
                "step": step,
                "run": claude_spend.current_run(),
                "review_run": claude_approved.review_run(),
            }
        )
        answer = fake.fake_answer(step, cached, prompt)
        return {"model": body["model"], "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": json.dumps(answer)}]}  # fmt: skip

    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    monkeypatch.setattr(agent_claude, "_request", lambda model, max_tokens, env: {
        "url": "https://fake.invalid/v1/messages", "headers": {}, "body": {}, "timeout": 5.0})  # fmt: skip
    return seen


def _step_of(prompt: str) -> str:
    for words, step in (("TASK S1", "aim_identify"), ("TASK S2", "aim_select"), ("TASK S3K", "aim_checklist_knowledge"),
                        ("TASK S3", "aim_checklist"), ("ATTACK THIS CHECKLIST", "aim_attack"), ("TASK S4", "aim_judge"),
                        ("TASK S5", "aim_edit"), ("was NOT found", "aim_checklist_retry")):  # fmt: skip
        if words in prompt:
            return step
    raise AssertionError("unknown step")


@pytest.fixture
def small_batches(monkeypatch):
    monkeypatch.setattr(S, "JUDGE_BATCH", 2)  # 7 items -> 4 judge calls, side by side


class _Slow(E.FakeModel):
    """The fake model, but the EARLIER judge batches answer LATER: the merge must still follow the one-at-a-time order."""

    def ask(self, **kw):
        if kw["step"] == "aim_judge":
            time.sleep(0.05 * max(0, 4 - kw["prompt"].count('"id": "')))
        return super().ask(**kw)


def _run(conn, model, run_id="run_par"):
    return aim_review.run(conn, run_id=run_id, paper_id=PAPER, allowed_books=LISTED, store=MemoryStore(), max_usd=5.0,
                          model=model)  # fmt: skip


def test_the_merged_lines_equal_the_one_at_a_time_lines(
    aim_db, small_batches, monkeypatch
):
    monkeypatch.setattr(S, "JUDGE_PARALLEL", 1)
    one = _run(aim_db, _Slow(kind="datasheet", subject_key="test_item"), "run_one")
    monkeypatch.setattr(S, "JUDGE_PARALLEL", 3)
    side = _run(aim_db, _Slow(kind="datasheet", subject_key="test_item"), "run_side")
    assert one.status == side.status == "done"
    assert side.lines == one.lines and len(side.lines) == 7


# ---- the run meter: the worst case of every call in flight ----------------------------------------------------------------


def _request(prompt="an invented prompt of a judge batch"):
    return {"step": "aim_judge", "model": MODEL, "system": "", "cached": None, "prompt": prompt, "carries": set(),
            "max_tokens": 1000}  # fmt: skip


def _worst():
    from app import claude_spend

    return claude_spend.worst_case_usd(MODEL, len(_request()["prompt"]), 1000)


def test_the_meter_refuses_a_third_call_whose_worst_case_would_cross(monkeypatch):
    """HAND-REVERT PROOF (money, rule 6): with `+ self.meter.held` taken out of `ClaudeModel.ask`, the third call is let through
    and this test fails; restored, it passes."""
    gate = threading.Event()
    started = []

    def send(self, step, model, parts, carries, max_tokens, cap_tokens, worst, rec):
        started.append(step)
        gate.wait(5)
        return {"judgments": []}

    monkeypatch.setattr(E.ClaudeModel, "_send", send)
    m = E.ClaudeModel(E.Meter(cap=2.5 * _worst()))
    threads = [threading.Thread(target=m.ask, kwargs=_request()) for _ in range(2)]
    for t in threads:
        t.start()
    for _ in range(100):
        if len(started) == 2:
            break
        time.sleep(0.01)
    assert len(started) == 2 and m.meter.held == pytest.approx(2 * _worst())
    with pytest.raises(E.StepFailed, match="run_cap"):
        m.ask(**_request())  # 2 in flight + this one would cross the run's cap
    gate.set()
    for t in threads:
        t.join(5)
    assert m.meter.held == pytest.approx(0.0)
    assert m.ask(**_request()) == {"judgments": []}  # once they ended, it fits


@pytest.mark.parametrize("outcome", ["ok", "failed", "fault"])
def test_the_run_meters_hold_is_released_on_every_path(monkeypatch, outcome):
    def send(self, *_a):
        if outcome == "failed":
            raise E.StepFailed("aim_judge: transport transport_ReadTimeout")
        if outcome == "fault":
            raise RuntimeError("an invented fault")
        return {}

    monkeypatch.setattr(E.ClaudeModel, "_send", send)
    m = E.ClaudeModel(E.Meter(cap=10.0))
    try:
        m.ask(**_request())
    except (E.StepFailed, RuntimeError):
        pass
    assert m.meter.held == 0.0


def test_a_call_that_does_not_fit_beside_the_calls_in_flight_waits_instead_of_being_refused(
    monkeypatch,
):
    def send(self, *_a):
        time.sleep(0.02)
        return {"ok": True}

    monkeypatch.setattr(E.ClaudeModel, "_send", send)
    m = E.ClaudeModel(E.Meter(cap=1.5 * _worst()))  # room for ONE call in flight
    results, stop = parallel.run_calls(m, [_request() for _ in range(4)], workers=3)
    assert stop == "" and [r[0] for r in results] == ["ok"] * 4 and m.meter.held == 0.0


def test_nothing_new_starts_after_a_cancel_and_the_unasked_stay_none():
    calls = []

    class _M:
        dry = True

        def ask(self, **kw):
            calls.append(kw["prompt"])
            time.sleep(0.02)
            return {}

    cancel_after = iter([False, False, True, True, True, True])
    results, stop = parallel.run_calls(_M(), [_request(f"p{i}") for i in range(6)], workers=2,
                                       cancelled=lambda: next(cancel_after))  # fmt: skip
    assert stop == "cancelled" and len(calls) == 2 and results[2:] == [None] * 4


# ---- through the real lane (a fake socket): the ledger's holds, the run id in every worker, no text in logs ----------------


def test_every_ledger_hold_is_closed_and_every_worker_carries_the_run(
    aim_db, small_batches, lane, caplog
):
    from app import claude_spend

    caplog.set_level(logging.DEBUG)
    r = aim_review.run(aim_db, run_id="run_par_lane", paper_id=PAPER, allowed_books=LISTED, store=MemoryStore(),
                       max_usd=5.0)  # fmt: skip
    assert r.status == "done", r.stop_reason
    judges = [s for s in lane if s["step"] == "aim_judge"]
    assert len(judges) == 4 and all(
        s["run"] == "run_par_lane" and s["review_run"] == "run_par_lane" for s in judges
    )
    assert not [
        e
        for e in claude_spend.entries()
        if e.get("run") == "run_par_lane" and e.get("reserved")
    ]
    words = [
        ln.strip() for t in PAPER_PAGES.values() for ln in t.splitlines() if ln.strip()
    ]
    assert not any(w in caplog.text for w in words)  # no document text in a log line


def test_a_failed_judge_call_keeps_not_judged_lines_and_closes_its_hold(
    aim_db, small_batches, lane, monkeypatch
):
    from app import claude_spend, reader_transport

    good = reader_transport.transport()
    fails = {"left": 1}

    def send(url, *, headers, body, timeout):
        if (
            _step_of(body["messages"][0]["content"][0]["text"]) == "aim_judge"
            and fails["left"]
        ):
            fails["left"] -= 1
            raise RuntimeError("an invented failure of one judge call")
        return good(url, headers=headers, body=body, timeout=timeout)

    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    r = aim_review.run(aim_db, run_id="run_par_fail", paper_id=PAPER, allowed_books=LISTED, store=MemoryStore(),
                       max_usd=5.0)  # fmt: skip
    assert r.status == "done"
    assert (
        sum(1 for ln in r.lines if ln["code_note"] == aim_review.NOT_JUDGED) == 2
    )  # the failed batch's two items
    assert not [
        e
        for e in claude_spend.entries()
        if e.get("run") == "run_par_fail" and e.get("reserved")
    ]


def test_a_cancel_mid_judging_closes_every_hold(aim_db, small_batches, lane):
    from app import claude_spend

    judged = {"n": 0}

    def cancelled():
        judged["n"] = sum(1 for s in lane if s["step"] == "aim_judge")
        return judged["n"] >= 1

    r = aim_review.run(aim_db, run_id="run_par_cancel", paper_id=PAPER, allowed_books=LISTED, store=MemoryStore(),
                       max_usd=5.0, cancelled=cancelled)  # fmt: skip
    assert r.status == "stopped" and "cancelled" in r.stop_reason
    assert any(ln["code_note"] == aim_review.NOT_JUDGED for ln in r.lines)
    assert not [
        e
        for e in claude_spend.entries()
        if e.get("run") == "run_par_cancel" and e.get("reserved")
    ]
