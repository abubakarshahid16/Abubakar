"""`scripts/nine_record_check.py`: it passes a consistent record and fails on each invariant (one planted fault each)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import (
    claude_spend,
    db,
    nine_call,
    nine_record,
    review_engine,
    review_shown,
    submittal_review,
)
from app.config import settings
from app.nine_call import Block, FakeTransport

nine_call.id_source(
    "t_fact",
    r"f:\d{1,9}(:\d{1,9}){0,3}",
    "SELECT 1 FROM t_facts WHERE run_id = ? AND fid = ?",
)
Q = nine_call.template("chk_q", "Which clause of {book}?", book="id")

SPEC = importlib.util.spec_from_file_location(
    "nine_record_check",
    Path(__file__).resolve().parents[2] / "scripts" / "nine_record_check.py",
)
chk = importlib.util.module_from_spec(SPEC)
sys.modules["nine_record_check"] = chk
SPEC.loader.exec_module(chk)

NOW = "2026-11-16T00:00:00Z"


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "chk.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc in ("paper", "book"):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',5,?)",
                (doc, f"{doc}.pdf", doc * 8, f"{doc}.pdf", NOW),
            )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('r','paper','running',?,?)",
            (NOW, NOW),
        )
        review_shown.record_in(conn, "r", ["paper", "book"], NOW)
        review_engine.record_in(
            conn,
            "r",
            {"choice": "claude", "text_leaves": True, "parts": []},
            "starter1",
            then_ai=False,
            bar_claude=False,
            now=NOW,
        )
        for doc, text in (("paper", "paper words"), ("book", "book words")):
            for n in (1, 2, 4):
                conn.execute(
                    "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
                    (doc, n, text, len(text)),
                )
        conn.execute("CREATE TABLE t_facts (run_id TEXT, fid TEXT)")
        conn.execute("INSERT INTO t_facts VALUES ('r', 'f:1:1')")
        conn.execute("CREATE TABLE agent_review_fact (run_id TEXT)")
        conn.execute("CREATE TABLE agent_review_line (run_id TEXT)")
        for _ in range(3):
            conn.execute("INSERT INTO agent_review_fact VALUES ('r')")
        conn.execute("INSERT INTO agent_review_line VALUES ('r')")
    nine_record.start_run("r")
    nine_record.reset_held_cache()
    nine_call._thaw_for_tests()
    t = FakeTransport(['{"a": 1}'])
    blocks = [
        Block("paper", "paper", (1, 2)),
        Block("rule_book", "book", (4,), chapter_id="4"),
    ]
    answer = nine_call.ask(
        "r", 4, blocks, (Q, {"book": "book"}), send=t, env=FakeTransport.ENV
    )
    assert answer.ok
    nine_record.role_end("r", 4, "ran", produced={"findings": 1})
    nine_record.role_end(
        "r", 1, "ran", produced={"facts": 3, "read_nothing": "stored values only"}
    )
    nine_record.role_end("r", 8, "ran", engine="code", produced={"lines": 1})
    yield "r"
    db.reset_connection()


def problems(run_id="r", ledger="live"):
    conn = db.connect()
    entries = [e for e in claude_spend.entries()] if ledger == "live" else ledger
    return chk.check(conn, run_id, entries)


def test_a_consistent_record_passes(run):
    assert problems() == []


def test_not_nine_rows_fails(run):
    with db.connect() as conn:
        conn.execute("DELETE FROM agent_review_role WHERE role_no = 9")
    assert any("not nine role rows" in p for p in problems())


def test_a_ran_role_with_a_call_and_no_read_row_fails(run):
    with db.connect() as conn:
        conn.execute("DELETE FROM agent_review_role_read")
    assert any(
        "role 4 ran and made a call but has no read row" in p for p in problems()
    )


def test_a_read_page_outside_the_document_fails(run):
    with db.connect() as conn:
        conn.execute(
            "UPDATE agent_review_role_read SET pages_json = '[1, 99]' WHERE document_id = 'paper'"
        )
    assert any("page 99 outside document paper" in p for p in problems())


def test_a_claude_read_of_a_document_not_on_the_stored_list_fails(run):
    with db.connect() as conn:
        review_shown.record_in(
            conn, "r", ["paper"], NOW
        )  # the list no longer names the book
    assert any("document book to Claude" in p for p in problems())


def test_a_call_without_exactly_one_ledger_line_fails_and_so_does_a_ledger_line_without_a_call(
    run,
):
    assert any("matches 0 ledger line" in p for p in problems(ledger=[]))
    entries = [e for e in claude_spend.entries()]
    twice = entries + [dict(entries[0])]
    assert any("matches 2 ledger line" in p for p in problems(ledger=twice))
    stray = entries + [{"run": "r", "step": "nine_reviewer", "prompt_sha256": "f" * 64}]
    assert any("has no call row with its digest" in p for p in problems(ledger=stray))


def test_a_produced_count_that_differs_from_its_rows_fails(run):
    nine_record.role_end("r", 1, "ran", produced={"facts": 4, "read_nothing": "x"})
    nine_record.role_end("r", 8, "ran", engine="code", produced={"lines": 2})
    found = problems()
    assert any("produced facts=4 but agent_review_fact holds 3" in p for p in found)
    assert any("produced lines=2 but agent_review_line holds 1" in p for p in found)


def test_the_script_reads_a_copy_read_only_prints_the_rows_and_exits_by_the_result(
    run, tmp_path, capsys
):
    folder = tmp_path / "copy"
    folder.mkdir()
    src = sqlite3.connect(tmp_path / "chk.sqlite")
    dst = sqlite3.connect(folder / "rag_intelligence.sqlite")
    src.backup(dst)
    dst.close()
    src.close()
    (folder / "claude_spend.jsonl").write_text(
        "\n".join(json.dumps(e) for e in claude_spend.entries()), encoding="utf-8"
    )
    assert chk.main(["--copy", str(folder), "--run", "r"]) == 0
    out = capsys.readouterr().out
    assert (
        "4 Reviewer: ran" in out
        and "OK: the record is consistent" in out
        and "paper.pdf" not in out
    )
    (folder / "claude_spend.jsonl").write_text(
        "", encoding="utf-8"
    )  # the ledger lost its line
    assert chk.main(["--copy", str(folder), "--run", "r"]) == 1
    assert "FAIL: call" in capsys.readouterr().out


def test_a_read_row_of_a_call_that_was_not_sent_fails(run):
    with db.connect() as conn:
        conn.execute(
            "UPDATE agent_review_role_call SET state = 'refused'"
        )  # a refused call that kept its read rows
    assert any("its call was not sent" in p for p in problems())
    with db.connect() as conn:
        conn.execute("DELETE FROM agent_review_role_call")
    assert any("its call was not sent" in p for p in problems())


def test_a_claude_call_without_a_question_template_fails(run):
    with db.connect() as conn:
        conn.execute("UPDATE agent_review_role_call SET question_id = NULL")
    assert any("has no question template recorded" in p for p in problems())


def _derived_call(run):
    block = Block(
        "review_record",
        name="notes",
        sources=("paper",),
        items=(("f:1:1", "paper words"),),
    )
    answer = nine_call.ask(
        run,
        4,
        [block],
        (Q, {"book": "book"}),
        send=FakeTransport(["{}"]),
        env=FakeTransport.ENV,
    )
    assert answer.ok
    return answer.call_id


def test_a_verified_derived_block_passes_and_each_planted_cell_fault_fails(run):
    call_id = _derived_call(run)
    assert problems() == []
    with (
        db.connect() as conn
    ):  # (a) the recorded span no longer matches the stored page
        conn.execute(
            "UPDATE pages SET text = 'other text here' WHERE document_id = 'paper'"
        )
    assert any("does not hold the cell" in p for p in problems())
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = 'paper words' WHERE document_id = 'paper'"
        )
        conn.execute("UPDATE agent_review_role_cell SET chars = 70 WHERE kind = 'id'")
    assert any(
        "typed id cell of 70" in p for p in problems()
    )  # (b) a typed cell that is prose-sized
    with db.connect() as conn:
        conn.execute("UPDATE agent_review_role_cell SET chars = 5 WHERE kind = 'id'")
        conn.execute("DELETE FROM agent_review_role_cell WHERE call_id = ?", (call_id,))
    assert any(
        "no cell rows" in p for p in problems()
    )  # (c) a derived block sent with no cells


def test_a_legacy_code_kind_cell_is_a_planted_fault():
    # the checker must not allow the removed `code` kind: adding it to TYPED_KINDS makes this test fail
    assert "code" not in chk.TYPED_KINDS
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE agent_review_role (run_id, role_no, state, produced_json);"
        "CREATE TABLE agent_review_role_read (run_id, role_no, call_id, document_id, document_kind, chapter_id, pages_json);"
        "CREATE TABLE agent_review_role_call (run_id, role_no, call_id, engine, state);"
        "CREATE TABLE agent_review_role_cell (run_id, role_no, call_id, block_name, row_no, col_no, kind, chars, cell_sha256,"
        " source_document_id, source_page, span_start, span_len);"
        "INSERT INTO agent_review_role_call VALUES ('r', 4, 'c1', 'claude', 'answered');"
        "INSERT INTO agent_review_role_read VALUES ('r', 4, 'c1', 'paper', 'review_record', 'notes', '[]');"
        "INSERT INTO agent_review_role_cell VALUES ('r', 4, 'c1', 'notes', 0, 0, 'code', 5, 'x', NULL, NULL, NULL, NULL);"
    )
    reads = conn.execute("SELECT * FROM agent_review_role_read").fetchall()
    calls = conn.execute("SELECT * FROM agent_review_role_call").fetchall()
    assert any(
        "unknown cell kind code" in p
        for p in chk._cell_problems(conn, "r", reads, calls)
    )


def test_the_file_reader_pairs_a_reservation_with_its_settle_line(run):
    """The real ledger holds a RESERVATION line and a SETTLE line per call: read raw, a call "matches 2 ledger lines" (the fault on the
    first paid run); read by the app's own reader, it matches its settle line only and the record passes."""
    path = Path(settings.claude_spend_log)
    raw = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(e.get("reserved") for e in raw) and any(e.get("settles") for e in raw)  # the shape under test is really there
    assert any("matches 2 ledger line" in p for p in problems(ledger=raw))  # what today's raw read did
    assert problems(ledger=chk.read_ledger(path)) == []
