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


def test_a_question_that_was_only_not_judged_is_a_point_not_a_comment(
    world, monkeypatch
):
    """ASK A -> C (RISKS 2): `aim_review.sendable` decides; a not-judged Question stays on "All points" and is counted there."""
    db.connect().execute("DELETE FROM aim_lines")
    db.connect().execute("DELETE FROM aim_runs")
    db.connect().execute("DELETE FROM review_runs")
    db.connect().commit()
    make_run(
        lines=[
            _line(1, "Question", "Question", code_note=aim_review.NOT_JUDGED),
            _line(2, "Question", "Question"),
        ]
    )
    body = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert [c["item_id"] for c in body["comments"]] == ["C02"]
    assert [p["item_id"] for p in body["points"]] == ["C01", "C02"]


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
    # the page cell of comment 2 (line 3) is empty, never 0 (the column found by its header: "Lines" now stands before it)
    assert rows[1][aim_review_sheet.COMMENT_HEADERS.index("Page")] is None


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
    cell = (
        wb["Comments"]
        .cell(
            row=aim_review_sheet.HEADER_ROW + 1,
            column=aim_review_sheet.COMMENT_HEADERS.index("Comment") + 1,
        )
        .value
    )
    whole = wb["All points"].cell(row=aim_review_sheet.HEADER_ROW + 1, column=8).value
    assert (
        cell.endswith(CUT_MARK)
        and len(cell) == aim_review_sheet.COMMENT_CELL_LIMIT
        and whole == long
    )
    assert (
        "full text of each place is on the sheet All points, No. 1"  # the note of a comment (one point, its places)
        in wb["Comments"]
        .cell(
            row=aim_review_sheet.HEADER_ROW + 1,
            column=aim_review_sheet.COMMENT_HEADERS.index("Note") + 1,
        )
        .value
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
    cell = wb["Comments"].cell(
        row=aim_review_sheet.HEADER_ROW + 1,
        column=aim_review_sheet.COMMENT_HEADERS.index("Comment") + 1,
    )
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


def test_the_found_during_review_sentence_has_one_home_in_the_backend():
    """The rule check's notes and the general review say the same sentence from `review_shown` only (join of C, ASK C)."""
    from pathlib import Path

    from app import aim_review_view, review_shown

    assert aim_review_view.UNLISTED_SENTENCE is review_shown.FOUND_DURING_REVIEW_WORDS
    app = Path(review_shown.__file__).parent
    homes = [
        p.name
        for p in app.rglob("*.py")
        if "were not sent because they were not on" in p.read_text(encoding="utf-8")
    ]
    assert homes == ["review_shown.py"]


def test_one_item_with_several_failing_places_keeps_every_line_and_the_counts_hold(
    world,
):
    """A's one-line-per-failing-place (order 14): several lines of ONE item, through the real store (`finish_run`), the page, the
    file and the completeness check: every line is kept by its line number and page = database = file."""
    run_id = "gen_run_multi"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                PAPER,
                "completed",
                "2026-11-18T14:00:00Z",
                "2026-11-18T14:00:00Z",
                "2026-11-18T14:00:00Z",
            ),
        )
        aim_review_store.start_run(conn, run_id, PAPER, "2026-11-18T14:00:00Z")
        conn.commit()
    same = {
        "item_id": "C07",
        "label": "Not met",
        "field": "Invented field",
        "quote": "",
        "comment": "invented",
        "source": "held standard",
    }
    lines = [{**same, "page": p, "finding_no": n} for n, p in ((1, 2), (2, 4), (3, 5))]
    lines.append(
        {
            "item_id": "C08",
            "label": "Met",
            "field": "Other field",
            "page": 1,
            "quote": "",
            "comment": "",
        }
    )
    aim_review_store.finish_run(
        db.connect(),
        run_id,
        {"status": "done", "lines": lines, "books": [BOOK]},
        "2026-11-18T14:01:00Z",
    )
    c = client(PAPER, BOOK)
    body = c.get(f"/api/reviews/papers/{PAPER}/general?run_id={run_id}").json()
    assert [p["item_id"] for p in body["points"]] == ["C07", "C07", "C07", "C08"]
    assert [p["page"] for p in body["points"]][:3] == [2, 4, 5]
    # one point at three places is ONE comment listing them (lead, 18 Nov 2026: merge repeats); every place stays a point
    assert len(body["comments"]) == 1 and body["comments"][0]["lines"] == [1, 2, 3]
    assert body["comments"][0]["pages"] == [2, 4, 5]
    assert body["completeness"]["ok"] is True
    assert (
        body["completeness"]["page"]
        == body["completeness"]["database"]
        == body["completeness"]["file_rows"]
        == 4
    )
    wb = _sheet(c.get(f"/api/reviews/papers/{PAPER}/general/sheet?run_id={run_id}"))
    assert len(aim_review_completeness._table(wb, "All points")) == 4
    assert len(aim_review_completeness._table(wb, "Comments")) == 1


def test_the_items_every_review_checks_are_counted_apart_from_the_checklist(world):
    """Order 14: the always-checked items (`aim_review.always`, not in the saved checklist) are counted apart on the page and in
    the file; with no saved checklist the items are the distinct items judged, never the line count (one item may give several lines)."""
    from app.aim_review import always

    lines = [
        _line(1, "Not met", "AI opinion: not met"),
        _line(2, "Question", "Question", item_id="C01"),
        _line(3, "Question", "Question", item_id="G1", topic=always.TOPIC),
        _line(4, "Met", "AI opinion: met", item_id="G2", topic=always.TOPIC),
    ]
    make_run("gen_run_always", lines, created="2026-11-18T15:00:00Z")
    c = client(PAPER, BOOK)
    body = c.get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_run_always").json()
    assert body["checklist"]["always_items"] == 2
    assert (
        body["checklist"]["items"] == 1
    )  # C01 twice is ONE item; no saved checklist row in this test
    wb = _sheet(
        c.get(f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_run_always")
    )
    text = [
        v
        for row in wb["How it was reviewed"].iter_rows(values_only=True)
        for v in row
        if v is not None
    ]
    assert "Items every review checks besides the checklist" in text


# ---- one comment per point: every place it applies to listed (lead, 18 Nov 2026: merge repeats; invented values) --------------


def _cmp(v):
    return json.dumps(
        {
            "result": "fail",
            "why": f"{v} bar <= 20 bar: false",
            "read_from": "verified quotes",
        }
    )


def test_four_places_of_one_point_are_one_comment_listing_four_pages_and_the_counts_hold(
    world,
):
    places = [
        _line(1, "Not met", "Fail, compared by code", item_id="C09", page=p, quote=f"Design pressure {v} bar gauge",
              comment=f"Design pressure {v} bar is above the 20 bar limit.", code_note=f"code compared: {v} bar <= 20 bar: false",
              code_compare_json=_cmp(v))
        for p, v in ((2, 25), (3, 26), (5, 27), (7, 28))
    ]  # fmt: skip
    other = _line(2, "Question", "Question", item_id="C10", page=4)
    make_run("gen_group", [*places, other], created="2026-11-18T16:00:00Z")
    c = client(PAPER, BOOK)
    body = c.get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_group").json()
    assert body["counts"]["points"] == 5 and body["counts"]["comments"] == 2
    one = body["comments"][0]
    assert one["lines"] == [1, 2, 3, 4] and one["pages"] == [2, 3, 5, 7]
    # the places' own words differ (each its own value), so each place keeps its own words (lossless; owner 18 Nov 16:35)
    # (the first place's quote and numbers are the comment's own Quote and Compared cells; the others are listed in its words)
    cells = " ".join((one["comment"], one["quote"], one["compared"]))
    for v in (25, 26, 27, 28):  # each place's own words, quote and numbers
        assert f"Design pressure {v} bar is above the 20 bar limit." in one["comment"]
        assert (
            f"Design pressure {v} bar gauge" in cells
            and f"{v} bar <= 20 bar: false" in cells
        )
    rep = body["completeness"]
    assert rep["ok"] is True and rep["page"] == rep["database"] == rep["file_rows"] == 5
    assert rep["comments"] == rep["comment_rows"] == 2
    wb = _sheet(c.get(f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_group"))
    rows = aim_review_completeness._table(wb, "Comments")
    lines_col = aim_review_sheet.COMMENT_HEADERS.index("Lines")
    assert [r[lines_col] for r in rows] == ["1, 2, 3, 4", "5"]
    assert rows[0][aim_review_sheet.COMMENT_HEADERS.index("Page")] == "2, 3, 5, 7"


def test_a_code_compared_fail_is_never_folded_into_a_question(world):
    fail = _line(1, "Not met", "Fail, compared by code", item_id="C11", page=2, code_note="code compared: 25 bar <= 20 bar: false",
                 code_compare_json=_cmp(25))  # fmt: skip
    question = _line(
        2,
        "Question",
        "Question",
        item_id="C11",
        page=3,
        code_note="the value is left open by the vendor",
    )
    other_kind = _line(3, "Not met", "Fail, compared by code", item_id="C11", page=4,
                       code_note="code compared two values of the paper: 26 bar <= 20 bar: false")  # fmt: skip
    make_run("gen_nofold", [fail, question, other_kind], created="2026-11-18T16:30:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_nofold")
        .json()
    )
    assert [c["lines"] for c in body["comments"]] == [
        [1],
        [2],
        [3],
    ]  # another label, another compare kind: apart
    assert body["completeness"]["ok"] is True


def test_every_sent_line_is_in_exactly_one_comment_or_the_file_is_refused():
    view = {
        "points": [{"n": 1, "label": "Question", "code_note": ""}, {"n": 2, "label": "Question", "code_note": ""},
                   {"n": 3, "label": "Met", "code_note": ""}],
    }  # fmt: skip
    col = aim_review_sheet.COMMENT_HEADERS.index("Lines")

    def row(lines):
        r = [None] * len(aim_review_sheet.COMMENT_HEADERS)
        r[col] = lines
        return r

    assert aim_review_completeness._lines_check([row("1, 2")], view) == []
    assert (
        "not in any comment: [2]"
        in aim_review_completeness._lines_check([row("1")], view)[0]
    )  # a forged, short file
    assert (
        "in more than one comment"
        in aim_review_completeness._lines_check([row("1, 2"), row("2")], view)[0]
    )
    assert (
        "not sent lines in a comment: [3]"
        in aim_review_completeness._lines_check([row("1, 2, 3")], view)[0]
    )


def test_the_summary_sheet_states_the_measured_score_of_the_papers_kind(world):
    """Piece G: the page's `measured` sentence is on the Summary sheet too (here the shipped table holds no score for the kind, so it
    says "not measured"); a run that names no kind leaves the cell empty, never a number."""
    make_run(
        "gen_run_measured", created="2026-11-18T16:00:00Z"
    )  # identity kind "datasheet" (make_run's default)
    c = client(PAPER, BOOK)
    body = c.get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_run_measured").json()
    measured = body["measured"]
    assert measured is not None and measured["sentence"]
    wb = _sheet(
        c.get(f"/api/reviews/papers/{PAPER}/general/sheet?run_id=gen_run_measured")
    )
    rows = [
        row
        for row in wb["Summary"].iter_rows(values_only=True)
        if row and row[0] == "Measured score of this kind"
    ]
    assert rows and rows[0][1] == measured["sentence"]


def test_different_findings_of_one_item_are_one_lossless_comment(world):
    """The owner's order (one comment per check point, listing every place; valve sheet at most 40 comments): the findings of
    one item are ONE comment, and it keeps every member's own words and field (final light check B1 forbade LOSING them, which
    this never does); a member's unverified quote is carried."""
    a = _line(
        1,
        "Question",
        "Question",
        item_id="G2",
        field="Design pressure",
        page=1,
        comment="Design pressure disagrees.",
    )
    b = _line(
        2,
        "Question",
        "Question",
        item_id="G2",
        field="Tag number",
        page=2,
        comment="The tag differs.",
        quote_unverified=1,
    )
    c = _line(
        3,
        "Question",
        "Question",
        item_id="G2",
        field="design  pressure",
        page=3,
        comment="Design pressure disagrees.",
    )
    make_run("gen_two", [a, b, c], created="2026-11-18T17:00:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_two")
        .json()
    )
    assert [cm["lines"] for cm in body["comments"]] == [[1, 2, 3]]
    one = body["comments"][0]
    assert (
        "Tag number (page 2) [rule: STD-X clause 4.2]: The tag differs."  # each place names its rule in one["comment"]
        and "Design pressure disagrees." in one["comment"]
    )
    assert one["quote_unverified"] is True and body["completeness"]["ok"] is True


# ---- one comment per CHECK: repeats of one checklist item merge, different items never (18 Nov 2026, grouping try 2) -------

KNOW = "engineering knowledge (book not held)"


def test_one_check_across_tags_and_pages_is_one_comment_with_each_places_own_words_and_value(
    world,
):
    rows = [
        _line(i, "Question", "Question", item_id="C07", field=f"Invented tag {i} set value", page=i,
              comment=f"Invented tag {i}: please confirm the value {i}0.", quote=f"invented quote {i}")
        for i in range(1, 4)
    ]  # fmt: skip
    make_run("gen_check", rows, created="2026-11-18T19:00:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_check")
        .json()
    )
    assert [cm["lines"] for cm in body["comments"]] == [[1, 2, 3]]
    one = body["comments"][0]
    assert one["pages"] == [1, 2, 3]
    cells = " ".join((one["comment"], one["quote"]))
    for i in range(
        1, 4
    ):  # lossless: each tag's field, page, own words (its own value) and quote
        assert f"Invented tag {i}: please confirm the value {i}0." in one["comment"]
        assert f"invented quote {i}" in cells
    for i in (2, 3):
        assert f"Invented tag {i} set value (page {i})" in one["comment"]
    rep = body["completeness"]
    assert rep["ok"] is True and rep["page"] == rep["database"] == rep["file_rows"] == 3
    assert rep["comments"] == rep["comment_rows"] == 1


def test_different_items_are_never_merged_whatever_their_source_or_rule_book(world):
    """No list of different points (a list buried findings): plain questions from no held standard, and plain questions
    against one rule book, each stay a comment of their own item."""
    rows = [
        *[_line(i, "Question", "Question", page=i, source=KNOW, book_document_id=None, standard="", clause="")
          for i in range(1, 4)],
        *[_line(i, "Question", "Question", page=i) for i in range(4, 7)],  # three items, one rule book (STD-X)
    ]  # fmt: skip
    make_run("gen_items", rows, created="2026-11-18T19:30:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_items")
        .json()
    )
    assert [cm["lines"] for cm in body["comments"]] == [[1], [2], [3], [4], [5], [6]]
    assert all(
        cm["comment"] == f"invented comment {cm['n']}" for cm in body["comments"]
    )
    assert body["completeness"]["ok"] is True


def test_an_editor_group_mark_never_merges_different_items_and_one_item_splits_by_label_and_compare_kind(
    world,
):
    """The editor's "same point" mark joins nothing in the view now (it spanned different items); one item's lines merge only
    when they show the same label and the same compare kind (a code-compared Fail never joins a Question)."""
    mark = "same point as line 1"
    cmp_rule = json.dumps(
        {
            "result": "fail",
            "read_from": "verified paper quotes",
            "why": "25 bar <= 20 bar: false",
        }
    )
    cmp_other = json.dumps({"read_from": "verified quotes", "why": "invented compare"})
    lines = [
        _line(1, "Question", "Question", item_id="C01", code_note=mark),
        _line(2, "Question", "Question", item_id="C02", code_note=mark),  # another item: its own comment
        _line(3, "Not met", "Fail, compared by code", item_id="C03", code_compare_json=cmp_rule),
        _line(4, "Question", "Question", item_id="C03"),  # same item, another label
        _line(5, "Question", "Question", item_id="C04", code_compare_json=cmp_other),
        _line(6, "Question", "Question", item_id="C04"),  # same item and label, another compare kind
        _line(7, "Question", "Question", item_id="C05"),
        _line(8, "Question", "Question", item_id="C05"),  # a true repeat
    ]  # fmt: skip
    make_run("gen_marks", lines, created="2026-11-18T20:00:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_marks")
        .json()
    )
    assert [c["lines"] for c in body["comments"]] == [
        [1],
        [2],
        [3],
        [4],
        [5],
        [6],
        [7, 8],
    ]
    assert body["comments"][2]["shown_label"] == "Fail, compared by code"
    rep = body["completeness"]
    assert rep["ok"] is True and rep["page"] == rep["database"] == rep["file_rows"] == 8
    assert rep["comments"] == rep["comment_rows"] == 7


def test_one_paper_field_raised_by_different_items_is_one_comment_naming_each_rule(
    world,
):
    """The same spot of the paper questioned by two rules and an always-checked item: one comment for that field, listing each
    rule and clause, tag and page with its own words and quote. Where the label only says WHERE (a sheet, a tag in brackets),
    it is the same field; a different field, a different label or a finding never joins."""
    rows = [
        _line(1, "Question", "Question", item_id="C01", field="Invented flow, Sheet 1", page=1, clause="4.1"),
        _line(2, "Question", "Question", item_id="C02", field="Invented flow (tag 2)", page=2, standard="STD-Y", clause="7.2"),
        _line(3, "Question", "Question", item_id="G1", field="invented  FLOW", page=3, source=KNOW, book_document_id=None,
              standard="", clause=""),
        _line(4, "Question", "Question", item_id="C04", field="Invented flow / invented size", page=4),  # another field
        _line(5, "AI opinion", "AI opinion", item_id="C05", field="Invented flow", page=5),  # another label
        _line(6, "Question", "Question", item_id="C06", field="Invented flow", page=6, code_note="provisional_unchecked"),
    ]  # fmt: skip
    make_run("gen_field", rows, created="2026-11-18T21:00:00Z")
    body = (
        client(PAPER, BOOK)
        .get(f"/api/reviews/papers/{PAPER}/general?run_id=gen_field")
        .json()
    )
    assert [cm["lines"] for cm in body["comments"]] == [[1, 2, 3], [4], [5], [6]]
    one = body["comments"][0]
    assert one["standard"] == "STD-X; STD-Y" and one["clause"] == "4.1; 7.2"
    assert (
        "Invented flow (tag 2) (page 2) [rule: STD-Y clause 7.2]: invented comment 2"
        in one["comment"]
    )
    assert "invented  FLOW (page 3): invented comment 3" in one["comment"]
    assert all(f"invented quote {i}" in one["quote"] for i in (1, 2, 3))
    rep = body["completeness"]
    assert rep["ok"] is True and rep["page"] == rep["database"] == rep["file_rows"] == 6
    assert rep["comments"] == rep["comment_rows"] == 4


def test_the_field_of_a_label_drops_only_where_words():
    from app.aim_review_view import point_field

    assert (
        point_field("Invented flow, Sheet 2 (service B)")
        == point_field("invented flow (tag 9)")
        == "invented flow"
    )
    assert point_field("Invented flow / invented size") != point_field("Invented flow")
    assert (
        point_field("Invented size, page 4") == "invented size"
        and point_field("(only where)") == ""
    )
