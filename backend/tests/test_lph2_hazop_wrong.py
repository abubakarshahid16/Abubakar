"""Order 14, lane LPH2: the HAZOP procedure sheet's WRONG items W-H4 to W-H10, general rules only. Invented data only."""

from __future__ import annotations

import json
import uuid

import pytest

from app import agent_general_review, agent_review_schema, agent_review_wording, crs_one, db
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
    assert crs_one.rules_asked_why(conn, run, 3, points) is None  # it asked some: nothing to explain
    other = _ai_run(paper, {"parts": {"1": {"held_fit_not_used": 0}}})
    assert crs_one.rules_asked_why(conn, other, 0, points) is None  # no reason recorded by the run: none invented


def test_a_stored_line_that_said_the_held_books_were_not_used_is_read_in_todays_true_words():
    stored = {"part": 1, "general": True, "text": agent_general_review.HELD_FIT_LINE_BEFORE, "held_rule_books": ["BOOK-A"]}
    now = agent_review_wording.read_time(stored)
    assert now["text"] == agent_general_review.HELD_FIT_LINE and "were not used" not in now["text"]
    assert stored["text"] == agent_general_review.HELD_FIT_LINE_BEFORE  # the stored row is never rewritten
    other = {"part": 1, "general": True, "text": "not checked against BOOK-Q, rule book not held"}
    assert agent_review_wording.read_time(other) == other


def test_the_pictures_the_ai_reviewer_did_not_read_are_the_pages_its_own_lines_name():
    paper = _submittal()
    for n, chars in ((1, 900), (2, 20), (3, 900), (4, 5)):
        _page(paper, n, chars)
    general = _ai_run(paper, {"mode": "general review"})
    conn = db.connect()
    assert crs_one.ai_pictures_not_read(conn, general) == agent_general_review.unread_pages(conn, paper) == [2, 4]
    assert crs_one.pictures_words([2, 4]).startswith("pages 2, 4: the AI reviewer reads text")
    rule_mode = _ai_run(paper, {"mode": "rule review"})
    assert crs_one.ai_pictures_not_read(conn, rule_mode) == []


# ------------------------------------------------------------------------------------------------ W-H10: editions said once, honestly


def test_a_found_online_edition_is_shown_only_with_its_source_and_a_date_before_the_search():
    from app import standards_web_search as sws

    base = {"outcome": sws.FOUND, "title": "Invented title", "latest_edition": "3.0", "year": 2019, "publisher": "Invented body",
            "url": "https://www.iso.org/standard/1.html", "searched_at": "2026-11-17T10:00:00+00:00"}  # fmt: skip
    assert sws.edition_words(base) == "3.0; (2019)"
    assert sws.words(base).endswith("(found online, not verified; the book is not held; searched on 2026-11-17)")
    assert sws.edition_words({**base, "year": 2026}) == "edition not found (the date given, 2026, is not before the search)"
    assert sws.edition_words({**base, "url": None}) == "edition not found (no source on the publisher's site)"
    assert sws.edition_words({**base, "year": None}) == "edition not found (no date given)"
    assert sws.edition_words({**base, "latest_edition": None, "year": None}) == "edition not found"
    assert "2026" not in sws.words({**base, "latest_edition": "1.0", "year": 2026}).split("searched on")[0].replace("(the date given, 2026", "")


def test_a_field_never_says_edition_not_recorded_beside_its_books_edition_status():
    from app import crs_editions

    tag = "(edition not recorded)"
    judged = {"id": "p1", "name": f"BOOK-A {tag} cl. 4.1", "action": f"BOOK-A {tag} cl. 4.1: invented words", "books": [{"id": "d1"}]}
    other = {"id": "p2", "name": f"BOOK-B {tag} cl. 2", "books": [{"id": "d2"}]}
    none = {"id": "p3", "name": "Invented field", "books": []}
    editions = {"d1": {"book": "BOOK-A", "status": "binds"}}
    got = crs_editions.names_without_unrecorded([judged, other, none], editions)
    assert got[0]["name"] == "BOOK-A cl. 4.1" and got[0]["action"] == "BOOK-A cl. 4.1: invented words"
    assert got[1] is other and got[2] is none  # a book not judged keeps its words
    assert crs_editions.names_without_unrecorded([judged], None) == [judged]  # the check off: byte-same
    assert judged["name"] == f"BOOK-A {tag} cl. 4.1"  # the page's list is never changed


# ------------------------------------------------------------------------------------------------ W-H8: the cells of a comment


def _rc_point(pid: str, req: str, **over) -> dict:
    ref = "BOOK-A (edition not recorded) cl. 5"
    return {"id": pid, "source": "rule_check", "rank": 4, "tile": "questions", "name": ref, "rule_ref": {"name": ref, "clause": ""},
            "_rule_stored": req, "decision": {"state": None}, "priority": "Medium", **over}  # fmt: skip


def test_two_different_requirements_of_one_clause_named_by_their_reference_are_two_comments():
    from app import crs_comments

    a = _rc_point("rc:1", "The invented system shall have two trips.")
    b = _rc_point("rc:2", "Invented: a definition of a word.")
    c = _rc_point("rc:3", "The invented system shall have two trips.")
    got = crs_comments.group([a, b, c])
    assert sorted(len(x["member_ids"]) for x in got) == [1, 2]  # the same requirement twice is one comment
    # the "(edition ...)" words a sheet drops never change the grouping
    shown = [{**p, "name": "BOOK-A cl. 5"} for p in (a, b, c)]
    assert sorted(len(x["member_ids"]) for x in crs_comments.group(shown)) == [1, 2]
    # a point with a field of the paper is still grouped by its field, whatever its requirement
    f1, f2 = (_rc_point(i, r, name="Invented field") for i, r in (("rc:4", "x one"), ("rc:5", "y two")))
    assert len(crs_comments.group([f1, f2])) == 1


def test_an_action_says_the_ai_suggestion_once_is_never_empty_and_the_requirement_is_never_nothing_beside_it():
    lead = "AI suggestion, engineer to confirm. "
    got = crs_one.full_texts(_rc_point("rc:1", "The invented valve shall close.", action=f'{lead}Requirement: "The invented valve shall close."',
                                       action_source="ai_suggestion"))  # fmt: skip
    assert got["action"].count("suggestion") == 1 and got["action"].endswith('Requirement: "The invented valve shall close."')
    assert got["requires"] == f'"The invented valve shall close." ({crs_one.STORED_NOT_FOUND})'
    assert crs_one.full_texts(_rc_point("rc:2", "x", action=None))["action"] == crs_one.NO_ACTION


def test_a_rule_text_cut_where_its_list_begins_carries_a_visible_mark_in_every_cell():
    cut = "When the invented factor is low the following shall be applied: a."
    got = crs_one.full_texts(_rc_point("rc:1", cut, rule_text=cut, action=f'Requirement: "{cut}". Check it.', action_source="check"))
    for cell in (got["action"], got["requires"]):
        assert f'"{cut}" {crs_one.LIST_NOT_STORED}' in cell
    whole = "The invented valve shall close in ten seconds."
    assert crs_one.LIST_NOT_STORED not in crs_one.full_texts(_rc_point("rc:2", whole, rule_text=whole))["requires"]
    assert crs_one.mark_cut_lists(f'"Invented items shall comply with ABC-1. b." (as stored)').count(crs_one.LIST_NOT_STORED) == 1
