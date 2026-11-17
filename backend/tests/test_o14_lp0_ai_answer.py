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
FAIL_AI_ONLY = "Fail (AI, rule approved by AI only, engineer to confirm)"  # the shared fixture's rules are stored "AI approved"
DISAGREE = "AI readers disagree (first: Pass, second: Fail), engineer to decide"
HINT = "7 (found by word match, not verified)"
NO_QUOTE = (
    "AI view without a verified quote of the value from the paper: engineer to check"
)


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
        # the second AI reader said no to the first reader's "met": no reader's answer is THE answer
        mk("R-8", "Query", "Pass", reason_code="met", second_opinion={"agree": False}, field="Field Disagree"),
        # a page found only by word match: printed as such
        mk("R-9", "Query", "Fail", reason_code="not_met", field="Field Hint", paper_page=None, page_hint=[7]),
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
    assert (
        got
        == {
            "R-1": None,  # proven by code: plain Fail stays
            "R-2": FAIL_AI_ONLY,  # the STORED tier "AI approved", said as it is
            "R-3": NO_QUOTE,  # no paper quote code verified: a question, no Pass / Fail (lead, with #1882)
            "R-4": PASS_NOT_APPROVED,  # the stored tier "not AI approved"
            "R-5": None,
            "R-6": A.NOT_APPLICABLE_LABEL,
            "R-8": DISAGREE,
            "R-9": FAIL_AI_ONLY,
        }
    )
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
    none = {
        k: v
        for k, v in mk("R-9", "Query", "Fail", reason_code="not_met").items()
        if k not in ("tier", "rule_tier")
    }
    assert (
        A.label(none) == "Fail (AI, rule approval not recorded, engineer to confirm)"
    )  # never a default that claims a fact
    assert A.label({**none, "tier": "not AI approved"}) == FAIL_NOT_APPROVED


def test_a_disagreement_is_never_shown_as_one_readers_answer():
    independent = {
        **mk("R-8", "Query", "Fail", reason_code="not_met"),
        "two_reader": {"verdict": "met"},
    }
    assert (
        A.label(independent)
        == "AI readers disagree (first: Fail, second: Pass), engineer to decide"
    )
    cut = mk(
        "R-8",
        "Query",
        "Fail",
        reason_code="not_met",
        second_opinion={"agree": None, "reason": "stop_max_tokens"},
    )
    assert (
        A.label(cut) == FAIL_AI_ONLY
    )  # a cut-off second answer never said the opposite
    assert A.is_label(DISAGREE) and A.answer_of(DISAGREE) is None


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
        page="2",
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
        page="2",
        evidence=None,
        hidden=True,
    )
    named = A.sentence(
        PASS_NOT_APPROVED,
        book="",
        clause="clause 4.1",
        page="2",
        evidence=None,
        linked=True,
    )
    assert (
        "rule book name not recorded, clause 4.1" in named and "not shown" not in named
    )
    by = {ln["item_id"]: ln for ln in _lines()}
    assert A.line_sentence(by["R-3"]).endswith(
        "; quote not found by code."
    )  # a stored quote code did not verify is never shown
    assert f", page {HINT};" in A.line_sentence(by["R-9"])


# ------------------------------------------------------------------------------------------------ the page as served


def test_the_page_shows_the_ai_answer_in_the_pill_and_keeps_plain_pass_fail_for_code_proven_rows():
    _doc, _c, _run, p = _world()
    assert (
        p["R-1"]["pill"] == "Not met · proven by code" and p["R-1"]["ai_answer"] is None
    )
    assert p["R-2"]["pill"] == FAIL_AI_ONLY and p["R-2"]["tile"] == "not_met"
    assert (
        p["R-3"]["pill"] == NO_QUOTE and p["R-3"]["tile"] == "questions"
    )  # no longer a bare "Question"
    assert p["R-8"]["pill"] == DISAGREE and p["R-8"]["ai_answer"].startswith(
        f"{DISAGREE}: STD-1"
    )
    assert f", page {HINT};" in p["R-9"]["ai_answer"]
    assert p["R-4"]["pill"] == PASS_NOT_APPROVED
    assert p["R-5"]["pill"] == "Question" and p["R-5"]["ai_answer"] is None
    assert (
        p["R-6"]["pill"] == A.NOT_APPLICABLE_LABEL
        and p["R-6"]["tile"] == "na_to_confirm"
    )  # its own section
    assert p["R-2"]["ai_answer"] == (
        f'{FAIL_AI_ONLY}: STD-1, clause 4.1, page 2; quote: "Nameplate: steel" (found on the page by code).'
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
        and listing["proposed_code"]["undecided"] == listing["of"] == 8
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
    assert any(t.startswith("Decisions: 0 of 8 decided") for t in lines)
    tiles = listing["counts"][
        "tiles"
    ]  # the AI rows are counted apart on the Met / Not met tiles, never as code-proven
    assert (tiles["not_met"]["proven_by_code"], tiles["not_met"]["one_reader"]) == (
        1,
        2,
    )


# ------------------------------------------------------------------------------------------------ the files as built


def test_the_team_file_prints_the_label_and_the_contractor_file_is_unchanged():
    doc, *_ = _world()
    team = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
    )
    head, rows = rows_after(team[crs_one.EVIDENCE_SHEET], "No")
    pills = {r[head.index("Field or item")]: r[head.index("Pill")] for r in rows}
    cls = {r[head.index("Field or item")]: r[head.index("Class")] for r in rows}
    assert pills["Field Silent"] == NO_QUOTE and pills["Field Opinion"] == FAIL_AI_ONLY
    assert pills["Field Disagree"] == DISAGREE
    # the Class cell of an AI row is marked as the AI's; plain words only for a code-proven row
    assert (
        cls["Field Opinion"] == "Not met (AI, engineer to confirm)"
        and cls["Field Proven"] == "Not met"
    )
    assert (
        cls["Field Unapproved"] == "Rule not yet approved"
        and cls["Field Silent"] == "Questions for you"
    )
    plain_beside_ai = [
        f
        for f in cls
        if A.is_label(pills[f]) and cls[f] in ("Not met", "Met", "Does not apply")
    ]
    assert plain_beside_ai == []
    _h, comment_rows = rows_after(team[crs_one.TEAM_SHEET], "Comment")
    head_c = _h
    by_field = {
        r[head_c.index("Field or item")]: r[head_c.index("Class")]
        for r in comment_rows
        if r and r[0]
    }
    assert (
        by_field["Field Opinion"] == "Not met (AI, engineer to confirm)"
        and by_field["Field Proven"] == "Not met"
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
        f"\n{FAIL_AI_ONLY}. The paper states" in comment["Field Opinion"]
    )  # was "The AI reviewer's view, not proven: ..."
    assert (
        f"\n{NO_QUOTE}. The words the reader quoted were not found"
        in comment["Field Silent"]
    )  # was a bare question
    assert f"\n{NO_QUOTE}. Quote not found by code." in comment["Field Unquoted"]
    assert f"\n{DISAGREE}. " in comment["Field Disagree"]
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

    assert S._team_kind("Not met (AI, engineer to confirm)", FAIL_NOT_APPROVED, "") == (
        "comment",
        "ai opinion",
        "",
    )
    assert S._team_kind("Met (AI, engineer to confirm)", PASS_NOT_APPROVED, "") is None
    assert S._team_kind("Rule not yet approved", PASS_NOT_APPROVED, "") is None
    assert S._team_kind("Not met (AI, engineer to confirm)", DISAGREE, "") == (
        "comment",
        "ai opinion",
        "",
    )
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
        crs_comments._status_words(by["R-3"]) == NO_QUOTE
    )  # was "a question for the engineer"
    assert (
        crs_comments._status_words(by["R-2"]) == FAIL_AI_ONLY
    )  # was "not met in the AI reviewer's view, not proven by code"
    assert crs_comments._status_words(by["R-1"]) == "not met (proven by code)"
    assert crs_comments._status_words(by["R-5"]) == "a question for the engineer"


def test_the_rule_checks_own_ai_not_met_shows_the_label_with_true_middle_words():
    from app import review_points as rp
    from tests.test_o14_firm_needs_clause import CTX, ROW, VERIFIED, _finding

    lead = "Question (AI, not settled, rule approval not recorded)"  # no requirement id on the row
    firm = rp.rule_point(
        dict(ROW), CTX, _finding("5.3.4"), VERIFIED, proof=(True, True)
    )
    rp.with_groups([firm])
    # #1882: a rule-check AI-written row stores no verdict, so it is a question, never "Fail (AI, ...)"; its line keeps the approval words
    assert (firm["rank"], firm["tile"], firm["pill"], firm.get("ai_label")) == (
        4,
        "questions",
        "Question",
        None,
    )
    assert firm["ai_answer"].startswith(
        f"{lead}: BOOK-9.pdf, clause 5.3.4, page 3; quote: "
    )
    asked = rp.rule_point(dict(ROW), CTX, _finding(""), VERIFIED, proof=(True, True))
    rp.with_groups([asked])
    assert (
        asked.get("ai_answer") is None
    )  # #1882's builder note: a row whose AI-written rule words are not the book's gets no line
    plain = rp.rule_point(
        {**ROW, "row_kind": "field_compare", "priority": "1"},
        CTX,
        _finding("5.3.4"),
        VERIFIED,
        proof=(True, True),
    )
    assert plain.get("ai_label") is None


def test_the_scorer_skips_an_ai_met_row_of_the_run_file(tmp_path):
    from openpyxl import Workbook
    from tools import answer_key_score as S

    wb = Workbook()
    ws = wb.active
    ws.title = "CRS"
    ws.append(
        ["Item No", "Document Name", "Page No./Section", "COMPANY Comments", "Status"]
    )
    ws.append(
        [
            1,
            "Paper A",
            "p.2 - Field Met",
            f"STD-1 requires x.\n{PASS_NOT_APPROVED}. The paper states y.",
            "AI opinion",
        ]
    )
    ws.append(
        [
            2,
            "Paper A",
            "p.3 - Field Not",
            f"STD-1 requires x.\n{FAIL_NOT_APPROVED}. The paper states z.",
            "AI opinion",
        ]
    )
    path = tmp_path / "run.xlsx"
    wb.save(path)
    got = S.read_crs(path)
    assert [ln.label for ln in got] == [
        "Field Not"
    ]  # the AI's own "met" is no comment and no pass


def test_a_rule_not_yet_approved_never_says_does_not_apply_outside_its_section():
    from app import review_points as rp

    line = mk(
        "R-11",
        "Query",
        None,
        item=NO,
        reason_code="not_applicable",
        field="Field Na Unapproved",
    )
    assert A.label(line) == A.NOT_APPLICABLE_LABEL  # the home's label for the line ...
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {},
        "readable": frozenset(),
    }
    p = rp.ai_point(line, ctx)
    rp.with_groups([p])
    assert (
        p["rank"] == 8
        and p["ai_label"] is None
        and p["pill"] == "Rule not yet approved"
    )  # ... said only in its own section


def test_a_readable_book_with_no_name_is_never_said_to_be_hidden():
    from app import review_points as rp

    line = {
        **mk("R-2", "Query", "Fail", reason_code="not_met", field="Field Opinion"),
        "standard": "",
    }
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {"R-2": ("doc_std", "")},
        "readable": frozenset({"doc_std"}),
    }
    seen = rp.ai_point(line, ctx)["ai_answer"]
    assert seen.startswith(
        f"{FAIL_AI_ONLY}: rule book name not recorded, clause 4.1, page 2;"
    ), seen
    unread = rp.ai_point(line, {**ctx, "readable": frozenset()})["ai_answer"]
    assert (
        f"{A.BOOK_HIDDEN}, clause not named" in unread
    )  # the viewer may not read it: neither named nor its clause shown


# ------------------------------------------------------------------------------------------------ review round 3


def test_a_rule_check_rows_words_come_from_its_looked_up_tier(monkeypatch):
    from app import review_points as rp
    from app import rule_labels
    from tests.test_o14_firm_needs_clause import CTX, ROW, VERIFIED, _finding

    said = {
        "req-ai": rule_labels.Tier("AI approved"),
        "req-person": rule_labels.Tier("engineer"),
        "req-human": rule_labels.Tier(None, rule_labels.NEEDS_A_HUMAN),
        "req-none": rule_labels.Tier(None, rule_labels.NOT_LABELLED),
    }
    monkeypatch.setattr(
        rule_labels,
        "usable_tier",
        lambda _conn, requirement_id=None, **_k: said[requirement_id],
    )
    want = {
        "req-ai": "rule approved by AI only",
        "req-person": "not proven by code",
        "req-human": "rule not approved",
        "req-none": "rule not sorted yet",
        None: "rule approval not recorded",
    }
    for req, why in want.items():
        finding = {**_finding("5.3.4"), "requirement_id": req}
        p = rp.rule_point(dict(ROW), dict(CTX), finding, VERIFIED, proof=(True, True))
        # #1882: always a question; its line says the rule's approval words, never "Fail (AI, ...)"
        assert p["ai_answer"].startswith(f"Question (AI, not settled, {why}): "), req


def _disagreeing_old_line() -> dict:
    """An older run's stored "AI thinks: met" whose second reader said no (stored before the wording made such a line a question)."""
    line = mk(
        "R-12",
        "Query",
        "Pass",
        reason_code="met",
        field="Field Old Disagree",
        second_opinion={"agree": False},
    )
    return {**line, "verdict_class": W.CLASS_OPINION, "verdict_label": W.THINKS_MET}


def test_a_disagreement_is_a_question_in_every_file_and_read_alike_by_the_scorer(
    tmp_path,
):
    from tools import answer_key_score as S

    from app import review_points as rp

    line = _disagreeing_old_line()
    assert WB.status_of(line) == (
        words.STATUS_QUERY,
        words.ORDER_QUERY,
    )  # never a Met / Not met row
    p = rp.ai_point(
        line,
        {
            "run_id": "r",
            "paper_document_id": "d",
            "book_of": {},
            "readable": frozenset(),
        },
    )
    rp.with_groups([p])
    assert (p["rank"], p["tile"], p["pill"]) == (4, "questions", DISAGREE)
    assert A.class_words("Questions for you", p) == A.DISAGREE_CLASS
    assert S._team_kind(A.DISAGREE_CLASS, DISAGREE, "") == ("comment", "query", "")
    run_file = tmp_path / "run.xlsx"
    WB.write([line], run_file, {**META, "rule_labels": {}}, "internal")
    assert [ln.status for ln in S.read_crs(run_file)] == [
        "query"
    ]  # the run file: a question too


def test_no_cell_of_an_ai_row_says_met_or_not_met_in_plain_words():
    lines = [
        *_lines(),
        {
            **mk("R-13", "Query", "Fail", reason_code="not_met", field="Field Indep"),
            "two_reader": {"verdict": "met"},
        },
    ]
    view = WB.layout_view(lines, {**META, "rule_labels": {}}, "internal")
    ev = view["evidence"]
    head = list(ev["columns"])
    plain = {"met", "not met", "not_met"}
    for row in ev["rows"]:
        if row[head.index("Status")] in (words.STATUS_AI, words.STATUS_QUERY):
            assert not [c for c in row if str(c or "").strip().lower() in plain], row[
                head.index("Item id (internal)")
            ]
    by = {r[head.index("Item id (internal)")]: r for r in ev["rows"]}
    assert by["R-2"][head.index("Reason code")] == "not_met (AI, engineer to confirm)"
    assert by["R-1"][head.index("Reason code")] in (
        None,
        "",
        "not_met",
    )  # a code-proven row keeps its own words
    assert (
        by["R-13"][head.index("Independent reader: verdict")]
        == "met (AI, engineer to confirm)"
    )


def test_the_team_files_reason_and_second_reader_cells_mark_an_ai_answer():
    from app import crs_one as one

    line = {
        **mk("R-14", "Query", "Pass", reason_code="met", field="Field Met"),
        "verdict_class": W.CLASS_OPINION,
        "why": "",
    }
    line["not_proven_reason"] = ""
    point = {"source": "ai_review", "_line": line}
    assert one.reason_of(point).endswith("met (AI, engineer to confirm)")
    proven = {
        "source": "ai_review",
        "_line": {
            **mk("R-1", "Fail", "Fail"),
            "why": "",
            "not_proven_reason": "",
            "reason_code": "met",
        },
    }
    assert "(AI," not in one.reason_of(proven)
    indep = {
        "source": "ai_review",
        "rank": 4,
        "_line": {**line, "two_reader": {"verdict": "not met"}},
    }
    assert (
        one.readers_of(indep)[1]
        == "independent reader: not met (AI, engineer to confirm)"
    )


def test_an_ai_answer_is_shown_only_beside_a_paper_quote_code_verified():
    """Lead's decision with PR #1882: no Pass / Fail of the AI without a verified paper quote, on the page, the files and the rule check."""
    from app import review_points as rp
    from tests.test_o14_firm_needs_clause import CTX, ROW, _finding

    assert A.NO_QUOTE_LABEL == NO_QUOTE
    by = {ln["item_id"]: ln for ln in _lines()}
    assert A.label(by["R-3"]) == NO_QUOTE and A.label(by["R-2"]) == FAIL_AI_ONLY
    said = A.line_sentence(by["R-3"])
    assert said.startswith(f"{NO_QUOTE}. STD-1, clause 4.1, page 2;") and said.endswith(
        "quote not found by code."
    )
    opinion = {
        **by["R-2"],
        "quotes_checked": {"paper": False, "clause": True},
    }  # a stored "AI thinks" with no verified quote
    assert WB.status_of(opinion) == (
        words.STATUS_QUERY,
        words.ORDER_QUERY,
    )  # never a Met / Not met row
    p = rp.ai_point(
        opinion,
        {
            "run_id": "r",
            "paper_document_id": "d",
            "book_of": {},
            "readable": frozenset(),
        },
    )
    rp.with_groups([p])
    assert (p["rank"], p["tile"], p["pill"]) == (4, "questions", NO_QUOTE)
    unseen = {"submittal": {"verified": False}, "standard": {"verified": True}}
    rc = rp.rule_point(
        dict(ROW), dict(CTX), _finding("5.3.4"), unseen, proof=(True, True)
    )
    rp.with_groups([rc])
    # #1882: a rule-check AI row is a question whatever it stores; with no verified passage its line says "quote not found by code"
    assert (rc["rank"], rc["pill"]) == (4, "Question") and rc["ai_answer"].endswith(
        "quote not found by code."
    )
    assert (
        A.class_words("Not met", {"ai_label": NO_QUOTE, "tile": "not_met"})
        == "Questions for you"
    )  # never a plain Not met beside it


# ------------------------------------------------------------------------------------------------ hotfix 19c: a deferred value


DEFERRED = "The paper leaves this value open (to be filled): engineer to confirm with the contractor"


def _deferred_lines() -> list[dict]:
    return [
        # the reader's own "not met" on a verified quote that leaves the value to the contractor (the 19a pump "Fail" rows)
        mk("R-D1", "Query", "Fail", reason_code="not_met", field="Field Deferred", paper_quote="Rated power | *"),
        # the reader's "met" the gate held because the quote defers (its reason says so)
        mk("R-D2", "Query", "Pass", reason_code="met", field="Field Deferred Met", paper_quote="Seal kind: by contractor"),
        # the same "not met" on a quote that gives a value: the AI's own answer stays
        mk("R-D3", "Query", "Fail", reason_code="not_met", field="Field Stated"),
    ]  # fmt: skip


def test_a_deferred_value_is_a_question_never_the_ai_readers_pass_or_fail():
    """Hotfix 19c: a line whose verified paper quote defers the value, or whose gate reason says so, shows the question words on the
    page, in the team file's Pill and Class cells and in the run file; never "Pass / Fail (AI, ...)" or "Met / Not met (AI, ...)"."""
    from tests.test_b1_review_points import ai_run, points_of

    assert (
        A.DEFERRED_LABEL == DEFERRED
        and A.is_label(DEFERRED)
        and A.answer_of(DEFERRED) is None
    )
    by = {ln["item_id"]: ln for ln in _deferred_lines()}
    assert {k: A.label(v) for k, v in by.items()} == {
        "R-D1": DEFERRED,
        "R-D2": DEFERRED,
        "R-D3": FAIL_AI_ONLY,
    }
    assert A.defers(
        {
            **by["R-D3"],
            "paper_quote": "",
            "not_proven_reason": "the quoted paper text defers or leaves open this value",
        }
    )
    unverified = {**by["R-D1"], "quotes_checked": {"paper": False, "clause": True}}
    assert not A.defers(
        unverified
    )  # a quote code did not verify never says what the paper does
    assert WB.status_of(by["R-D1"]) == (words.STATUS_QUERY, words.ORDER_QUERY)
    assert A.line_sentence(by["R-D1"]).startswith(
        f"{DEFERRED}. STD-1, clause 4.1, page 2;"
    )

    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(doc, _deferred_lines())
    client = _client(doc, "doc_std")
    pts = {p["id"].rsplit(":", 1)[1]: p for p in points_of(client, doc)["points"]}
    assert (pts["R-D1"]["tile"], pts["R-D1"]["pill"]) == ("questions", DEFERRED)
    assert pts["R-D2"]["pill"] == DEFERRED and pts["R-D3"]["pill"] == FAIL_AI_ONLY

    team = load_workbook(
        io.BytesIO(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
    )
    head, rows = rows_after(team[crs_one.EVIDENCE_SHEET], "No")
    pill = {r[head.index("Field or item")]: r[head.index("Pill")] for r in rows}
    cls = {r[head.index("Field or item")]: r[head.index("Class")] for r in rows}
    assert (
        pill["Field Deferred"] == DEFERRED
        and cls["Field Deferred"] == "Questions for you"
    )
    assert (
        pill["Field Deferred Met"] == DEFERRED
        and cls["Field Deferred Met"] == "Questions for you"
    )
    assert cls["Field Stated"] == "Not met (AI, engineer to confirm)"

    for lines in (
        _deferred_lines()[:1],
        _deferred_lines()[1:2],
    ):  # one line a file: the two would merge into one comment
        view = WB.layout_view(lines, {**META, "rule_labels": {}}, "internal")
        (row,) = view["rows"]
        assert f"\n{DEFERRED}. " in row[3]
        assert "(AI, rule" not in row[3] and " (AI, engineer to confirm)" not in row[3]
