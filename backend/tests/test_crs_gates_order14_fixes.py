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
