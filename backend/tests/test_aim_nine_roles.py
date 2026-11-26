"""The nine-role record on the general review (owner order 15 Nov 2026; lead-4 26 Nov: built on the general method; `aim_review.roles`).
A whole run with the fake model; invented paper and books; no paid call, no socket."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import aim_review
from app.aim_review import engine as E
from app.aim_review import roles, updates
from app.aim_review.paper import _marked
from app.config import settings
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

RUN = "run_nine_t1"


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _run(conn, model=None):
    model = model or E.FakeModel(kind="datasheet", subject_key="test_item")
    result = aim_review.run(conn, run_id=RUN, paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=MemoryStore(),
                            max_usd=5.0, model=model)  # fmt: skip
    body = {"calls": result.calls, "lines": result.lines}
    updates.nine_end(RUN, body)
    return result, model


def _request(kw) -> str:
    return "\x00".join(str(kw.get(k) or "") for k in ("system", "cached", "prompt"))


def _tables(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _rows(conn, table):
    return [
        dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE run_id = ?", (RUN,))
    ]


def test_off_the_run_is_main_no_table_is_made_and_the_model_is_the_runs_own(aim_db):
    assert settings.agent_review_nine_roles_enabled is False  # off by default
    marker = object()
    assert updates.nine_wrap(marker, RUN, PAPER) is marker
    _run(aim_db)
    assert not {roles.ROLES, roles.CALLS, roles.READS} & _tables(aim_db)


def test_on_nine_rows_every_call_is_recorded_answered_and_each_role_ends_with_its_state(
    aim_db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    _r, model = _run(aim_db)
    rows = {r["role_no"]: r for r in _rows(aim_db, roles.ROLES)}
    assert sorted(rows) == list(range(1, 10))
    calls = _rows(aim_db, roles.CALLS)
    assert len(calls) == len(model.asked) and {c["state"] for c in calls} == {
        "answered"
    }
    # one row per call (the judge's calls run side by side, so not in a fixed order)
    assert sorted(c["step"] for c in calls) == sorted(a["step"] for a in model.asked)
    # the reader (naming the paper) and the judge ran; the two code roles ran
    assert rows[1]["state"] == "ran" and rows[4]["state"] == "ran"
    assert rows[7]["state"] == rows[8]["state"] == "ran" and rows[7]["engine"] == "code"
    for r in (
        rows.values()
    ):  # a role that made no call says so; no role is left "not reached"
        assert r["why"] != roles.NOT_REACHED
        if r["state"] != "ran":
            assert r["why"] and r["calls"] == 0
    assert json.loads(rows[1]["produced_json"])["paper_pages_sent"] > 0


def test_the_read_rows_are_the_documents_each_call_declared_and_the_paper_pages_whose_text_it_held(
    aim_db, monkeypatch
):
    """The record is written from the request itself: each call's read rows name exactly its declared documents (the gate's
    `carries`), and the paper's pages are those whose marked text is in the request, with the checksum of that text."""
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    sent = []

    class Spy(E.FakeModel):
        def ask(self, **kw):
            sent.append(kw)
            return super().ask(**kw)

    _run(aim_db, Spy(kind="datasheet", subject_key="test_item"))
    calls = _rows(aim_db, roles.CALLS)
    reads = _rows(aim_db, roles.READS)
    from app.aim_review.paper import load_paper

    paper = load_paper(aim_db, PAPER)
    assert len(calls) == len(sent)
    by_sha = {roles._sha(_request(kw)): kw for kw in sent}
    for call in calls:  # each row matched to its own request by the request's checksum
        kw = by_sha[call["request_sha256"]]
        mine = [r for r in reads if r["call_id"] == call["call_id"]]
        assert {r["document_id"] for r in mine} == {str(c) for c in kw["carries"]}
        for r in (x for x in mine if x["document_kind"] == "paper"):
            pages = [
                n
                for n, t in sorted(paper.pages.items())
                if t and _marked(n, t) in _request(kw)
            ]
            assert (
                json.loads(r["pages_json"]) == pages and pages
            )  # a call that declares the paper holds its pages
            assert r["text_sha256"] == roles._sha(
                "".join(paper.pages[n] for n in pages)
            )


def test_a_request_holding_the_paper_that_does_not_declare_it_is_refused_before_it_leaves(
    aim_db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    from app.aim_review import steps as S
    from app.aim_review.engine import StepFailed
    from app.aim_review.paper import load_paper

    inner = E.FakeModel()
    rec = updates.nine_wrap(inner, RUN, PAPER)
    with pytest.raises(StepFailed, match="undeclared_paper"):
        rec.ask(step="aim_select", model="m", system="", cached=S.paper_block(load_paper(aim_db, PAPER)), prompt="x",
                carries={BOOK_A}, max_tokens=10)  # fmt: skip
    assert inner.asked == []  # never handed on
    assert [c["state"] for c in _rows(aim_db, roles.CALLS)] == ["refused"]


def test_a_failed_call_makes_its_role_ran_partly_with_the_code(aim_db, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    _run(
        aim_db,
        E.FakeModel(
            kind="datasheet",
            subject_key="test_item",
            fail={"aim_edit": "stop_max_tokens"},
        ),
    )
    row = next(r for r in _rows(aim_db, roles.ROLES) if r["role_no"] == 9)
    assert row["state"] == "ran_partly" and "calls not answered" in row["why"]
    assert any(
        c["state"] == "failed" for c in _rows(aim_db, roles.CALLS) if c["role_no"] == 9
    )


def test_every_step_name_of_the_general_review_has_its_role():
    """A new step would be counted as the reviewer's by default: name it in ROLE_OF_STEP (this test lists the package's steps)."""
    pkg = Path(roles.__file__).parent
    found = set()
    for f in pkg.glob("*.py"):
        found |= set(re.findall(r'step="(aim_[a-z_]+)"', f.read_text()))
        found |= set(re.findall(r'^STEP\s*=\s*"(aim_[a-z_]+)"', f.read_text(), re.M))
    found.discard(
        "aim_judge"
    )  # the judge names its step through a variable; it is mapped (role 4)
    assert found and found <= set(roles.ROLE_OF_STEP), sorted(
        found - set(roles.ROLE_OF_STEP)
    )


def test_a_rule_books_reads_are_the_pages_of_its_rules_pages_and_clause_windows_the_request_holds(
    aim_db, monkeypatch
):
    """Roles 3 and 4 (lead-4, 26 Nov 2026): a rule book's read rows name the pages of its own stored text found in the request (a
    rule of the material, a page of a book read by its pages, the judge's clause window), with the checksum of that text; the
    librarian's catalogue (names and subjects only) holds none; no piece of rule-book text is left unmatched."""
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    sent = []

    class Spy(E.FakeModel):
        def ask(self, **kw):
            sent.append(kw)
            return super().ask(**kw)

    _run(aim_db, Spy(kind="datasheet", subject_key="test_item"))
    calls = {c["call_id"]: c for c in _rows(aim_db, roles.CALLS)}
    reads = [r for r in _rows(aim_db, roles.READS) if r["document_kind"] == "rule_book"]
    assert reads and all(c["book_text_unmatched"] == 0 for c in calls.values())
    books = roles.Books()
    by_sha = {roles._sha(_request(kw)): kw for kw in sent}
    with_pages = 0
    for r in reads:
        kw, step = (
            by_sha[calls[r["call_id"]]["request_sha256"]],
            calls[r["call_id"]]["step"],
        )
        mine = roles._book_pieces(r["document_id"], roles.probes(_request(kw)), books)
        assert json.loads(r["pages_json"]) == sorted({p for p, _x in mine})
        assert r["chars"] == sum(len(x) for _p, x in mine)
        if step == "aim_select":
            assert (
                r["chars"] == 0
            )  # the catalogue names books, it sends none of their text
        with_pages += bool(mine)
    assert with_pages  # the checklist material and the judge's windows hold book pages
    rows = {r["role_no"]: r for r in _rows(aim_db, roles.ROLES)}
    assert json.loads(rows[4]["produced_json"]).get("rule_book_pages_sent", 0) > 0


def test_a_piece_of_rule_book_text_that_no_declared_book_holds_is_counted():
    """A rule text of a book the call does not declare is never silently taken for a declared book's."""

    class NoBooks(roles.Books):
        def rules(self, doc):
            return {"Invented rule text of book A.": 3}

        def pages(self, doc):
            return {}

    request = json.dumps(
        {
            "rule": "R0001",
            "book": "B01",
            "clause": "1",
            "page": 3,
            "text": "Invented rule text of book Z.",
        }
    )
    rows, unmatched = roles.reads_of(
        request, {"doc_book_a"}, None, "aim_checklist", NoBooks()
    )
    assert unmatched == 1 and rows[0]["pages"] == [] and rows[0]["chars"] == 0
    request = json.dumps(
        {
            "rule": "R0001",
            "book": "B01",
            "clause": "1",
            "page": 3,
            "text": "Invented rule text of book A.",
        }
    )
    rows, unmatched = roles.reads_of(
        request, {"doc_book_a"}, None, "aim_checklist", NoBooks()
    )
    assert (
        unmatched == 0
        and rows[0]["pages"] == [3]
        and rows[0]["text_sha256"] == roles._sha("Invented rule text of book A.")
    )
