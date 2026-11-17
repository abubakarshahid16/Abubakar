"""Rule 5 on every surface of the AI review (order 14, PR #1883 on PR #1876): a DATASHEET line whose rule book the viewer may not read
shows him none of the book's words, through the ONE guard `review_points.for_viewer` and its ALLOW-LIST (`crs_ai_viewer.shown`):
the paper's own words and the line's class only, every rule-side field one fixed sentence. No numbering, no text search: a line
break, a fragment, a clause number alone or another spelling of the book's name cannot slip through. The run file keeps the full
lines' grouping, split, order and Status for every viewer. A reader of every book gets exactly what main gives. Invented values."""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app import agent_review_jobs, crs_ai_viewer, db
from app import review_points as rp
from app.config import settings
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, sheet_text
from tests.test_crs_endpoint import _client, _submittal, temp_db  # noqa: F401 - fixture

BOOK_DOC, BOOK_FILE = "doc_std", "STD-A-001.pdf"
BOOK, OTHER_BOOK = (
    "STD-1",
    "STD-9",
)  # the names the lines cite the hidden book by (invented)
RULE_WORDS, AI_WORDS = "Nameplates shall be steel and fixed", "It is steel"
SECRETS = (
    BOOK, OTHER_BOOK, RULE_WORDS, AI_WORDS,
    "stainless steel", "7.3.9",  # a rule quote broken by a line break; a clause number alone
    "STDA001",  # another spelling of the book's own name, on a line that links no book
    "asks for steel", "Figure 9", "Use steel",  # the second reader's reason, a figure, the reader's suggested action
    "Tag plate: brass",  # a paper quote code did not verify: shown to no one who may not see the line
    "against the rule for",  # never a sentence that runs into the fixed one
)  # fmt: skip
HIDDEN = crs_ai_viewer.HIDDEN_RULE
UNVERIFIED = (
    "Tag plate: brass"  # a paper quote code did not find on its page (invented)
)
DOC: list[str] = []


@pytest.fixture(autouse=True)
def on(monkeypatch, temp_db):  # noqa: F811
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)


def setup_world() -> str:
    """A paper and its AI run against the held rule book BOOK_DOC (a library book: it holds a stored rule)."""
    doc = _submittal()
    _submittal(BOOK_DOC, BOOK_FILE)
    with db.connect() as conn:
        conn.execute("INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
                     " created_at, updated_at) VALUES ('rq1', ?, '1', 1, 'x', 'x', 't', 't')", (BOOK_DOC,))  # fmt: skip
    lines = [
        mk("R-1", "Fail", "Fail"),
        mk("R-8", "Query", None, why=f"the clause of {BOOK} was not confirmed", comment=f"Use steel per {BOOK}",
           second_opinion={"agree": False, "reason": f"{BOOK} asks for steel"}, clause_figure=f"Figure 9 of {BOOK}"),
        mk("R-21", "Query", "Fail", why="no second opinion", field="", field_roles=[]),
        mk("R-22", "Query", "Fail", why="no second opinion", field="", field_roles=[]),
        mk("R-23", "Query", "Fail", why="no second opinion", field="", field_roles=[], standard=OTHER_BOOK),
        mk("R-30", "Query", "Fail", why="no second opinion", clause="7.3.9", clause_quote="Plates shall be\nstainless steel"),
        mk("R-40", "Query", None, why="the value is held per STDA001 table", standard=""),
        mk("R-50", "Query", None, why="x y", quotes_checked={"paper": False, "clause": True}, paper_quote=UNVERIFIED),
        # a coverage line: N rules of the hidden book could not be matched (its book is named in the coverage note)
        mk("G-1", "Query", None, item={"source": "group"}, group_count=3, field="", field_roles=[]),
    ]  # fmt: skip
    ai = ai_run(doc, lines, book_doc=BOOK_DOC)
    with (
        db.connect() as conn
    ):  # R-40 links no book: it is hidden only because its words name the book
        conn.execute(
            "UPDATE agent_review_rule SET standard_document_id = NULL, rule_book = '' WHERE rule_key = 'R-40'"
        )
    DOC[:] = [doc]
    return ai


def full():
    return _client(
        DOC[0], BOOK_DOC
    )  # the scope override is global: made again before each use


def restricted():
    return _client(DOC[0])


def sheets(data: bytes) -> dict[str, int]:
    wb = load_workbook(io.BytesIO(data))
    return {
        ws.title: sum(
            1 for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)
        )
        for ws in wb.worksheets
    }


def statuses(data: bytes) -> list:
    return [
        r[-1]
        for r in load_workbook(io.BytesIO(data))["CRS"].iter_rows(values_only=True)
    ]


def leaked(text: str) -> list[str]:
    return [s for s in SECRETS if s in text]


def test_the_run_file_shows_a_restricted_viewer_no_rule_words_and_the_same_split():
    ai = setup_world()
    url = f"/api/reviews/runs/{ai}/agent/crs?copy=internal"
    hidden, shown = restricted().get(url), full().get(url).content
    assert hidden.status_code == 200, hidden.text
    text = sheet_text(hidden.content)
    assert leaked(text) == [], leaked(text)
    assert HIDDEN in text and "holds no verified quote" not in text
    assert BOOK in sheet_text(shown) and "holds no verified quote" in sheet_text(
        shown
    )  # (so the checks above are not vacuous)
    assert sheets(hidden.content) == sheets(shown) and statuses(
        hidden.content
    ) == statuses(shown)  # the same split, order, Status
    assert (
        shown == (agent_review_jobs.run_dir(ai) / "crs-internal.xlsx").read_bytes()
    )  # main's bytes for the reader of the book


def test_the_lines_tab_and_the_trace_show_a_restricted_viewer_no_rule_words():
    ai = setup_world()
    lines_url = f"/api/reviews/runs/{ai}/agent/lines"
    hidden, shown = restricted().get(lines_url), full().get(lines_url)
    assert hidden.status_code == 200 and leaked(hidden.text) == [], leaked(hidden.text)
    assert [ln["verdict_class"] for ln in hidden.json()["lines"]] == [
        ln["verdict_class"] for ln in shown.json()["lines"]
    ]
    assert BOOK in shown.text
    for item in ("R-1", "R-8", "R-30", "R-40"):
        got = restricted().get(f"/api/reviews/runs/{ai}/agent/lines/{item}/trace")
        assert got.status_code == 200 and leaked(got.text) == [], (
            item,
            leaked(got.text),
        )
        assert (
            got.json()["rule_book"] == HIDDEN
        )  # one sentence, never a number that differs between the tab and the trace


def test_rules_used_counts_a_hidden_rule_and_never_names_it():
    ai = setup_world()
    url = f"/api/reviews/runs/{ai}/rules-used"
    hidden, shown = restricted().get(url).json(), full().get(url).json()
    assert len(hidden["asked"]) == len(shown["asked"]) and BOOK in json.dumps(shown)
    assert BOOK not in json.dumps(hidden) and all(
        r["rule_book"] == HIDDEN for r in hidden["asked"] if r["rule_book"]
    )


def test_a_reader_of_every_book_is_unchanged_by_the_guard(monkeypatch):
    ai = setup_world()
    urls = [
        f"/api/reviews/runs/{ai}/agent/lines",
        f"/api/reviews/runs/{ai}/agent/lines/R-8/trace",
        f"/api/reviews/runs/{ai}/rules-used",
    ]
    before = [full().get(u).json() for u in urls]
    monkeypatch.setattr(rp, "for_viewer", lambda line, ctx: line)  # the guard off
    monkeypatch.setattr(rp, "documents_hidden", lambda *a: False)
    assert [full().get(u).json() for u in urls] == before


def test_two_viewers_of_one_run_file_never_share_a_file():
    from app import review_points_service as svc

    ai = setup_world()
    folder = agent_review_jobs.run_dir(ai)
    pid = next(
        p["id"]
        for p in full().get(f"/api/reviews/papers/{DOC[0]}/points").json()["points"]
        if p["id"].endswith(":R-8")
    )
    assert (
        full()
        .post(
            f"/api/reviews/papers/{DOC[0]}/points/decision",
            json={"point_id": pid, "state": "keep"},
        )
        .status_code
        == 200
    )
    mine = svc.decided_ai_sheet(
        ai, DOC[0], "internal", folder, frozenset({DOC[0], BOOK_DOC})
    )
    theirs = svc.decided_ai_sheet(ai, DOC[0], "internal", folder, frozenset({DOC[0]}))
    assert mine.name != theirs.name
    assert leaked(sheet_text(theirs.read_bytes())) == [] and BOOK in sheet_text(
        mine.read_bytes()
    )


def test_a_summary_names_only_the_project_papers_the_viewer_may_read():
    ai = setup_world()
    _submittal("doc-proj-q", "project-q.pdf")
    with db.connect() as conn:
        conn.execute("INSERT INTO agent_review_general (run_id, project_json) VALUES (?, ?)",
                     (ai, json.dumps([{"document_id": "doc-proj-q", "name": "project-q.pdf"}])))  # fmt: skip
    hidden = restricted().get(f"/api/reviews/runs/{ai}/agent/summary").json()
    assert (
        "project-q" not in json.dumps(hidden) and hidden["project_papers_hidden"] == 1
    )
    shown = (
        _client(DOC[0], BOOK_DOC, "doc-proj-q")
        .get(f"/api/reviews/runs/{ai}/agent/summary")
        .json()
    )
    assert (
        shown["project_papers_used"][0]["name"] == "project-q.pdf"
        and shown["project_papers_hidden"] is None
    )


def test_a_stored_line_that_cannot_be_read_is_hidden_from_a_restricted_viewer():
    from app.api.agent_review import UNREADABLE_LINE

    ai = setup_world()
    with db.connect() as conn:
        conn.execute("UPDATE agent_review_line SET line_json = '{not json', reason = ? WHERE run_id = ? AND item_id = 'R-8'",
                     (f"stored words of {BOOK}", ai))  # fmt: skip
    hidden = restricted().get(f"/api/reviews/runs/{ai}/agent/lines").text
    assert BOOK not in hidden and UNREADABLE_LINE in hidden
    assert (
        f"stored words of {BOOK}"
        in full().get(f"/api/reviews/runs/{ai}/agent/lines").text
    )  # a reader of every book: as stored


def test_a_comment_note_counts_the_points_whose_rule_is_not_shown_and_stays_whole():
    from app import crs_one

    c = {"n_points": 3, "disagree": False, "tags": [], "strongest": {"id": "a"}}
    ms = [
        c["strongest"],
        {"id": "b", "name": "Field B", "rank": 4},
        {"id": "c", "name": "A requirement", "rank": 4, "_name_hidden": True},
    ]
    note = crs_one.comment_note(c, ms)
    assert (
        "Field B" in note
        and "A requirement" not in note
        and "1 more point(s) whose rule is not shown to you" in note
    )


def test_the_page_points_and_the_team_file_show_a_hidden_datasheet_point_through_the_same_allow_list():
    # one rule on every surface: a hidden point's action, reason and the team file's cells come from the allow-list; its rank,
    # grouping and counts from the full line (the same for both viewers)
    setup_world()
    page = restricted().get(f"/api/reviews/papers/{DOC[0]}/points")
    team = restricted().get(
        f"/api/reviews/papers/{DOC[0]}/crs", params={"copy": "team"}
    )
    assert page.status_code == 200 and team.status_code == 200, (page.text, team.text)
    text = sheet_text(team.content)
    assert leaked(page.text) == [] and leaked(text) == [], (
        leaked(page.text),
        leaked(text),
    )
    full_page = full().get(f"/api/reviews/papers/{DOC[0]}/points").json()
    full_team = sheet_text(
        full().get(f"/api/reviews/papers/{DOC[0]}/crs", params={"copy": "team"}).content
    )
    assert (
        leaked(full_team) != []
    )  # the reader of the book sees them (so the check above is not vacuous)
    mine = page.json()
    assert (mine["of"], mine["comment_count"]) == (
        full_page["of"],
        full_page["comment_count"],
    )
    assert [p["rank"] for p in mine["points"]] == [
        p["rank"] for p in full_page["points"]
    ]


def test_a_reader_of_every_book_gets_layout_view_untouched_on_a_decided_run():
    # final check (lead): nothing hidden from him, so no cell of his file is touched: "Rules not asked" keeps its counts
    from app import crs_ai_workbook as wb
    from app import review_point_decisions as dm
    from app import review_points_service as svc

    ai = setup_world()
    folder = agent_review_jobs.run_dir(ai)
    (folder / "crs-meta.json").write_text(
        json.dumps(
            {
                "paper": DOC[0],
                "run_id": ai,
                "rule_labels": {
                    "summary_lines": ["3 rules not asked: invented reason"]
                },
            }
        )
    )
    pid = next(
        p["id"]
        for p in full().get(f"/api/reviews/papers/{DOC[0]}/points").json()["points"]
        if p["id"].endswith(":R-8")
    )
    assert (
        full()
        .post(
            f"/api/reviews/papers/{DOC[0]}/points/decision",
            json={"point_id": pid, "state": "keep"},
        )
        .status_code
        == 200
    )
    got = full().get(f"/api/reviews/runs/{ai}/agent/crs?copy=internal").content
    conn = db.connect()
    lines = dm.apply_to_lines(
        DOC[0], ai, svc.stored_lines(conn, ai), svc._names(dm.people(DOC[0]))
    )
    want = wb.layout_view(lines, svc.run_meta(conn, ai, DOC[0], folder), "internal")
    from app import crs_layout

    assert got == crs_layout.build_layout_crs(want)  # main's own drawing, byte for byte
    assert HIDDEN not in sheet_text(got) and "3 rules not asked" in sheet_text(got)


def test_both_viewers_are_served_the_same_rows_even_when_the_stored_file_is_older():
    # final check (lead): a stored file drawn by an older reading (its split differs) is never served to one viewer while the other
    # gets a sheet drawn now: both are drawn now, so the rows on every sheet are the same
    from app import agent_review_crs as C
    from tests.test_agent_review_crs import META

    ai = setup_world()
    folder = agent_review_jobs.run_dir(ai)
    lines = [
        mk("R-1", "Pass", "Pass"),
        *[mk(f"R-{n}", "Query", None, why="x y") for n in (8, 21, 22, 23, 30, 40, 50)],
        mk(
            "G-1",
            "Query",
            None,
            item={"source": "group"},
            group_count=3,
            field="",
            field_roles=[],
        ),
    ]
    C.write_internal(
        lines, folder / "crs-internal.xlsx", {**META, "run_id": ai, "paper": DOC[0]}
    )  # an older reading, its own split
    url = f"/api/reviews/runs/{ai}/agent/crs?copy=internal"
    mine, theirs = full().get(url), restricted().get(url)
    assert mine.status_code == theirs.status_code == 200, (mine.text, theirs.text)
    assert sheets(mine.content) == sheets(theirs.content) and statuses(
        mine.content
    ) == statuses(theirs.content)


def test_the_shown_line_carries_only_a_paper_quote_code_verified():
    line = mk(
        "R-50",
        "Query",
        None,
        why="x y",
        quotes_checked={"paper": False, "clause": True},
        paper_quote=UNVERIFIED,
    )
    assert "paper_quote" not in crs_ai_viewer.shown(line)
    assert (
        crs_ai_viewer.shown(mk("R-1", "Fail", "Fail"))["paper_quote"]
        == "Nameplate: steel"
    )  # verified: the paper's own words
