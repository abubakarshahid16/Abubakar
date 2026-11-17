# ruff: noqa: F811  (the fixture `world` is imported from the general review tests)
"""Order 14, a senior engineer's read of a contract's CRS (items W-C3, W-C5, W-C6, W-C8, W-C9). INVENTED papers, words and models.

W-C6  no AI text is stored cut: the general review's comment (word limit), the rule review's reasoning (two "sentences", a split
      at "e.g.") and comment (40 words, 160 characters) were cut BEFORE the file with no mark, and the reader's view dropped words
      out of a sentence. The completeness check now checks the stored lines against the run's record and the shown reasoning
      against the stored one. A reply cut at the model's length limit is said in plain words and kept in the record.
W-C3  a general review's "Not reviewed" line is a status (Not reviewed: which part, why), never a question.
W-C5  sheet 1's count line and its not-checked line are true, from one count.
W-C8  one name for who raised a rule-check point and on which engine.
W-C9  a page an AI step named that code did not prove is never shown as the page.
"""

from __future__ import annotations

import json

from app import (
    agent_general_job,
    agent_review_schema,
    ai_engineering_check,
    ai_text_whole,
    crs_ai_actions,
    crs_ai_words,
    db,
    kind_words,
    review_points,
)
from app import agent_general_review as core
from app import agent_review_crs as crs_lines
from app import agent_review_two_reader as two
from app import agent_review_verdict as verdict
from app import crs_completeness as cc
from app import review_points_content as content
from tests.test_agent_general_review import (  # noqa: F401
    PAGES,
    Q_FORMS,
    GFake,
    build,
    by_part,
    full_fake,
    go,
    world,
)

LONG_COMMENT = (
    " ".join(f"word{n}" for n in range(1, 41))
    + " and the consequence for the schedule is unclear."
)
LONG_WHAT = (
    " ".join(f"part{n}" for n in range(1, 26)) + " so the closing step has no owner."
)


# ------------------------------------------------------------------------------------------------ W-C6: stored whole


def test_a_general_comment_longer_than_the_prompts_word_limit_is_stored_whole(world):
    assert len(LONG_COMMENT.split()) > 40

    def p5(_last):
        return {
            "comments": [
                {"quote": {"page": 3, "text": Q_FORMS}, "comment": LONG_COMMENT}
            ]
        }

    g, runner = build(world, GFake(p5=p5), items=[], project=())
    [note] = by_part(go(g, runner), 5)
    assert note["text"] == LONG_COMMENT
    agent_review_schema.ensure_schema()
    agent_general_job.store_lines(db.connect(), "run-w", g.lines)
    stored = (
        db.connect()
        .execute(
            "SELECT reason FROM agent_review_line WHERE item_id = ?", (note["item_id"],)
        )
        .fetchone()[0]
    )
    assert stored == LONG_COMMENT


def test_a_general_finding_longer_than_its_word_limit_is_stored_whole(world):
    from tests.test_agent_general_review import Q_ACTIONS

    def p3(_last):
        return {"findings": [{"kind": "open_action", "quote_a": {"page": 2, "text": Q_ACTIONS}, "quote_b": None,
                              "what": LONG_WHAT, "severity": "low"}]}  # fmt: skip

    g, runner = build(world, GFake(p3=p3), items=[], project=())
    [line] = by_part(go(g, runner), 3)
    assert line["text"] == LONG_WHAT


def test_the_rule_reviews_reasoning_and_the_second_readers_are_stored_whole():
    said = "The paper states the set pressure. The operating pressures (e.g. 4 barg and 1.3 barg) exceed 1 barg. So it applies."
    assert crs_lines.whole_reasoning(said) == said
    long = " ".join(["the second reader explains"] * 40)
    rec = two.second_answer({"reasoning": long}, ai=verdict.QUERY, reason_code="x", checks=verdict.QuoteCheck(False, False),
                            absent=False, model="m", usd=0.0)  # fmt: skip
    assert rec["reasoning"] == long


def test_a_reply_cut_at_its_length_limit_is_said_plainly_and_kept_marked_in_the_record(
    world,
):
    g, runner = build(world, full_fake(stop="max_tokens"))
    lines = go(g, runner)
    assert any(ai_text_whole.REPLY_CUT in ln["text"] for ln in lines)
    assert not any("stop_max_tokens" in ln["text"] for ln in lines)
    cut = [
        json.loads(r)
        for r in (world / "r1" / "trace.jsonl").read_text().splitlines()
        if '"answer_cut"' in r
    ]
    assert cut and all(r["cut_by_length_limit"] is True and r["text"] for r in cut)


# ------------------------------------------------------------------------------------------------ W-C6: the check sees a stored cut


def _store(run, lines):
    agent_review_schema.ensure_schema()
    with db.connect() as conn:
        for item, line in lines:
            conn.execute(
                "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, reason, line_json, decided_at)"
                " VALUES (?,?,?,?,?,?,'2026-01-01')",
                (
                    run,
                    item,
                    "Query for the engineer",
                    "Query",
                    line.get("text") or line.get("reasoning") or "",
                    json.dumps(line),
                ),
            )


def test_the_completeness_check_reports_a_line_stored_cut_and_restore_puts_the_whole_text_back(
    world, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", world)
    whole = "The sheet gives the set pressure. The margin (e.g. 10 per cent) is not shown, so it cannot be checked here."
    cut = "The sheet gives the set pressure. The margin (e.g."
    folder = world / "agent_reviews" / "run-c"
    (folder / "steps").mkdir(parents=True)
    (folder / "trace.jsonl").write_text(
        json.dumps(
            {"type": "item", "item_id": "S-1", "lead_answer": {"reasoning": whole}}
        )
        + "\n"
    )
    (folder / "steps" / "p5-w0.json").write_text(
        json.dumps({"text": json.dumps({"comments": [{"comment": LONG_COMMENT}]})})
    )
    general_cut = " ".join(LONG_COMMENT.split()[:40])
    _store("run-c", [("S-1", {"item_id": "S-1", "reasoning": cut}),
                     ("G-001", {"item_id": "G-001", "general": True, "part": 5, "text": general_cut}),
                     ("S-2", {"item_id": "S-2", "reasoning": "A whole answer."})])  # fmt: skip
    problems = ai_text_whole.problems("run-c")
    assert len(problems) == 2 and all(
        "stored cut before this file" in p for p in problems
    )
    assert ai_text_whole.restore(db.connect(), "run-c", folder) == 2
    assert ai_text_whole.problems("run-c") == []
    got = {
        r[0]: json.loads(r[1])
        for r in db.connect().execute(
            "SELECT item_id, line_json FROM agent_review_line"
        )
    }
    assert got["S-1"]["reasoning"] == whole and got["G-001"]["text"] == LONG_COMMENT


def test_a_run_without_a_stored_cut_reports_nothing(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", world)
    (world / "agent_reviews" / "run-d").mkdir(parents=True)
    (world / "agent_reviews" / "run-d" / "trace.jsonl").write_text(
        json.dumps(
            {"type": "item", "item_id": "S-1", "lead_answer": {"reasoning": "Whole."}}
        )
        + "\n"
    )
    _store("run-d", [("S-1", {"item_id": "S-1", "reasoning": "Whole."})])
    assert ai_text_whole.problems("run-d") == []


# ------------------------------------------------------------------------------------------------ W-C6: the reader's view of the reasoning


def test_the_reasoning_cell_keeps_every_word_of_a_sentence_and_marks_a_sentence_left_out():
    said = "No clause text was supplied, so the margin cannot be read. The sheet leaves the power blank."
    view = crs_ai_actions.reasoning_part(
        {"reasoning": said}, crs_ai_words.STATUS_QUERY, ""
    )
    assert (
        said in view
    )  # the old filter took "cannot be read" out of the middle of the first sentence
    coded = "The value is given. The reason code is not_met_value per the gate. The unit is bar."
    shown = ai_text_whole.plain_whole(coded)
    assert "The value is given." in shown and "The unit is bar." in shown
    assert ai_text_whole.LEFT_OUT.format(n=1) in shown
    assert ai_text_whole.reasoning_left_out(coded, shown) == 0


def test_the_check_counts_a_sentence_cut_from_the_reasoning_without_the_mark():
    said = "No clause text was supplied, so the margin cannot be read. The sheet leaves the power blank."
    old_view = crs_ai_words.plain(
        said
    )  # the older filter: words out of the middle of a sentence, no mark
    assert ai_text_whole.reasoning_left_out(said, old_view) == 1
    assert cc.words_left_out({"_line": {"reasoning": said}}, old_view) == 1
    assert (
        cc.words_left_out(
            {"_line": {"reasoning": said}}, ai_text_whole.plain_whole(said)
        )
        == 0
    )


# ------------------------------------------------------------------------------------------------ W-C3


def _ctx():
    return {"run_id": "r1", "paper_document_id": "doc_x", "book_of": {}, "readable": frozenset({"doc_x"}), "library": [],
            "everything": True, "documents": frozenset({"doc_x"})}  # fmt: skip


def test_a_general_not_reviewed_line_is_a_status_never_a_question():
    line = core.finalize_line({"part": 2, "verdict_class": core.CLASS_NOT_REVIEWED, "subkind": None, "document": "doc_x",
                               "text": core.NO_CHECKLIST, "item_id": "G-001", "text_source": "the model's words"})  # fmt: skip
    p = review_points.ai_point({**line, "general": True}, _ctx())
    assert (
        p["rank"] == 8
        and p["other_kind"] == crs_ai_words.KIND_NOT_REVIEWED
        and p["action"] is None
    )
    assert p["name"] == f"Not reviewed: the completeness checklist: {core.NO_CHECKLIST}"
    note = core.finalize_line({"part": 5, "verdict_class": core.CLASS_NOTE, "subkind": core.SUB_ENGINEERING, "document": "doc_x",
                               "text": "An invented note.", "item_id": "G-002"})  # fmt: skip
    assert review_points.ai_point({**note, "general": True}, _ctx())["rank"] != 8


# ------------------------------------------------------------------------------------------------ W-C5


def test_sheet_one_counts_reviewed_not_reviewed_and_not_checked_from_one_count():
    raw = [
        {"other_kind": crs_ai_words.KIND_NOT_REVIEWED},
        {"_book_missing": "Invented Book 7"},
        {},
        {},
    ]
    split = cc.review_split(raw)
    assert split == {"reviewed": 2, "not_reviewed": 1, "not_checked": 1}
    line = cc.team_statement(4, 3, split)
    assert line.startswith(
        "4 points in this review, 4 in this file, as 3 comments: 2 reviewed;"
    )
    assert (
        "1 not reviewed" in line
        and "1 not checked (rule book not held)" in line
        and "4 points reviewed" not in line
    )
    assert (
        cc.team_statement(2, 2, {"reviewed": 2, "not_reviewed": 0, "not_checked": 0})
        == "2 points reviewed, 2 in this file, as 2 comments"
    )


def test_the_not_checked_sentence_is_about_the_rule_check_never_that_nothing_was_checked():
    old = "No widget checklist is held, so no point of this widget was checked; that does not mean the widget is acceptable."
    assert "no point of this widget was checked" not in kind_words.current_not_checked(
        old
    )
    assert kind_words.current_not_checked(old).startswith(
        "No widget checklist is held, so the rule check compared no point"
    )


# ------------------------------------------------------------------------------------------------ W-C8


def test_one_name_for_who_raised_a_rule_check_point():
    assert (
        content.reader_words(content.checked_by("ai_engineering_check"))
        == "Rule check: AI engineering check (an AI step)"
    )
    assert (
        content.reader_words(content.checked_by("clause_review"))
        == "Rule check: clause review (an AI step)"
    )
    assert (
        content.reader_words(content.checked_by("datasheet_check"))
        == "Rule check: datasheet checklist (code)"
    )
    assert content.rule_check_engine("Claude") == "code, with its AI steps on Claude"


# ------------------------------------------------------------------------------------------------ W-C9


def test_a_page_an_ai_step_named_is_shown_only_when_code_proved_it():
    page = "Article 9. The order of the invented documents is listed here."
    ai = {"origin": ai_engineering_check.ORIGIN}
    assert not ai_engineering_check.page_verified(
        {**ai, "contractor_section": "A list of the documents (sub-article 9.9)"}, page
    )
    assert ai_engineering_check.page_verified(
        {**ai, "contractor_section": "The order of the invented documents"}, page
    )
    assert ai_engineering_check.page_verified(
        {**ai, "contractor_evidence_text": "Article 9."}, page
    )
    assert ai_engineering_check.page_verified({"origin": "datasheet_check"}, "")
