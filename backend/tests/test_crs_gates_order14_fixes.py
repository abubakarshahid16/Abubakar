"""The three CRS gates that failed on a real review (order 14): G3 (a question shown as "nothing to correct"), G5 (a firm "not met"
resting on one reader's word that the paper is silent) and G7 (the run file drawn again without its kept meta listed no book missing).
Each test fails without its fix. Invented data only: no client paper, no real book text, invented book names (STD-A-100 ...)."""

from __future__ import annotations

import sqlite3

from app import agent_review_verdict as v
from app import agent_review_wording as w
from app import crs_ai_words as words
from app import crs_comments
from app import review_points as rp
from app.review_points_service import run_meta
from tests.test_agent_review_routes import (
    client,  # noqa: F401 - fixture: a finished AI run on an invented paper
)
from tests.test_crs_gates import Row, g

# ------------------------------------------------------------------------------------------------ G5: silence needs a proof


def _absent_line(**extra) -> dict:
    """A stored AI line as an older run wrote it: the reader said the paper does not state the field (Fail, reason absent), code
    could not prove the absence, so the gate made it a Query; the stored class is the old 'AI thinks: not met'."""
    return {
        "source": "rule", "item_id": "R-1", "verdict": "Query", "ai_verdict": "Fail", "reason_code": "absent",
        "decided_by": "engineer", "why": "not shown on the sheet; code cannot prove an absence",
        "verdict_class": w.CLASS_OPINION, "verdict_label": w.THINKS_NOT_MET, "paper_quote": "Inlet loss",
        "quotes_checked": {"paper": True, "clause": True, "both": True, "clause_strong": True},
        "standard": "STD-A-100", "clause": "4.1", **extra,
    }  # fmt: skip


def test_one_readers_word_that_the_paper_is_silent_is_a_query_never_a_firm_not_met():
    got = w.classify(_absent_line())
    assert (
        got["verdict_class"] == w.CLASS_QUERY and got["verdict_label"] == w.WORD_QUERY
    )
    assert "cannot prove an absence" in got["not_proven_reason"]
    # every silence code of the app, not only "absent"
    for code in v.SILENCE_CODES:
        assert (
            w.classify(_absent_line(reason_code=code))["verdict_class"] == w.CLASS_QUERY
        )


def test_a_not_met_on_a_stated_value_and_a_proven_absence_keep_their_class():
    stated = _absent_line(
        reason_code="not_met", why="the code compared no value on this line"
    )
    assert (
        w.classify(stated)["verdict_class"] == w.CLASS_OPINION
    )  # one reader's not-met on a value it quoted
    proven = _absent_line(verdict="Fail", decided_by=v.BY_ABSENCE)
    assert w.classify(proven)["verdict_class"] == w.CLASS_PROVEN
    proof = _absent_line(absence_check={"proven": True})
    assert not w.silence_unproven(proof) and w.silence_unproven(_absent_line())


def test_an_older_runs_stored_opinion_is_read_as_todays_query_and_never_raised():
    got = w.read_time(_absent_line())
    assert (
        got["verdict_class"] == w.CLASS_QUERY and got["verdict_label"] == w.WORD_QUERY
    )
    assert (
        rp.rank_of_ai_line(got)[0] == 4
    )  # a Question on the page and in both files, not "Not met, one reader"
    assert (
        rp.rank_of_ai_line(_absent_line())[0] == 3
    )  # the stored line as it was (what the CRS showed)
    # narrowing only: a stored Query is never made an opinion, a proven line is never touched
    query = _absent_line(verdict_class=w.CLASS_QUERY, verdict_label=w.WORD_QUERY, reason_code="not_met",
                         why="the code compared no value on this line")  # fmt: skip
    assert w.read_time(query)["verdict_class"] == w.CLASS_QUERY
    proven = _absent_line(
        verdict="Fail",
        decided_by=v.BY_ABSENCE,
        verdict_class=w.CLASS_PROVEN,
        verdict_label="Fail",
    )
    assert w.read_time(proven)["verdict_class"] == w.CLASS_PROVEN
    # an AI "met" is never narrowed at read time: as a Query it would become a new comment row of an older run's CRS
    met = _absent_line(ai_verdict="Pass", reason_code="pass_field_unknown", verdict_label=w.THINKS_MET,
                       why="code could not confirm this AI 'met'")  # fmt: skip
    assert (
        w.classify(met)["verdict_class"] == w.CLASS_QUERY
        and w.read_time(met)["verdict_class"] == w.CLASS_OPINION
    )


def test_g5_no_longer_fails_the_rows_once_they_are_questions():
    line = w.read_time(_absent_line())
    row = Row("R1", rank=rp.rank_of_ai_line(line)[0], reason="absent", paper_value="Inlet loss", value_verified=True,
              book="STD-A-100", clause="4.1")  # fmt: skip
    assert g.g5_firm([row]).failed == []
    old = Row(
        "R1",
        rank=3,
        reason="absent",
        paper_value="Inlet loss",
        value_verified=True,
        book="STD-A-100",
        clause="4.1",
    )
    assert g.g5_firm([old]).failed == [
        ("R1", "absent, not proven by code")
    ]  # the gate itself is unchanged


# ------------------------------------------------------------------------------------------------ G3: the CRS's own noise words


def test_the_crs_drops_every_nothing_to_do_phrase_the_gate_fails():
    for said, kept in (
        (
            "No action needed; keep the stamp requirement.",
            "Keep the stamp requirement.",
        ),
        ("No change required. The value is on page 2.", "The value is on page 2."),
        ("Nothing to correct.", ""),
        ("Page 3 is unreadable.", "Page 3 is"),
    ):
        got = words.drop_noise(said)
        assert got == kept and g.noise_in(got) is None, said
    assert (
        g.NOISE_PATTERNS[: len(words.NOTHING_TO_DO_PATTERNS)]
        == words.NOTHING_TO_DO_PATTERNS
    )  # one home


# ------------------------------------------------------------------------------------------------ G3: a doubted "met" is a question


def _met_line(**extra) -> dict:
    return {
        "source": "rule", "verdict": "Query", "ai_verdict": "Pass", "reason_code": "pass_field_unknown",
        "paper_quote": "Lever: required", "quotes_checked": {"paper": True, "clause": True}, **extra,
    }  # fmt: skip


def test_met_question_why_names_each_recorded_doubt_about_the_paper():
    assert (
        crs_comments.met_question_why(_met_line()) is None
    )  # the guard's objection alone: nothing open about the paper
    assert (
        crs_comments.met_question_why(_met_line(second_opinion={"agree": False}))
        == v.DISAGREE_WHY
    )
    assert (
        crs_comments.met_question_why(_met_line(quotes_checked={"paper": False}))
        == v.UNVERIFIED_PAPER_WHY
    )
    assert (
        crs_comments.met_question_why(_met_line(not_mentioned_hold=True))
        == v.NOT_STATED_WHY
    )
    assert (
        crs_comments.met_question_why(_met_line(paper_quote="Lever: By Contractor"))
        == v.DEFERRED_WHY
    )
    assert crs_comments.met_question_why(_met_line(ai_verdict="Fail")) is None


def test_tick_only_still_ticks_only_a_met_whose_one_doubt_is_the_clause_quote():
    def point(**extra):
        return {
            "_line": _met_line(
                reason_code="met",
                quotes_checked={"paper": True, "clause": False},
                **extra,
            )
        }

    assert crs_comments.tick_only(point())
    assert not crs_comments.tick_only(point(second_opinion={"agree": False}))
    assert not crs_comments.tick_only(point(not_mentioned_hold=True))
    assert not crs_comments.tick_only(
        {"_line": _met_line()}
    )  # a pass_ reason is never ticked (R94)


def test_g3_passes_a_pass_reason_question_whose_line_records_a_doubt_and_still_fails_one_without():
    cells = ("Lever", "Contractor to confirm the lever against STD-A-100 clause 4.2.")
    doubted = Row("C1", rank=4, reason="pass_field_unknown", cells=cells,
                  open_question=g._open_question(_met_line(second_opinion={"agree": False})))  # fmt: skip
    bare = Row(
        "C2",
        rank=4,
        reason="pass_field_unknown",
        cells=cells,
        open_question=g._open_question(_met_line()),
    )
    got = g.g3_noise([doubted, bare])
    assert got.failed == [("C2", "pass reason")]
    assert g._open_question({}) == ""


# ------------------------------------------------------------------------------------------------ G7: books not held from the record


def _conn_with_missing(run_id: str, names: list[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE agent_review_missing_book (run_id TEXT, name TEXT, why TEXT, PRIMARY KEY (run_id, name))"
    )
    conn.executemany(
        "INSERT INTO agent_review_missing_book VALUES (?,?,?)",
        [(run_id, n, "not in the library") for n in names],
    )
    return conn


def test_a_run_file_drawn_without_its_kept_meta_still_lists_every_book_not_held(
    tmp_path,
):
    conn = _conn_with_missing("run-1", ["STD-X-1", "STD-Y-2"])
    meta = run_meta(
        conn, "run-1", "doc_paper", tmp_path
    )  # no crs-meta.json in the folder
    assert meta["paper"] == "doc_paper" and meta["run_id"] == "run-1"
    assert [b["rule_book"] for b in meta["rule_labels"]["missing_rule_books"]] == [
        "STD-X-1",
        "STD-Y-2",
    ]
    (tmp_path / "crs-meta.json").write_text(
        '{"rule_labels": {"equipment": "valve", "missing_rule_books": []}}'
    )
    meta = run_meta(conn, "run-1", "doc_paper", tmp_path)
    assert (
        meta["rule_labels"]["equipment"] == "valve"
        and len(meta["rule_labels"]["missing_rule_books"]) == 2
    )
    # a run with no record keeps the file's own list
    (tmp_path / "crs-meta.json").write_text(
        '{"rule_labels": {"missing_rule_books": [{"rule_book": "STD-Z-3"}]}}'
    )
    assert run_meta(conn, "run-2", "doc_paper", tmp_path)["rule_labels"][
        "missing_rule_books"
    ] == [{"rule_book": "STD-Z-3"}]
    (tmp_path / "crs-meta.json").write_text("not json")
    assert run_meta(conn, "run-2", "doc_paper", tmp_path) == {
        "paper": "doc_paper",
        "run_id": "run-2",
    }


def test_a_line_whose_book_the_run_does_not_hold_shows_the_book_as_not_held_and_no_clause():
    from app.agent_review_crs import against

    missing = [{"rule_book": "STD-Q-9", "why": "not in the library"}]
    lines = [
        {
            "source": "skill",
            "standard": "STD Q-9",
            "clause": "6.5",
            "clause_quote": "Loads shall be stated.",
        },
        {
            "source": "code",
            "standard": "STD-Q-9",
            "clause": "2.1",
            "standard_document_id": "doc_q",
        },  # links a held document
        {"source": "rule", "standard": "STD-A-100", "clause": "4.1"},
    ]
    marked = words.mark_not_held(lines, missing)
    assert [bool(ln.get(words.NOT_HELD_KEY)) for ln in marked] == [True, False, False]
    assert (
        against(marked[0]) == "STD Q-9 (rule book not held)"
        and against(marked[2]) == "STD-A-100 clause 4.1"
    )
    assert words.mark_not_held(marked, missing) == marked  # idempotent
    row = g._line_row("R1", marked[0], cells=("STD Q-9 (rule book not held)",))
    assert (row.clause, row.shows_rule_words, row.quotes) == ("", False, ())
    assert (
        g.g7_missing([row], ["STD-Q-9"], [], ["STD-Q-9 (not in the library)"]).failed
        == []
    )
    old = g._line_row(
        "R1", lines[0], cells=("STD Q-9 clause 6.5",)
    )  # the line as the file showed it before
    assert g.g7_missing([old], ["STD-Q-9"], [], ["STD-Q-9"]).failed == [
        ("R1", "rule words shown for a book not held")
    ]


# ------------------------------------------------------------------------------------------------ G7 through the BUILT run file


NOT_HELD_META = {"paper": "Paper A", "run_id": "run-1", "date": "2026-11-17", "header": {"project": "Project Q"},
                 "rule_labels": {"missing_rule_books": [{"rule_book": "STD-Q-9", "why": "not in the library"}]}}  # fmt: skip
Q_QUOTE, Q_RULE = (
    "Nozzle loads shall be listed for every branch.",
    "Nozzle loads shall be stated on the sheet.",
)


def _built(lines: list[dict], copy: str) -> str:
    """Every cell of the run file the app's own builder draws, as one text."""
    import io

    import openpyxl

    from app import crs_ai_workbook, crs_layout

    data = crs_layout.build_layout_crs(
        crs_ai_workbook.layout_view(lines, NOT_HELD_META, copy)
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    return "\n".join(
        str(c)
        for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for c in row
        if c is not None
    )


def _not_held_lines() -> list[dict]:
    from tests.test_o14_b_crs_writer import mk

    ask = mk("R-1", field="Nozzle load", standard="STD-Q-9", clause="6.5", clause_quote=Q_QUOTE, requirement=Q_RULE,
             quotes_checked={"paper": True, "clause": False})  # fmt: skip
    proven = mk("R-2", "Fail", "Fail", field="Seal flush", standard="STD-Q-9", clause="7.2", reason_code=None,
                compare={"decided": True, "verdict": "does_not_meet"})  # fmt: skip
    held = mk("R-3", "Fail", "Fail", field="Set pressure", reason_code=None, standard_document_id="doc_1",
              compare={"decided": True, "verdict": "does_not_meet"})  # fmt: skip
    return [ask, proven, held]


def test_the_built_team_file_shows_a_book_not_held_and_none_of_its_clause_or_rule_words():
    team = _built(_not_held_lines(), "internal")
    assert "STD-Q-9 (rule book not held)" in team
    assert "clause 6.5" not in team and "6.5" not in team.replace(
        "STD-Q-9 (rule book not held)", ""
    )
    assert (
        Q_QUOTE not in team
    )  # the Evidence sheet's clause quote (`shown_clause_quote`)
    assert (
        Q_RULE not in team
    )  # the stored rule text is never printed for a book not held


def test_a_proven_line_on_a_book_not_held_is_an_engineer_question_and_never_reaches_the_contractor():
    lines = _not_held_lines()
    team = _built(lines, "internal")
    assert "STD-Q-9 clause 7.2" in team  # a proven line keeps its clause
    assert (
        words.PROVEN_NOT_HELD_WHY in team and "Engineer to check the rule" in team
    )  # an engineer question
    contractor = _built(lines, "contractor")
    assert (
        "STD-Q-9" not in contractor and "not held" not in contractor
    )  # never a firm contractor row, never the internal mark
    assert (
        "STD-1 clause 4.1" in contractor
    )  # the proven Fail on a held book is still issued
    got = words.mark_not_held(
        [lines[1]], NOT_HELD_META["rule_labels"]["missing_rule_books"]
    )[0]
    assert (
        got["verdict"] == "Query"
        and got["verdict_class"] == w.CLASS_QUERY
        and words.NOT_HELD_KEY not in got
    )


def test_a_calculator_line_naming_a_part_of_a_book_not_held_is_that_book_not_held():
    missing = [{"rule_book": "API-610"}]
    calc = {
        "source": "code",
        "standard": "API 610 datasheet annex",
        "clause": "A.1",
        "verdict": "Query",
    }
    assert (
        words.mark_not_held([calc], missing)[0][words.NOT_HELD_KEY] is True
    )  # the annex is part of the book: not held
    proven = words.mark_not_held([{**calc, "verdict": "Fail"}], missing)[0]
    assert (
        proven["verdict"] == "Query" and proven["clause"] == "A.1"
    )  # code's verdict on a book not held: the engineer checks it
    other = words.mark_not_held(
        [{**calc, "standard": "API 682 datasheet annex"}], missing
    )[0]
    assert (
        words.NOT_HELD_KEY not in other
    )  # another book of the family is not that book


def test_g7_still_fails_a_not_held_line_whose_stored_rule_text_the_file_prints():
    line = {
        "source": "rule",
        "standard": "STD-Q-9",
        "clause": "6.5",
        "requirement": Q_RULE,
        words.NOT_HELD_KEY: True,
    }
    shown = g._line_row(
        "R1",
        line,
        cells=(f'The stored rule text, not found in the book by code: "{Q_RULE}".',),
    )
    assert g.g7_missing([shown], ["STD-Q-9"], [], ["STD-Q-9"]).failed == [
        ("R1", "rule words shown for a book not held")
    ]
    quiet = g._line_row("R1", line, cells=("STD-Q-9 (rule book not held)",))
    assert g.g7_missing([quiet], ["STD-Q-9"], [], ["STD-Q-9"]).failed == []


# ------------------------------------------------------------------------------------------------ the lines tab reads what the CRS reads


def _stored_row(line: dict) -> dict:
    import json

    return {"item_id": line["item_id"], "verdict_class": line["verdict_class"], "word": "AI thinks: not met", "page": 1,
            "clause": "4.1", "rule_book": "STD-A-100", "reason": "stored", "rule_tier": "AI approved", "part": None,
            "text_source": None, "line_json": json.dumps(line)}  # fmt: skip


def test_the_lines_tab_shows_an_older_runs_unproven_silence_as_the_query_the_crs_shows():
    from app.api import agent_review as api

    got = api._read_line(_stored_row(_absent_line(rule_tier="AI approved")))
    assert got.verdict_class == w.CLASS_QUERY and got.word == "Query"


def test_the_query_counts_read_the_lines_as_the_crs_reads_them():
    """The groups count the READER's own Queries only (its answer was "Query"); an older run's AI "not met" read as a Query today is a
    Query of the gate, not of the reader, so it is in no group (the page and the first sheet count the same way)."""
    import json

    from app.agent_review_local import AI_QUERY_WHY
    from app.api import agent_review as api

    conn = _conn_with_missing("run-1", [])
    conn.execute(
        "CREATE TABLE agent_review_line (run_id TEXT, item_id TEXT, verdict_class TEXT, word TEXT, line_json TEXT)"
    )
    asked = _absent_line(
        item_id="R-2",
        ai_verdict="Query",
        why=AI_QUERY_WHY,
        verdict_class=w.CLASS_QUERY,
        verdict_label=w.WORD_QUERY,
    )
    for ln in (_absent_line(), asked):
        conn.execute("INSERT INTO agent_review_line VALUES (?,?,?,?,?)",
                     ("run-1", ln["item_id"], ln["verdict_class"], ln["verdict_label"], json.dumps(ln)))  # fmt: skip
    groups, no_answer = api._query_groups(conn, "run-1")
    assert (
        groups.contractor_silent + groups.engineer_drawing + groups.could_not_decide,
        no_answer,
    ) == (1, 0)


def test_the_page_and_the_lines_tab_read_a_proven_line_on_a_book_not_held_as_the_crs_does(
    client,  # noqa: F811 - the fixture
):
    import json

    from app import db, review_points
    from tests.test_agent_review_routes import finished_run

    run_id = finished_run(client)
    conn = db.connect()
    row = conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
        (run_id,),
    ).fetchone()
    line = {**json.loads(row["line_json"]), "verdict": "Fail", "ai_verdict": "Fail", "decided_by": v.BY_CODE, "error": None,
            "verdict_class": w.CLASS_PROVEN, "verdict_label": "Fail", "standard": "STD-Q-9", "standard_document_id": None,
            "compare": {"decided": True, "verdict": "does_not_meet"}}  # fmt: skip
    conn.execute("UPDATE agent_review_line SET verdict_class = ?, word = 'Fail', line_json = ? WHERE run_id = ? AND item_id = ?",
                 (w.CLASS_PROVEN, json.dumps(line), run_id, row["item_id"]))  # fmt: skip
    conn.execute(
        "INSERT INTO agent_review_missing_book (run_id, name, why) VALUES (?, 'STD-Q-9', 'not in the library')",
        (run_id,),
    )
    conn.commit()
    points, _held = review_points.ai_points_of_run(
        conn, run_id, "doc_paper", frozenset()
    )
    mine = [
        p for p in points if (p.get("_line") or {}).get("item_id") == row["item_id"]
    ]
    assert (
        mine and mine[0]["rank"] == 4
    )  # a Question on the page, as in the run file: never "Not met, proven by code"
    listed = client.get(f"/api/reviews/runs/{run_id}/agent/lines").json()["lines"]
    assert [x["verdict_class"] for x in listed if x["item_id"] == row["item_id"]] == [
        w.CLASS_QUERY
    ]
