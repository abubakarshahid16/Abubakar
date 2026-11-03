# ruff: noqa: F811 - pytest fixtures imported by name
"""Lane 6, M4: the project specification is marked only by a person, compared when marked, and reported in every review.

Invented documents only; no model called.
"""

from __future__ import annotations

import pytest

from app import db, export_status
from app import project_specification as ps
from tests.test_633_honest_exports import (  # noqa: F401 - the fixtures
    _completed_run,
    _doc,
    _user,
    temp_storage,
    world,
)


def _contract(doc_id="contract1"):
    return _doc(doc_id, "CONTRACT_DOCUMENT", "The pump motor shall be rated 55 kW.")


def test_every_review_says_none_held_until_a_person_marks_one(world):
    assert ps.line(world["sub"], world["scope"]) == "Project specification: none held"
    (note,) = ps.notes(world["sub"], world["scope"])
    assert note["standard"] == "none held" and note["detail"].endswith("none held")


def test_only_the_owner_marks_one_and_nothing_else_can():
    sub, spec = _doc("s1", "CONTRACTOR_SUBMITTAL", "x"), _contract()
    _user("eng", [sub, spec])
    with db.connect() as conn:  # an ordinary user: take the admin grant away
        conn.execute(
            "DELETE FROM user_roles WHERE user_id = 'eng' AND role_id = (SELECT id FROM roles WHERE name='admin')"
        )
    ok, why = ps.mark(sub, spec, "eng")
    assert not ok and "owner" in why and ps.marked(sub) is None
    assert ps.mark(sub, spec, "nobody")[0] is False


def test_a_mark_needs_a_submittal_and_a_contract_document_or_standard():
    sub, spec = _doc("s2", "CONTRACTOR_SUBMITTAL", "x"), _contract("c2")
    other = _doc("o2", "SUPPORTING_DOCUMENT", "x")
    _user("own", [sub, spec, other])
    assert ps.mark(sub, sub, "own")[0] is False
    assert (
        ps.mark(spec, sub, "own")[0] is False
    )  # the first document must be the submittal
    assert (
        ps.mark(sub, other, "own")[0] is False
    )  # a supporting document is not a specification
    assert ps.mark(sub, spec, "own") == (True, "") and ps.marked(sub) == spec


def test_a_mark_can_be_undone_and_the_record_stays():
    sub, spec = _doc("s3", "CONTRACTOR_SUBMITTAL", "x"), _contract("c3")
    _user("own3", [sub, spec])
    ps.mark(sub, spec, "own3")
    ps.mark(sub, spec, "own3", undo=True)
    assert ps.marked(sub) is None
    assert (
        db.connect()
        .execute("SELECT COUNT(*) FROM project_specification_mark")
        .fetchone()[0]
        == 2
    )


def test_a_specification_the_caller_may_not_read_is_none_held():
    sub, spec = _doc("s4", "CONTRACTOR_SUBMITTAL", "x"), _contract("c4")
    _user("own4", [sub, spec])
    ps.mark(sub, spec, "own4")
    assert ps.line(sub, frozenset({sub, spec})).startswith(
        "Project specification: c4.pdf was marked"
    )
    assert ps.line(sub, frozenset({sub})) == "Project specification: none held"


def test_the_line_never_says_compared_when_no_requirement_was_read(world):
    ps.mark(world["sub"], "std_api", "adm")
    with db.connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET superseded_at = '2026-01-01' WHERE standard_document_id='std_api'"
        )
    assert "nothing was compared against it" in ps.line(world["sub"], world["scope"])
    assert (
        ps.pin(_completed_run(world), world["sub"], world["scope"]) is False
    )  # nothing to compare: nothing pinned


def test_a_marked_specification_with_requirements_is_reported_and_pinned_to_the_run(
    world,
):
    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    assert "used: std_api.pdf" in ps.line(world["sub"], world["scope"])
    assert ps.pin(run_id, world["sub"], world["scope"]) is True
    row = (
        db.connect()
        .execute(
            "SELECT selection_method, included, selection_reason FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = 'std_api'",
            (run_id,),
        )
        .fetchone()
    )
    assert (
        row["selection_method"] == "manual"
        and row["included"] == 1
        and "administrator" in row["selection_reason"]
    )
    notes = export_status.equipment_notes(world["sub"], run_id, world["scope"])
    assert any("Project specification used" in n["detail"] for n in notes)


def test_nothing_is_pinned_when_none_is_marked_or_it_cannot_be_read(world):
    run_id = _completed_run(world)
    assert ps.pin(run_id, world["sub"], world["scope"]) is False
    ps.mark(world["sub"], "std_api", "adm")
    assert ps.pin(run_id, world["sub"], frozenset({world["sub"]})) is False


@pytest.mark.parametrize("who", ["adm"])
def test_the_review_job_pins_at_the_standards_step(world, who):
    ps.mark(world["sub"], "std_api", who)
    run_id = _completed_run(world)
    row = (
        db.connect()
        .execute(
            "SELECT selection_method FROM review_applicable_standards WHERE review_run_id = ? AND standard_document_id = 'std_api'",
            (run_id,),
        )
        .fetchone()
    )
    assert row["selection_method"] == "manual"


def _rows_of(run_id):
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM review_applicable_standards WHERE review_run_id = ?"
            " ORDER BY standard_document_id, rowid",
            (run_id,),
        )
    ]


def test_pin_never_overwrites_an_engineers_exclusion_of_the_specification(world):
    from app import applicability

    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    applicability.record_selection(
        review_run_id=run_id,
        standard_document_id="std_api",
        method=applicability.METHOD_MANUAL,
        reason="engineer decision",
        included=False,
        exclusion_reason="not for this job",
    )
    before = _rows_of(run_id)
    assert ps.pin(run_id, world["sub"], world["scope"]) is False
    after = _rows_of(run_id)
    assert after == before
    (mine,) = [r for r in after if r["standard_document_id"] == "std_api"]
    assert mine["included"] == 0 and mine["exclusion_reason"] == "not for this job"


def test_the_latest_mark_wins_after_mark_unmark_mark():
    sub = _doc("s7", "CONTRACTOR_SUBMITTAL", "x")
    a, b = _contract("a7"), _contract("b7")
    _user("own7", [sub, a, b])
    for spec, undo in ((a, False), (b, False), (a, True), (a, False)):
        assert ps.mark(sub, spec, "own7", undo=undo)[0]
    assert ps.marked(sub) == a  # A was marked last; B was replaced by it
    ps.mark(sub, b, "own7", undo=True)  # B is not the current one: nothing changes
    assert ps.marked(sub) == a
    ps.mark(sub, b, "own7")  # a second specification replaces the first
    assert ps.marked(sub) == b
    ps.mark(sub, b, "own7", undo=True)
    assert ps.marked(sub) is None


def test_an_admin_without_a_read_grant_cannot_mark_and_the_refusal_leaks_nothing():
    sub = _doc("s8", "CONTRACTOR_SUBMITTAL", "x")
    spec = _doc("c8", "CONTRACT_DOCUMENT", "The pump motor shall be rated 55 kW.")
    _user("own8", [sub])  # an admin, but with no grant on the specification
    ok, why = ps.mark(sub, spec, "own8")
    assert not ok and ps.marked(sub) is None
    assert why == ps.NOT_READABLE
    for leak in (
        "CONTRACT_DOCUMENT",
        "COMPANY_STANDARD",
        "c8",
        "contract",
        "submittal",
    ):
        assert leak not in why
    # the same words for a document that does not exist
    assert ps.mark(sub, "no-such-doc", "own8") == (False, ps.NOT_READABLE)
    # and for an unreadable submittal
    assert ps.mark("hidden-sub", sub, "own8") == (False, ps.NOT_READABLE)


def test_with_no_mark_a_review_changes_nothing_in_its_rows(world):
    run_id = _completed_run(world)
    before = _rows_of(run_id)
    marks_before = (
        db.connect()
        .execute("SELECT COUNT(*) FROM project_specification_mark")
        .fetchone()[0]
    )
    assert ps.pin(run_id, world["sub"], world["scope"]) is False
    assert _rows_of(run_id) == before
    assert (
        db.connect()
        .execute("SELECT COUNT(*) FROM project_specification_mark")
        .fetchone()[0]
        == marks_before
    )


def test_a_specification_with_no_requirements_read_is_not_pinned_over_nothing(world):
    # a marked specification the caller may read, but nothing was read from it: pin records no row at all
    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM review_applicable_standards WHERE review_run_id = ? AND standard_document_id = 'std_api'",
            (run_id,),
        )
        conn.execute(
            "UPDATE standard_requirements SET superseded_at = '2026-01-01' WHERE standard_document_id='std_api'"
        )
    assert ps.pin(run_id, world["sub"], world["scope"]) is False
    assert not [r for r in _rows_of(run_id) if r["standard_document_id"] == "std_api"]


def test_the_requirements_guard_comes_before_the_pin(world):
    # with requirements read, the same call pins: so the zero-requirements refusal above is the guard's own doing
    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM review_applicable_standards WHERE review_run_id = ? AND standard_document_id = 'std_api'",
            (run_id,),
        )
    assert ps.pin(run_id, world["sub"], world["scope"]) is True
    assert [r for r in _rows_of(run_id) if r["standard_document_id"] == "std_api"]


def test_the_note_says_what_the_run_did_not_what_the_mark_says(world):
    from app import applicability

    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    applicability.record_selection(
        review_run_id=run_id,
        standard_document_id="std_api",
        method=applicability.METHOD_MANUAL,
        reason="engineer decision",
        included=False,
        exclusion_reason="not for this job",
    )
    ps.pin(run_id, world["sub"], world["scope"])
    (note,) = export_status.equipment_notes(world["sub"], run_id, world["scope"])[:1]
    assert "excluded it from this run" in note["detail"]
    assert "used" not in note["detail"]


def test_a_later_mark_or_unmark_never_rewrites_an_earlier_runs_note(world):
    run_a = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    ps.pin(run_a, world["sub"], world["scope"])
    before = ps.notes(world["sub"], world["scope"], run_a)
    ps.mark(world["sub"], "std_api", "adm", undo=True)
    assert ps.marked(world["sub"]) is None
    assert ps.notes(world["sub"], world["scope"], run_a) == before
    assert "used: std_api.pdf" in before[0]["detail"]


def test_a_run_with_no_stored_facts_says_so_and_never_borrows_the_current_mark(world):
    ps.mark(world["sub"], "std_api", "adm")
    (note,) = ps.notes(world["sub"], world["scope"], "run-never-pinned")
    assert note["detail"] == "Project specification: not recorded for this run"


def test_the_stored_note_hides_a_specification_the_caller_may_not_read(world):
    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    ps.pin(run_id, world["sub"], world["scope"])
    (note,) = ps.notes(world["sub"], frozenset({world["sub"]}), run_id)
    assert note["detail"] == "Project specification: none held"
    assert "std_api" not in str(note)


def test_the_wording_names_no_owner_for_what_any_administrator_did(world):
    run_id = _completed_run(world)
    ps.mark(world["sub"], "std_api", "adm")
    ps.pin(run_id, world["sub"], world["scope"])
    (note,) = ps.notes(world["sub"], world["scope"], run_id)
    assert "marked by an administrator" in note["detail"]
    assert "owner" not in note["detail"]
