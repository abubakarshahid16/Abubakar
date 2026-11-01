"""#1522, owner decision 1 Nov: a playbook's section-presence check runs even when
the playbook's standard is NOT held (PLAYBOOK_PRESENCE_WITHOUT_STANDARD_ENABLED,
only together with PLAYBOOK_SECTION_PRESENCE_ENABLED).

INVENTED documents built in code only (CLAUDE.md rule 3). No model. Never "met",
"compliant" or Pass without the standard: the state stays standard_not_held.
"""

from __future__ import annotations

import pytest

from app import db, playbooks
from app.config import settings
from tests.test_1522_procedure_playbook_rows import (  # noqa: F401  (temp_storage is an autouse fixture)
    _crs,
    _doc,
    _mine,
    _run,
    temp_storage,
)
from tests.test_w5b_679_playbooks import HAZOP_SECTIONS, hold

CUT = "Nodes"
ELEMENT = "Division of the plant into nodes"


def _switches(monkeypatch, *, presence=True, without=True):
    monkeypatch.setattr(settings, "procedure_playbook_rows_enabled", True)
    monkeypatch.setattr(settings, "playbook_section_presence_enabled", presence)
    monkeypatch.setattr(settings, "playbook_presence_without_standard_enabled", without)


def _row(rows, title):
    return next(r for r in rows if r["comment"].split(" (")[0].endswith(title))


def _clause():
    found, _ = playbooks.available()
    el = next(e for e in found["hazop_procedure"].elements if e.title == ELEMENT)
    return f"{el.standard} {el.clause}"


def test_the_switch_is_off_by_default():
    assert settings.playbook_presence_without_standard_enabled is False


def test_a_missing_section_without_the_standard_is_section_not_found(monkeypatch):
    _switches(monkeypatch)
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    row = _row(_mine(_crs(_run(_doc("p2", cut)))[0]), ELEMENT)
    assert (
        f"Section not found: {ELEMENT}. Required by {_clause()} per the approved playbook; "
        "standard not held, its text is not quoted; engineer to confirm."
    ) in row["comment"]
    assert row["playbook_state"] == playbooks.STANDARD_NOT_HELD
    assert row["engineer_confirmed"] is False
    low = row["comment"].lower()
    assert " met" not in low and "compliant" not in low and "pass" not in low
    assert row["page_section"] == ""


def test_a_present_section_without_the_standard_gives_the_found_row_with_its_page(
    monkeypatch,
):
    _switches(monkeypatch)
    row = _row(_mine(_crs(_run(_doc("p1", HAZOP_SECTIONS)))[0]), ELEMENT)
    page = 1 + next(i for i, s in enumerate(HAZOP_SECTIONS, start=1) if s[0] == CUT)
    assert f'section found at page {page} (heading "{CUT}")' in row["comment"]
    assert "its content is not checked because" in row["comment"]
    assert "is not held; engineer to confirm" in row["comment"]
    assert "Section not found" not in row["comment"]
    assert row["playbook_state"] == playbooks.STANDARD_NOT_HELD
    assert row["page_section"] == f"page {page}"
    low = row["comment"].lower()
    assert " met" not in low and "compliant" not in low and "pass" not in low


def test_a_passing_mention_in_another_section_is_not_the_section(monkeypatch):
    _switches(monkeypatch)
    # "Worksheet" still mentions recommendations in passing; the follow-up section is gone
    cut = [s for s in HAZOP_SECTIONS if s[0] != "Follow-up"]
    row = _row(
        _mine(_crs(_run(_doc("p3", cut)))[0]), "Recommendations and their follow-up"
    )
    assert (
        "Section not found: Recommendations and their follow-up. Required by IEC 61882 7"
        in row["comment"]
    )
    assert row["playbook_state"] == playbooks.STANDARD_NOT_HELD


def test_content_stated_under_another_heading_is_unclear_never_not_found(monkeypatch):
    _switches(monkeypatch)
    # the node text sits in full under the "Analysis" heading: not proven absent
    moved = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    moved = [
        (
            t,
            b
            + " The plant is divided into nodes, each a section with a clear design intent.",
        )
        if t == "Analysis"
        else (t, b)
        for t, b in moved
    ]
    row = _row(_mine(_crs(_run(_doc("p5", moved)))[0]), ELEMENT)
    page = 1 + next(i for i, s in enumerate(moved, start=1) if s[0] == "Analysis")
    assert (
        f'unclear: no section of its own was found, but it is stated at page {page} (heading "Analysis")'
        in (row["comment"])
    )
    assert "Section not found" not in row["comment"]
    assert row["playbook_state"] == playbooks.STANDARD_NOT_HELD


def test_a_document_without_headings_is_never_section_not_found(monkeypatch):
    _switches(monkeypatch)
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    doc = _doc("p6", cut)
    with db.connect() as conn:
        conn.execute(
            "UPDATE chunks SET section = NULL, context = NULL WHERE document_id = ?",
            (doc,),
        )
    rows = _mine(_crs(_run(doc))[0])
    assert rows and all("Section not found" not in r["comment"] for r in rows)
    assert (
        "no section heading was read from this document"
        in _row(rows, ELEMENT)["comment"]
    )


def test_an_unclear_result_stays_unclear(monkeypatch):
    _switches(monkeypatch)
    # a section of its own ("Follow-up" holds no cue; "Recommendations" does) without an owner
    part = [
        ("Recommendations", "Recommendations are tracked until closed out.")
        if t == "Follow-up"
        else (t, b)
        for t, b in HAZOP_SECTIONS
    ]
    part = [
        (
            t,
            b.replace(
                "with an action column for recommendations", "with one column per field"
            ),
        )
        for t, b in part
    ]
    row = _row(
        _mine(_crs(_run(_doc("p4", part)))[0]), "Recommendations and their follow-up"
    )
    assert "unclear:" in row["comment"] and "owner" in row["comment"]
    assert (
        "Section not found" not in row["comment"]
        and "section found at" not in row["comment"]
    )
    assert row["playbook_state"] == playbooks.STANDARD_NOT_HELD


def test_the_report_keeps_the_state_and_adds_the_section_result(monkeypatch):
    _switches(monkeypatch)
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    found, _ = playbooks.available()
    doc = _doc("p2", cut)
    report = playbooks.review(
        doc, found["hazop_procedure"], allowed_document_ids=frozenset({doc})
    )
    e = next(e for e in report["elements"] if e["title"] == ELEMENT)
    assert (
        e["state"] == playbooks.STANDARD_NOT_HELD
        and e["section_state"] == playbooks.MISSING
    )
    assert report["counts"]["present"] == 0
    assert report["counts"]["standard_not_held"] == len(
        found["hazop_procedure"].elements
    )


@pytest.mark.parametrize(
    "presence,without", [(True, False), (False, True), (False, False)]
)
def test_off_or_without_presence_is_byte_identical(monkeypatch, presence, without):
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    _switches(monkeypatch, presence=presence, without=False)
    before = _crs(_run(_doc("p2", cut)))
    _switches(monkeypatch, presence=presence, without=without)
    after = _crs(_run(_doc("p2b", cut)))

    def strip(crs):
        rows, _meta = crs
        return [
            {k: v for k, v in r.items() if k != "document_name"} for r in _mine(rows)
        ]

    assert strip(before) == strip(after)
    assert all("is not in the library" in r["comment"] for r in _mine(after[0]))

    found, _ = playbooks.available()
    report = playbooks.review(
        "p2b", found["hazop_procedure"], allowed_document_ids=frozenset({"p2b"})
    )
    if not (presence and without):
        assert all("section_state" not in e for e in report["elements"])


def test_the_standard_held_path_is_unchanged(monkeypatch):
    hold("IEC 61882")
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    _switches(monkeypatch, without=False)
    before = _mine(_crs(_run(_doc("p2", cut)))[0])
    _switches(monkeypatch, without=True)
    after = _mine(_crs(_run(_doc("p2b", cut)))[0])
    assert [r["comment"] for r in before] == [r["comment"] for r in after]
    assert all("Section not found" not in r["comment"] for r in after)
    assert all(r["playbook_state"] != playbooks.STANDARD_NOT_HELD for r in after)
