"""The general review's page JSON, its Excel file and the hard completeness rule (order 14, piece C). Invented data only.

Every test is made to FAIL without the code it guards (the hand-reverts are listed in BUILD/HANDBACK-C.md)."""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import (
    access,
    aim_review,
    aim_review_completeness,
    aim_review_gate,
    aim_review_sheet,
    aim_review_store,
    aim_review_view,
    db,
)
from app.config import settings
from app.crs_completeness import CUT_MARK, Incomplete, team_statement
from app.main import app
from tests.test_crs_endpoint import (  # noqa: F401 - fixture (a fresh database per test)
    NOW,
    temp_db,
)

PAPER = "doc_inv_paper"
BOOK = "doc_inv_book"
HIDDEN_BOOK = "doc_inv_secret"
RUN = "gen_run_1"


def _doc(doc_id: str, filename: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',5,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, NOW),
        )


def _line(i: int, label: str, shown: str, **over) -> dict:
    base = {
        "item_id": f"C{i:02d}", "label": label, "shown_label": shown, "field": f"Invented field {i}", "page": 2 + i,
        "quote": f"invented quote {i}", "quote_unverified": 0, "comment": f"invented comment {i}", "standard": "STD-X",
        "book_document_id": BOOK, "clause": f"4.{i}", "source": "held standard", "topic": "invented topic",
        "code_note": None, "numbers_json": None, "code_compare_json": None,
    }  # fmt: skip
    return {**base, **over}


LINES = [
    _line(1, "Not met", "Fail, compared by code"),
    _line(2, "Met", "AI opinion: met"),
    _line(3, "Question", "Question", page=None),
    _line(4, "Does not apply", "AI opinion: does not apply"),
    _line(5, "AI opinion", "AI opinion", quote_unverified=1),
    _line(6, "Met", "Pass, compared by code"),
]


def make_run(
    run_id: str = RUN,
    lines=None,
    *,
    status: str = "done",
    paper: str = PAPER,
    created: str = "2026-11-18T10:00:00Z",
    books=None,
    unlisted=None,
    usd: float | None = 0.51,
) -> None:
    """A finished general run as `aim_review_store.finish_run` leaves it (inserted directly: finish_run is piece D's)."""
    lines = LINES if lines is None else lines
    aim_review_store.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, paper, "completed", created, created, created),
        )
        conn.execute(
            f"INSERT INTO {aim_review_store.RUNS} (run_id, paper_document_id, status, method_version, identity_json, checklist_key,"
            " checklist_sha256, checklist_reused, books_json, not_held_json, unlisted_json, usd, seconds, calls_json, stop_reason,"
            " created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, paper, status, "aim-1", json.dumps({"kind": "datasheet", "equipment_type": None, "subject": "invented"}),
                "invented-key", "sha-x", 1, json.dumps(books if books is not None else [BOOK]),
                json.dumps([{"name": "Invented Public Standard", "why": "cited, not held"}]), json.dumps(unlisted or []), usd, 12.5,
                json.dumps([{"step": "aim_judge", "model": "m", "usd": 0.51, "input_tokens": 1, "output_tokens": 2, "seconds": 3.0, "ok": True, "code": None}]),
                None, created, created,
            ),
        )  # fmt: skip
        for no, ln in enumerate(lines, 1):
            cols = ["run_id", "line_no", *ln]
            conn.execute(
                f"INSERT INTO {aim_review_store.LINES} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                (run_id, no, *ln.values()),
            )


@pytest.fixture
def world(temp_db):  # noqa: F811
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    _doc(HIDDEN_BOOK, "invented-secret.pdf")
    make_run(books=[BOOK, HIDDEN_BOOK])
    return


def client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app)


def _sheet(response):
    assert response.status_code == 200, response.text
    return load_workbook(io.BytesIO(response.content))


# ---------------------------------------------------------------------------------------------------- the page JSON


def test_the_page_json_has_the_contract_shape(world):
    got = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general")
    assert got.status_code == 200
    body = got.json()
    assert body["mark"] == aim_review_gate.AI_MARK == "AI, to be checked"
    assert (
        body["status"] == "completed"
        and body["method"] == "aim-1"
        and body["run_id"] == RUN
    )
    assert body["counts"] == {
        "points": 6, "comments": 3, "by_label": {"Met": 2, "Not met": 1, "Question": 1, "Does not apply": 1, "AI opinion": 1},
        "by_shown_label": body["counts"]["by_shown_label"], "boundary": "this paper, this review",
    }  # fmt: skip
    assert [c["n"] for c in body["comments"]] == [1, 3, 5]
    assert set(body["comments"][0]) >= {
        "n",
        "field",
        "page",
        "label",
        "shown_label",
        "comment",
        "quote",
        "item_id",
        "standard",
        "clause",
        "source",
    }
    assert len(body["points"]) == 6 and set(body["points"][0]) >= {
        "topic",
        "code_note",
        "quote_unverified",
    }
    assert (
        body["checklist"]["key"] == "invented-key"
        and body["checklist"]["reused"] is True
    )
    assert body["cost"] == {"usd": 0.51}
    assert (
        body["completeness"]["ok"] is True and body["completeness"]["sentence"] is None
    )
    assert (
        body["completeness"]["page"],
        body["completeness"]["database"],
        body["completeness"]["file_rows"],
    ) == (6, 6, 6)


def test_a_comment_is_a_sendable_label_in_line_order(world):
    body = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert [c["label"] for c in body["comments"]] == [
        "Not met",
        "Question",
        "AI opinion",
    ]
    assert all(c["label"] in aim_review.SENDABLE for c in body["comments"])


def test_what_a_person_sees_is_the_stored_shown_label(world):
    got = {
        p["item_id"]: p["shown_label"]
        for p in client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general")
        .json()["points"]
    }
    assert (
        got["C01"] == "Fail, compared by code"
        and got["C06"] == "Pass, compared by code"
    )
    assert got["C02"] == "AI opinion: met" and got["C03"] == "Question"


def test_a_null_page_renders_as_nothing_not_zero(world):
    body = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert body["comments"][1]["page"] is None
    ws = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))[
        aim_review_sheet.COMMENTS
    ]
    rows = [
        r
        for r in ws.iter_rows(min_row=aim_review_sheet.HEADER_ROW + 1, values_only=True)
        if r[0] is not None
    ]
    assert rows[1][2] is None  # the page cell of comment 2 (line 3) is empty, never 0


def test_a_book_the_caller_may_not_read_is_a_count_never_named(world):
    body = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert [b["id"] for b in body["books"]] == [BOOK] and body[
        "books_not_readable"
    ] == 1
    assert "invented-secret" not in json.dumps(body) and HIDDEN_BOOK not in json.dumps(
        body
    )
    wb = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))
    text = "\n".join(
        str(c)
        for ws in wb
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c is not None
    )
    assert (
        "invented-secret" not in text
        and "1 more rule book(s) the reader of this file may not open" in text
    )


def test_the_unlisted_books_sentence_is_the_existing_one(world):
    make_run("gen_run_2", created="2026-11-18T11:00:00Z", unlisted=["b1", "b2"])
    body = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert body["unlisted_books"] == {
        "count": 2,
        "sentence": "2 more rule book(s) apply to this paper. They were not sent because they were not on the list you saw. Review again to include them.",
    }
    assert client(PAPER, BOOK).get(
        f"/api/reviews/papers/{PAPER}/general?run_id={RUN}"
    ).json()["unlisted_books"] == {"count": 0, "sentence": None}


def test_a_run_of_another_paper_or_none_at_all_is_404(world):
    _doc("doc_inv_other", "invented-other.pdf")
    make_run("gen_other", paper="doc_inv_other")
    c = client(PAPER, BOOK, "doc_inv_other")
    assert (
        c.get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_other").status_code
        == 404
    )
    assert (
        c.get("/api/reviews/papers/doc_inv_book/general").status_code == 404
    )  # a paper with no general review


def test_outside_the_scope_is_404_like_a_document_that_does_not_exist(world):
    c = client(BOOK)  # may not read the paper
    for path in ("general", "general/sheet"):
        a = c.get(f"/api/reviews/papers/{PAPER}/{path}")
        b = c.get(f"/api/reviews/papers/doc_does_not_exist/{path}")
        assert a.status_code == b.status_code == 404
        assert a.json()["detail"]["message"] == b.json()["detail"]["message"]


def test_the_latest_general_run_wins_unless_an_earlier_review_is_newer(world):
    from app import aim_review_view as v

    conn = db.connect()
    run = aim_review_store.latest_run(conn, PAPER)
    assert v.is_latest(conn, PAPER, run) is True  # no earlier-engine review at all
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (
                "rc_new",
                PAPER,
                "completed",
                "2026-11-19T10:00:00Z",
                "2026-11-19T10:00:00Z",
                "2026-11-19T10:00:00Z",
            ),
        )
    assert (
        v.is_latest(conn, PAPER, run) is False
    )  # the older engine reviewed it again later: the old sections are drawn
    assert (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general")
        .json()["is_latest"]
        is False
    )


def test_a_run_that_has_not_ended_has_no_counts_and_no_file(world):
    make_run("gen_running", [], status="running", created="2026-11-18T12:00:00Z")
    c = client(PAPER, BOOK)
    assert (
        c.get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_running").status_code
        == 409
    )
    assert (
        c.get(
            f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_running"
        ).status_code
        == 409
    )


def test_a_stopped_run_keeps_its_lines_and_says_so(world):
    make_run("gen_stop", status="stopped", created="2026-11-18T12:00:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_stop")
        .json()
    )
    assert (
        body["status"] == "stopped"
        and body["counts"]["points"] == 6
        and body["completeness"]["ok"] is True
    )


# ---------------------------------------------------------------------------------------------------- the file


def test_every_sheet_carries_the_mark_and_the_first_sheet_states_the_counts(world):
    wb = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))
    assert wb.sheetnames == ["Summary", "Comments", "All points", "How it was reviewed"]
    for ws in wb:
        assert ws["A1"].value == "AI, to be checked", ws.title
    first = "\n".join(
        str(c) for r in wb["Summary"].iter_rows(values_only=True) for c in r if c
    )
    assert (
        team_statement(6, 3) in first and "6 points reviewed, 6 in this file" in first
    )
    for name in ("Comments", "All points"):
        rows = [
            r
            for r in wb[name].iter_rows(
                min_row=aim_review_sheet.HEADER_ROW + 1, values_only=True
            )
            if r[0] is not None
        ]
        assert rows and all(r[-1] == "AI, to be checked" for r in rows)


def test_the_rows_on_the_sheets_are_the_counts(world):
    wb = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))
    assert len(aim_review_completeness._table(wb, "All points")) == 6
    assert len(aim_review_completeness._table(wb, "Comments")) == 3


def test_a_cell_is_cut_only_with_the_mark_and_is_whole_on_all_points(world):
    long = "invented words " * 200  # 3000 characters
    lines = [
        _line(1, "Not met", "AI opinion: not met", comment=long, quote=long),
        _line(2, "Met", "AI opinion: met"),
    ]
    make_run("gen_long", lines, created="2026-11-18T12:00:00Z")
    r = client(PAPER, BOOK).get(
        f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_long"
    )
    wb = _sheet(r)
    cell = wb["Comments"].cell(row=aim_review_sheet.HEADER_ROW + 1, column=5).value
    whole = wb["All points"].cell(row=aim_review_sheet.HEADER_ROW + 1, column=8).value
    assert (
        cell.endswith(CUT_MARK)
        and len(cell) == aim_review_sheet.COMMENT_CELL_LIMIT
        and whole == long
    )
    assert (
        "full text is on the sheet All points, No. 1"
        in wb["Comments"].cell(row=aim_review_sheet.HEADER_ROW + 1, column=11).value
    )
    # a short comment is not marked
    assert not LINES[0]["comment"].endswith(CUT_MARK)


def test_a_cut_without_the_mark_is_refused(world, monkeypatch):
    long = "invented words " * 200
    make_run(
        "gen_long",
        [_line(1, "Not met", "AI opinion: not met", comment=long)],
        created="2026-11-18T12:00:00Z",
    )
    monkeypatch.setattr(
        aim_review_sheet, "CUT_MARK", ""
    )  # a builder that cuts silently
    r = client(PAPER, BOOK).get(
        f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_long"
    )
    assert r.status_code == 409 and "cut" in r.json()["detail"]["message"]


def test_all_points_beyond_excels_own_limit_is_refused_not_cut_silently(world):
    huge = "x" * (aim_review_sheet.EXCEL_CELL_LIMIT + 10)
    make_run(
        "gen_huge",
        [_line(1, "Not met", "AI opinion: not met", comment=huge)],
        created="2026-11-18T12:00:00Z",
    )
    r = client(PAPER, BOOK).get(
        f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_huge"
    )
    assert (
        r.status_code == 409
        and "cut on the sheet All points" in r.json()["detail"]["message"]
    )


def test_a_text_that_looks_like_a_formula_is_stored_as_text(world):
    make_run(
        "gen_f",
        [
            _line(
                1,
                "Not met",
                "AI opinion: not met",
                comment='=HYPERLINK("http://invented.example","x")',
            )
        ],
        created="2026-11-18T12:00:00Z",
    )
    wb = _sheet(
        client(PAPER, BOOK).get(
            f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_f"
        )
    )
    cell = wb["Comments"].cell(row=aim_review_sheet.HEADER_ROW + 1, column=5)
    assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")


# ---------------------------------------------------------------------------------------------------- the hard rule


def test_counts_that_differ_by_one_line_refuse_the_download_with_the_sentence(
    world, monkeypatch
):
    real = aim_review_store.lines
    monkeypatch.setattr(
        aim_review_view.aim_review_store,
        "lines",
        lambda conn, run_id: real(conn, run_id)[:-1],
    )  # the page loses a line
    r = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet")
    assert r.status_code == 409
    msg = r.json()["detail"]["message"]
    assert (
        "not complete and was not given out" in msg
        and "the page has 5 points" in msg
        and "the database holds 6 lines" in msg
    )
    assert "Missing: point 6 (C06)" in msg
    page = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general")
        .json()["completeness"]
    )
    assert (
        page["ok"] is False
        and page["sentence"] == msg
        and (page["page"], page["database"], page["file_rows"]) == (5, 6, 5)
    )


def test_a_file_that_loses_a_row_after_the_page_counted_is_refused(world, monkeypatch):
    real = aim_review_sheet.point_rows
    monkeypatch.setattr(
        aim_review_sheet, "point_rows", lambda model: real(model)[:-1]
    )  # the builder drops the last row
    with pytest.raises(Incomplete) as e:
        aim_review_completeness.file_or_refuse(RUN, access.unrestricted_scope())
    assert (
        e.value.report["page"] == 6
        and e.value.report["database"] == 6
        and e.value.report["file_rows"] == 5
    )
    assert "the file has 5 rows" in str(e.value) and "point 6" in str(e.value)


def test_a_file_that_loses_a_comment_row_is_refused(world, monkeypatch):
    real = aim_review_sheet.comment_rows
    monkeypatch.setattr(
        aim_review_sheet, "comment_rows", lambda model: real(model)[:-1]
    )
    with pytest.raises(Incomplete) as e:
        aim_review_completeness.file_or_refuse(RUN, access.unrestricted_scope())
    assert (e.value.report["comments"], e.value.report["comment_rows"]) == (3, 2)


def test_a_sheet_without_the_mark_is_refused(world, monkeypatch):
    monkeypatch.setattr(aim_review_sheet, "_head", lambda ws, title: None)
    with pytest.raises(Incomplete) as e:
        aim_review_completeness.file_or_refuse(RUN, access.unrestricted_scope())
    assert "does not carry the mark" in str(e.value)


def test_the_check_is_stored_with_the_run_after_it_ends(world):
    rep = aim_review_completeness.record_after_run(RUN)
    assert rep["ok"] is True
    stored = json.loads(aim_review_store.run(db.connect(), RUN)["completeness_json"])
    assert (stored["page"], stored["database"], stored["file_rows"]) == (6, 6, 6)
    assert (
        aim_review_completeness.record_after_run("no_such_run") is None
    )  # never fails the run


def test_the_count_check_script_agrees_with_the_app(world, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "crs_count_check",
        Path(__file__).resolve().parents[2] / "scripts" / "crs_count_check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._general(RUN, access.unrestricted_scope(), aim_review_completeness) == 0
    out = capsys.readouterr().out
    assert (
        "points on the page      6" in out
        and "lines in the database   6" in out
        and "all counts agree" in out
    )


def test_the_count_check_script_exits_1_on_a_difference(world, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "crs_count_check",
        Path(__file__).resolve().parents[2] / "scripts" / "crs_count_check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = aim_review_sheet.point_rows
    monkeypatch.setattr(aim_review_sheet, "point_rows", lambda model: real(model)[:-1])
    assert mod._general(RUN, access.unrestricted_scope(), aim_review_completeness) == 1
    assert "DIFFERENT" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------------- no contractor copy


@pytest.mark.parametrize("copy", ["contractor"])
def test_the_contractor_copy_is_refused_with_the_one_sentence(world, copy):
    r = client(PAPER, BOOK).get(
        f"/api/reviews/papers/{PAPER}/general/sheet?copy={copy}"
    )
    assert r.status_code == 409
    assert r.json()["detail"]["message"] == aim_review_gate.NO_CONTRACTOR_COPY_WORDS
    assert "AI, to be checked" in r.json()["detail"]["message"]


def test_the_module_offers_no_contractor_file_at_all():
    assert not [n for n in dir(aim_review_sheet) if "contractor" in n.lower()]
    assert not [
        n
        for n in dir(aim_review_completeness)
        if "contractor" in n.lower() or "sign" in n.lower()
    ]


def test_the_download_is_a_real_team_xlsx_named_after_the_paper(world):
    r = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet")
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="general-review-invented-paper.xlsx"'
    )


def test_the_routes_serve_stored_runs_even_when_the_old_engine_is_on(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "review_old_engine_enabled", True)
    assert (
        client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").status_code
        == 200
    )
