"""LP2 (order 14 live proof, 17 Nov 2026): a general review's line on a CRS row says WHAT to check, never only "Engineer to check
the item.": the paper's point, its page (or "page not recorded") and the reason it rests on (the AI reviewer's own words, labelled as
its words, or the review's own reason). Built through the real files: the AI run's file (`crs_ai_workbook.layout_view` drawn by
`crs_layout.build_layout_crs`, read back) and the paper's one CRS rows (`review_points.ai_point` -> `crs_one.comment_cells`).
Invented values only."""

from __future__ import annotations

import io
import json

import openpyxl
import pytest

from app import agent_general_crs as question
from app import agent_general_review as core
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import crs_comments, crs_layout, crs_one
from app import review_points as rp
from app.crs_completeness import _table_rows
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

BARE = "Engineer to check the item."
META = {"paper": "Paper Z", "run_id": "run-lp2", "date": "2026-11-17"}
AI_TEXT = "The isolation step names a valve tag that the valve list does not hold"
CODE_TEXT = core.NO_CHECKLIST


def stored(part: int, cls: str, n: int, text: str, *, model: bool, **kw) -> dict:
    """A general line as `agent_general_job.store_lines` keeps it (`"general": true`), read as every CRS reads it."""
    line = core.finalize_line(
        {"part": part, "verdict_class": cls, "document": "doc-z", "text": text, **kw}
    )
    line.update(general=True, line_id=f"G-{n:03d}", item_id=f"G-{n:03d}", part_word=core.PART_WORDS[part],
                text_source=core.TEXT_FROM_MODEL if model else None)  # fmt: skip
    return line


def lines() -> list[dict]:
    return words.read_now(
        [
            stored(
                5,
                core.CLASS_NOTE,
                1,
                AI_TEXT,
                model=True,
                subkind=core.SUB_ENGINEERING,
                quotes_verified_by_code=True,
                quote_a={
                    "document": "doc-z",
                    "page": 4,
                    "text": "Close valve XV-901 before the test",
                },
            ),
            stored(2, core.CLASS_NOT_REVIEWED, 2, CODE_TEXT, model=False, subkind=None),
            stored(
                2,
                core.CLASS_QUERY,
                3,
                "checklist: test interval: not found in the paper",
                model=True,
                subkind=core.SUB_CHECKLIST,
                topic="test interval",
            ),
            stored(
                1,
                core.CLASS_NOT_CHECKED,
                4,
                "not checked against STD-77, rule book not held",
                model=False,
                subkind=None,
                rule_book="STD-77",
            ),
        ],
        [],
    )


def run_file_comments(given: list[dict]) -> list[str]:
    data = crs_layout.build_layout_crs(WB.layout_view(given, META, "internal"))
    ws = openpyxl.load_workbook(io.BytesIO(data))[crs_layout.LAYOUT_MAIN_SHEET]
    return [
        " ".join(str(c) for c in r if c is not None) for r in _table_rows(ws, "Item No")
    ]


def test_every_general_row_of_the_run_file_names_its_point_page_and_reason():
    rows = run_file_comments(lines())
    assert len(rows) == 4
    assert not any(BARE in r for r in rows)
    note = next(r for r in rows if "engineering comment" in r)
    assert (
        "Engineer to check the paper's point (engineering comment), page 4: the AI reviewer's words, not proven by code: \""
        + AI_TEXT
        + '".'
        in note
    )
    assert (
        '"Close valve XV-901 before the test", page 4' in note
    )  # the quote code verified, with its page
    assert (
        "Contractor to confirm compliance with the rule" not in note
    )  # an engineer's question asks no contractor
    unread = next(r for r in rows if CODE_TEXT in r)
    assert f"page not recorded: the review's own reason: {CODE_TEXT}." in unread
    assert (
        "the AI reviewer's words" not in unread
    )  # code's own words are never labelled as the AI's
    checklist = next(r for r in rows if "test interval" in r)
    assert (
        'Engineer to check the checklist point "test interval", page not recorded'
        in checklist
    )
    assert not any(
        "AI reviewer's words" in r for r in rows if "STD-77" in r or CODE_TEXT in r
    )
    book = next(r for r in rows if "STD-77" in r)
    assert "Engineer to check the paper against STD-77" in book
    assert "No rule book was checked for this point (named: STD-77)." in book


CTX = {"run_id": "r", "paper_document_id": "doc-z", "book_of": {}, "readable": frozenset(), "library": [], "everything": True,
       "documents": frozenset()}  # fmt: skip


def test_the_page_crs_row_takes_the_same_question_and_the_verified_quote():
    line = lines()[0]
    point = rp.ai_point(dict(line), CTX)
    assert point["action"] == question.question_row(line).action
    assert point["paper_quote"] == "Close valve XV-901 before the test"
    assert point["page"] == 4
    c = crs_comments.group([{**point, "id": "a1"}])[0]
    cells, _cut = crs_one.comment_cells(c, {"a1": {**point, "id": "a1"}})
    text = " ".join(str(x) for x in cells if x is not None)
    assert BARE not in text
    assert f'the AI reviewer\'s words, not proven by code: "{AI_TEXT}"' in text
    assert (
        '"Close valve XV-901 before the test" (Checked by code: found on the page.)'
        in text
    )


def test_a_viewer_who_may_not_read_a_named_book_gets_no_free_words_and_no_name():
    line = {**lines()[3], "text": "the paper cites STD-9 for the test, which we hold"}
    hidden_ctx = {
        **CTX,
        "everything": False,
        "library": [{"id": "doc-std9", "document_number": "STD-9"}],
    }
    point = rp.ai_point(dict(line), hidden_ctx)
    assert "STD-9" not in point["action"] and "STD-77" not in point["action"]
    assert (
        question.HIDDEN in point["action"] and question.UNNAMED_BOOKS in point["action"]
    )
    shown = rp.ai_point(dict(line), {**hidden_ctx, "readable": frozenset({"doc-std9"})})
    assert "STD-9" in shown["action"]  # he may read the book: the words are his to see


def test_a_line_that_is_not_a_general_review_line_keeps_the_rule_review_wording():
    rule = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Query",
        "field": "Set pressure",
        "standard": "STD-1",
    }
    assert question.question_row(rule) is None
    assert (
        question.question_row({**rule, "general": "yes"}) is None
    )  # only the stored flag itself


def test_a_line_code_wrote_is_never_labelled_as_the_ai_reviewers_words():
    # the review's own "not reviewed" sentence of a part whose text source is the reader's: code wrote it, so it is the review's reason
    line = stored(
        4,
        core.CLASS_NOT_REVIEWED,
        9,
        f"not reviewed: {core.NO_PROJECT_PAPER}",
        model=True,
        subkind=None,
    )
    action = question.question_row(line).action
    assert "the AI reviewer's words" not in action
    assert (
        f"page not recorded: the review's own reason: not reviewed: {core.NO_PROJECT_PAPER}."
        in action
    )


# ------------------------------------------------------------------------------------------------ review round 2 (rule 5 and rule 4)
PAPER, PROJ = (
    "doc-z",
    "doc-proj-q",
)  # invented ids: the paper under review and a project paper
PROJ_QUOTE, PROJ_WHAT = (
    "Flush the line for ten minutes",
    "the flushing time is not stated",
)


def part4(
    cls: str = core.CLASS_QUERY,
    text: str = f"the paper is silent on this requirement of {PROJ}: {PROJ_WHAT}",
    **kw,
) -> dict:
    """A part-4 line against the project paper PROJ, with its quote verified by code (invented)."""
    base = {"subkind": core.SUB_SILENT, "other_document": PROJ, "quotes_verified_by_code": True,
            "quote_other": {"document": PROJ, "page": 2, "text": PROJ_QUOTE}}  # fmt: skip
    return stored(4, cls, 7, text, model=True, **{**base, **kw})


def viewer(*readable: str, library=()) -> dict:
    return {
        **CTX,
        "paper_document_id": PAPER,
        "everything": False,
        "readable": frozenset(readable),
        "library": list(library),
        # the held documents: a document is hidden only when it is RESOLVED (held) and the viewer may not read it
        "documents": frozenset({PAPER, PROJ, *(e["id"] for e in library)}),
    }


def every_word(point: dict) -> str:
    return json.dumps(point, default=str)


def test_a_project_paper_the_viewer_may_not_read_is_never_named_or_quoted_on_the_page():
    # rule 5: the page point of a part-4 line names its project paper and prints the AI's words about its requirement only to a viewer
    # who may read that paper (the reviewer's round-1 leak: only held rule books were tested)
    hidden = every_word(rp.ai_point(part4(), viewer(PAPER)))
    assert PROJ not in hidden and PROJ_QUOTE not in hidden and PROJ_WHAT not in hidden
    assert question.HIDDEN in hidden and question.HIDDEN_DOCUMENT in hidden
    shown = every_word(rp.ai_point(part4(), viewer(PAPER, PROJ)))
    assert (
        PROJ in shown and PROJ_QUOTE in shown and PROJ_WHAT in shown
    )  # he may read it: his to see
    # final check (lead): a document that is not held (deleted: its id stays on the stored line) is no one's to read: hidden too
    gone = part4(
        other_document="doc-gone",
        quote_other={"document": "doc-gone", "page": 2, "text": PROJ_QUOTE},
    )
    assert PROJ_QUOTE not in every_word(rp.ai_point(gone, viewer(PAPER)))
    assert question.HIDDEN_DOCUMENT in every_word(rp.ai_point(gone, viewer(PAPER)))


def test_under_hide_no_cell_names_a_topic_a_sub_kind_or_a_quote_of_a_document_the_viewer_may_not_read():
    # rule 5: ONE guard inside question_row (`viewed`), so every branch (point, part 1, part 2, the action) obeys the flag
    topic = stored(2, core.CLASS_QUERY, 8, "checklist: STD-9 hydrotest pressure: not found in the paper", model=False,
                   subkind=core.SUB_CHECKLIST, topic="STD-9 hydrotest pressure")  # fmt: skip
    library = [{"id": "doc-std9", "document_number": "STD-9"}]
    point = rp.ai_point(dict(topic), viewer(PAPER, library=library))
    assert "STD-9" not in every_word(point)
    disagree = part4(core.CLASS_NOTE, subkind=core.SUB_DISAGREES.format(document=PROJ), text=PROJ_WHAT,
                     quote_paper={"document": PAPER, "page": 1, "text": "Flush for two minutes"})  # fmt: skip
    for line in (topic, disagree, part4()):
        row = question.question_row({**line, question.HIDE_KEY: True})
        cells = " ".join((row.point, *row.cells))
        assert not any(x in cells for x in ("STD-9", PROJ, PROJ_QUOTE, PROJ_WHAT)), (
            cells
        )
    row = question.question_row({**disagree, question.HIDE_KEY: True})
    assert "disagrees with a document that is not available to you" in row.action
    assert (
        row.requires == "A document that is not available to you applies to this paper."
    )  # the part-4 quote is not printed
    assert (
        row.paper_quote == "Flush for two minutes"
    )  # the paper's own quote is the viewer's: kept


def run_world(doc: str, lines: list[dict]) -> str:
    """An invented finished AI run of `doc` whose lines are general lines, with its stored file drawn without a viewer (as the job does)."""
    import uuid

    from app import agent_review_jobs, agent_review_schema, db

    agent_review_schema.ensure_schema()
    run_id, now = str(uuid.uuid4()), "2026-11-17T00:00:00+00:00"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, doc, "completed", now, now, now),
        )
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, usd, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, doc, "procedure", "test", 0.0, now),
        )
        for ln in lines:
            conn.execute(
                "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, page, clause, rule_book, reason, rule_tier,"
                " line_json, trace_json, decided_at, part, text_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    ln["item_id"],
                    ln["verdict_class"],
                    ln["word"],
                    None,
                    "",
                    "",
                    ln["text"],
                    None,
                    json.dumps(ln),
                    "{}",
                    now,
                    core.PART_WORDS[ln["part"]],
                    ln.get("text_source"),
                ),
            )
    folder = agent_review_jobs.run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    WB.write(
        lines,
        folder / "crs-internal.xlsx",
        {"paper": doc, "run_id": run_id},
        "internal",
    )
    return run_id


@pytest.mark.usefixtures("temp_db")
def test_the_ai_run_file_is_drawn_for_its_viewer_and_never_names_a_paper_he_may_not_read(
    monkeypatch,
):
    # rule 5: the route serves the run file to anyone who may read the paper (`_run_or_404`); a general line naming a project paper he
    # may not read is drawn through its guard, in a file of its own name
    from app.config import settings
    from tests.test_b1_review_points import sheet_text
    from tests.test_crs_endpoint import _client, _submittal

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)
    _submittal(PAPER, "paper-z.pdf")
    _submittal(PROJ, "project-q.pdf")
    run_id = run_world(PAPER, [part4()])
    url = f"/api/reviews/runs/{run_id}/agent/crs?copy=internal"
    restricted = _client(PAPER).get(url)
    assert restricted.status_code == 200, restricted.text
    text = sheet_text(restricted.content)
    assert not any(x in text for x in (PROJ, PROJ_QUOTE, PROJ_WHAT)), text
    assert question.HIDDEN in text
    full = sheet_text(_client(PAPER, PROJ).get(url).content)
    assert (
        PROJ in full and PROJ_QUOTE in full and PROJ_WHAT in full
    )  # the reader of both papers gets the stored file


def test_a_page_point_with_a_quote_code_did_not_verify_prints_neither_the_quote_nor_checked_by_code():
    line = {**lines()[0], "quotes_verified_by_code": False}
    point = rp.ai_point(dict(line), CTX)
    assert point["paper_quote"] is None
    c = crs_comments.group([{**point, "id": "a1"}])[0]
    cells, _cut = crs_one.comment_cells(c, {"a1": {**point, "id": "a1"}})
    text = " ".join(str(x) for x in cells if x is not None)
    assert (
        "Close valve XV-901 before the test" not in text
        and "Checked by code" not in text
    )
    assert point["page"] is None  # an unverified quote's page is not THE page either


def bare_run():
    from app.agent_general_parts import GeneralRun

    g = object.__new__(
        GeneralRun
    )  # only what the line builders read: the paper, the unread pages, the lines
    g.paper, g.unread, g.lines, g.second_models = PAPER, [], [], set()
    return g


def made(g) -> dict:
    return {**g.lines[-1], "general": True}


def test_code_written_sentences_of_parts_two_to_five_are_the_reviews_own_reason_and_the_ais_words_stay_its_own():
    # rule 4: a sentence code built is never labelled as the AI reviewer's words; the AI's words inside it keep their label
    g = bare_run()
    s = {
        "kind": "silent",
        "document": PROJ,
        "quote_paper": None,
        "quote_other": {"page": 2, "text": PROJ_QUOTE},
        "what": PROJ_WHAT,
    }
    g._p4_line(s, "kept", True)
    assert (
        f"the review's own reason: the paper is silent on this requirement of {PROJ}; "
        f'the AI reviewer\'s words, not proven by code: "{PROJ_WHAT}".'
        in question.question_row(made(g)).action
    )
    g._p4_line(
        {
            **s,
            "kind": "contradicts",
            "quote_paper": {"page": 1, "text": "Flush for two minutes"},
        },
        "kept",
        False,
    )
    conflict = question.question_row(made(g)).action
    assert (
        "the review's own reason: a possible conflict with" in conflict
        and "AI reviewer's words" not in conflict
    )
    g._p2_line(
        {"item_id": "C-1", "topic": "test interval"},
        {"status": "absent", "verified": False, "a": {}},
    )
    absent = question.question_row(made(g)).action
    assert (
        "the review's own reason: checklist: test interval: not found" in absent
        and "AI reviewer's words" not in absent
    )
    g._p2_line(
        {"item_id": "C-2", "topic": "hold time"},
        {"status": "partial", "verified": False, "a": {"note": "no minutes given"}},
    )
    partial = question.question_row(made(g)).action
    assert (
        "the review's own reason: checklist: hold time: partly covered; the AI reviewer's words, not proven by code: \"no minutes given\""
        in partial
    )


def test_the_field_column_names_the_lines_own_topic_never_the_fixed_phrase_and_grouping_is_unchanged():
    # owner, 17 Nov 2026: the "Field or item" column said "A point of the AI review" on every AI note; it now says what the point is
    # about (its topic, else its kind), through the guard; the grouping key stays the internal one
    FIXED = "A point of the AI review"
    topic = stored(2, core.CLASS_QUERY, 8, "checklist: hold time: not found in the paper", model=False,
                   subkind=core.SUB_CHECKLIST, topic="hold time")  # fmt: skip
    points = [rp.ai_point(dict(ln), viewer(PAPER)) for ln in (*lines(), topic, part4())]
    names = [p["name"] for p in points]
    assert FIXED not in names
    assert (
        "hold time" in names and f"AI note: {core.SUB_ENGINEERING}" in names
    )  # a kind is a sentence, never bare (round 2)
    assert (
        f"Query: {core.SUB_SILENT} against {PROJ}" not in names
    )  # the project paper he may not read is not named
    assert f"Query: {core.SUB_SILENT} against {question.HIDDEN_DOCUMENT}" in names
    groups = crs_comments.group(
        [{**p, "id": f"p{n}"} for n, p in enumerate(points)], findings_only=False
    )
    assert len(groups) == len(points)  # each general line its own comment, as before

    assert core.SUB_ENGINEERING not in names  # no bare sub-kind


# ------------------------------------------------------------------------------------------------ review round 2: every other surface
def restricted_world(monkeypatch, decide=None):
    """The run of `test_the_ai_run_file...` with a part-4 line against PROJ and (optionally) an engineer's decision on it."""
    from app import agent_review_jobs
    from app.config import settings
    from tests.test_crs_endpoint import _submittal

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    _submittal(PAPER, "paper-z.pdf")
    _submittal(PROJ, "project-q.pdf")
    line = part4(core.CLASS_NOTE, text=PROJ_WHAT, subkind=core.SUB_DISAGREES.format(document=PROJ),
                 second_model_reason=f"both quotes speak of {PROJ_QUOTE}")  # fmt: skip
    run_id = run_world(PAPER, [line])
    if decide:
        point = next(
            p
            for p in full().get(f"/api/reviews/papers/{PAPER}/points").json()["points"]
            if p["id"].endswith(":G-007")
        )
        r = full().post(
            f"/api/reviews/papers/{PAPER}/points/decision",
            json={"point_id": point["id"], **decide},
        )
        assert r.status_code == 200, r.text
    return run_id, agent_review_jobs.run_dir(run_id)


def full():
    """A client of the reader of both papers (the scope override is global: made again before each use)."""
    from tests.test_crs_endpoint import _client

    return _client(PAPER, PROJ)


def restricted():
    """A client of a viewer who may read the paper, not the project paper."""
    from tests.test_crs_endpoint import _client

    return _client(PAPER)


SECRETS = (PROJ, PROJ_QUOTE, PROJ_WHAT)


@pytest.mark.usefixtures("temp_db")
def test_the_lines_tab_and_the_trace_never_give_a_restricted_viewer_the_hidden_words(
    monkeypatch,
):
    run_id, _f = restricted_world(monkeypatch)
    lines_url = f"/api/reviews/runs/{run_id}/agent/lines"
    trace_url = f"/api/reviews/runs/{run_id}/agent/lines/G-007/trace"
    for url in (lines_url, trace_url):
        hidden = restricted().get(url)
        assert hidden.status_code == 200, hidden.text
        assert not any(x in hidden.text for x in SECRETS), url
        assert any(x in full().get(url).text for x in SECRETS), (
            url
        )  # the reader of both papers sees them


ENGINEER = "Engineer: per the project paper, flush for ten minutes"


@pytest.mark.parametrize(
    "decide",
    [{"state": "edit", "text": ENGINEER}, {"state": "remove", "reason": ENGINEER}],
)
@pytest.mark.usefixtures("temp_db")
def test_an_engineers_edit_or_reason_on_a_hidden_line_never_reaches_a_restricted_viewer(
    monkeypatch, decide
):
    from tests.test_b1_review_points import sheet_text

    run_id, _f = restricted_world(monkeypatch, decide)
    words = ENGINEER
    page = restricted().get(f"/api/reviews/papers/{PAPER}/points").text
    team = sheet_text(
        restricted()
        .get(f"/api/reviews/papers/{PAPER}/crs", params={"copy": "team"})
        .content
    )
    contractor = sheet_text(
        restricted()
        .get(f"/api/reviews/papers/{PAPER}/crs", params={"copy": "contractor"})
        .content
    )
    run_file = sheet_text(
        restricted().get(f"/api/reviews/runs/{run_id}/agent/crs?copy=internal").content
    )
    for name, text in (
        ("page", page),
        ("team", team),
        ("contractor", contractor),
        ("run file", run_file),
    ):
        assert words not in text and not any(x in text for x in SECRETS), name
    assert (
        question.engineer_hidden_words(decide["state"]) in page
    )  # said by what he did
    assert (
        words in full().get(f"/api/reviews/papers/{PAPER}/points").text
    )  # his own words are his


@pytest.mark.usefixtures("temp_db")
def test_two_viewers_of_one_run_file_never_share_a_file(monkeypatch):
    from app import review_points_service as svc

    run_id, folder = restricted_world(monkeypatch, {"state": "keep"})
    mine = svc.decided_ai_sheet(
        run_id, PAPER, "internal", folder, frozenset({PAPER, PROJ})
    )
    theirs = svc.decided_ai_sheet(run_id, PAPER, "internal", folder, frozenset({PAPER}))
    assert (
        mine.name != theirs.name
    )  # a restricted file never overwrites, or is served as, the full one
    from tests.test_b1_review_points import sheet_text

    assert not any(x in sheet_text(theirs.read_bytes()) for x in SECRETS)
    assert any(x in sheet_text(mine.read_bytes()) for x in SECRETS)


@pytest.mark.usefixtures("temp_db")
def test_a_datasheet_line_whose_rule_book_is_hidden_keeps_the_engineers_edit_from_a_restricted_viewer(
    monkeypatch,
):
    # the same guard on a datasheet review: an edit on a line whose book the viewer may not read is never shown to him; the reader
    # of the book sees the run file under the same name as before (`crs-internal-decided.xlsx`) and his own words
    from app import review_points_service as svc
    from app.config import settings
    from tests.test_agent_review_crs import mk
    from tests.test_b1_review_points import ai_run, sheet_text
    from tests.test_crs_endpoint import _client, _submittal

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "old_crs_download_enabled", True)
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai = ai_run(doc, [mk("R-8", "Query", None, why="x y")])
    points = (
        _client(doc, "doc_std")
        .get(f"/api/reviews/papers/{doc}/points")
        .json()["points"]
    )
    pid = next(p["id"] for p in points if p["id"].endswith(":R-8"))
    assert _client(doc, "doc_std").post(f"/api/reviews/papers/{doc}/points/decision",
                                        json={"point_id": pid, "state": "edit", "text": ENGINEER}).status_code == 200  # fmt: skip
    page = _client(doc).get(f"/api/reviews/papers/{doc}/points").text
    team = sheet_text(
        _client(doc)
        .get(f"/api/reviews/papers/{doc}/crs", params={"copy": "team"})
        .content
    )
    run_file = sheet_text(
        _client(doc).get(f"/api/reviews/runs/{ai}/agent/crs?copy=internal").content
    )
    assert not any(ENGINEER in t for t in (page, team, run_file))
    assert (
        ENGINEER
        in _client(doc, "doc_std").get(f"/api/reviews/papers/{doc}/points").text
    )
    from app import agent_review_jobs

    own = svc.decided_ai_sheet(
        ai, doc, "internal", agent_review_jobs.run_dir(ai), frozenset({doc, "doc_std"})
    )
    assert own.name == "crs-internal-decided.xlsx" and ENGINEER in sheet_text(
        own.read_bytes()
    )


@pytest.mark.usefixtures("temp_db")
def test_a_rule_check_point_whose_rule_book_is_hidden_keeps_the_engineers_edit_from_a_restricted_viewer(
    monkeypatch,
):
    from app.config import settings
    from tests.test_b1_review_points import world_with_both
    from tests.test_crs_endpoint import _client

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    doc, _rc, _ai, _c = world_with_both()
    points = (
        _client(doc, "doc_std")
        .get(f"/api/reviews/papers/{doc}/points")
        .json()["points"]
    )
    pid = next(p["id"] for p in points if p["id"].startswith("rc:"))
    assert _client(doc, "doc_std").post(f"/api/reviews/papers/{doc}/points/decision",
                                        json={"point_id": pid, "state": "edit", "text": ENGINEER}).status_code == 200  # fmt: skip
    assert ENGINEER not in _client(doc).get(f"/api/reviews/papers/{doc}/points").text
    assert (
        ENGINEER
        in _client(doc, "doc_std").get(f"/api/reviews/papers/{doc}/points").text
    )


# ------------------------------------------------------------------------------------------------ review round 3: where "hidden" is decided
HIDDEN_SENTENCES = (
    question.ENGINEER_HIDDEN,
    question.ENGINEER_REMOVED,
    question.ENGINEER_KEPT,
)


def edit_rule_check_point(doc: str, reader, text: str) -> str:
    points = reader().get(f"/api/reviews/papers/{doc}/points").json()["points"]
    pid = next(p["id"] for p in points if p["id"].startswith("rc:"))
    r = reader().post(
        f"/api/reviews/papers/{doc}/points/decision",
        json={"point_id": pid, "state": "edit", "text": text},
    )
    assert r.status_code == 200, r.text
    return pid


def files_of(doc: str, reader) -> dict[str, str]:
    from tests.test_b1_review_points import sheet_text

    out = {"page": reader().get(f"/api/reviews/papers/{doc}/points").text}
    for copy in ("team", "contractor"):
        got = reader().get(f"/api/reviews/papers/{doc}/crs", params={"copy": copy})
        assert got.status_code == 200, (copy, got.text)
        out[copy] = sheet_text(got.content)
    return out


@pytest.mark.usefixtures("temp_db")
def test_a_reader_of_every_book_sees_his_own_edit_on_a_rule_check_point_with_no_book_everywhere(
    monkeypatch,
):
    # the lead's round-3 scenario: he reads the paper and every rule book, one UNRELATED paper is withheld, and he edits a rule-check
    # point that links no book. No document is named, so nothing is hidden: his own words, never "a document you may not read"
    from app.config import settings
    from tests.test_crs_endpoint import _client, _finding, _run, _submittal

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    _submittal("doc-unrelated", "unrelated.pdf")
    _finding(
        doc,
        _run(doc, recommended="Approved with Comments"),
        "NON_COMPLIANT",
        standard_document_id=None,
        standard_clause=None,
    )
    reader = lambda: _client(doc, "doc_std")  # noqa: E731 - the scope override is global: made again before each use
    edit_rule_check_point(doc, reader, ENGINEER)
    for name, text in files_of(doc, reader).items():
        assert ENGINEER in text, name
        assert not any(s in text for s in HIDDEN_SENTENCES), name


@pytest.mark.usefixtures("temp_db")
def test_a_truly_unreadable_linked_book_hides_the_edit_and_the_contractor_file_never_carries_a_placeholder(
    monkeypatch,
):
    from app import crs_completeness
    from app.config import settings
    from tests.test_b1_review_points import world_with_both
    from tests.test_crs_endpoint import _client

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    doc, _rc, _ai, _c = world_with_both()
    edit_rule_check_point(doc, lambda: _client(doc, "doc_std"), ENGINEER)
    got = files_of(doc, lambda: _client(doc))
    assert all(ENGINEER not in t for t in got.values())
    assert (
        question.ENGINEER_HIDDEN in got["page"]
        and question.ENGINEER_HIDDEN in got["team"]
    )
    assert not any(
        s in got["contractor"] for s in HIDDEN_SENTENCES
    )  # left out, counted apart, no sentence about documents
    assert f"1 {crs_completeness.REASON_NOT_SHOWN}" in got["contractor"]
    assert (
        ENGINEER in files_of(doc, lambda: _client(doc, "doc_std"))["contractor"]
    )  # the reader of the book: issued


@pytest.mark.usefixtures("temp_db")
def test_a_hidden_remove_or_keep_reason_says_what_the_engineer_did(monkeypatch):
    from app.config import settings
    from tests.test_b1_review_points import world_with_both
    from tests.test_crs_endpoint import _client

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    doc, _rc, _ai, _c = world_with_both()
    points = (
        _client(doc, "doc_std")
        .get(f"/api/reviews/papers/{doc}/points")
        .json()["points"]
    )
    ai = [p["id"] for p in points if p["id"].startswith("ai:")]
    for pid, state in zip(ai, ("remove", "keep"), strict=False):
        r = _client(doc, "doc_std").post(
            f"/api/reviews/papers/{doc}/points/decision",
            json={"point_id": pid, "state": state, "reason": ENGINEER},
        )
        assert r.status_code == 200, r.text
    page = _client(doc).get(f"/api/reviews/papers/{doc}/points").text
    assert ENGINEER not in page
    assert question.ENGINEER_REMOVED in page and question.ENGINEER_KEPT in page


def test_a_deleted_rule_book_is_not_available_to_any_viewer():
    # check of 2d3857f8 (lead): a deleted book's id stays on stored lines and rule-check rows; no one is allowed it, so its words are
    # hidden from every viewer, a reader of the whole library included (fail closed, counted)
    from app import review_points_service as svc

    everyone = {**CTX, "paper_document_id": PAPER, "readable": frozenset({PAPER, "doc-std"}), "everything": True,
                "documents": frozenset({PAPER, "doc-std"}), "book_of": {}}  # fmt: skip
    line = {
        "item_id": "R-9",
        "standard": "STD-77",
        "standard_document_id": "doc-deleted",
        "reasoning": "per STD-77",
    }
    assert rp.book_doc_of(line, everyone) == "doc-deleted" and rp.words_hidden(
        line, everyone
    )
    assert not rp.words_hidden(
        {**line, "standard_document_id": "doc-std"}, everyone
    )  # a held book he may read: shown
    assert svc.readability_proof(
        {}, None, ["doc-deleted"], everyone["readable"], [], True
    ) == (False, False)
    assert svc.readability_proof(
        {}, None, ["doc-std"], everyone["readable"], [], True
    ) == (True, True)
