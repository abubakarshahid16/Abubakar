"""ONE REVIEWER, PR 4: the review's notes (pages not read, rule books not held, standards not cited) are points of the one list, internal only,
never a Fail, never twice. Invented data only."""

from __future__ import annotations

import json

import pytest

from app import (
    applicability,
    crs_ai_words,
    db,
    review_point_decisions,
    review_points_service,
)
from app.config import settings
from tests.test_b1_review_points import (
    ai_run,
    decide,
    points_of,
    sheet_text,
    world_with_both,
)
from tests.test_agent_review_crs import mk
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _submittal,
    temp_db,
)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(
        settings, "ai_review_calculator_enabled", True
    )  # the notes are the calculator's: behind its setting (R48m 3)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)
    monkeypatch.setattr(
        applicability, "standards_check", lambda *a, **k: {"required_not_cited": []}
    )


def world(coverage=None, missing=()):
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai = ai_run(doc, [mk("R-1", "Fail", "Fail")])
    with db.connect() as conn:
        if coverage is not None:
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                (json.dumps({"page_coverage": coverage}), ai),
            )
        for name in missing:
            conn.execute(
                "INSERT INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
                (ai, name, "not in the library"),
            )
    return doc, ai, _client(doc, "doc_std")


def notes(listing):
    return [p for p in listing["points"] if p["id"].startswith("note:")]


def test_unread_pages_are_one_question_point_naming_them():
    doc, ai, client = world({"pages_total": 12, "pages_not_read_into_fields": [3, 7]})
    got = notes(points_of(client, doc))
    assert len(got) == 1 and got[0]["name"] == "Pages not read"
    assert "2 of 12 pages" in got[0]["action"] and "3, 7" in got[0]["action"]
    assert (
        got[0]["tile"] == "questions"
        and got[0]["firm"] is None
        and got[0]["source"] == "ai_review"
    )


def test_every_page_read_or_no_record_makes_no_pages_point_and_says_no_zero():
    doc, ai, client = world({"pages_total": 12, "pages_not_read_into_fields": []})
    assert not [
        p for p in notes(points_of(client, doc)) if p["name"] == "Pages not read"
    ]


def test_a_run_with_no_page_record_says_nothing_never_zero_pages_unread():
    doc, ai, client = world(None)
    assert notes(points_of(client, doc)) == []


def test_a_rule_book_not_held_is_a_point_that_says_nothing_is_met():
    doc, ai, client = world(missing=("Invented Spec A", "Invented Spec B"))
    got = notes(points_of(client, doc))
    assert sorted(p["name"] for p in got) == [
        "Rule book not held: Invented Spec A",
        "Rule book not held: Invented Spec B",
    ]
    assert all(
        "Nothing is said to be met" in p["action"] and p["rank"] == 4 for p in got
    )


def test_standards_not_cited_is_ONE_question_point_never_a_fail(monkeypatch):
    rows = [
        {"identifier": "API 521", "held": True, "by": "type", "reason": "invented"},
        {"identifier": "ISO 4126", "held": False, "by": "type", "reason": "invented"},
        {"identifier": "API 521", "held": True, "by": "type", "reason": "invented"},
    ]
    monkeypatch.setattr(
        applicability, "standards_check", lambda *a, **k: {"required_not_cited": rows}
    )
    doc, ai, client = world()
    got = [
        p for p in notes(points_of(client, doc)) if p["name"] == "Standards not cited"
    ]
    assert len(got) == 1 and got[0]["rank"] == 4 and got[0]["tile"] == "questions"
    assert (
        "API 521" in got[0]["action"]
        and "ISO 4126" in got[0]["action"]
        and "not a finding" in got[0]["action"]
    )
    assert got[0]["firm"] is None and "Fail" not in got[0]["pill"]


def test_a_note_is_decided_like_any_point_and_never_reaches_the_contractor_copy(
    monkeypatch,
):
    monkeypatch.setattr(
        applicability,
        "standards_check",
        lambda *a, **k: {
            "required_not_cited": [
                {
                    "identifier": "API 521",
                    "held": True,
                    "by": "type",
                    "reason": "invented",
                }
            ]
        },
    )
    doc, ai, client = world({"pages_total": 5, "pages_not_read_into_fields": [2]})
    pid = next(
        p["id"]
        for p in notes(points_of(client, doc))
        if p["name"] == "Standards not cited"
    )
    assert decide(client, doc, pid, "keep").status_code == 200
    after = next(p for p in points_of(client, doc)["points"] if p["id"] == pid)
    assert after["decision"]["state"] == review_point_decisions.KEEP
    from app import agent_review_jobs

    path = review_points_service.decided_ai_sheet(  # LP2 round 2: drawn for a viewer, who here may read the paper
        ai, doc, "contractor", agent_review_jobs.run_dir(ai), frozenset({doc})
    )
    text = sheet_text(path.read_bytes())
    assert (
        "Standards not cited" not in text
        and "API 521" not in text
        and "Pages not read" not in text
    )


def test_a_check_that_could_not_run_is_a_point_not_an_all_fine(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(applicability, "standards_check", boom)
    doc, ai, client = world()
    got = notes(points_of(client, doc))
    assert [p["name"] for p in got] == ["The standards-cited check did not run"]
    assert (
        "RuntimeError" in got[0]["action"] and "not a clean result" in got[0]["action"]
    )


def test_with_a_rule_check_run_the_notes_are_not_said_twice(monkeypatch):
    monkeypatch.setattr(
        applicability,
        "standards_check",
        lambda *a, **k: {
            "required_not_cited": [
                {
                    "identifier": "API 521",
                    "held": True,
                    "by": "type",
                    "reason": "invented",
                }
            ]
        },
    )
    doc, rc, ai, client = world_with_both()
    assert notes(points_of(client, doc)) == []


def test_no_code_word_reaches_the_words_of_a_note(monkeypatch):
    monkeypatch.setattr(
        applicability,
        "standards_check",
        lambda *a, **k: {
            "required_not_cited": [
                {
                    "identifier": "API 521",
                    "held": True,
                    "by": "type",
                    "reason": "invented",
                }
            ]
        },
    )
    doc, ai, client = world(
        {"pages_total": 5, "pages_not_read_into_fields": [2]},
        missing=("Invented Spec A",),
    )
    for p in notes(points_of(client, doc)):
        assert not crs_ai_words.has_banned(p["name"] + " " + p["action"])


# ---------------------------------------------------------------------------------------- the questions of code lines read as GROUPS


def _code_q(item, field, why, tag="T1", rule="PSV-1"):
    return {
        **mk(item, "Query", None, why=why),
        "source": "code",
        "code_kind": "checklist",
        "field": field,
        "equipment_tag": tag,
        "clause": rule,
        "why": why,
    }


def test_checks_the_sheet_could_not_make_for_the_same_reason_are_one_group_across_fields_and_tags():
    from app import review_points as rp

    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {},
        "readable": frozenset(),
    }
    defer = [
        _code_q(
            f"C-{i}",
            f,
            f"{f} is marked 'By Contractor' on page {i}; the contractor is to provide the value.",
            tag=f"T{i}",
        )
        for i, f in enumerate(["Valve size", "Back press. Variable", "Orifice"], 1)
    ]
    phase = [
        _code_q(
            "C-9",
            "Set pressure",
            "Could not be checked: the fluid phase is not stated.",
            rule="PSV-19",
        ),
        _code_q(
            "C-10",
            "Density",
            "Could not be checked: the fluid phase is not stated.",
            rule="PSV-20",
        ),
    ]
    points = [rp.ai_point(x, ctx) for x in defer + phase]
    keys = {p["id"]: p["group_key"] for p in points}
    assert (
        len({keys["ai:r:C-1"], keys["ai:r:C-2"], keys["ai:r:C-3"]}) == 1
        and keys["ai:r:C-1"] is not None
    )
    assert (
        keys["ai:r:C-9"] == keys["ai:r:C-10"] and keys["ai:r:C-9"] != keys["ai:r:C-1"]
    )
    rp.with_groups(points)
    assert {
        p["pill"] for p in points if p["id"] in ("ai:r:C-1", "ai:r:C-2", "ai:r:C-3")
    } == {"Question · 3 alike"}


def test_a_model_question_and_a_code_proof_failure_are_not_pulled_into_a_code_group():
    from app import review_points as rp

    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {},
        "readable": frozenset(),
    }
    model = rp.ai_point(mk("R-1", "Query", None, why="x y"), ctx)
    assert model["group_key"] is None  # no book, no clause: never grouped (as before)
    assert rp.code_question_key(mk("R-1", "Query", None, why="x y")) is None


# ---------------------------------------------------------------------------------------- the checks that are only "stated" are summed in ONE point


def test_the_presence_summary_is_one_internal_point_with_the_counts():
    from app import review_points_notes as N

    calc = {"presence_checked": 81, "presence_stated": 70, "presence_missing": 11}
    got = N.presence_point("run1", calc)
    assert (
        got["id"] == "note:run1:presence"
        and got["rank"] == 4
        and got["tile"] == "questions"
        and got["firm"] is None
    )
    assert (
        "81 fields are only checked as stated (not compared): stated 70, missing 11"
        in got["action"]
    )
    assert (
        N.presence_point(
            "r", {"presence_checked": 0, "presence_stated": 0, "presence_missing": 0}
        )
        is None
    )
    assert (
        N.presence_point("r", None) is None
        and N.presence_point("r", {"presence_checked": "x"}) is None
    )


def test_the_run_counts_carry_the_presence_numbers_and_the_list_shows_the_summary(
    monkeypatch,
):
    doc, ai, client = world()
    with db.connect() as conn:
        conn.execute(
            "UPDATE agent_review_run SET counts_json = ? WHERE run_id = ?",
            (
                json.dumps(
                    {
                        "calculator": {
                            "presence_checked": 4,
                            "presence_stated": 3,
                            "presence_missing": 1,
                        }
                    }
                ),
                ai,
            ),
        )
    got = [p for p in notes(points_of(client, doc)) if p["id"].endswith(":presence")]
    assert len(got) == 1 and "4 fields are only checked as stated" in got[0]["action"]


def test_with_the_calculator_setting_off_the_list_has_no_notes_at_all(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_calculator_enabled", False)
    doc, ai, client = world(
        {"pages_total": 12, "pages_not_read_into_fields": [3, 7]},
        missing=("Invented Spec A",),
    )
    assert notes(points_of(client, doc)) == []  # byte-same as before the notes existed


def test_the_numbers_that_make_two_questions_different_stay_in_the_group_key_but_the_page_goes():
    from app import review_points as rp

    def key(why, field="Rate"):
        return rp.code_question_key(
            {"source": "code", "field": field, "equipment_tag": "T1", "why": why}
        )

    assert key("two values conflict: 10 vs 12") != key("two values conflict: 7 vs 9")
    assert key("two values conflict: 10 vs 12", "Rate") == key(
        "two values conflict: 10 vs 12", "Other"
    )  # the field name goes
    assert key("is marked 'By Contractor' on page 3") == key(
        "is marked 'By Contractor' on page 4"
    )
    assert key("is marked 'By Contractor' on pages 1-5; state it") == key(
        "is marked 'By Contractor' on page 2; state it"
    )
