"""A failed call inside a two-reader step: what the run was charged is on the batch's lines (verdict, absence, other-paper).

Each failure kind (transport error, cut-off, bad reply with and without usage, cap refusal) inside each of the three steps:
the run's increase equals the summed line increase, against the same run with that step off. Invented data; no network."""

# ruff: noqa: F811
from __future__ import annotations

import json

import pytest

from app import agent_claude, db
from app import agent_review_request as request_mod
from app import agent_review_run as run_mod
from app import agent_review_two_reader_run as step_run
from app.config import settings
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_two_reader import TwoLane, step_of
from tests.test_agent_two_reader_absence import absence_step, both, paper  # noqa: F401
from tests.test_agent_two_reader_absence import setup as absence_setup
from tests.test_agent_two_reader_other import lane as other_lane
from tests.test_agent_two_reader_other import on, other_step  # noqa: F401, RUF100

KINDS = ["transport", "cut", "bad_usage", "bad_nousage", "cap"]


@pytest.fixture(autouse=True)
def _strict(monkeypatch):
    monkeypatch.setattr(
        step_run.TwoReaderMixin, "strict_charge", True
    )  # a batch element with no line fails the test


def _ids(body) -> list[str]:
    last = body["messages"][0]["content"][-1]["text"]
    return [q["item_id"] for q in json.loads(last.split("\n\n")[0]).get("items", [])]


class Breaker:
    """Wraps a lane; the second reader's call that `match(body)` selects fails in the given way, every other call passes."""

    def __init__(self, inner, kind, match):
        self.inner, self.kind, self.match, self.hit = inner, kind, match, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __call__(self, url, *, headers, body, timeout):
        if body.get("model") != agent_claude.SECOND_MODEL or not self.match(body):
            return self.inner(url, headers=headers, body=body, timeout=timeout)
        self.hit += 1
        usage = {"input_tokens": 4000, "output_tokens": 700}
        if self.kind == "transport":
            raise TimeoutError("invented timeout")
        reply = {
            "model": "fake-second-model-2",
            "content": [{"type": "text", "text": '{"answers": [{"it'}],
        }
        if self.kind == "cut":
            return {**reply, "stop_reason": "max_tokens", "usage": usage}
        if self.kind == "bad_usage":
            return {**reply, "stop_reason": "refusal", "usage": usage}
        return {**reply, "stop_reason": "refusal"}  # bad reply, no usage came back


def _totals(run_id):
    run = (
        db.connect()
        .execute("SELECT usd FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()["usd"]
    )
    lines = sum(
        json.loads(r["line_json"]).get("usd") or 0.0 for r in lines_of(run_id).values()
    )
    return run, lines


def _check(w, monkeypatch, switch, build, kind, match, state):
    """The run with the step off, then with it on and one of its calls failing in `kind`."""
    monkeypatch.setattr(settings, switch, False)
    build()
    off = _totals(run_review())
    monkeypatch.setattr(settings, switch, True)
    db.reset_connection()
    build()
    breaker = w["fake"] = Breaker(w["fake"], kind, match)
    if kind == "cap":
        real = run_mod.Runner.call

        def call(self, model, parts, max_tokens, once=False):
            body = {
                "model": model,
                "system": parts["system"],
                "messages": parts["messages"],
            }
            if model == agent_claude.SECOND_MODEL and match(body):
                breaker.hit += 1
                raise request_mod.StepCapStop("invented cap")
            return real(self, model, parts, max_tokens, once)

        monkeypatch.setattr(run_mod.Runner, "call", call)
    run_id = run_review()
    on = _totals(run_id)
    assert (
        breaker.hit == 1 and state(run_id)["off"] is not None
    )  # the failure happened and switched the step off
    run_extra, line_extra = on[0] - off[0], on[1] - off[1]
    assert run_extra == pytest.approx(0.0 if kind == "cap" else run_extra) and (
        kind == "cap" or run_extra > 0
    )
    assert line_extra == pytest.approx(
        run_extra, abs=1e-9
    )  # exactly, whatever the rounding of the shares


@pytest.mark.parametrize("kind", KINDS)
def test_verdict_step_a_failed_batch_of_several_lines_charges_the_lines(
    w, monkeypatch, kind
):
    from app import agent_review_two_reader as two  # noqa: F401

    _check(
        w, monkeypatch, "agent_review_two_reader_verdict_enabled",
        lambda: w.__setitem__("fake", TwoLane()),
        kind, lambda body: request_mod.SYSTEM[:60] in json.dumps(body["system"]),
        step_of,
    )  # fmt: skip


@pytest.mark.parametrize("kind", KINDS)
def test_absence_step_a_failed_batch_of_one_charges_the_line(
    w, monkeypatch, both, kind
):
    from app import agent_review_two_reader_absence as ab

    def build():
        if not w.get("paper_written"):
            paper()
            w["paper_written"] = True
        absence_setup(w)

    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    plan = run_mod.plan_pages  # the switch also sends a short paper whole to every item: plan it so in the run without the step too
    monkeypatch.setattr(
        run_mod, "plan_pages", lambda *a, **k: plan(*a, **{**k, "whole_short": True})
    )
    _check(
        w, monkeypatch, "agent_review_two_reader_absence_enabled", build, kind,
        lambda body: ab.ABSENCE_SYSTEM in json.dumps(body["system"]).replace("\\n", "\n")
        or "reading a supplier paper" in json.dumps(body["system"]),
        absence_step,
    )  # fmt: skip


@pytest.mark.parametrize("kind", KINDS)
def test_other_paper_step_a_failed_batch_of_one_charges_the_line(
    w, monkeypatch, on, kind
):
    _check(
        w, monkeypatch, "agent_review_two_reader_other_paper_enabled",
        lambda: other_lane(w),
        kind, lambda body: _ids(body) == ["R-coat"], other_step,
    )  # fmt: skip


def test_the_shares_add_up_exactly_and_a_batch_element_without_a_line_fails_loudly():
    class Host(step_run.TwoReaderMixin):
        import threading

        _lock = threading.Lock()
        sink = None

        def __init__(self):
            self.lines = {f"i{n}": {"item_id": f"i{n}", "usd": 0.0} for n in range(3)}

        def exit_line(self, line):
            return line

    host = Host()
    wrapped = [
        {"item": {"item_id": "i0"}},
        {"line": {"item_id": "i1"}},
        {"item_id": "i2"},
    ]  # the three element shapes
    host._charge_batch(wrapped, 0.100001)
    assert sum(ln["usd"] for ln in host.lines.values()) == pytest.approx(
        0.100001, abs=1e-12
    )
    with pytest.raises(LookupError):
        host._charge_batch([{"item_id": "nobody"}], 0.01)
