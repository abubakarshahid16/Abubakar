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
        and "owner" in row["selection_reason"]
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
