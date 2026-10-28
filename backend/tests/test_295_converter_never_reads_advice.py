"""Order 295.7 item 3 (planner, after clean-v21 verified two wrong rows): the review's reading of the converter's
drafts never reads a row whose STORED requirement is a recommendation or a definition, even if the draft says
`verified` (belt and braces beside the converter's own refusal). Invented standards only."""

from __future__ import annotations

import pytest

from app import rule_roles
from app.db import connect
from tests.test_274_sentence_checks import (  # noqa: F401 - fixtures
    SENTENCE,
    _mirror,
    _on,
    _row,
    _rules,
    cworld,
    review_run,
    temp_storage,
)


@pytest.fixture
def world(request):
    return request.getfixturevalue("cworld")


def _retype(stmt, requirement_type):
    with connect() as conn:
        conn.execute(
            "UPDATE standard_requirements SET requirement_type = ? WHERE id = ?",
            (requirement_type, stmt),
        )


def test_a_statement_with_a_verified_row_is_read_and_is_the_control(
    world, monkeypatch, tmp_path
):
    world["folder"] = _mirror(tmp_path / "ok", [_row(SENTENCE, applies=None)])
    _on(world, monkeypatch)
    assert list(_rules(world)) == [world["stmt"]]


@pytest.mark.parametrize(
    "kind", ["recommendation", "definition", "applicability_trigger"]
)
def test_a_verified_draft_row_is_never_a_rule_for_a_stored_row_that_is_not_a_statement(
    world, monkeypatch, tmp_path, kind
):
    world["folder"] = _mirror(tmp_path / kind, [_row(SENTENCE, applies=None)])
    _retype(world["stmt"], kind)
    _on(world, monkeypatch)
    assert _rules(world) == {}


@pytest.mark.parametrize("kind", ["recommendation", "definition"])
def test_a_verified_draft_row_never_names_a_field_for_a_stored_row_of_those_types(
    world, monkeypatch, tmp_path, kind
):
    world["folder"] = _mirror(tmp_path / f"n{kind}", [_row(SENTENCE, applies=None)])
    _on(world, monkeypatch)
    row = {
        "id": "r1",
        "requirement_type": kind,
        "requirement_text": SENTENCE,
        "raw_unit": "barg",
        "unit": "barg",
    }
    assert rule_roles.reviewed_names([row], "Pressure Safety Valve") == {}
    row["requirement_type"] = (
        "numeric_limit"  # the same row as a numeric limit IS mapped: the control
    )
    assert rule_roles.reviewed_names([row], "Pressure Safety Valve") == {
        "r1": "design pressure"
    }
