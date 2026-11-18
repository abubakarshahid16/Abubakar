"""The request of every general-review call: its shape (`check_body`, the same check before every paid send), and the one lane:
`claude_approved.carrying(ids)` -> `claude_spend.metered(step=..)` -> `reader_transport.transport()`, inside
`claude_spend.for_run(run_id)` and `claude_approved.reviewing(run_id)`. The socket is a fake here: nothing leaves."""

from __future__ import annotations

import json

import pytest

from app import aim_review
from app.aim_review import engine as E
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    BOOK_C,
    PAPER,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


GOOD = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 1000,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
}


def test_a_valid_body_passes_the_shape_check():
    assert E.check_body(GOOD) == []
    body = {**GOOD, **E.build_parts("sys", "cached paper", "ask", "low")}
    assert E.check_body(body) == []


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"temperature": 0.2}, "temperature"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"max_tokens": 70000}, "max_tokens"),
        ({"model": "other"}, "no model id"),
        ({"stream": True}, "unknown keys"),
        ({"output_config": {"effort": "huge"}}, "effort"),
        ({"messages": []}, "user turn"),
        ({"system": [{"type": "text", "text": ""}]}, "empty system text block"),
        (
            {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": " "}]}
                ]
            },
            "empty message text block",
        ),
        (
            {
                "system": [
                    {
                        "type": "text",
                        "text": "a",
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                * 5
            },
            "cache_control",
        ),
    ],
)
def test_a_body_the_api_would_refuse_is_caught_before_sending(change, words):
    assert any(words in p for p in E.check_body({**GOOD, **change}))


def test_build_parts_never_builds_an_empty_block():
    parts = E.build_parts("", None, "ask", None)
    assert "system" not in parts and "output_config" not in parts
    assert parts["messages"][0]["content"][0]["text"] == "ask"


def _step_of(body: dict) -> str:
    prompt = body["messages"][0]["content"][0]["text"]
    for words, step in (
        ("TASK S1", "aim_identify"),
        ("TASK S2", "aim_select"),
        (
            "TASK S3K",
            "aim_checklist_knowledge",
        ),  # before "TASK S3": the knowledge task's name starts with it
        ("TASK S3", "aim_checklist"),
        ("ATTACK THIS CHECKLIST", "aim_attack"),
        (
            "TASK S4C",
            "aim_second_read",
        ),  # before "TASK S4": the second reader's name starts with it
        (
            "TASK S4B",
            "aim_answered",
        ),  # before "TASK S4": the whole-paper check's name starts with it
        ("TASK S4", "aim_judge"),
        (
            "TASK S5",
            "aim_edit",
        ),  # the editor after S4: it may only take a comment off the sheet
        ("was NOT found", "aim_checklist_retry"),
    ):
        if words in prompt:
            return step
    raise AssertionError("unknown step")


@pytest.fixture
def fake_lane(monkeypatch):
    """The Claude lane with a fake socket: what each send saw is kept."""
    from app import agent_claude, claude_approved, claude_spend, reader_transport

    seen: list[dict] = []
    fake = E.FakeModel(kind="datasheet", subject_key="test_item")

    def send(url, *, headers, body, timeout):
        step = _step_of(body)
        cached = "".join(
            b["text"] for b in body.get("system") or [] if isinstance(b, dict)
        )
        prompt = body["messages"][0]["content"][0]["text"]
        seen.append(
            {
                "step": step,
                "carried": claude_approved.carried(),
                "run": claude_spend.current_run(),
                "review_run": claude_approved.review_run(),
                "model": body["model"],
            }
        )
        answer = fake.fake_answer(step, cached, prompt)
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "content": [{"type": "text", "text": json.dumps(answer)}],
        }

    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    monkeypatch.setattr(
        agent_claude,
        "_request",
        lambda model, max_tokens, env: {
            "url": "https://fake.invalid/v1/messages",
            "headers": {},
            "body": {},
            "timeout": 5.0,
        },
    )
    return seen


def test_every_call_is_declared_metered_and_tagged_with_the_run(aim_db, fake_lane):
    from app import claude_spend

    r = aim_review.run(
        aim_db,
        run_id="run_aim_lane",
        paper_id=PAPER,
        allowed_books=frozenset({BOOK_A, BOOK_B}),
        store=MemoryStore(),
        max_usd=5.0,
    )
    assert r.status == "done", r.stop_reason
    steps = [s["step"] for s in fake_lane]
    assert steps[0] == "aim_identify" and "aim_judge" in steps and "aim_attack" in steps
    for s in fake_lane:
        assert s["run"] == "run_aim_lane" and s["review_run"] == "run_aim_lane"
        assert s["carried"] is not None and s["carried"] <= {PAPER, BOOK_A, BOOK_B}
        assert BOOK_C not in s["carried"]
    assert {s["model"] for s in fake_lane if s["step"] == "aim_attack"} == {
        "claude-opus-5-5"
    }
    ledger = [
        e
        for e in claude_spend.entries()
        if e.get("run") == "run_aim_lane" and not e.get("reserved")
    ]
    assert sorted({e["step"] for e in ledger}) == sorted(set(steps))
    assert len(ledger) == len(fake_lane)
    # one row per model call; the code row "aim_read_pages" (where each page came from, no model, no cost) is not a call
    assert r.usd > 0 and len([c for c in r.calls if c["model"] != "code"]) == len(
        fake_lane
    )


def test_a_closed_lane_sends_nothing_and_stops_the_run(aim_db, monkeypatch):
    from app import reader_transport

    monkeypatch.setattr(reader_transport, "transport", lambda: None)
    r = aim_review.run(
        aim_db,
        run_id="run_aim_closed",
        paper_id=PAPER,
        allowed_books=frozenset({BOOK_A}),
        store=MemoryStore(),
        max_usd=5.0,
    )
    assert r.status == "stopped" and "gate_closed" in r.stop_reason
    assert r.usd == 0.0


def test_a_document_the_gate_refuses_is_never_sent(aim_db, fake_lane, monkeypatch):
    """The send gate is asked by the metered wrapper itself: a refusal stops that call before the socket."""
    from app import claude_approved

    monkeypatch.setattr(
        claude_approved, "refusal", lambda: ("not_approved", "refused in this test")
    )
    r = aim_review.run(
        aim_db,
        run_id="run_aim_refused",
        paper_id=PAPER,
        allowed_books=frozenset({BOOK_A}),
        store=MemoryStore(),
        max_usd=5.0,
    )
    assert r.status == "stopped"
    assert fake_lane == []
