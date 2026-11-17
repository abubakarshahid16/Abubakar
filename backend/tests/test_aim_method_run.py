"""`aim_review.run` with the fake model: consent (only listed books), the build reads no paper, a stopped run still returns one
line per item, nothing is written, no document text in a log line, page windows for a long paper. No paid call, no socket."""

from __future__ import annotations

import logging

import pytest

from app import aim_review
from app.aim_review import engine as E
from app.aim_review import steps as S
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    BOOK_C,
    BOOK_RULES,
    PAPER,
    PAPER_PAGES,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


LISTED = frozenset({BOOK_A, BOOK_B})


def _run(conn, store=None, model=None, allowed=LISTED, **kw):
    model = model or E.FakeModel(kind="datasheet", subject_key="test_item")
    store = store if store is not None else MemoryStore()
    return (
        aim_review.run(
            conn,
            run_id="run_aim_t1",
            paper_id=PAPER,
            allowed_books=allowed,
            store=store,
            max_usd=5.0,
            model=model,
            **kw,
        ),
        model,
        store,
    )


def test_a_run_writes_one_line_per_checklist_item_in_order(aim_db):
    r, _model, store = _run(aim_db)
    assert r.status == "done" and r.stop_reason == ""
    saved = store.get(r.checklist_key)
    assert [ln["item_id"] for ln in r.lines] == [it["id"] for it in saved["items"]]
    assert [ln["line_no"] for ln in r.lines] == list(range(1, len(r.lines) + 1))
    assert all(ln["label"] in aim_review.LABELS for ln in r.lines)
    assert (
        r.checklist_key == "datasheet__test_item"
        and r.checklist_sha256
        and not r.checklist_reused
    )
    assert saved["built_from"] == "standards only, no paper"
    assert r.identity["kind"] == "datasheet"


def test_the_catalog_never_holds_a_book_outside_the_list(aim_db):
    r, model, _store = _run(aim_db)
    for call in model.asked:
        assert call["carries"] <= LISTED | {PAPER}, call["step"]
        assert BOOK_C not in call["prompt"] and "QX-STD-303" not in call["prompt"]
        for _clause, _page, text in BOOK_RULES[BOOK_C]:
            assert text not in call["prompt"]
    assert set(r.books) <= LISTED
    assert BOOK_C not in r.books


def test_with_only_one_book_listed_the_other_is_never_carried(aim_db):
    r, model, _store = _run(aim_db, allowed=frozenset({BOOK_A}))
    assert all(BOOK_B not in c["carries"] for c in model.asked)
    assert set(r.books) == {BOOK_A}


def test_the_checklist_build_reads_no_paper(aim_db):
    _r, model, _store = _run(aim_db)
    build = [
        c
        for c in model.asked
        if c["step"]
        in ("aim_select", "aim_checklist", "aim_checklist_retry", "aim_attack")
    ]
    assert build, "the checklist was built"
    for call in build:
        assert not call["cached"], call["step"]
        assert PAPER not in call["carries"]
        for page_text in PAPER_PAGES.values():
            for line in page_text.splitlines():
                assert line not in call["prompt"]
    judge = [c for c in model.asked if c["step"] in ("aim_identify", "aim_judge")]
    assert judge and all(c["cached"] and PAPER in c["carries"] for c in judge)


def test_the_build_guard_refuses_a_paper_block_before_it_is_asked(aim_db):
    from app.aim_review.checklist import NoPaper

    inner = E.FakeModel()
    guard = NoPaper(inner, aim_db, PAPER)
    with pytest.raises(E.StepFailed, match="build_saw_paper"):
        guard.ask(
            step="aim_checklist",
            model="claude-sonnet-5-5",
            system="",
            cached="a paper",
            prompt="x",
            carries={BOOK_A},
            max_tokens=10,
        )
    with pytest.raises(E.StepFailed, match="build_saw_paper"):
        guard.ask(
            step="aim_checklist",
            model="claude-sonnet-5-5",
            system="",
            cached=None,
            prompt="x",
            carries={BOOK_A, PAPER},
            max_tokens=10,
        )
    assert inner.asked == []


def test_a_saved_checklist_is_reused_and_no_build_call_is_made(aim_db):
    store = MemoryStore()
    first, _m, _s = _run(aim_db, store=store)
    second, model, _s = _run(aim_db, store=store)
    assert second.checklist_reused and second.checklist_sha256 == first.checklist_sha256
    assert [
        c["step"] for c in model.asked if c["step"] not in ("aim_identify", "aim_judge")
    ] == []
    assert len(store.puts) == 1
    assert [ln["item_id"] for ln in second.lines] == [
        ln["item_id"] for ln in first.lines
    ]


def test_a_saved_item_whose_book_is_not_on_the_list_is_not_judged_and_is_counted(
    aim_db,
):
    store = MemoryStore()
    first, _m, _s = _run(aim_db, store=store)
    saved = store.get(first.checklist_key)
    a_item = next(it for it in saved["items"] if it.get("book_id") == BOOK_A)
    second, model, _s = _run(aim_db, store=store, allowed=frozenset({BOOK_B}))
    line = next(ln for ln in second.lines if ln["item_id"] == a_item["id"])
    assert line["label"] == "Question" and line["code_note"] == aim_review.NOT_JUDGED
    assert not aim_review.sendable(line)
    assert BOOK_A in second.unlisted_books and second.unlisted_count == len(
        second.unlisted_books
    )
    assert all(BOOK_A not in c["carries"] for c in model.asked)
    assert len(second.lines) == len(saved["items"])


def test_a_stopped_run_still_returns_one_line_per_item(aim_db):
    store = MemoryStore()
    first, _m, _s = _run(aim_db, store=store)
    model = E.FakeModel(
        kind="datasheet",
        subject_key="test_item",
        fail={"aim_judge": "run_cap (USD 5.00 would be crossed)"},
    )
    r, _m, _s = _run(aim_db, store=store, model=model)
    assert r.status == "stopped" and "run_cap" in r.stop_reason
    assert len(r.lines) == len(first.lines)
    assert all(
        ln["label"] == "Question" and ln["code_note"] == aim_review.NOT_JUDGED
        for ln in r.lines
    )
    assert all(ln["comment"].startswith("not judged (") for ln in r.lines)
    assert not any(aim_review.sendable(ln) for ln in r.lines)


def test_a_cancelled_run_stops_between_batches_and_keeps_every_line(aim_db):
    store = MemoryStore()
    first, _m, _s = _run(aim_db, store=store)
    r, model, _s = _run(aim_db, store=store, cancelled=lambda: True)
    assert r.status == "stopped" and r.stop_reason == "cancelled"
    assert len(r.lines) == len(first.lines)
    assert not [c for c in model.asked if c["step"] == "aim_judge"]


def test_a_model_failure_never_raises(aim_db):
    model = E.FakeModel(fail={"aim_identify": "no_json"})
    r, _m, _s = _run(aim_db, model=model)
    assert r.status == "stopped" and "no_json" in r.stop_reason
    assert r.lines == []


def test_a_fault_inside_a_step_is_a_stopped_run_not_a_crash(aim_db, monkeypatch):
    def boom(*_a, **_k):
        raise KeyError("x")

    monkeypatch.setattr(S, "s4_judge", boom)
    r, _m, _s = _run(aim_db)
    assert r.status == "stopped" and r.stop_reason == "fault: KeyError"


def test_a_paper_with_no_stored_pages_stops_with_a_code(aim_db):
    with aim_db:
        aim_db.execute("DELETE FROM pages WHERE document_id = ?", (PAPER,))
    r, model, _s = _run(aim_db)
    assert r.status == "stopped" and r.stop_reason.startswith("no_pages")
    assert model.asked == []


def _db_state(conn) -> list:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    return [
        (t, conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in tables
    ]


def test_run_never_writes_the_database(aim_db):
    before, changes = _db_state(aim_db), aim_db.total_changes
    _run(aim_db)
    assert _db_state(aim_db) == before
    assert aim_db.total_changes == changes


def test_no_document_text_in_any_log_line(aim_db, caplog):
    caplog.set_level(logging.DEBUG)
    _run(
        aim_db,
        model=E.FakeModel(
            kind="datasheet", subject_key="test_item", fail={"aim_judge": "no_json"}
        ),
    )
    with aim_db:
        aim_db.execute("DELETE FROM pages WHERE document_id = ?", (PAPER,))
    _run(aim_db)
    words = [ln for t in PAPER_PAGES.values() for ln in t.splitlines() if ln.strip()]
    words += [text for rules in BOOK_RULES.values() for _c, _p, text in rules]
    for rec in caplog.records:
        msg = rec.getMessage()
        for w in words:
            assert w not in msg and w[:30] not in msg, rec.name


def test_a_store_that_refuses_the_checklist_does_not_stop_the_review(aim_db):
    class Refusing(MemoryStore):
        def put(self, key, checklist, *, run_id, usd):
            raise ValueError("refused")

    r, _m, _s = _run(aim_db, store=Refusing())
    assert r.status == "done" and r.checklist_sha256 == "" and r.lines


def test_the_run_meter_stops_before_a_call_that_would_cross_it(aim_db):
    """ClaudeModel: a worst case above the run's cap is refused BEFORE anything is built or sent."""
    model = E.ClaudeModel()
    r = aim_review.run(
        aim_db,
        run_id="run_aim_cap",
        paper_id=PAPER,
        allowed_books=LISTED,
        store=MemoryStore(),
        max_usd=0.0,
        model=model,
    )
    assert r.status == "stopped" and "run_cap" in r.stop_reason
    assert r.calls and r.calls[0]["code"] == "run_cap" and r.usd == 0.0


def test_not_judged_lines_stay_in_lines_but_are_never_sendable():
    line = {"label": "Question", "code_note": aim_review.NOT_JUDGED}
    assert not aim_review.sendable(line)
    assert aim_review.sendable({"label": "Question", "code_note": ""})
    assert aim_review.sendable(
        {"label": "Not met", "code_note": "code compared: 12 <= 10: false"}
    )
    assert not aim_review.sendable({"label": "Met", "code_note": ""})
    assert not aim_review.sendable({"label": "Does not apply", "code_note": ""})


# ------------------------------------------------------------------ page windows


def test_a_long_paper_is_judged_by_page_windows_and_answers_are_merged(
    aim_db, monkeypatch
):
    import re

    import app.aim_review.paper as paper_mod

    monkeypatch.setattr(paper_mod, "windows", lambda paper, kind: [[1], [2]])

    def judge(step, cached, prompt):
        assert "PART OF A LONGER PAPER" in prompt
        on_one = "=== PAGE 1 ===" in cached
        quote = "Operating temperature of the test item: 80 degC at the outlet"
        return {
            "judgments": [
                {"id": cid, "label": "Met", "page": 1, "quote": quote}
                if on_one
                else {"id": cid, "not_here": True}
                for cid in re.findall(r'"id": "(C\d+)"', prompt)
            ]
        }

    model = E.FakeModel(
        kind="datasheet", subject_key="test_item", answers={"aim_judge": judge}
    )
    r, model, _s = _run(aim_db, model=model)
    judges = [c for c in model.asked if c["step"] == "aim_judge"]
    assert len(judges) == 2  # one batch, two windows
    assert {
        ("=== PAGE 1 ===" in c["cached_text"], "=== PAGE 2 ===" in c["cached_text"])
        for c in judges
    } == {(True, False), (False, True)}
    held = [ln for ln in r.lines if ln["source"] == "held standard"]
    assert held and all(ln["label"] == "Met" and ln["page"] == 1 for ln in held)


def test_an_item_no_window_shows_is_a_question_that_says_so(aim_db, monkeypatch):
    import app.aim_review.paper as paper_mod

    monkeypatch.setattr(paper_mod, "windows", lambda paper, kind: [[1], [2]])

    def judge(step, cached, prompt):
        import re

        return {
            "judgments": [
                {"id": cid, "not_here": True}
                for cid in re.findall(r'"id": "(C\d+)"', prompt)
            ]
        }

    r, _m, _s = _run(
        aim_db,
        model=E.FakeModel(
            kind="datasheet", subject_key="test_item", answers={"aim_judge": judge}
        ),
    )
    assert r.lines and all(
        ln["label"] == "Question" and ln["code_note"] == S.NOT_ON_ANY_PAGE
        for ln in r.lines
    )
    assert all(aim_review.sendable(ln) for ln in r.lines)


def test_a_firm_finding_in_one_window_is_kept_over_a_met_in_another():
    from app.aim_review.paper import Paper

    paper = Paper(paper_id="p", pages=PAPER_PAGES)
    it = {
        "id": "C001",
        "book": "",
        "clause": "",
        "source": S.HELD,
        "topic": "t",
        "kind": "presence",
    }
    js = [
        {
            "label": "Met",
            "page": 1,
            "quote": "Operating temperature of the test item: 80 degC at the outlet",
        },
        {
            "label": "Not met",
            "page": 2,
            "quote": "Body material of the test item: carbon steel to the buyer list",
        },
        {
            "label": "Not met",
            "page": 2,
            "quote": "words that are on no page of the paper at all",
        },
    ]
    got = S._merge(it, js, paper, {}, "", True)
    assert got["label"] == "Not met" and got["page"] == 2 and got["quote"]


def test_a_paper_that_fits_is_one_window_with_no_window_line(aim_db):
    _r, model, _s = _run(aim_db)
    judges = [c for c in model.asked if c["step"] == "aim_judge"]
    assert judges and all("PART OF A LONGER PAPER" not in c["prompt"] for c in judges)
    assert all(
        "=== PAGE 1 ===" in c["cached_text"] and "=== PAGE 2 ===" in c["cached_text"]
        for c in judges
    )
