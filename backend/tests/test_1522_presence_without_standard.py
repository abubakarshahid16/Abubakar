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
        f"Section not found: {ELEMENT}. Required by {_clause()} per the draft HAZOP "
        "checklist (not yet engineer-approved); standard not held, its text is not "
        "quoted; engineer to confirm."
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


NODE = "The plant is divided into nodes, each a section with a clear design intent."


def _moved(sentence=NODE):
    rest = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    return [(t, b + " " + sentence) if t == "Analysis" else (t, b) for t, b in rest]


def _page_of(sections, title):
    return 1 + next(i for i, s in enumerate(sections, start=1) if s[0] == title)


def test_an_unclear_row_quotes_the_passage_verified_on_its_page(monkeypatch):
    _switches(monkeypatch)
    moved = _moved()
    doc = _doc("q1", moved)
    row = _row(_mine(_crs(_run(doc))[0]), ELEMENT)
    page = _page_of(moved, "Analysis")
    assert f'stated at page {page} (heading "Analysis"): "{NODE}"' in row["comment"]
    assert row["page_section"] == f"page {page}"
    with db.connect() as conn:
        text = conn.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?", (doc, page)
        ).fetchone()[0]
    assert playbooks.quote_in(NODE, text)


def test_the_quote_is_at_most_15_words(monkeypatch):
    _switches(monkeypatch)
    long = (
        "The plant is divided into nodes by the study leader before the sessions start, "
        "each node a part of the process with one design intent and its own lines."
    )
    row = _row(_mine(_crs(_run(_doc("q2", _moved(long))))[0]), ELEMENT)
    quote = row["comment"].split(': "', 1)[1].split('"', 1)[0]
    assert quote == " ".join(long.split()[:15])
    assert len(quote.split()) == 15


def test_a_quote_not_on_the_cited_page_is_not_shown(monkeypatch):
    _switches(monkeypatch)
    moved = _moved()
    doc = _doc("q3", moved)
    with db.connect() as conn:  # the page text no longer holds the passage
        conn.execute(
            "UPDATE pages SET text = 'Analysis' WHERE document_id = ? AND page_no = ?",
            (doc, _page_of(moved, "Analysis")),
        )
    row = _row(_mine(_crs(_run(doc))[0]), ELEMENT)
    assert NODE not in row["comment"]
    assert "no quote could be verified on the page text" in row["comment"]


def test_the_wording_names_the_draft_checklist_never_approved(monkeypatch):
    _switches(monkeypatch)
    cover = "HAZOP and SIL Procedure\nDocument HP-001 revision 0"
    rows = _mine(_crs(_run(_doc("w1", HAZOP_SECTIONS, cover=cover)))[0])
    sil = [r for r in rows if r["comment"].startswith("SIL")]
    hazop = [r for r in rows if r["comment"].startswith("HAZOP")]
    assert sil and hazop
    assert any(
        "per the draft SIL checklist (not yet engineer-approved)" in r["comment"]
        for r in sil
    )
    assert all("HAZOP checklist" not in r["comment"] for r in sil)
    assert all("approved playbook" not in r["comment"] for r in rows)
    assert all(
        "approved" not in r["comment"].replace("not yet engineer-approved", "")
        for r in rows
    )


def test_the_heading_named_is_the_one_holding_the_section_not_the_first_on_the_page(
    monkeypatch,
):
    _switches(monkeypatch)
    doc = _doc("h1", HAZOP_SECTIONS)
    nodes = _page_of(HAZOP_SECTIONS, CUT)
    with db.connect() as conn:  # a PDF-like page: another section's chunk comes first
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
            "text,token_count,content_hash,retrievable) VALUES (?,?,?,?,?,?,?,'prose',?,1,?,1)",
            (
                "h1-first",
                doc,
                "h1.pdf",
                0,
                nodes,
                nodes,
                "Preparation notes",
                "Preparation notes\nThe drawings are issued.",
                "h-h1-first",
            ),
        )
    row = _row(_mine(_crs(_run(doc))[0]), ELEMENT)
    assert f'section found at page {nodes} (heading "{CUT}")' in row["comment"]
    assert "Preparation notes" not in row["comment"]


@pytest.mark.parametrize("locator", [None, "4 > 4.6 > para 1-2"])
def test_a_chunk_spanning_pages_cites_the_verified_page_in_the_page_column(
    monkeypatch, locator
):
    _switches(monkeypatch)
    moved = _moved()
    doc = _doc("s1", moved)
    first = _page_of(moved, "Analysis")
    second = first + 1
    with (
        db.connect() as conn
    ):  # the chunk spans two pages; the passage is on the second
        conn.execute(
            "UPDATE chunks SET page_end = ?, locator = ?"
            " WHERE document_id = ? AND page_start = ?",
            (second, locator, doc, first),
        )
        conn.execute(
            "UPDATE pages SET text = 'Analysis' WHERE document_id = ? AND page_no = ?",
            (doc, first),
        )
        conn.execute(
            "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = ?",
            ("\n" + NODE, doc, second),
        )
    row = _row(_mine(_crs(_run(doc))[0]), ELEMENT)
    assert f'stated at page {second} (heading "Analysis"): "{NODE}"' in row["comment"]
    assert row["page_section"] == f"page {second}"
