"""A Schedule held as a main paper plus its attachments is offered by name and, once chosen, is READ WHOLE for the contract's questions
(a long Schedule is read in windows, not cut at its first pages); a question settles with a quote code found on the part's page.
Invented documents and words only. No model, no call."""

from __future__ import annotations

import pytest

from app.aim_review import references as R
from tests.test_aim_method_helpers import _doc
from tests.test_r_reference_papers import AGREEMENT, _line, _paper, Part, conn  # noqa: F401 - fixtures

FORM = "doc_cb_form"
MAIN, ATT1, ATT2 = "doc_cb_main", "doc_cb_att1", "doc_cb_att2"
FORM_PAGES = {
    1: "FORM OF AGREEMENT\nThe design scope is set out in Schedule B.\nPayment follows Schedule C.\n"
}
CLAUSE = "The contractor shall provide a coordinated design with a design basis memorandum for every discipline"


def _long_schedule_pages(n_pages: int, target_page: int) -> dict[int, str]:
    filler = (
        "General conditions apply to the whole scope of the work as described elsewhere in this part. "
        * 40
    )
    pages = {i: f"{filler}\n" for i in range(1, n_pages + 1)}
    pages[1] = "SCHEDULE B\nJOB SPECIFICATION\n" + pages[1]
    pages[target_page] += f"\n{CLAUSE}.\n"
    return pages


@pytest.fixture
def world(conn):
    with conn:
        _doc(conn, FORM, "form.pdf", "CONTRACT_DOCUMENT", FORM_PAGES)
        _doc(
            conn,
            MAIN,
            "09 - SCHEDULE B - Job Specification - Rev 06.pdf",
            "CONTRACT_DOCUMENT",
            _long_schedule_pages(60, 55),
        )
        _doc(
            conn,
            ATT1,
            "09a - SCHEDULE B - Att I A - Office facilities - Rev 02.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE B\nATTACHMENT I A\nOffice facilities."},
        )
        _doc(
            conn,
            ATT2,
            "09b - SCHEDULE B - Att I B - Temporary facilities - Rev 03.pdf",
            "CONTRACT_DOCUMENT",
            {1: "SCHEDULE B\nATTACHMENT I B\nTemporary facilities."},
        )
    return conn


def test_a_schedule_held_as_main_plus_attachments_is_offered_by_name_as_the_main_paper(
    world,
):
    res = R.resolve(world, FORM, FORM_PAGES)
    assert [(o.name, o.doc_id) for o in res.offers] == [
        ("Schedule B", MAIN)
    ]  # not "held more than once", not the attachments
    chosen = R.resolve(world, FORM, FORM_PAGES, frozenset({MAIN}))
    assert [(r.name, r.doc_id) for r in chosen.refs] == [("Schedule B", MAIN)]


def test_the_questions_are_asked_over_every_window_and_settled_with_a_quote_of_the_page_that_holds_it(
    world,
):
    lines = [
        _line(
            1,
            "Please confirm that the Schedule B scope requires a coordinated design.",
            quote="The design scope is set out in Schedule B.",
        )
    ]
    asked = []

    def answer(kw):
        asked.append(kw["prompt"])
        in_window = f"[page 55]" in kw["prompt"]
        return {
            "checks": [
                {
                    "n": 1,
                    "result": "agrees" if in_window else "not_stated",
                    "page": 55,
                    "quote": CLAUSE,
                    "comment": "The part requires a coordinated design.",
                }
            ]
        }

    record, _carried = R.check(
        world, Part(answer), _paper_of(world), lines, frozenset({MAIN}), "m"
    )
    assert len(asked) >= 2, "a 60-page Schedule is read in more than one window"
    ln = lines[0]
    assert ln["label"] == "Met" and ln["comment"].startswith(
        "Schedule B, page 55: "
    )  # B's clause and page, not 'please confirm'
    row = next(r for r in record if r["part"] == "Schedule B")
    assert (
        row["status"] == "read"
        and row["settled"] == 1
        and row["pages_read"] == row["pages_held"] == 60
    )


def test_a_question_no_window_states_says_the_whole_schedule_was_read(world):
    lines = [
        _line(
            1,
            "Please confirm the rate card in Schedule B.",
            quote="The design scope is set out in Schedule B.",
        )
    ]
    model = Part({"checks": [{"n": 1, "result": "not_stated"}]})
    record, _ = R.check(world, model, _paper_of(world), lines, frozenset({MAIN}), "m")
    assert (
        lines[0]["comment"].startswith("Schedule B was read and does not state this.")
        and "pages 1 to" not in lines[0]["comment"]
    )
    assert len(model.calls) >= 2  # every window was read before saying so


def test_an_unverified_quote_in_a_window_leaves_the_question_as_it_was(world):
    lines = [
        _line(
            1,
            "Please confirm the design basis in Schedule B.",
            quote="The design scope is set out in Schedule B.",
        )
    ]
    before = dict(lines[0])
    model = Part(
        {
            "checks": [
                {
                    "n": 1,
                    "result": "agrees",
                    "page": 55,
                    "quote": "words the part never says anywhere at all",
                    "comment": "c",
                }
            ]
        }
    )
    R.check(world, model, _paper_of(world), lines, frozenset({MAIN}), "m")
    assert lines[0]["comment"] == before["comment"] and lines[0]["label"] == "Question"


def _paper_of(conn):
    from app.aim_review.paper import load_paper

    return load_paper(conn, FORM)


def test_a_window_that_fails_midway_counts_only_the_pages_that_came_back_and_the_record_says_which_were_not_read(
    world,
):
    """A page counts as read only if text came back for it: window 2 fails -> pages_read is window 1's pages, the unread pages are named."""
    from app.aim_review.engine import StepFailed

    lines = [
        _line(
            1,
            "Please confirm the rate card in Schedule B.",
            quote="The design scope is set out in Schedule B.",
        )
    ]
    calls = []

    def answer(kw):
        calls.append(kw["prompt"])
        if len(calls) == 2:
            raise StepFailed("aim_reference: stop network")
        return {"checks": [{"n": 1, "result": "not_stated"}]}

    record, _ = R.check(
        world, Part(answer), _paper_of(world), lines, frozenset({MAIN}), "m"
    )
    row = next(r for r in record if r["part"] == "Schedule B")
    assert row["status"] == "read in part"
    assert (
        row["pages_held"] == 60 and 0 < row["pages_read"] < 60
    )  # only window 1 came back
    assert (
        "were not read" in row["reason"] and f"of {row['pages_held']}" in row["reason"]
    )
    assert (
        lines[0]["comment"] == "Please confirm the rate card in Schedule B."
    )  # no 'does not state this' after a failed window


def test_the_team_file_and_the_page_say_how_many_pages_of_a_part_were_read():
    from app import aim_review_sheet as S

    words = S.reference_words(
        {
            "status": "read in part",
            "pages_read": 43,
            "pages_held": 84,
            "reason": "pages 44-84 were not read: a call stopped",
        }
    )
    assert (
        words
        == "read in part; pages read 43 of 84; pages 44-84 were not read: a call stopped"
    )
    assert S.reference_words({"status": "not held"}) == "not held"


def test_the_how_sheet_of_the_team_file_lists_each_part_with_its_pages_read():
    from openpyxl import Workbook

    from app import aim_review_sheet as S

    model = {
        "checklist": {"key": "k", "items": 1, "always_items": 0, "built_from": "invented books", "reused": None},
        "run_id": "r", "created_at": None, "finished_at": None, "seconds": None, "calls": [],
        "references": [{"part": "Schedule B", "status": "read in part", "pages_read": 43, "pages_held": 84,
                        "reason": "pages 44-84 were not read: a call stopped"}],
    }  # fmt: skip
    ws = Workbook().active
    S._how(ws, model)
    cells = {str(r[0]): str(r[1]) for r in ws.iter_rows(values_only=True) if r and r[0]}
    assert (
        cells["Part of the contract: Schedule B"]
        == "read in part; pages read 43 of 84; pages 44-84 were not read: a call stopped"
    )
