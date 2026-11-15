"""B1 of the nine-role review: the call seam (`nine_call.ask`) and the stored record (`nine_record`). Invented documents; a fake
Messages transport; no network, no key, no model."""

from __future__ import annotations

import hashlib
import json

import pytest

from app import (
    agent_claude,
    claude_approved,
    claude_spend,
    db,
    nine_call,
    nine_record,
    review_engine,
    review_shown,
    submittal_review,
)
from app.config import settings
from app.nine_call import Block, FakeTransport, RoleGate

NOW = "2026-11-16T00:00:00Z"
PAPER_TEXT, BOOK_TEXT, HELD_TEXT = (
    "PAPER TEXT alpha 12 bar",
    "BOOK TEXT clause 4.1 shall",
    "HELD TEXT should never leave",
)


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "nine.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    agent_claude.reset_shared_meter_for_tests()
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc in ("paper", "book", "held"):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',1,?)",
                (doc, f"{doc}.pdf", doc * 8, f"{doc}.pdf", NOW),
            )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('run1','paper','running',?,?)",
            (NOW, NOW),
        )
        review_shown.record_in(
            conn, "run1", ["paper", "book"], NOW
        )  # the stored list names the paper and the book, not "held"
    nine_record.start_run("run1")
    yield
    db.reset_connection()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def blocks(*, with_held=False):
    out = [
        Block("paper", "paper", (1, 2), PAPER_TEXT),
        Block(
            "book", "rule_book", (4,), BOOK_TEXT, chapter_id="4", part_no=1, part_of=2
        ),
    ]
    if with_held:
        out.append(Block("held", "project_document", (1,), HELD_TEXT))
    return out


def ask(transport=None, role=4, blocks_=None, **kw):
    t = transport or FakeTransport(['{"ok": 1}'])
    answer = nine_call.ask(
        "run1",
        role,
        blocks_ or blocks(),
        "Which clause?",
        send=t,
        env=FakeTransport.ENV,
        **kw,
    )
    return answer, t


def body_texts(body: dict) -> list[str]:
    return [
        c["text"]
        for m in body["messages"]
        for c in m["content"]
        if c.get("type") == "text"
    ]


def ledger():
    return [e for e in claude_spend.entries() if e.get("run") == "run1"]


# ------------------------------------------------------------------------------------------------ the five record tests


def test_every_document_text_in_the_body_has_a_read_row_and_every_read_row_is_in_the_body():
    answer, t = ask()
    body = t.bodies[0]
    texts = body_texts(body)
    rows = nine_record.load_record("run1").roles[3].reads
    assert answer.ok and len(rows) == 2
    for text in (
        PAPER_TEXT,
        BOOK_TEXT,
    ):  # (1) each document text in the body has a row with its checksum
        assert any(r.text_sha256 == sha(text) and r.chars == len(text) for r in rows)
        assert text in texts
    for r in rows:  # (2) each read row's checksum is found in the body
        assert any(sha(x) == r.text_sha256 for x in texts)
    assert (
        rows[1].chapter_id == "4"
        and (rows[1].part_no, rows[1].part_of) == (1, 2)
        and rows[1].document_kind == "rule_book"
    )


def test_a_block_cannot_enter_a_request_without_a_row():
    """One function builds both: a block that is in the body is in `kept`, and `kept` gives the rows."""
    answer, t = ask(
        blocks_=blocks() + [Block("paper", "paper", (3,), "EXTRA BLOCK text")]
    )
    rows = nine_record.load_record("run1").roles[3].reads
    assert len(rows) == 3 and "EXTRA BLOCK text" in body_texts(t.bodies[0])
    assert {r.text_sha256 for r in rows} >= {sha("EXTRA BLOCK text")}
    assert len(
        [x for x in body_texts(t.bodies[0]) if x.startswith("[document block")]
    ) == len(rows)


def test_a_refused_call_has_state_refused_no_body_and_no_ledger_line():
    with review_engine.barring():  # Local only: nothing may be sent
        answer, t = ask()
    assert (
        not answer.ok
        and answer.state == "refused"
        and answer.error_code == "no_block_left"
    )
    assert t.bodies == [] and ledger() == []
    call = nine_record.load_record("run1").calls[0]
    assert call.state == "refused" and call.usd is None and call.request_sha256 == ""
    assert nine_record.load_record("run1").roles[3].reads == ()


def test_a_held_document_never_reaches_the_body_and_is_named_as_not_sent():
    answer, t = ask(blocks_=blocks(with_held=True))
    assert answer.ok and answer.not_sent == (("held", "not_approved"),)
    assert HELD_TEXT not in json.dumps(t.bodies[0])
    assert "held" not in {
        r.document_id for r in nine_record.load_record("run1").roles[3].reads
    }
    assert "held" not in answer.kept


def test_code_roles_make_no_call_and_write_counts_only():
    with pytest.raises(nine_call.NineCallError):
        nine_call.ask(
            "run1", 7, blocks(), "q", send=FakeTransport(), env=FakeTransport.ENV
        )
    nine_record.role_end(
        "run1", 7, "ran", produced={"quotes_checked": 12, "found": [3, 4]}
    )
    with pytest.raises(ValueError):
        nine_record.role_end(
            "run1", 8, "ran", produced={"words": "x" * 200}
        )  # a long string is not a count
    with pytest.raises(ValueError):
        nine_record.role_end("run1", 8, "ran", produced={"nested": {"a": 1}})


# ---------------------------------------------------------------------------------------------- step, ledger, money


def test_the_step_of_the_role_reaches_the_ledger_line_and_a_plain_call_still_writes_agent_review():
    ask(role=4)
    assert [e["step"] for e in ledger()] == ["nine_reviewer"]
    # a call with no `step` (today's callers) writes "agent_review", byte for byte as before
    sender = FakeTransport(['{"a": 1}'])
    with claude_approved.carrying(["paper"]), claude_spend.for_run("run1"):
        agent_claude._call(
            agent_claude.LEAD_MODEL,
            {"messages": [{"role": "user", "content": "x"}]},
            200,
            sender,
            FakeTransport.ENV,
        )
    assert [e["step"] for e in ledger()] == ["nine_reviewer", "agent_review"]


def test_the_sent_row_digest_is_the_ledger_digest_and_is_written_before_the_answer_ends():
    answer, t = ask()
    call = nine_record.load_record("run1").calls[0]
    assert (
        call.request_sha256
        == ledger()[0]["prompt_sha256"]
        == agent_claude.request_digest(t.bodies[0] | {})
    )
    assert (
        call.step == "nine_reviewer"
        and call.state == "answered"
        and call.usd == ledger()[0]["cost_usd"] > 0
    )


def test_a_role_that_reaches_its_budget_stops_with_ran_partly():
    gate = RoleGate.for_role(
        4, budget_usd=0.0001
    )  # smaller than the worst case of one call
    answer, t = ask(gate=gate)
    assert (
        not answer.ok
        and answer.error_code == "role_budget"
        and t.bodies == []
        and ledger() == []
    )
    nine_record.role_end(
        "run1", 4, "ran_partly", why="stopped at the role budget; no chapter was read"
    )
    role = nine_record.load_record("run1").roles[3]
    assert role.state == "ran_partly" and "budget" in role.why
    with pytest.raises(ValueError):
        nine_record.role_end(
            "run1", 4, "ran_partly"
        )  # a role that did not run in full says why


def test_a_local_call_writes_a_call_row_with_no_cost_and_no_ledger_line():
    seen = []

    def local(parts):
        seen.append(parts)
        return {"text": '{"x": 1}', "model": "local-a"}

    answer = nine_call.ask(
        "run1", 4, blocks(with_held=True), "q", engine="local", local_send=local
    )
    assert answer.ok and answer.usd is None and answer.data == {"x": 1}
    call = nine_record.load_record("run1").calls[0]
    assert (
        call.engine == "local"
        and call.usd is None
        and call.state == "answered"
        and call.model == "local-a"
    )
    assert ledger() == []
    nine_record.role_end("run1", 4, "ran", engine="local")
    assert nine_record.load_record("run1").roles[3].usd is None  # not known, never 0
    assert HELD_TEXT in json.dumps(
        seen[0]
    )  # Local sends nothing off the machine: the gate is for Claude


def test_the_nine_rows_exist_from_the_start_and_a_resume_keeps_a_finished_role():
    rec = nine_record.load_record("run1")
    assert [r.role_no for r in rec.roles] == list(range(1, 10)) and all(
        r.state == "not_run" and r.why == "not reached" for r in rec.roles
    )
    assert (
        rec.shown_document_ids == ("book", "paper")
        and "not run: 1 Reader: not reached" in rec.roles_line()
    )
    nine_record.role_end("run1", 1, "ran", produced={"facts": 7})
    nine_record.start_run("run1")  # a restart
    assert nine_record.load_record("run1").roles[0].state == "ran"
    assert nine_record.load_record("nobody") is None


def test_a_role_with_no_step_name_cannot_call_and_a_failed_call_is_recorded_with_a_code_only():
    answer, t = ask(transport=FakeTransport(raises=RuntimeError("secret words")))
    assert (
        not answer.ok
        and answer.state == "failed"
        and answer.error_code.startswith("transport_")
    )
    call = nine_record.load_record("run1").calls[0]
    assert call.state == "failed" and "secret" not in json.dumps(call.__dict__)


def test_on_the_local_model_a_picture_is_named_as_not_read_and_its_text_is_kept():
    seen = []

    def local(parts):
        seen.append(parts)
        return {"text": "{}", "model": "m"}

    pic = {"media_type": "image/png", "data": "AAAA"}
    answer = nine_call.ask(
        "run1",
        1,
        [
            Block("paper", "paper", (1,), "page words", picture=pic),
            Block("paper", "paper", (2,), None, picture=pic),
        ],
        "q",
        engine="local",
        local_send=local,
    )
    assert answer.ok and ("paper", "picture_not_read_locally") in answer.not_sent
    assert "AAAA" not in json.dumps(seen[0]) and "page words" in json.dumps(seen[0])
    assert (
        nine_record.load_record("run1").roles[0].reads[0].pictures == 0
    )  # the record says what was sent: no picture


def test_a_picture_on_claude_is_sent_and_counted_in_the_read_row():
    pic = {"media_type": "image/png", "data": "AAAA"}
    answer, t = ask(
        role=1, blocks_=[Block("paper", "paper", (1,), "page words", picture=pic)]
    )
    assert answer.ok and any(
        c.get("type") == "image" for m in t.bodies[0]["messages"] for c in m["content"]
    )
    assert nine_record.load_record("run1").roles[0].reads[0].pictures == 1


def test_a_reused_answer_is_recorded_as_reused_with_no_cost_and_no_ledger_line():
    call_id = nine_call.record_reused("run1", 4, blocks(), "a" * 64)
    call = nine_record.load_record("run1").calls[0]
    assert (
        call.call_id == call_id
        and call.state == "reused"
        and call.usd is None
        and ledger() == []
    )
    assert len(nine_record.load_record("run1").roles[3].reads) == 2
