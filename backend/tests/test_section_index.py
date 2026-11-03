"""Test B / HAZOP (part of #805): attachments, appendix and table titles are sections too, indexed at review time.
Invented procedure text of the same SHAPE (a catch-all attachments heading with coded attachment titles and table titles
inside it); never a real document's text."""

from __future__ import annotations

import pytest

from app import playbooks, section_index
from app.config import settings
from tests.test_w5b_679_playbooks import (  # noqa: F401  (fixtures and helpers)
    by_id,
    chunker,
    d,
    db,
    extract,
    hold,
    run,
    temp_storage,
    upload,
)

LINES = [
    ("Heading1", "Purpose and scope"),
    (
        None,
        "This procedure describes how a HAZOP study is carried out. The scope covers all new units.",
    ),
    ("Heading1", "Study team"),
    (
        None,
        "The study leader chairs the sessions. A scribe records the worksheet. Team members attend.",
    ),
    ("Heading1", "Attachments and templates"),
    (None, "The attachments below are part of this procedure."),
    (None, "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION"),
    (
        None,
        "The plant is divided into nodes, each a section with a clear design intent.",
    ),
    (None, "ZX-77-ATT03 - GUIDEWORDS IN STUDY SESSIONS"),
    (None, "Guidewords such as no, more and less are applied to each parameter."),
    (None, "Table A03.1: List of Parameters and Guidewords"),
    (None, "ZX-77-ATT04 - STUDY METHOD"),
    (
        None,
        "Each consequence is ranked with the risk matrix using severity and likelihood.",
    ),
]


def ingest_lines(tmp_path) -> str:
    xml = "".join(
        d.para(text, style=style) if style else d.para(text) for style, text in LINES
    )
    path = d.build(tmp_path / "proc.docx", xml)
    with path.open("rb") as fh:
        row, _job, _dup = upload.ingest(fh, "proc.docx")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (row["id"],))
    return row["id"]


def h04(tmp_path, monkeypatch, on):
    monkeypatch.setattr(settings, "section_index_enabled", on)
    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    monkeypatch.setattr(settings, "playbook_presence_without_standard_enabled", True)
    return by_id(run(ingest_lines(tmp_path)))["H04"]


# --- the headings of any kind -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION",
        "Annex B - Calibration of the method",
        "Appendix C: Data sheets",
        "Attachment 4 \u2013 Reporting template",
        "Table B7.2: Invented targets",
        "Table 3. Pump list",
        "Figure 2 - Flow of the method",
    ],
)
def test_headings_of_any_kind_are_recognised_by_class(line):
    assert section_index.heading_of_line(line, in_attachment=False) == line


@pytest.mark.parametrize(
    "line",
    [
        "Table B7.2 is used to rate the invented scenario",
        "Table 4 shows the value",
        "ATTACHMENTS AND TEMPLATES",
        "The attachment ATT02 describes the nodes in detail and is part of the study basis.",
        "1. Reliability - a guard reduces the invented loss by at least a factor of two.",
    ],
)
def test_prose_a_plain_heading_and_a_sentence_item_are_not_indexed_headings(line):
    assert section_index.heading_of_line(line, in_attachment=True) is None


def test_a_short_numbered_item_is_a_heading_only_inside_an_attachment():
    line = "6. Independent Protection Layers"
    assert section_index.heading_of_line(line, in_attachment=True) == line
    assert section_index.heading_of_line(line, in_attachment=False) is None


# --- refine, in memory ------------------------------------------------------------------------------------------------


def chunk(text, section="5. ATTACHMENTS AND TEMPLATES"):
    return {
        "section": section,
        "context": section,
        "text": text,
        "page_start": 1,
        "page_end": 2,
        "ordinal": 7,
        "locator": "page 1",
    }


def test_refine_splits_a_catch_all_passage_at_its_coded_titles_and_keeps_the_pages(
    monkeypatch,
):
    monkeypatch.setattr(settings, "section_index_enabled", True)
    pages = {
        1: ["intro", "ZX-77-ATT02 - NODES"],
        2: ["nodes text", "ZX-77-ATT03 - GUIDEWORDS"],
    }
    monkeypatch.setattr(section_index, "_pages", lambda document_id: pages)
    text = (
        "intro\nZX-77-ATT02 - NODES\nnodes text\nZX-77-ATT03 - GUIDEWORDS\nwords text"
    )
    out = section_index.refine([chunk(text)], "doc")
    assert [c["section"] for c in out] == [
        "5. ATTACHMENTS AND TEMPLATES",
        "ZX-77-ATT02 - NODES",
        "ZX-77-ATT03 - GUIDEWORDS",
    ]
    assert [c["page_start"] for c in out[1:]] == [1, 2]
    assert (
        out[1]["text"].startswith("ZX-77-ATT02 - NODES")
        and "words text" not in out[1]["text"]
    )
    assert len({c["ordinal"] for c in out}) == 3  # each piece is its own passage
    assert (
        chunk(text)["section"] == "5. ATTACHMENTS AND TEMPLATES"
    )  # nothing stored changes


def test_refine_off_returns_the_body_as_it_was(monkeypatch):
    monkeypatch.setattr(settings, "section_index_enabled", False)
    body = [chunk("ZX-77-ATT02 - NODES\nx")]
    assert section_index.refine(body, "doc") is body


def test_a_dash_that_differs_between_the_chunk_and_the_page_text_still_finds_the_page(
    monkeypatch,
):
    monkeypatch.setattr(settings, "section_index_enabled", True)
    monkeypatch.setattr(
        section_index, "_pages", lambda d: {1: ["x"], 5: ["ZX-77-ATT05 - WORKSHEET"]}
    )
    out = section_index.refine([chunk("ZX-77-ATT05 \u2013 WORKSHEET\nrows")], "doc")
    assert (
        out[0]["page_start"] == 5
    )  # a later page than the stored range: found by the printed line


# --- the playbook rows -------------------------------------------------------------------------------------------------


def test_an_attachment_titled_for_the_element_is_its_own_section_when_on(
    tmp_path, monkeypatch
):
    row = h04(tmp_path, monkeypatch, on=True)
    assert row["state"] != "missing"
    assert "ATT02" in row["reason"] and row["section_state"] == "present"
    assert "page" in row["reason"]


def test_without_the_index_the_same_document_names_no_such_section(
    tmp_path, monkeypatch
):
    row = h04(tmp_path, monkeypatch, on=False)
    assert row["section_state"] != "present"
    assert row["reason"].startswith("unclear: no section of its own was found")


def test_a_cue_word_in_a_generic_title_is_not_a_section_about_the_element():
    found, _ = playbooks.available()
    element = next(
        e for e in found["sil_procedure"].elements if e.id == "S10"
    )  # SRS and records
    chunk_ = {
        "section": "4.2 REFERENCE DATA AND DOCUMENTATION",
        "context": "4. DEVELOPMENT",
    }
    settings.section_index_enabled = False
    assert (
        playbooks.own_section(element, chunk_) is True
    )  # the old behaviour: "documentation" is a cue
    settings.section_index_enabled = True
    try:
        assert playbooks.own_section(element, chunk_) is False
    finally:
        settings.section_index_enabled = False


def test_a_numbered_item_title_needs_more_than_one_word_in_common_with_the_element():
    found, _ = playbooks.available()
    element = next(
        e for e in found["hazop_procedure"].elements if e.id == "H06"
    )  # causes, consequences, safeguards
    settings.section_index_enabled = True
    try:
        item = {
            "section": "2. Initiating Cause Frequency",
            "context": "5. ATTACHMENTS",
            "heading_loose": True,
        }
        assert playbooks.own_section(element, item) is False
        clause = {
            "section": "2. Initiating Cause Frequency",
            "context": "5. ATTACHMENTS",
        }
        assert (
            playbooks.own_section(element, clause) is True
        )  # an original clause heading keeps the old rule
    finally:
        settings.section_index_enabled = False
