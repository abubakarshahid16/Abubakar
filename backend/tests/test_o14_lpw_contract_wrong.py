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
        json.dumps(
            {
                "text": json.dumps(
                    {"comments": [{"quote": QUOTE, "comment": LONG_COMMENT}]}
                )
            }
        )
    )
    general_cut = " ".join(LONG_COMMENT.split()[:40])
    _store("run-c", [("S-1", {"item_id": "S-1", "reasoning": cut}),
                     ("G-001", {"item_id": "G-001", "general": True, "part": 5, "text": general_cut, "quote_a": QUOTE}),
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
    reasons = dict(
        db.connect().execute("SELECT item_id, reason FROM agent_review_line").fetchall()
    )
    assert (
        reasons["S-1"] == cut and reasons["G-001"] == LONG_COMMENT
    )  # a rule row's reason column is never rewritten
    assert (
        ai_text_whole.restore(db.connect(), "run-c", folder) == 0
    )  # a second pass changes nothing


QUOTE = {"page": 3, "text": "Appendix Z lists the forms."}


def _record(world, run, trace=(), general=()):
    folder = world / "agent_reviews" / run
    (folder / "steps").mkdir(parents=True)
    (folder / "trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in trace))
    (folder / "steps" / "p5-w0.json").write_text(
        json.dumps({"text": json.dumps({"comments": list(general)})})
    )
    return folder


def test_two_whole_general_comments_that_share_their_first_words_are_neither_cut_nor_rewritten(
    world, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", world)
    one = "State where the invented forms are held and who keeps them up to date."
    two_ = "State where the invented forms are held, and give the revision of each."
    other = {"page": 2, "text": "Actions are recorded without owner or date."}
    folder = _record(
        world,
        "run-s",
        general=[{"quote": QUOTE, "comment": one}, {"quote": other, "comment": two_}],
    )
    _store("run-s", [("G-001", {"item_id": "G-001", "general": True, "part": 5, "text": one, "quote_a": QUOTE}),
                     ("G-002", {"item_id": "G-002", "general": True, "part": 5, "text": two_, "quote_a": other})])  # fmt: skip
    assert ai_text_whole.problems("run-s") == []
    assert ai_text_whole.restore(db.connect(), "run-s", folder) == 0
    # a line stored cut gets back ITS OWN words, never the longer words of another line that start the same way
    mine = "State where the invented forms are held and name the owner."
    longer = "State where the invented forms are held, and give the revision, the date and the owner of each form."
    third = {"page": 1, "text": "See Table 9 for the schedule."}
    folder = _record(
        world,
        "run-t",
        general=[
            {"quote": QUOTE, "comment": mine},
            {"quote": third, "comment": longer},
        ],
    )
    _store("run-t", [("G-001", {"item_id": "G-001", "general": True, "part": 5, "text": " ".join(mine.split()[:8]), "quote_a": QUOTE}),
                     ("G-002", {"item_id": "G-002", "general": True, "part": 5, "text": longer, "quote_a": third})])  # fmt: skip
    assert len(ai_text_whole.problems("run-t")) == 1
    assert ai_text_whole.restore(db.connect(), "run-t", folder) == 1
    got = dict(
        db.connect()
        .execute("SELECT item_id, reason FROM agent_review_line WHERE run_id = 'run-t'")
        .fetchall()
    )
    assert got == {"G-001": mine, "G-002": longer}
    assert ai_text_whole.restore(db.connect(), "run-t", folder) == 0


def test_a_whole_lead_reasoning_is_never_called_cut_by_a_longer_second_readers(
    world, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", world)
    stored = "The set pressure is stated."  # the line's own words (here: not the first reader's recorded answer)
    trace = [{"type": "item", "item_id": "S-1", "lead_answer": {"reasoning": "Other invented words entirely."},
              "second_opinion_answer": {"reasoning": stored + " The margin is not."}}]  # fmt: skip
    folder = _record(world, "run-l", trace=trace)
    _store("run-l", [("S-1", {"item_id": "S-1", "reasoning": stored})])
    assert ai_text_whole.problems("run-l") == []
    assert ai_text_whole.restore(db.connect(), "run-l", folder) == 0


def test_a_run_that_keeps_no_record_is_said_unchecked(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", world)
    _store("run-n", [("S-1", {"item_id": "S-1", "reasoning": "Whole."})])
    got = ai_text_whole.check("run-n")
    assert got["problems"] == [] and got["unchecked"] == ai_text_whole.NOT_CHECKED
    report = {"ok": True, "stored_text_unchecked": got["unchecked"]}
    assert ai_text_whole.NOT_CHECKED in cc.sentence_of(report)


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


def test_the_reasoning_cell_keeps_every_word_and_replaces_only_internal_codes_in_place():
    said = "No clause text was supplied, so the margin cannot be read. The sheet leaves the power blank."
    view = crs_ai_actions.reasoning_part(
        {"reasoning": said}, crs_ai_words.STATUS_QUERY, ""
    )
    assert (
        said in view
    )  # the old filter took "cannot be read" out of the middle of the first sentence
    plain_words = "The coupling guard is brass, e.g. for a zone with a gate valve, i.e. non-sparking. The tier is not stated."
    assert (
        ai_text_whole.plain_whole(plain_words) == plain_words
    )  # a plain word is never a reason to leave anything out
    coded = "Line S-EQ-24 says the value is given. The unit is bar."
    shown = ai_text_whole.plain_whole(coded)
    assert (
        shown
        == f"Line {ai_text_whole.ID_MARK} says the value is given. The unit is bar."
    )
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
        "4 points in this review, 4 in this file, as 3 comments: 2 raised as a finding or a question"
    )
    assert (
        "1 not reviewed" in line
        and "1 not checked (rule book not held)" in line
        and "4 points reviewed" not in line
    )
    assert (
        "reviewed"
        not in cc.team_statement(
            2, 2, {"reviewed": 2, "not_reviewed": 0, "not_checked": 0}
        ).split(":")[0]
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
    by_ai = content.value_read_by_ai({"_fact": {"extraction_method": "vision"}})
    assert content.reader_words(content.checked_by("datasheet_check"), by_ai) == (
        "Rule check: datasheet checklist (code; value read by an AI reader)"
    )
    assert not content.value_read_by_ai({"_fact": {"extraction_method": "geometry"}})


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


def test_a_page_the_ai_named_is_printed_with_its_note_never_as_the_page():
    from app import crs_comments

    assert crs_comments.point_page_words(
        {"page": 3, "page_note": review_points.AI_NAMED_PAGE}
    ) == ("3 (named by the AI, not proven by code)")
    assert crs_comments.comment_page_words(
        {
            "pages": [2, 3],
            "page_hints": [3],
            "page_notes": {3: review_points.AI_NAMED_PAGE},
        }
    ) == ("2, 3 (named by the AI, not proven by code)")


# ------------------------------------------------------------------------------------------------ the AI's ask and the calculator's reason


def test_the_ais_ask_and_the_calculators_reason_are_whole():
    from app import agent_review_calculator as calc

    ask = "Give the set pressure basis, e.g. the relieving case. Then state the margin used for the invented valve."
    assert crs_lines.ai_ask({"comment": ask}) == ask
    long = " ".join(["the stated value and the limit use different bases"] * 10)
    import pytest

    mp = pytest.MonkeyPatch()
    mp.setattr(
        calc.comparison,
        "compare",
        lambda *a, **k: {"status": "NEEDS_ENGINEER_REVIEW", "rationale": long},
    )
    try:
        out = calc.numeric_line({"id": "S-1", "field": "Set pressure"}, {"id": "q1", "text": "x"},
                                {"field_value": "5", "unit": "bar", "page": 1}, submittal_facts=[],
                                page_text="Set pressure 5 bar", clause_quote=None, clause_text=None)  # fmt: skip
    finally:
        mp.undo()
    assert long in out["why"]


# ------------------------------------------------------------------------------------------------ the restore script


def _script(argv):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "restore_whole_ai_text.py"
    spec = importlib.util.spec_from_file_location("lpw_restore_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(argv)


def _script_world(world):
    from app.config import settings

    whole = (
        "The sheet gives the set pressure. The margin (e.g. 10 per cent) is not shown."
    )
    _record(
        world,
        "run-x",
        trace=[{"type": "item", "item_id": "S-1", "lead_answer": {"reasoning": whole}}],
    )
    _store(
        "run-x",
        [
            (
                "S-1",
                {
                    "item_id": "S-1",
                    "reasoning": "The sheet gives the set pressure. The margin (e.g.",
                },
            )
        ],
    )
    return settings.db_path, whole


def _reasoning():
    return json.loads(
        db.connect()
        .execute("SELECT line_json FROM agent_review_line WHERE item_id = 'S-1'")
        .fetchone()[0]
    )["reasoning"]


def test_the_script_counts_only_by_default_and_a_second_pass_changes_nothing(
    world, capsys
):
    path, whole = _script_world(world)
    assert (
        _script(["--db", str(path), "run-x"]) == 0 and _reasoning() != whole
    )  # dry run: nothing written
    assert json.loads(capsys.readouterr().out)["cut_before"] == 1
    assert (
        _script(["--db", str(path), "--apply", "run-x"]) == 0 and _reasoning() == whole
    )
    assert json.loads(capsys.readouterr().out)["runs"]["run-x"]["lines_restored"] == 1
    assert _script(["--db", str(path), "--apply", "run-x"]) == 0
    assert json.loads(capsys.readouterr().out)["runs"]["run-x"]["lines_restored"] == 0


def test_the_script_refuses_a_live_database_without_live_and_goes_through_the_guard_with_it(
    world, monkeypatch, capsys
):
    import pytest

    from app import live_guard

    path, whole = _script_world(world)
    monkeypatch.setattr(live_guard, "is_live_shaped", lambda _p: True)
    with pytest.raises(SystemExit):
        _script(["--db", str(path), "--apply", "run-x"])
    assert _reasoning() != whole
    asked = []

    class Clearance:
        backup_path = "invented-backup"

    def cleared(
        target, **kw
    ):  # the invented guard: records the ask, and the process is then cleared to write (as the real one does)
        asked.append(kw["reason"])
        monkeypatch.setattr(live_guard, "is_live_shaped", lambda _p: False)
        return Clearance()

    monkeypatch.setattr(live_guard, "prepare_live_write", cleared)
    assert _script(["--db", str(path), "--live", "run-x"]) == 0
    assert asked and _reasoning() == whole
    assert json.loads(capsys.readouterr().out)["rollback_point"] == "invented-backup"


# ------------------------------------------------------------------------------------------------ a text dropped entirely


def test_a_row_that_holds_only_its_kind_while_its_line_holds_words_is_named():
    words = "The invented procedure names no owner for the closing step of each action."
    general = {"general": True, "item_id": "G-007", "text": words}
    by_no = {
        1: {"_line": general},  # the row holds only its kind: named
        2: {"_line": {**general, "item_id": "G-008"}},  # the row holds the words: fine
        3: {
            "_line": {"item_id": "S-1", "reasoning": words}
        },  # a rule line: its reasoning has its own check
        4: {
            "_line": {**general, "item_id": "G-009", "text": ""}
        },  # words hidden from this viewer: nothing to show
    }
    rows = [
        [
            1,
            "Question",
            "A point of the AI review",
            "Engineer to check the item.",
            None,
        ],
        [
            2,
            "Question",
            "A point of the AI review",
            f'the AI reviewer\'s words, not proven by code: "{words}"',
            None,
        ],
        [3, "Question", "Closing step", "Engineer to check the item.", None],
        [
            4,
            "Question",
            "A point of the AI review",
            "Engineer to check the item.",
            None,
        ],
    ]
    assert cc.words_dropped(rows, by_no) == [
        "row 1: the words of the AI line G-007 are not in the file (the row holds only its kind)"
    ]
