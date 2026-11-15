"""B1 of the nine-role review: the call seam (`nine_call.ask`) and the stored record (`nine_record`). Invented documents; a fake
Messages transport; no network, no key, no model."""

from __future__ import annotations

import hashlib
import json

import pytest

from app import (
    agent_claude,
    agent_review_pages,
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
from app.nine_call import Block, FakeTransport, RoleGate, TemplateError

NOW = "2026-11-16T00:00:00Z"
PAGES = {
    "paper": {1: "PAPER PAGE ONE alpha 12 bar", 2: "PAPER PAGE TWO beta"},
    "book": {4: "BOOK CLAUSE 4.1 shall hold", 5: "BOOK PAGE FIVE"},
    "held": {1: "HELD TEXT should never leave"},
}
Q = nine_call.template(
    "test_q", "Which clause of {book} on page {page}?", book="id", page="int"
)
S = nine_call.template(
    "test_s", "You are a senior engineer reviewing a {kind}.", kind="token"
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
        for doc, pages in PAGES.items():
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',?,?)",
                (doc, f"{doc}.pdf", doc * 8, f"{doc}.pdf", max(pages), NOW),
            )
            for n, text in pages.items():
                conn.execute(
                    "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
                    (doc, n, text, len(text)),
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
        Block("paper", "paper", (1, 2)),
        Block("rule_book", "book", (4,), chapter_id="4", part_no=1, part_of=2),
    ]
    if with_held:
        out.append(Block("project_document", "held", (1,)))
    return out


def ask(transport=None, role=4, blocks_=None, **kw):
    t = transport or FakeTransport(['{"ok": 1}'])
    kw.setdefault("question", (Q, {"book": "book", "page": 4}))
    answer = nine_call.ask(
        "run1", role, blocks_ or blocks(), send=t, env=FakeTransport.ENV, **kw
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


def ask_args(question=None):
    return (question or (Q, {"book": "book", "page": 4}),)


# --------------------------------------------------------------------------------------- the five record tests


def test_every_document_text_in_the_body_has_a_read_row_and_every_read_row_is_in_the_body():
    answer, t = ask()
    texts = body_texts(t.bodies[0])
    rows = nine_record.load_record("run1").roles[3].reads
    paper_text = PAGES["paper"][1] + "\n" + PAGES["paper"][2]
    assert answer.ok and len(rows) == 2
    for text in (
        paper_text,
        PAGES["book"][4],
    ):  # (1) the words in the body are the STORED pages, each with a row and its checksum
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
    answer, t = ask(blocks_=blocks() + [Block("paper", "paper", (2,))])
    rows = nine_record.load_record("run1").roles[3].reads
    assert len(rows) == 3
    assert len(
        [x for x in body_texts(t.bodies[0]) if x.startswith("[document block")]
    ) == len(rows)


def test_a_refused_call_has_state_refused_no_body_and_no_ledger_line():
    with review_engine.barring():  # Local only: nothing may be sent
        answer, t = ask(engine="claude")
    assert (
        not answer.ok
        and answer.state == "refused"
        and answer.error_code == "run_is_local"
    )
    assert t.bodies == [] and ledger() == []
    call = nine_record.load_record("run1").calls[0]
    assert call.state == "refused" and call.usd is None and call.request_sha256 == ""
    assert nine_record.load_record("run1").roles[3].reads == ()


def test_a_held_document_never_reaches_the_body_and_is_named_as_not_sent():
    answer, t = ask(blocks_=blocks(with_held=True))
    assert answer.ok and answer.not_sent == (("held", "not_approved"),)
    assert PAGES["held"][1] not in json.dumps(t.bodies[0])
    assert (
        "held"
        not in {r.document_id for r in nine_record.load_record("run1").roles[3].reads}
        and "held" not in answer.kept
    )


def test_code_roles_make_no_call_and_write_counts_only():
    with pytest.raises(nine_call.NineCallError):
        nine_call.ask(
            "run1",
            7,
            blocks(),
            (Q, {"book": "book", "page": 1}),
            send=FakeTransport(),
            env=FakeTransport.ENV,
        )
    nine_record.role_end(
        "run1", 7, "ran", produced={"quotes_checked": 12, "found": [3, 4]}
    )
    with pytest.raises(ValueError):
        nine_record.role_end("run1", 8, "ran", produced={"words": "x" * 200})
    with pytest.raises(ValueError):
        nine_record.role_end("run1", 8, "ran", produced={"nested": {"a": 1}})


# ------------------------------------------------------------------------------------- step, ledger, money


def test_the_step_of_the_role_reaches_the_ledger_line_and_a_plain_call_still_writes_agent_review():
    ask(role=4)
    assert [e["step"] for e in ledger()] == ["nine_reviewer"]
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


def test_the_sent_row_digest_is_the_ledger_digest():
    answer, t = ask()
    call = nine_record.load_record("run1").calls[0]
    assert (
        call.request_sha256
        == ledger()[0]["prompt_sha256"]
        == agent_claude.request_digest(t.bodies[0])
    )
    assert (
        call.step == "nine_reviewer"
        and call.state == "answered"
        and call.usd == ledger()[0]["cost_usd"] > 0
    )


def test_a_role_that_reaches_its_budget_stops_with_ran_partly():
    answer, t = ask(gate=RoleGate.for_role(4, budget_usd=0.0001))
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
        nine_record.role_end("run1", 4, "ran_partly")


def test_a_failed_call_of_unknown_cost_counts_at_the_reserved_amount_against_the_role_budget():
    answer, _t = ask(transport=FakeTransport(raises=RuntimeError("secret words")))
    assert (
        not answer.ok
        and answer.state == "failed"
        and answer.error_code.startswith("transport_")
    )
    call = nine_record.load_record("run1").calls[0]
    assert (
        call.state == "failed"
        and call.usd is None
        and "secret" not in json.dumps(call.__dict__)
    )
    assert (
        nine_record.role_usd("run1", 4) == 0.0 and nine_record.role_spend("run1", 4) > 0
    )  # reported unknown, counted conservatively
    gate = RoleGate.for_role(4, budget_usd=nine_record.role_spend("run1", 4) + 1e-9)
    again, t = ask(gate=gate)
    assert again.error_code == "role_budget" and t.bodies == []


def test_a_call_refused_at_the_spend_reservation_has_no_read_rows(monkeypatch):
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.000001)
    answer, t = ask()
    assert (
        not answer.ok
        and answer.state == "refused"
        and t.bodies == []
        and ledger() == []
    )
    rec = nine_record.load_record("run1")
    assert rec.calls[0].state == "refused" and rec.roles[3].reads == ()


def test_the_local_call_writes_a_row_with_no_cost_and_no_ledger_line_and_the_gate_is_for_claude_only():
    seen = []

    def local(parts):
        seen.append(parts)
        return {"text": '{"x": 1}', "model": "local-a"}

    answer = nine_call.ask(
        "run1",
        4,
        blocks(with_held=True),
        (Q, {"book": "book", "page": 4}),
        engine="local",
        local_send=local,
    )
    assert (
        answer.ok
        and answer.usd is None
        and answer.data == {"x": 1}
        and answer.engine == "local"
    )
    call = nine_record.load_record("run1").calls[0]
    assert (
        call.engine == "local"
        and call.usd is None
        and call.model == "local-a"
        and ledger() == []
    )
    nine_record.role_end("run1", 4, "ran", engine="local")
    assert nine_record.load_record("run1").roles[3].usd is None
    assert PAGES["held"][1] in json.dumps(
        seen[0]
    )  # Local sends nothing off the machine


def test_on_the_local_model_a_picture_is_named_as_not_read_and_its_text_is_kept():
    seen = []

    def local(parts):
        seen.append(parts)
        return {"text": "{}", "model": "m"}

    answer = nine_call.ask(
        "run1",
        1,
        [Block("paper", "paper", (1,)), Block("paper", "paper", (2,), picture=True)],
        (Q, {"book": "paper", "page": 1}),
        engine="local",
        local_send=local,
    )
    assert answer.ok and ("paper", "picture_not_read_locally") in answer.not_sent
    assert nine_record.load_record("run1").roles[0].reads[0].pictures == 0


def test_a_picture_on_claude_is_rendered_by_the_seam_and_counted_in_the_read_row(
    monkeypatch,
):
    monkeypatch.setattr(
        agent_review_pages, "document_ref", lambda conn, doc: {"stored_path": "x"}
    )
    monkeypatch.setattr(
        agent_review_pages,
        "page_image",
        lambda ref, page, **k: b"\x89PNG\r\n\x1a\n" + b"0" * 40,
    )
    answer, t = ask(role=1, blocks_=[Block("paper", "paper", (1,), picture=True)])
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
    nine_record.start_run("run1")
    assert (
        nine_record.load_record("run1").roles[0].state == "ran"
        and nine_record.load_record("nobody") is None
    )


# ---------------------------------------------------------------------------- R63: the engine is the run's


def test_a_run_whose_plan_kept_the_ai_review_local_is_never_sent_to_claude_outside_barring():
    with db.connect() as conn:
        review_engine.ensure_schema(conn)
        review_engine.record_in(
            conn,
            "run1",
            {"choice": "local"},
            "u",
            then_ai=False,
            bar_claude=True,
            now=NOW,
        )
        conn.commit()
    assert nine_call.engine_of_run("run1") == "local"
    asked, t = ask(engine="claude")  # a caller cannot choose Claude over a Local run
    assert (
        not asked.ok
        and asked.error_code == "run_is_local"
        and t.bodies == []
        and ledger() == []
    )
    seen = []
    derived = nine_call.ask(
        "run1",
        4,
        blocks(),
        (Q, {"book": "book", "page": 4}),
        local_send=lambda p: seen.append(p) or {"text": "{}", "model": "m"},
    )
    assert (
        derived.ok and derived.engine == "local" and len(seen) == 1 and ledger() == []
    )  # the engine is DERIVED: Local


def test_a_run_with_no_bar_is_claude():
    assert nine_call.engine_of_run("run1") == "claude"


# ------------------------------------------------------------------------- R63: text only from templates and blocks


def test_question_and_system_are_templates_never_free_strings():
    with pytest.raises((TypeError, ValueError)):
        nine_call.render("a free string")  # type: ignore[arg-type]
    with pytest.raises(Exception):
        nine_call.ask(
            "run1",
            4,
            blocks(),
            "HELD TEXT should never leave",
            send=FakeTransport(),
            env=FakeTransport.ENV,
        )  # type: ignore[arg-type]
    for bad in (
        {"book": "a\nb", "page": 1},
        {"book": "x" * 80, "page": 1},
        {"book": "ok", "page": "7"},
        {"book": "ok"},
        {"book": "ok", "page": 1, "x": 1},
    ):
        with pytest.raises(TemplateError):
            nine_call.render((Q, bad))
    with pytest.raises(TemplateError):
        nine_call.render(("no_such_template", {}))
    with pytest.raises(nine_call.NineCallError):
        nine_call.template(
            "test_q", "other words {book}", book="id"
        )  # the same id with other words


def test_a_held_documents_words_cannot_ride_in_a_template_parameter():
    leak = PAGES[
        "held"
    ][
        1
    ]  # 28 characters: a short token is allowed, so the cap is 60 and one line; a long copy is refused
    long_copy = leak + " " + leak + " " + leak
    with pytest.raises(TemplateError):
        nine_call.render((S, {"kind": long_copy}))
    with pytest.raises(TemplateError):
        nine_call.render((S, {"kind": leak + "\nmore"}))


def test_the_template_id_and_the_parameter_digest_are_recorded_with_the_call():
    ask(system=(S, {"kind": "datasheet"}))
    with db.connect() as conn:
        row = conn.execute(
            "SELECT question_id, system_id, params_sha256 FROM agent_review_role_call"
        ).fetchone()
    assert (
        row["question_id"] == "test_q"
        and row["system_id"] == "test_s"
        and len(row["params_sha256"]) == 64
    )


def test_the_seam_loads_the_stored_pages_and_a_caller_cannot_hand_it_text():
    with pytest.raises(TypeError):
        Block("paper", "paper", (1,), text="words from the caller")  # type: ignore[call-arg]
    answer, t = ask(blocks_=[Block("paper", "paper", (1, 3))])  # page 3 is not stored
    assert (
        not answer.ok
        and answer.error_code == "no_block_left"
        and answer.not_sent == (("paper", "no_stored_text"),)
        and t.bodies == []
    )
    answer, t = ask(blocks_=[Block("paper", "paper", (1, 2), char_from=5, char_to=13)])
    full = PAGES["paper"][1] + "\n" + PAGES["paper"][2]
    assert (
        full[5:13] in body_texts(t.bodies[0])
        and nine_record.load_record("run1").roles[3].reads[0].chars == 8
    )


def test_a_derived_block_names_its_sources_every_source_is_gated_and_each_gets_a_read_row():
    derived = Block(
        "review_record",
        name="fact_sheet",
        sources=("paper", "book"),
        items=(("f:1:1", "Design pressure", "12 bar", "p1"),),
    )
    answer, t = ask(blocks_=[derived])
    assert (
        answer.ok
        and "Design pressure | 12 bar" not in ""
        and any("Design pressure" in x for x in body_texts(t.bodies[0]))
    )
    rows = nine_record.load_record("run1").roles[3].reads
    assert [(r.document_id, r.document_kind, r.chapter_id) for r in rows] == [
        ("paper", "review_record", "fact_sheet"),
        ("book", "review_record", "fact_sheet"),
    ]
    held = Block(
        "review_record", name="note", sources=("paper", "held"), items=(("a", "b"),)
    )
    dropped, t2 = ask(blocks_=[held, Block("paper", "paper", (1,))])
    assert ("held", "not_approved") in dropped.not_sent and not any(
        "note" in x for x in body_texts(t2.bodies[0])
    )


def test_a_derived_block_must_name_sources_and_hold_short_one_line_tokens():
    with pytest.raises(nine_call.NineCallError):
        Block("review_record", name="x", sources=(), items=(("a",),))
    with pytest.raises(TemplateError):
        Block("review_record", name="x", sources=("paper",), items=(("a\nb",),))
    with pytest.raises(TemplateError):
        Block("review_record", name="x", sources=("paper",), items=(("w" * 61,),))
    with pytest.raises(TemplateError):
        Block(
            "review_record",
            name="x",
            sources=("paper",),
            items=tuple(("w" * 59,) for _ in range(600)),
        )


def test_a_reason_is_short_and_one_line():
    with pytest.raises(ValueError):
        nine_record.role_end("run1", 2, "ran_partly", why="x" * 121)
    with pytest.raises(ValueError):
        nine_record.role_end("run1", 2, "ran_partly", why="two\nlines")
    nine_record.role_end("run1", 2, "ran_partly", why="x" * 120)
