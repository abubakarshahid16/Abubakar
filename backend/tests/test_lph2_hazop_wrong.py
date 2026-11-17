"""Order 14, lane LPH2: the HAZOP procedure sheet's WRONG items W-H4 to W-H10, general rules only. Invented data only."""

from __future__ import annotations

import json
import uuid

import pytest

from app import (
    agent_general_review,
    agent_review_schema,
    agent_review_wording,
    crs_one,
    db,
)
from app.config import settings
from tests.test_crs_endpoint import NOW, _submittal, temp_db  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)


def _ai_run(paper: str, counts: dict) -> str:
    agent_review_schema.ensure_schema()
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, counts_json, started_at)"
            " VALUES (?,?,?,?,?,?)",
            (run, paper, "procedure", "invented", json.dumps(counts), NOW),
        )
    return run


def _page(paper: str, n: int, chars: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,1)",
            (paper, n, "x" * chars, chars),
        )


# ------------------------------------------------------------------------------------------------ W-H7: one source per statement


def test_why_no_rule_was_asked_is_said_beside_the_rule_checks_own_count():
    """The sheet said "rules asked 0" and an AI line said the held books "were not used" beside the rule check's rule points from
    them. The one statement names both steps from the run's own counts."""
    paper = _submittal()
    run = _ai_run(paper, {"parts": {"1": {"held_fit_not_used": 2}}})
    points = [
        {"source": "rule_check", "_book_doc": "doc_book_a"},
        {"source": "rule_check", "_book_doc": "doc_book_b"},
        {"source": "rule_check", "_book_doc": "doc_book_c", "_book_missing": "BOOK-Z"},
        {"source": "ai_review", "_book_doc": "doc_book_a"},
    ]
    conn = db.connect()
    got = crs_one.rules_asked_why(conn, run, 0, points)
    assert got == (
        "the AI reviewer's own rule step is switched off for this kind of paper; the rule check compared the paper with the held rule "
        "books: 2 rule point(s) on the sheet CRS"
    )
    assert (
        crs_one.rules_asked_why(conn, run, 3, points) is None
    )  # it asked some: nothing to explain
    other = _ai_run(paper, {"parts": {"1": {"held_fit_not_used": 0}}})
    assert (
        crs_one.rules_asked_why(conn, other, 0, points) is None
    )  # no reason recorded by the run: none invented


def test_a_stored_line_that_said_the_held_books_were_not_used_is_read_in_todays_true_words():
    stored = {
        "part": 1,
        "general": True,
        "text": agent_general_review.HELD_FIT_LINE_BEFORE,
        "held_rule_books": ["BOOK-A"],
    }
    now = agent_review_wording.read_time(stored)
    assert (
        now["text"] == agent_general_review.HELD_FIT_LINE
        and "were not used" not in now["text"]
    )
    assert (
        stored["text"] == agent_general_review.HELD_FIT_LINE_BEFORE
    )  # the stored row is never rewritten
    other = {
        "part": 1,
        "general": True,
        "text": "not checked against BOOK-Q, rule book not held",
    }
    assert agent_review_wording.read_time(other) == other


def test_the_pictures_the_ai_reviewer_did_not_read_are_the_pages_its_own_lines_name():
    paper = _submittal()
    for n, chars in ((1, 900), (2, 20), (3, 900), (4, 5)):
        _page(paper, n, chars)
    general = _ai_run(paper, {"mode": "general review"})
    conn = db.connect()
    assert (
        crs_one.ai_pictures_not_read(conn, general)
        == agent_general_review.unread_pages(conn, paper)
        == [2, 4]
    )
    assert crs_one.pictures_words([2, 4]).startswith(
        "pages 2, 4: the AI reviewer reads text"
    )
    rule_mode = _ai_run(paper, {"mode": "rule review"})
    assert crs_one.ai_pictures_not_read(conn, rule_mode) == []


# ------------------------------------------------------------------------------------------------ W-H10: editions said once, honestly


def test_a_found_online_edition_is_shown_only_with_its_source_and_a_date_not_after_the_search():
    from app import crs_reference
    from app import standards_web_search as sws

    base = {"outcome": sws.FOUND, "title": "Invented title", "latest_edition": "3.0", "year": 2019, "publisher": "Invented body",
            "url": "https://www.iso.org/standard/1.html", "searched_at": "2026-11-17T10:00:00+00:00"}  # fmt: skip
    found = crs_reference.found_online_edition
    assert found(base) == "3.0; (2019)"
    assert sws.words(base).endswith(
        "(found online, not verified; the book is not held; searched on 2026-11-17)"
    )
    assert (
        found({**base, "year": 2026}) == "3.0; (2026)"
    )  # the year of the search, with its source: shown (lead, review of #1891)
    assert (
        found({**base, "year": 2027})
        == "edition not found (the date given, 2027, is after the search)"
    )
    assert (
        found({**base, "url": None})
        == "edition not found (no source on the publisher's site)"
    )
    assert found({**base, "year": None}) == "edition not found (no date given)"
    assert found({**base, "latest_edition": None, "year": None}) == "edition not found"


def test_a_field_never_says_edition_not_recorded_beside_its_books_edition_status():
    from app import crs_editions

    tag = "(edition not recorded)"
    judged = {
        "id": "p1",
        "name": f"BOOK-A {tag} cl. 4.1",
        "action": f"BOOK-A {tag} cl. 4.1: invented words",
        "books": [{"id": "d1"}],
    }
    other = {"id": "p2", "name": f"BOOK-B {tag} cl. 2", "books": [{"id": "d2"}]}
    none = {"id": "p3", "name": "Invented field", "books": []}
    editions = {"d1": {"book": "BOOK-A", "status": "binds"}}
    got = crs_editions.names_without_unrecorded([judged, other, none], editions)
    assert (
        got[0]["name"] == "BOOK-A cl. 4.1"
        and got[0]["action"] == "BOOK-A cl. 4.1: invented words"
    )
    assert got[1] is other and got[2] is none  # a book not judged keeps its words
    assert crs_editions.names_without_unrecorded([judged], None) == [
        judged
    ]  # the check off: byte-same
    assert judged["name"] == f"BOOK-A {tag} cl. 4.1"  # the page's list is never changed


# ------------------------------------------------------------------------------------------------ W-H8: the cells of a comment


def _rc_point(pid: str, req: str, **over) -> dict:
    ref = "BOOK-A (edition not recorded) cl. 5"
    return {"id": pid, "source": "rule_check", "rank": 4, "tile": "questions", "name": ref, "rule_ref": {"name": ref, "clause": ""},
            "_rule_stored": req, "decision": {"state": None}, "priority": "Medium", **over}  # fmt: skip


def test_an_action_says_the_ai_suggestion_once_is_never_empty_and_the_requirement_is_never_nothing_beside_it():
    lead = "AI suggestion, engineer to confirm. "
    got = crs_one.full_texts(_rc_point("rc:1", "The invented valve shall close.", action=f'{lead}Requirement: "The invented valve shall close."',
                                       action_source="ai_suggestion"))  # fmt: skip
    assert got["action"].count("suggestion") == 1 and got["action"].endswith(
        'Requirement: "The invented valve shall close."'
    )
    assert (
        got["requires"]
        == f'"The invented valve shall close." ({crs_one.STORED_NOT_FOUND})'
    )
    assert (
        crs_one.full_texts(_rc_point("rc:2", "x", action=None))["action"]
        == crs_one.NO_ACTION
    )
    # a set-apart row ("Rule not yet approved", "Not a requirement to check") is never told to write an action
    apart = _rc_point(
        "rc:3",
        "x",
        action=None,
        rank=8,
        tile="does_not_apply",
        other_kind="Rule not yet approved",
    )
    assert crs_one.full_texts(apart)["action"] == ""


def test_a_rule_text_cut_where_its_list_begins_carries_a_visible_mark_and_a_quote_of_the_paper_never_does():
    cut = "When the invented factor is low the following shall be applied: a."
    paper = "The invented study covers these items: a."
    got = crs_one.full_texts(
        _rc_point(
            "rc:1",
            cut,
            rule_text=cut,
            action=f'Requirement: "{cut}". The paper says "{paper}".',
            action_source="check",
        )
    )
    for cell in (got["action"], got["requires"]):
        assert f'"{cut}" {crs_one.LIST_NOT_STORED}' in cell
    assert (
        f'"{paper}" {crs_one.LIST_NOT_STORED}' not in got["action"]
    )  # rule 4: the mark speaks of the rule book only
    whole = "The invented valve shall close in ten seconds."
    assert (
        crs_one.LIST_NOT_STORED
        not in crs_one.full_texts(_rc_point("rc:2", whole, rule_text=whole))["requires"]
    )
    rule = "Invented items shall comply with ABC-1. b."
    assert (
        crs_one.mark_cut_lists(f'"{rule}" (as stored)', [rule]).count(
            crs_one.LIST_NOT_STORED
        )
        == 1
    )
    assert (
        crs_one.mark_cut_lists(f'"{rule}" (as stored)', []) == f'"{rule}" (as stored)'
    )


# ------------------------------------------------------------------------------------------------ W-H4: not a requirement to check


_N = [0]


def _rule(section: str | None, clause: str | None, text: str) -> str:
    """An invented stored rule under a chunk titled `section`; returns its id."""
    _N[0] += 1
    rid, cid = f"req-{_N[0]}", f"chk-{_N[0]}"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,token_count,content_hash,retrievable)"
            " VALUES (?,'doc_book','b.pdf',?,1,1,?,'prose','x',1,?,1)",
            (cid, _N[0], section, f"h-{cid}"),
        )
        conn.execute(
            "INSERT INTO standard_requirements (id,standard_document_id,clause,requirement_text,chunk_id,created_at,updated_at)"
            " VALUES (?,'doc_book',?,?,?,?,?)",
            (rid, clause, text, cid, NOW, NOW),
        )
    return rid


def test_one_function_sets_apart_only_the_books_deviations_clause_and_a_true_definition():
    """W-H4 through #1889's `rule_text_place.place_of_requirement`: a requirement word keeps a rule a requirement, except the book's
    top-level conflicts-and-deviations clause and a true defining sentence (lead, review 2 of #1891: a scope clause can oblige)."""
    from app import rule_text_place as rtp

    _submittal("doc_book", "b.pdf")
    conn = db.connect()

    def why(section, clause, text):
        return rtp.place_of_requirement(conn, _rule(section, clause, text))

    assert (
        why(
            "2 Conflicts and Deviations",
            "2.1",
            "Any deviation shall follow the invented procedure.",
        )
        == rtp.DEVIATIONS_CLAUSE
    )
    assert (
        why("4.2 Terms", "4.2", "Shall: Indicates a mandatory requirement.")
        == rtp.DEFINITION
    )
    assert (
        why(
            "3 Definitions",
            "3",
            'For this invented standard, the words "hot fluid" shall mean a fluid above 60 C.',
        )
        == rtp.DEFINITION
    )
    # a requirement word keeps every other rule a requirement: a scope clause, other titles, a stored clause of another clause
    for section in (
        "1 Scope",
        "1 Purpose and Scope",
        "7.2 Exceptions",
        "8.4 Deviations",
        "3 Applicability",
        "3 References",
        "4.2 Terms",
    ):
        assert (
            why(section, section.split()[0], "The invented valve shall close in 10 s.")
            is None
        ), section
    assert (
        why("2 Conflicts and Deviations", "4.3", "The invented valve shall close.")
        is None
    )
    assert (
        why("2 Conflicts and Deviations", None, "Any deviation shall follow X.") is None
    )  # no stored clause number: never
    assert (
        why("4.2 Terms", None, "Shall: Indicates a mandatory requirement.") is None
    )  # nor a definition with no clause number
    assert (
        why(
            "5 Design",
            "5.1",
            "A trip is defined as a stop. The invented valve shall close.",
        )
        is None
    )


def test_the_points_own_record_decides_first_and_a_set_apart_point_asks_nothing(
    monkeypatch,
):
    from app import review_points as rp

    _submittal("doc_book", "b.pdf")
    rid = _rule("2 Conflicts and Deviations", "2", "Any deviation shall follow X.")
    row = {
        "row_kind": "clause_review",
        "finding_id": "f1",
        "standard_reference": "BOOK-A",
        "page_section": "",
        "comment": "",
    }
    finding = {"requirement_id": rid, "standard_document_id": "doc_book", "standard_clause": "2", "requirement": "Any deviation shall follow X.",
               "required_action": 'Requirement: "Any deviation shall follow X." Engineer to check.'}  # fmt: skip
    ctx = {
        "readable": frozenset({"doc_book"}),
        "paper_document_id": "doc_p",
        "req_sections": {rid: "2 Conflicts and Deviations"},
    }
    monkeypatch.setattr(rp, "clause_unconfirmed", lambda *a, **k: "")
    monkeypatch.setattr(rp, "shown_rule_words", lambda *a, **k: None)
    got = rp.rule_point(row, ctx, finding, {})
    assert (
        got["rank"] == 8
        and got["tile"] == "does_not_apply"
        and got["other_kind"] == rp.content.NOT_A_REQUIREMENT
    )
    assert (
        got["action"] == rp.content.NOT_A_REQUIREMENT_ACTION
        and "Requirement:" not in got["action"]
    )
    assert "conflicts-and-deviations" in got[
        "_not_a_requirement"
    ] and "conflicts-and-deviations" in crs_one.apart_proof(got)
    # its own record decides first: a decided verdict, a value of the paper, an ask of its own: never set apart
    for over, r in (({"compliance_status": "NON_COMPLIANT"}, row), ({"contractor_evidence_text": "Invented value 5"}, row),
                    ({}, {**row, "comment": "Invented: state the deviation number on the sheet."})):  # fmt: skip
        kept = rp.rule_point(
            r, ctx, {**finding, **over}, {"submittal": {"verified": True, "page": 2}}
        )
        assert kept["rank"] != 8 and not kept["_not_a_requirement"], over


# ------------------------------------------------------------------------------------------------ W-H5: the AI's note on the paper's own table


def test_the_ai_checks_note_on_the_papers_own_table_keeps_its_words_and_its_value_its_label():
    from app import review_points as rp

    row = {
        "row_kind": "ai_engineering_check",
        "finding_id": "f2",
        "standard_reference": "BOOK-Z",
        "page_section": "",
        "comment": "",
    }
    finding = {"standard_document_id": None, "standard_clause": None, "contractor_section": "Invented row", "contractor_evidence_text": "80",
               "finding": "The invented values carry no unit.", "requirement": "Missing units"}  # fmt: skip
    ctx = {"readable": frozenset(), "paper_document_id": "doc_p", "_library": []}
    got = rp.rule_point(row, ctx, finding, {"submittal": {"verified": True, "page": 3}})
    assert (
        got["rank"] == 4
        and "The invented values carry no unit." in got["action"]
        and rp.BOOK_MISSING not in got["action"]
    )
    assert got["reason_words"] == rp.content.AI_NOTE_REASON.format(book="BOOK-Z")
    assert crs_one.paper_shows(got).startswith('the paper\'s "Invented row": "80"')
    # a rule question of a book not held that names its clause stays that book's question
    named = rp.rule_point(
        {**row, "standard_reference": "BOOK-Z 4.1"},
        ctx,
        {**finding, "standard_clause": "4.1"},
        {},
    )
    assert rp.BOOK_MISSING in named["action"] and not named.get("paper_label")


# ------------------------------------------------------------------------------------------------ W-H6: the section map's three defects


def test_the_draft_notice_is_said_once_for_the_sheet():
    from app import procedure_playbook_rows as ppr

    assert (
        ppr.notice_line(["Draft A.", "Draft A.", None, "Draft B."])
        == f"{ppr.BY}: Draft A. Draft B."
    )
    assert ppr.notice_line([None, ""]) is None


def test_an_element_one_playbook_finds_is_never_not_found_by_another_playbook_of_the_same_paper():
    from app import playbooks
    from app import procedure_playbook_rows as ppr

    pb_a, pb_b = (
        type("PB", (), {"id": i, "title": t})()
        for i, t in (("a", "Invented A procedure"), ("b", "Invented B procedure"))
    )
    found = {"title": "Change management", "section_state": playbooks.UNCLEAR, "cited_page": 8, "evidence": [{"locator": "p.8"}],
             "reason": "unclear: stated at page 8", "source": {"standard": "BOOK-X"}}  # fmt: skip
    lost = {"title": "Change Management", "section_state": playbooks.MISSING, "evidence": [], "reason": "Section not found: x",
            "source": {"standard": "BOOK-Y"}}  # fmt: skip
    other = {
        "title": "Team",
        "section_state": playbooks.MISSING,
        "evidence": [],
        "reason": "Section not found: team",
        "source": {"standard": "BOOK-Y"},
    }
    ppr.same_element_found([(pb_a, found), (pb_b, lost), (pb_b, other)])
    assert lost["section_state"] == playbooks.UNCLEAR and lost["cited_page"] == 8
    assert (
        "found by the Invented A procedure checklist at page 8" in lost["reason"]
        and "BOOK-Y is not held" in lost["reason"]
    )
    assert (
        other["reason"] == "Section not found: team"
    )  # no other playbook found it: left as it was


def test_a_heading_that_names_only_another_elements_subject_is_not_this_elements_own_section():
    from app import playbooks

    worksheet = playbooks.Element(
        "E1",
        "Worksheet",
        "x",
        "BOOK",
        "7",
        (("worksheet", ("worksheet*",)), ("action column", ("action*",))),
    )
    recs = playbooks.Element(
        "E3",
        "Recommendations",
        "x",
        "BOOK",
        "8",
        (("recommendations", ("recommendation*", "actions")),),
    )
    assert playbooks._another_subject(
        worksheet, "4.5 Invented Actions", (worksheet, recs)
    )
    assert not playbooks._another_subject(
        worksheet, "4.6 Worksheet and actions", (worksheet, recs)
    )  # its own subject is named
    team = playbooks.Element(
        "E2",
        "Team",
        "x",
        "BOOK",
        "6",
        (("leader", ("leader",)), ("members", ("team member*",))),
    )
    named = playbooks.Element(
        "E4", "Named", "x", "BOOK", "1", (("named", ("invented",)),)
    )
    assert not playbooks._another_subject(
        team, "4.3 Invented Team Members", (team, named)
    )  # its words are its own
