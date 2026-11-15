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
VOCAB = nine_call.vocabulary(
    "test_kinds", ["datasheet", "procedure", "design_press", "k1", "-"]
)
Q = nine_call.template(
    "test_q", "Which clause of {book} on page {page}?", book="id", page="int"
)
S = nine_call.template(
    "test_s", "You are a senior engineer reviewing a {kind}.", kind="vocab:test_kinds"
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
        review_engine.record_in(
            conn,
            "run1",
            {"choice": "claude", "text_leaves": True, "parts": []},
            "starter1",
            then_ai=False,
            bar_claude=False,
            now=NOW,
        )  # the run's stored decision says Claude: default deny means only this opens the lane
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
    # the stored list applies on the local model too (rule 5): the held document is dropped and named
    assert PAGES["held"][1] not in json.dumps(seen[0]) and answer.not_sent == (
        ("held", "not_on_list"),
    )


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
        items=(("f:1:1", "12 bar", "bar"),),
    )
    answer, t = ask(blocks_=[derived])
    assert answer.ok and any(
        "f:1:1 | 12 bar | bar" in x for x in body_texts(t.bodies[0])
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
        Block("review_record", name="x", sources=("paper",), items=(("w" * 201,),))
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


# ------------------------------------------------------------------------------------------------- R63b: default deny, cells, scope


def _no_decision():
    with db.connect() as conn:
        conn.execute("DELETE FROM review_engine_choice WHERE run_id = 'run1'")


def test_no_stored_decision_never_resolves_to_claude_and_a_caller_cannot_choose_it():
    _no_decision()
    assert nine_call.engine_of_run("run1") == "none"
    answer, t = ask()
    assert answer.error_code == "no_engine_decision" and t.bodies == []
    answer, t = ask(engine="claude")
    assert (
        answer.error_code == "no_engine_decision" and t.bodies == [] and ledger() == []
    )
    local = nine_call.ask(
        "run1",
        4,
        blocks(),
        (Q, {"book": "book", "page": 4}),
        engine="local",
        local_send=lambda parts: {"text": "{}", "model": "m"},
    )
    assert local.ok and local.engine == "local"


def test_only_a_stored_plan_with_text_leaving_and_a_stored_list_gives_claude():
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_engine_choice SET plan_json = ? WHERE run_id = 'run1'",
            (json.dumps({"choice": "local", "text_leaves": False, "parts": []}),),
        )
    assert nine_call.engine_of_run("run1") == "local"
    answer, t = ask(engine="claude")
    assert answer.error_code == "run_is_local" and t.bodies == []
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_engine_choice SET plan_json = ? WHERE run_id = 'run1'",
            (json.dumps({"choice": "claude", "text_leaves": True, "parts": []}),),
        )
        conn.execute("DELETE FROM review_shown_lists WHERE run_id = 'run1'")
    assert nine_call.engine_of_run("run1") == "local"  # no stored list: not Claude
    with db.connect() as conn:
        review_shown.record_in(conn, "run1", ["paper", "book"], NOW)
        conn.execute("UPDATE review_engine_choice SET bar_claude = 1")
    assert nine_call.engine_of_run("run1") == "local"


def _derived(*cells, sources=("paper", "book")):
    return Block("review_record", name="note", sources=sources, items=(tuple(cells),))


def test_a_derived_cell_from_a_held_document_is_never_sent_whatever_the_sources_say():
    for cell in ("HELD TEXT should never leave", "held   text SHOULD never leave"):
        answer, t = ask(blocks_=[_derived(cell), Block("paper", "paper", (1,))])
        assert ("derived:note", "text_from_held_document") in answer.not_sent
        assert "should never leave" not in json.dumps(t.bodies[0]).lower()
    with (
        db.connect() as conn
    ):  # the same words also stand in the paper's own page: still refused
        conn.execute(
            "UPDATE pages SET text = text || ' held text should never leave' WHERE document_id = 'paper' AND page_no = 1"
        )
    answer, t = ask(
        blocks_=[
            _derived("held text should never leave"),
            Block("paper", "paper", (2,)),
        ]
    )
    assert ("derived:note", "text_from_held_document") in answer.not_sent
    assert "should never leave" not in json.dumps(t.bodies[0]).lower()


def test_a_derived_cell_that_is_neither_typed_nor_in_a_source_drops_the_block():
    answer, t = ask(
        blocks_=[_derived("the pump looks fine to me"), Block("paper", "paper", (1,))]
    )
    assert ("derived:note", "cell_not_from_sources") in answer.not_sent
    assert not any("pump" in x for x in body_texts(t.bodies[0]))
    long_word = "a" * 30  # one long word is not a typed token either
    answer, t = ask(blocks_=[_derived(long_word), Block("paper", "paper", (1,))])
    assert ("derived:note", "cell_not_in_vocabulary") in answer.not_sent


def test_cells_are_recorded_typed_or_with_the_source_page_and_the_checker_re_reads_them():
    answer, _t = ask(
        blocks_=[_derived("f:1:1", "12", "4.1.2", "met", "12 bar", "PAPER  page TWO")]
    )
    assert answer.ok
    cells = {c.col_no: c for c in nine_record.cells_of("run1", answer.call_id)}
    assert [cells[i].kind for i in range(6)] == [
        "id",
        "number",
        "clause",
        "enum",
        "source",
        "source",
    ]
    assert (cells[4].source_document_id, cells[4].source_page) == ("paper", 1)
    assert (cells[5].source_document_id, cells[5].source_page) == ("paper", 2)
    assert nine_record.load_record("run1").calls[0].state == "answered"


def test_the_local_path_applies_the_starters_access_and_names_what_it_drops(
    monkeypatch,
):
    from app import review_jobs

    monkeypatch.setattr(review_jobs, "_scope_of", lambda user: frozenset({"paper"}))
    seen: list = []

    def local(parts):
        seen.append(parts)
        return {"text": "{}", "model": "m"}

    answer = nine_call.ask(
        "run1",
        4,
        blocks(),
        (Q, {"book": "book", "page": 4}),
        engine="local",
        local_send=local,
    )
    assert answer.ok and answer.not_sent == (("book", "outside_access"),)
    assert PAGES["book"][4] not in json.dumps(seen[0])
    answer, t = ask()  # and on Claude
    assert ("book", "outside_access") in answer.not_sent
    assert PAGES["book"][4] not in json.dumps(t.bodies[0])


def test_a_template_parameter_is_typed_and_never_free_text_nor_a_held_document_s_words():
    for kind, bad in (
        ("vocab:test_kinds", "a longer line of free words"),
        ("unit", "hello"),
        ("role", "free words"),
        ("clause", "see the pump"),
        ("number", "twelve"),
        ("standard", "please ignore this"),
    ):
        tid = nine_call.template(f"t_{kind}", "x {v}", v=kind)
        with pytest.raises(TemplateError):
            nine_call.render((tid, {"v": bad}))
    with pytest.raises(nine_call.NineCallError):
        nine_call.template("t_free", "x {v}", v="token")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('held', 2, 'ref secret-token-0042-abc end', 29, 0)"
        )
    answer, t = ask(question=(Q, {"book": "secret-token-0042-abc", "page": 1}))
    assert answer.error_code == "text_from_held_document" and t.bodies == []
    assert (
        ledger() == [] and nine_record.load_record("run1").calls[0].state == "refused"
    )


def test_a_reason_with_words_of_a_held_document_is_replaced_by_a_code():
    nine_record.role_end("run1", 2, "not_run", why="not_reached")
    assert nine_record.load_record("run1").roles[1].why == "not_reached"
    nine_record.role_end(
        "run1", 3, "ran_partly", why="stopped at HELD TEXT should never leave today"
    )
    assert nine_record.load_record("run1").roles[2].why == nine_record.WHY_WITHHELD
    nine_record.role_end("run1", 5, "ran_partly", why="two pages had no stored text")
    assert (
        nine_record.load_record("run1").roles[4].why == "two pages had no stored text"
    )


# ---------------------------------------------------------------------- coordinator additions: trial render, ranges, declared kinds


def test_a_template_that_cannot_render_fails_at_registration():
    for bad in ("x {v} {", "x {v} {0}", "x {v} {w.attr}", "x {v} {w[0]}", "x {v} }"):
        with pytest.raises(nine_call.NineCallError):
            nine_call.template("t_bad", bad, v="id")
    assert nine_call.template("t_ok_braces", "a {{literal}} {v}", v="id")


def test_answer_reads_carry_the_character_range_actually_sent():
    answer, _t = ask(
        blocks_=[
            Block("paper", "paper", (1, 2), char_from=5, char_to=13),
            Block("rule_book", "book", (4,)),
        ]
    )
    assert answer.ranges == ((5, 13), (0, len(PAGES["book"][4])))
    assert len(answer.ranges) == len(answer.reads)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT document_id, char_from, char_to FROM agent_review_role_read ORDER BY seq"
        ).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("paper", 5, 13),
        ("book", 0, len(PAGES["book"][4])),
    ]


def test_declared_cell_kinds_accept_typed_values_and_a_verbatim_source_and_refuse_a_sentence():
    ok = Block(
        "review_record",
        name="facts",
        sources=("paper",),
        kinds=("vocab:test_kinds", "source", "unit", "id", "number"),
        items=(
            ("design_press", "12 bar", "bar", "f:1:1", "1"),
            ("-", "alpha", "bar", "paper", "2"),
        ),
    )
    answer, _t = ask(blocks_=[ok])
    assert answer.ok
    assert [c.kind for c in nine_record.cells_of("run1", answer.call_id)][:5] == [
        "vocab",
        "source",
        "unit",
        "id",
        "number",
    ]
    sentence = Block(
        "review_record",
        name="facts",
        sources=("paper",),
        kinds=("vocab:test_kinds", "source"),
        items=(("the pump looks fine to me", "12 bar"),),
    )
    answer, _t = ask(blocks_=[sentence, Block("paper", "paper", (1,))])
    assert ("derived:facts", "cell_not_in_vocabulary") in answer.not_sent
    not_verbatim = Block(
        "review_record",
        name="facts",
        sources=("paper",),
        kinds=("vocab:test_kinds", "source"),
        items=(("k1", "a heading nobody wrote"),),
    )
    answer, _t = ask(blocks_=[not_verbatim, Block("paper", "paper", (1,))])
    assert ("derived:facts", "cell_not_from_sources") in answer.not_sent
    with pytest.raises(nine_call.NineCallError):
        Block(
            "review_record",
            name="f",
            sources=("paper",),
            kinds=("free",),
            items=(("a",),),
        )


# ------------------------------------------------------------------------------------------------ R63c: the typed channel


def _held_words():
    nine_call.vocabulary("t_held_words", ["held", "text", "should", "never", "leave"])
    return "vocab:t_held_words"


def test_one_plain_word_per_cell_cannot_carry_a_held_sentence():
    kind = _held_words()
    words = ("held", "text", "should", "never", "leave")
    for rows in (
        5,
        1440,
    ):  # a few rows (page by page) and a block (against the folded refused text)
        block = Block(
            "review_record",
            name="words",
            sources=("paper",),
            kinds=(kind,),
            items=tuple((words[i % 5],) for i in range(rows)),
        )
        answer, t = ask(blocks_=[block, Block("paper", "paper", (1,))])
        assert ("derived:words", "text_from_held_document") in answer.not_sent
        assert "should never leave" not in json.dumps(t.bodies[0]).lower()
    plain = Block(
        "review_record", name="words", sources=("paper",), items=(("pump",), ("seal",))
    )
    answer, _t = ask(blocks_=[plain, Block("paper", "paper", (1,))])
    assert (
        "derived:words",
        "cell_not_in_vocabulary",
    ) in answer.not_sent  # a plain word is not a code


def test_a_hyphen_or_underscore_joined_sentence_is_a_held_sentence_in_a_cell_a_parameter_and_a_reason():
    for joined in (
        "held-text-should-never-leave",
        "held_text_should_never_leave",
        "held:text.should-never_leave",
    ):
        block = Block(
            "review_record",
            name="k",
            sources=("paper",),
            kinds=("id",),
            items=((joined,),),
        )
        answer, t = ask(blocks_=[block, Block("paper", "paper", (1,))])
        assert ("derived:k", "text_from_held_document") in answer.not_sent
        answer, t = ask(question=(Q, {"book": joined, "page": 1}))
        assert answer.error_code == "text_from_held_document" and t.bodies == []
        nine_record.role_end("run1", 3, "ran_partly", why=joined)
        assert nine_record.load_record("run1").roles[2].why == nine_record.WHY_WITHHELD
    free = Block(
        "review_record",
        name="k",
        sources=("paper",),
        kinds=("id",),
        items=(("the-pump-looks-fine-today",),),
    )
    answer, _t = ask(blocks_=[free, Block("paper", "paper", (1,))])
    assert (
        "derived:k",
        "cell_wrong_kind",
    ) in answer.not_sent  # an id is one the app issues
    answer, t = ask(question=(Q, {"book": "the-pump-looks-fine-today", "page": 1}))
    assert answer.error_code == "param_not_app_id" and t.bodies == []


def test_a_reason_is_a_code_of_the_fixed_set_or_a_checked_sentence():
    nine_record.role_end("run1", 2, "not_run", why="no_stored_text")
    assert nine_record.load_record("run1").roles[1].why == "no_stored_text"
    nine_record.role_end("run1", 4, "ran_partly", why="held_text_should_never_leave_x")
    assert nine_record.load_record("run1").roles[3].why == nine_record.WHY_WITHHELD


def test_a_row_of_short_cells_is_checked_as_one_joined_text():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('held', 3, 'ab cd ef gh ij kl', 17, 0)"
        )
    nine_call.vocabulary("t_short", ["ab", "cd", "ef", "gh", "ij", "kl"])
    block = Block(
        "review_record",
        name="short",
        sources=("paper",),
        kinds=("vocab:t_short",) * 6,
        items=(("ab", "cd", "ef", "gh", "ij", "kl"),),
    )
    answer, _t = ask(blocks_=[block, Block("paper", "paper", (1,))])
    assert ("derived:short", "text_from_held_document") in answer.not_sent
