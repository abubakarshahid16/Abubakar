"""Review round 1 of PR #1897 (order 14): the fresh reviewer's attack tests, adopted into the PR, plus the four guards it found
untested. Invented values only. Each test asserts the SAFE behaviour: the code stamp rests on verified quotes only (B1), a value
left to the vendor is always a Question (B2), a rule book the viewer may not read is never named (B3), a stopped run is shown as
stopped, no bare method word in the file, the saved checklist names its books, the run's cost is the ledger's."""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app import aim_review, aim_review_store
from app.aim_review import engine as E
from app.aim_review import steps as S
from app.aim_review.paper import Paper
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

PAGES = {
    1: "Design pressure of the test item: 12 bar gauge at the inlet\nOperating temperature: 80 degC at the outlet\n",
    2: "Noise level of the test item: to be advised by the vendor later\nBody material: carbon steel, grade to buyer list\n"
    "Corrosion allowance of the test item: BY CONTRACTOR\nHydrotest pressure of the test item: *\n"
    "Flange rating of the test item: VTA\nNozzle load of the test item: TBD\n",
}
P = Paper(paper_id="doc_p", pages=PAGES)
BOOKS = {"B01": {"alias": "B01", "book": "doc_b", "identifier": "QX-STD-101"}}
RULE_QUOTE = (
    "The design pressure of the item shall not exceed 20 bar gauge in any case."
)


def _item(kind="limit", source=S.HELD, **kw):
    it = {"id": "C001", "book": "B01" if source == S.HELD else "", "clause": "4.1", "source": source, "topic": "t",
          "kind": kind, "rule_quote": RULE_QUOTE}  # fmt: skip
    it.update(kw)
    return it


def _shown(d: dict) -> str:
    return aim_review_store.shown_label(d["label"], d.get("code_compare"))


# ---- attack point 3: Pass / Fail without a real code comparison -----------------------------------------------------------


def test_p3a_a_rule_value_the_rule_quote_does_not_hold_never_earns_fail_by_code():
    """The model gives the limit as 10; the item's verified rule quote says 20. The paper's 12 bar complies with the rule."""
    j = {"label": "Not met", "quote": "Design pressure of the test item: 12 bar gauge at the inlet", "page": 1,
         "numbers": {"paper_value": "12", "paper_unit": "bar", "operator": "<=", "rule_value": "10", "rule_unit": "bar"}}  # fmt: skip
    d = S._decide(_item(), j, P, BOOKS, "")
    assert _shown(d) != aim_review_store.FAIL_BY_CODE, (d["label"], d["code_compare"])


def test_p3b_a_paper_unit_the_quote_does_not_hold_never_earns_fail_by_code():
    """The quote says 12 bar; the model gives the unit as MPa. 12 bar complies with <= 20 bar."""
    j = {"label": "Not met", "quote": "Design pressure of the test item: 12 bar gauge at the inlet", "page": 1,
         "numbers": {"paper_value": "12", "paper_unit": "MPa", "operator": "<=", "rule_value": "20", "rule_unit": "bar"}}  # fmt: skip
    d = S._decide(_item(), j, P, BOOKS, "")
    assert _shown(d) != aim_review_store.FAIL_BY_CODE, (d["label"], d["code_compare"])


def test_p3c_a_flipped_operator_never_earns_pass_by_code():
    """The rule says 'shall not exceed 20'; the model gives '>='. A paper value of 25 would be shown 'Pass, compared by code'."""
    pages = {1: "Design pressure of the test item: 25 bar gauge at the inlet\n"}
    j = {"label": "Met", "quote": "Design pressure of the test item: 25 bar gauge at the inlet", "page": 1,
         "numbers": {"paper_value": "25", "paper_unit": "bar", "operator": ">=", "rule_value": "20", "rule_unit": "bar"}}  # fmt: skip
    d = S._decide(_item(), j, Paper(paper_id="doc_p", pages=pages), BOOKS, "")
    assert _shown(d) != aim_review_store.PASS_BY_CODE, (d["label"], d["code_compare"])


@pytest.mark.parametrize(
    "quote",
    [
        "Corrosion allowance of the test item: BY CONTRACTOR",
        "Hydrotest pressure of the test item: *",
        "Flange rating of the test item: VTA",
        "Nozzle load of the test item: TBD",
        "Noise level of the test item: to be advised by the vendor later",
    ],
)
@pytest.mark.parametrize("label", ["Met", "Not met", "AI opinion"])
def test_p3d_a_deferred_value_is_always_a_question(quote, label):
    d = S._decide(
        _item(kind="presence"),
        {"label": label, "quote": quote, "page": 2},
        P,
        BOOKS,
        "",
    )
    assert d["label"] == "Question", (quote, label, d["label"])


# ---- attack point 1: a contract among the listed books, no consent --------------------------------------------------------


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def test_p1_a_contract_role_book_on_the_allowed_list_is_never_carried_without_consent(
    aim_db,
):
    with aim_db:
        aim_db.execute(
            "UPDATE document_classification SET document_role = 'CONTRACT_DOCUMENT' WHERE document_id = ?",
            (BOOK_B,),
        )
    model = E.FakeModel(kind="datasheet", subject_key="test_item")
    r = aim_review.run(aim_db, run_id="run_rev_c", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}),
                       store=MemoryStore(), max_usd=5.0, model=model)  # fmt: skip
    sent = [c for c in model.asked if BOOK_B in c["carries"]]
    assert BOOK_B not in r.books
    # the fake asks the gate inside the same declaration: a call that declared the contract must have been refused
    assert all(False for _ in sent) or r.status == "stopped", [c["step"] for c in sent]


def test_p1_a_saved_checklist_book_that_became_a_contract_is_not_carried(aim_db):
    store = MemoryStore()
    aim_review.run(aim_db, run_id="run_rev_1", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                   max_usd=5.0, model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    with aim_db:
        aim_db.execute(
            "UPDATE document_classification SET document_role = 'CONTRACT_DOCUMENT' WHERE document_id = ?",
            (BOOK_B,),
        )
    model = E.FakeModel(kind="datasheet", subject_key="test_item")
    r = aim_review.run(aim_db, run_id="run_rev_2", paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=store,
                       max_usd=5.0, model=model)  # fmt: skip
    assert BOOK_B not in r.books, (r.status, r.stop_reason, r.books)


# ---- attack point 6: a failed call's worst case is kept; no reservation stays open ----------------------------------------


def test_p6_a_billed_failure_keeps_its_worst_case_and_leaves_no_open_reservation(
    aim_db, monkeypatch
):
    import httpx

    from app import agent_claude, claude_spend, reader_transport

    def send(url, *, headers, body, timeout):
        raise httpx.ReadTimeout("invented timeout")

    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    monkeypatch.setattr(agent_claude, "_request",
                        lambda model, max_tokens, env: {"url": "https://fake.invalid/v1/messages", "headers": {}, "body": {}, "timeout": 5.0})  # fmt: skip
    r = aim_review.run(aim_db, run_id="run_rev_m", paper_id=PAPER, allowed_books=frozenset({BOOK_A}), store=MemoryStore(),
                       max_usd=5.0)  # fmt: skip
    assert r.status == "stopped"
    assert r.usd > 0, (
        "a read timeout may have been billed: its worst case must stay in the run's cost"
    )
    mine = [e for e in claude_spend.entries() if e.get("run") == "run_rev_m"]
    assert mine and not [e for e in mine if e.get("reserved")], mine
    assert abs(sum(float(e.get("cost_usd") or 0) for e in mine) - r.usd) < 1e-6


# ---- rule 5 on the page and in the file; the sheet's labels; the store's book ids -----------------------------------------


def test_r5_a_line_from_a_book_the_viewer_may_not_read_does_not_name_it(temp_db_world):
    from tests import test_aim_sheet_rule as T

    secret = T._line(
        7,
        "Not met",
        "AI opinion: not met",
        standard="QX-SECRET-909",
        book_document_id=T.HIDDEN_BOOK,
        clause="9.9",
    )
    T.make_run(
        "gen_run_r5",
        [*T.LINES, secret],
        created="2026-11-18T12:00:00Z",
        books=[T.BOOK, T.HIDDEN_BOOK],
    )
    c = T.client(
        T.PAPER, T.BOOK
    )  # may read the paper and one book; NOT the hidden book
    body = json.dumps(
        c.get(f"/api/reviews/papers/{T.PAPER}/general?run_id=gen_run_r5").json()
    )
    assert T.HIDDEN_BOOK not in body, "the hidden book's document id is served"
    assert "QX-SECRET-909" not in body, "the hidden book's identifier is served"
    wb = load_workbook(
        io.BytesIO(
            c.get(
                f"/api/reviews/papers/{T.PAPER}/general/sheet?run_id=gen_run_r5"
            ).content
        )
    )
    text = "\n".join(
        str(v)
        for ws in wb
        for row in ws.iter_rows(values_only=True)
        for v in row
        if v is not None
    )
    assert "QX-SECRET-909" not in text, "the hidden book's identifier is in the file"


def test_p3e_no_sheet_shows_a_bare_met_or_not_met(temp_db_world):
    from tests import test_aim_sheet_rule as T

    wb = load_workbook(
        io.BytesIO(
            T.client(T.PAPER, T.BOOK)
            .get(f"/api/reviews/papers/{T.PAPER}/general/sheet")
            .content
        )
    )
    bare = [
        (ws.title, v)
        for ws in wb
        for row in ws.iter_rows(values_only=True)
        for v in row
        if v in ("Met", "Not met")
    ]
    assert bare == [], bare


def test_p4_a_paper_whose_only_general_run_stopped_still_shows_it(temp_db):  # noqa: F811
    from tests import test_aim_sheet_rule as T

    T._doc(T.PAPER, "invented-paper.pdf")
    T._doc(T.BOOK, "invented-book.pdf")
    T.make_run("gen_run_stop", status="stopped")
    r = T.client(T.PAPER, T.BOOK).get(f"/api/reviews/papers/{T.PAPER}/general")
    assert r.status_code == 200, (r.status_code, r.text[:200])


def test_store_the_saved_checklist_row_names_its_books(temp_db):  # noqa: F811
    from app import db

    aim_review_store.ensure_schema()
    cl = {
        "built_from": aim_review_store.BUILT_FROM,
        "items": [],
        "books": [
            {
                "alias": "B01",
                "book": "doc_inv_book",
                "identifier": "QX-STD-1",
                "committee": "",
                "why": "w",
                "chosen_subjects": "all",
                "required": True,
            }
        ],
    }  # fmt: skip  (the shape `checklist.s3_checklist` writes)
    aim_review_store.DbChecklistStore(db.connect()).put(
        "datasheet__inv", cl, run_id="r", usd=0.0
    )
    assert aim_review_store.checklists(db.connect())[0]["books"] == ["doc_inv_book"]


from tests.test_crs_endpoint import temp_db  # noqa: E402,F401 - fixture


@pytest.fixture
def temp_db_world(temp_db):  # noqa: F811
    from tests import test_aim_sheet_rule as T

    T._doc(T.PAPER, "invented-paper.pdf")
    T._doc(T.BOOK, "invented-book.pdf")
    T._doc(T.HIDDEN_BOOK, "invented-secret.pdf")
    T.make_run(books=[T.BOOK, T.HIDDEN_BOOK])


# ---- the four guards round 1 found untested ---------------------------------------------------------------------------------


def test_a_billed_failure_keeps_its_worst_case_in_the_run_meter(aim_db, monkeypatch):
    """`engine.ClaudeModel.ask`: a failure the provider may have billed adds its worst case to the run's own meter, so the next
    call that would cross the cap is stopped BEFORE it is sent (money)."""
    import httpx

    from app import agent_claude, reader_transport

    sent = []

    def send(url, *, headers, body, timeout):
        sent.append(1)
        raise httpx.ReadTimeout("invented timeout")

    monkeypatch.setattr(reader_transport, "transport", lambda: send)
    monkeypatch.setattr(agent_claude, "_request",
                        lambda model, max_tokens, env: {"url": "https://fake.invalid/v1/messages", "headers": {}, "body": {}, "timeout": 5.0})  # fmt: skip
    meter = E.Meter(cap=5.0)
    m = E.ClaudeModel(meter)
    with pytest.raises(E.StepFailed):
        m.ask(step="aim_judge", model="claude-sonnet-5-5", system="", cached=None, prompt="invented prompt", carries=set(),
              max_tokens=1000)  # fmt: skip
    assert meter.spent > 0 and meter.calls[-1].usd == meter.spent
    meter.cap = meter.spent  # no room left: the next call is stopped before it is sent
    before = len(sent)
    with pytest.raises(E.StepFailed, match="run_cap"):
        m.ask(step="aim_judge", model="claude-sonnet-5-5", system="", cached=None, prompt="invented prompt", carries=set(),
              max_tokens=1000)  # fmt: skip
    assert len(sent) == before


# ---- the review's fix check: three small notes ----------------------------------------------------------------------------


def test_an_unreadable_ledger_after_the_run_keeps_the_lines_and_stores_the_cost_as_not_read(
    aim_db, monkeypatch
):
    from app import claude_spend

    def broken():
        raise OSError("invented: the ledger cannot be read")

    monkeypatch.setattr(claude_spend, "run_spent", broken)
    r = aim_review.run(aim_db, run_id="run_rev_l", paper_id=PAPER, allowed_books=frozenset({BOOK_A}), store=MemoryStore(),
                       max_usd=5.0, model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    assert r.status == "done" and r.lines, "a paid run's lines are never lost"
    assert r.usd is None  # null, rendered as nothing, never 0
    assert any(c.get("code") == E.COST_NOT_READ for c in r.calls)


@pytest.mark.parametrize(
    "quote",
    [
        "Wall thickness of the test item: 12 mm *",
        "Design temperature of the test item: 80 degC (*)",
    ],
)
def test_a_value_followed_by_a_lone_star_is_deferred_by_code(quote):
    d = S._decide(
        _item(kind="presence"),
        {"label": "Met", "quote": quote, "page": 1},
        Paper("doc_s", {1: quote + "\n"}),
        BOOKS,
        "",
    )
    assert d["label"] == "Question" and d["deferred"] is True


def test_a_star_glued_to_a_figure_or_a_word_is_not_taken_for_the_mark():
    from app import blank_markers

    assert not blank_markers.value_left_open("Wall thickness: 12*")
    assert not blank_markers.value_left_open("*Note 3 applies to the wall")
    assert not blank_markers.value_left_open("Wall thickness: 12 mm")


def test_a_line_whose_book_is_no_longer_held_shows_only_the_fixed_words(temp_db_world):
    from app import aim_review_view
    from tests import test_aim_sheet_rule as T

    gone = T._line(
        8,
        "Question",
        "Question",
        standard="QX-GONE-707",
        book_document_id="doc_inv_gone",
        clause="7.7",
    )
    T.make_run(
        "gen_run_gone", [*T.LINES, gone], created="2026-11-18T13:00:00Z", books=[T.BOOK]
    )
    body = (
        T.client(T.PAPER, T.BOOK)
        .get(f"/api/reviews/papers/{T.PAPER}/general?run_id=gen_run_gone")
        .json()
    )
    text = json.dumps(body)
    assert "doc_inv_gone" not in text and "QX-GONE-707" not in text
    assert body["points"][-1]["standard"] == aim_review_view.HIDDEN_BOOK_WORDS
