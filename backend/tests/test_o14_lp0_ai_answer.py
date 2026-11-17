"""Owner's item LP0 (17 Nov 2026, order 14): "Show the AI's own answer instead of a Query: 'Pass / Fail (AI, rule not approved, engineer
to confirm)' with standard, clause, page and quote. 'Does not apply (AI, engineer to confirm)' goes in a separate tick-to-confirm section.
Plain Pass and Fail only for code-proven rows. Do not count AI rows as decisions in the score."

Every check reads the route as served or the file as built (the page's points, the paper's team and contractor files, the AI run's own
file, the answer scorer reading the built file back). Invented values only; no model, no network."""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app import agent_review_ai_answer as A
from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app import crs_completeness, crs_one
from app.agent_review_verdict import FAIL, PASS
from app.config import settings
from tests.test_agent_review_crs import META, NO, OK, SK, mk
from tests.test_b1_review_points import ai_run, points_of
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _submittal,
    temp_db,
)
from tests.test_k4_one_crs import rows_after, scope_all

FAIL_NOT_APPROVED = "Fail (AI, rule not approved, engineer to confirm)"
PASS_NOT_APPROVED = "Pass (AI, rule not approved, engineer to confirm)"


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def _lines() -> list[dict]:
    return [
        mk("R-1", "Fail", "Fail", field="Field Proven"),  # code compared the value: plain Fail
        mk("R-2", "Query", "Fail", reason_code="not_met", why="second reader not asked", field="Field Opinion"),
        # the reader says the sheet does not state it; nothing proved that: a question that HID the AI's "not met" before LP0
        mk("R-3", "Query", "Fail", reason_code="absent", why="not shown on the sheet; code cannot prove an absence",
           field="Field Silent", quotes_checked={"paper": False, "clause": True}),
        mk("R-4", "Pass", "Pass", item=NO, field="Field Unapproved"),  # a rule not yet approved: the AI's "met"
        mk("R-5", "Query", None, field="Field Asked"),  # the reader gave no answer: a plain question
        mk("R-6", "Query", None, reason_code="not_applicable", field="Field Na"),  # an unproven "does not apply"
    ]  # fmt: skip


def _world():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    run_id = ai_run(doc, _lines())
    client = _client(doc, "doc_std")
    by_item = {p["id"].rsplit(":", 1)[1]: p for p in points_of(client, doc)["points"]}
    return doc, client, run_id, by_item


# ------------------------------------------------------------------------------------------------ the one home (pure)


def test_the_label_is_the_owners_words_and_only_for_a_line_code_did_not_prove():
    got = {ln["item_id"]: A.label(ln) for ln in _lines()}
    assert got == {
        "R-1": None,  # proven by code: plain Fail stays
        "R-2": FAIL_NOT_APPROVED,  # an AI-approved rule is not approved by a person
        "R-3": FAIL_NOT_APPROVED,
        "R-4": PASS_NOT_APPROVED,
        "R-5": None,
        "R-6": A.NOT_APPLICABLE_LABEL,
    }
    assert A.NOT_APPLICABLE_LABEL == "Does not apply (AI, engineer to confirm)"


def test_the_middle_words_are_true_for_an_approved_checklist_and_a_person_approved_rule():
    checklist = mk(
        "S-1",
        "Query",
        "Fail",
        item={"source": "skill", "item_id": "S-1"},
        reason_code="not_met",
    )
    assert A.label(checklist) == "Fail (AI, not proven by code, engineer to confirm)"
    owner = {**mk("R-9", "Query", "Fail", reason_code="not_met"), "tier": "owner"}
    assert A.label(owner) == "Fail (AI, not proven by code, engineer to confirm)"


def test_a_book_not_held_a_two_reader_verdict_and_an_error_show_no_ai_answer():
    held = {
        **mk("R-7", "Query", "Fail", reason_code="not_met"),
        words.NOT_HELD_KEY: True,
    }
    assert A.label(held) is None  # a rule book not held is never guessed (gate G7)
    assert (
        A.label(
            {
                **mk("R-8", "Query", "Fail", reason_code="not_met"),
                "error": "stop_max_tokens",
            }
        )
        is None
    )
    two = {**mk("R-10", "Query", "Fail"), "verdict_class": W.CLASS_TWO_READERS}
    assert W.is_two_reader(two) or A.label(two) is None


def test_the_answer_line_says_standard_clause_page_and_quote_or_that_code_did_not_find_it():
    found = A.sentence(
        FAIL_NOT_APPROVED,
        book="STD-1",
        clause="clause 4.1",
        page=2,
        evidence="Nameplate: steel",
    )
    assert (
        found
        == f'{FAIL_NOT_APPROVED}: STD-1, clause 4.1, page 2; quote: "Nameplate: steel" (found on the page by code).'
    )
    none = A.sentence(
        FAIL_NOT_APPROVED, book=None, clause=A.NO_CLAUSE, page=None, evidence=None
    )
    assert (
        none
        == f"{FAIL_NOT_APPROVED}: no held rule book linked, clause not named, page not recorded; quote not found by code."
    )
    moved = {
        "clause": "",
        words.CLAUSE_UNCONFIRMED_KEY: "4.1",
    }  # a clause code moved off the line (LP1 holds such a "not met")
    assert A.clause_words(moved).startswith("clause 4.1 not confirmed by code")
    assert "not shown" in A.sentence(
        PASS_NOT_APPROVED,
        book=None,
        clause="clause 4.1",
        page=2,
        evidence=None,
        hidden=True,
    )


# ------------------------------------------------------------------------------------------------ the page as served


def test_the_page_shows_the_ai_answer_in_the_pill_and_keeps_plain_pass_fail_for_code_proven_rows():
    _doc, _c, _run, p = _world()
    assert (
        p["R-1"]["pill"] == "Not met · proven by code" and p["R-1"]["ai_answer"] is None
    )
    assert p["R-2"]["pill"] == FAIL_NOT_APPROVED and p["R-2"]["tile"] == "not_met"
    assert (
        p["R-3"]["pill"] == FAIL_NOT_APPROVED and p["R-3"]["tile"] == "questions"
    )  # no longer a bare "Question"
    assert p["R-4"]["pill"] == PASS_NOT_APPROVED
    assert p["R-5"]["pill"] == "Question" and p["R-5"]["ai_answer"] is None
    assert (
        p["R-6"]["pill"] == A.NOT_APPLICABLE_LABEL
        and p["R-6"]["tile"] == "na_to_confirm"
    )  # its own section
    assert p["R-2"]["ai_answer"] == (
        f'{FAIL_NOT_APPROVED}: STD-1, clause 4.1, page 2; quote: "Nameplate: steel" (found on the page by code).'
    )
    assert p["R-3"]["ai_answer"].endswith("; quote not found by code.")
    plain = [
        x
        for x in p.values()
        if x["pill"].split(" ")[0] in (PASS, FAIL) and "(AI," not in x["pill"]
    ]
    assert (
        plain == []
    )  # a plain "Pass" / "Fail" pill is never shown; a proven one says "proven by code"


def test_ai_rows_count_as_not_decided_everywhere():
    doc, client, *_ = _world()
    listing = points_of(client, doc)
    assert (
        listing["decided"] == 0
        and listing["proposed_code"]["undecided"] == listing["of"] == 6
    )
    assert "No review code proposed yet" in listing["proposed_code"]["line"]
    stored = [W.apply(ln) for ln in _lines()]
    assert (
        W.decisions_of((ln["verdict_class"], ln["verdict_label"]) for ln in stored)[
            "total"
        ]
        == 1
    )  # the proven Fail only
    team = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
    )
    lines = [
        str(r[0])
        for r in team[crs_one.TEAM_SHEET].iter_rows(values_only=True)
        if r and r[0]
    ]
    assert any(t.startswith("Decisions: 0 of 6 decided") for t in lines)


# ------------------------------------------------------------------------------------------------ the files as built


def test_the_team_file_prints_the_label_and_the_contractor_file_is_unchanged():
    doc, *_ = _world()
    team = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
    )
    head, rows = rows_after(team[crs_one.EVIDENCE_SHEET], "No")
    pills = {r[head.index("Field or item")]: r[head.index("Pill")] for r in rows}
    assert (
        pills["Field Silent"] == FAIL_NOT_APPROVED
        and pills["Field Opinion"] == FAIL_NOT_APPROVED
    )
    assert (
        pills["Field Proven"] == "Not met · proven by code"
        and pills["Field Asked"] == "Question"
    )
    contractor = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "contractor"))
    )
    text = " ".join(
        str(c)
        for ws in contractor
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c is not None
    )
    assert (
        "(AI," not in text
        and "Field Silent" not in text
        and "Field Opinion" not in text
    )


def test_the_run_file_shows_the_ai_answer_on_its_question_and_opinion_rows():
    lines = [
        *_lines(),  # R-7: an AI "not met" whose paper quote code did not find
        mk("R-7", "Query", "Fail", reason_code="not_met", field="Field Unquoted", paper_quote="", quotes_checked={"paper": False, "clause": True}),
    ]  # fmt: skip
    view = WB.layout_view(lines, {**META, "rule_labels": {}}, "internal")
    comment = {r[2].split(" - ")[-1]: r[3] for r in view["rows"]}
    assert (
        f"\n{FAIL_NOT_APPROVED}. The paper states" in comment["Field Opinion"]
    )  # was "The AI reviewer's view, not proven: ..."
    assert (
        f"\n{FAIL_NOT_APPROVED}. The words the reader quoted were not found"
        in comment["Field Silent"]
    )  # was a bare question
    assert (
        f"\n{FAIL_NOT_APPROVED}. Quote not found by code." in comment["Field Unquoted"]
    )
    assert (
        "(AI," not in comment["Field Proven"] and "(AI," not in comment["Field Asked"]
    )
    na_other = [
        r for r in view["other"]["rows"] if "Field Na" in str(r[2])
    ]  # with LP1 (#1875) the line is on "Not a comment"
    assert f"\n{A.NOT_APPLICABLE_LABEL}. " in comment.get("Field Na", "") or (
        na_other and A.NOT_APPLICABLE_LABEL in " ".join(str(c) for c in na_other[0])
    )
    cells = " ".join(str(c) for r in view["rows"] for c in r if c is not None)
    assert (
        words.AI_VIEW_PREFIX not in cells
    )  # the older "AI reviewer's view" sentence gave no label
    other = " ".join(str(c) for r in view["other"]["rows"] for c in r if c is not None)
    assert (
        f"{PASS_NOT_APPROVED}: STD-1, clause 4.1, page 2" in other
    )  # the rule not yet approved: its answer, said


def test_the_scorer_reads_an_ai_answer_as_an_ai_row_never_as_a_decision(tmp_path):
    from tools import answer_key_score as S

    assert S._team_kind("Not met", FAIL_NOT_APPROVED, "") == (
        "comment",
        "ai opinion",
        "",
    )
    assert S._team_kind("Met", PASS_NOT_APPROVED, "") is None
    assert S._team_kind("Questions for you", f"{FAIL_NOT_APPROVED} · 3 alike", "") == (
        "comment",
        "query",
        "",
    )
    doc, *_ = _world()
    path = tmp_path / "team.xlsx"
    path.write_bytes(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
    got = S.read_crs(path)
    assert not [ln for ln in got if ln.unknown_verdict]
    assert (
        sum(1 for ln in got if ln.status in ("fail", "pass")) == 1
    )  # the code-proven row only
    assert S.decision_figures([], got)["n"] == 1
    lines = _lines()
    run_file = tmp_path / "run.xlsx"
    WB.write(lines, run_file, {**META, "rule_labels": {}}, "internal")
    run = S.read_crs(run_file)
    assert (
        sum(1 for ln in run if ln.status in ("fail", "pass")) == 1
        and S.decision_figures([], run)["n"] == 1
    )


def test_the_owners_words_live_in_one_place():
    assert A.LABEL.format(answer=FAIL, why=A.WHY_NOT_APPROVED) == FAIL_NOT_APPROVED
    assert (
        A.is_label(FAIL_NOT_APPROVED)
        and A.answer_of(PASS_NOT_APPROVED) == PASS
        and not A.is_label("Question")
    )
    assert A.says_met(f"x\n{PASS_NOT_APPROVED}. The paper states") and not A.says_met(
        FAIL_NOT_APPROVED
    )
    assert SK and OK  # the invented items of the shared fixture


def test_a_merged_line_says_its_ai_answer_in_the_run_file_too():
    from app import crs_comments

    by = {ln["item_id"]: ln for ln in _lines()}
    assert (
        crs_comments._status_words(by["R-3"]) == FAIL_NOT_APPROVED
    )  # was "a question for the engineer"
    assert (
        crs_comments._status_words(by["R-2"]) == FAIL_NOT_APPROVED
    )  # was "not met in the AI reviewer's view, not proven by code"
    assert crs_comments._status_words(by["R-1"]) == "not met (proven by code)"
    assert crs_comments._status_words(by["R-5"]) == "a question for the engineer"


def test_the_rule_checks_own_ai_not_met_shows_the_label_with_true_middle_words():
    from app import review_points as rp
    from tests.test_o14_firm_needs_clause import CTX, ROW, VERIFIED, _finding

    label = "Fail (AI, not proven by code, engineer to confirm)"
    firm = rp.rule_point(
        dict(ROW), CTX, _finding("5.3.4"), VERIFIED, proof=(True, True)
    )
    rp.with_groups([firm])
    assert (firm["rank"], firm["tile"], firm["pill"]) == (
        3,
        "not_met",
        label,
    )  # was "Not met · one reader"; rank and tile kept
    assert firm["ai_answer"].startswith(
        f"{label}: BOOK-9.pdf, clause 5.3.4, page 3; quote: "
    )
    asked = rp.rule_point(dict(ROW), CTX, _finding(""), VERIFIED, proof=(True, True))
    rp.with_groups([asked])
    assert (asked["rank"], asked["pill"]) == (
        4,
        label,
    ) and ", clause not named, " in asked["ai_answer"]  # a question that hid it
    plain = rp.rule_point(
        {**ROW, "row_kind": "field_compare", "priority": "1"},
        CTX,
        _finding("5.3.4"),
        VERIFIED,
        proof=(True, True),
    )
    assert plain.get("ai_label") is None
