"""Test B / HAZOP (part of #805): attachments, appendix and table titles are sections too, indexed at review time.
Invented procedure text of the same SHAPE (a catch-all attachments heading with coded attachment titles and table titles
inside it); never a real document's text."""

from __future__ import annotations

import json

import pytest

from app import db, playbooks, section_index
from app.config import settings
from tests.test_w5b_679_playbooks import (  # noqa: F401  (fixtures and helpers)
    by_id,
    chunker,
    d,
    extract,
    hold,
    run,
    temp_storage,
    upload,
)


@pytest.fixture(autouse=True)
def storage(request):
    """The helper module's temporary database, for every test here."""
    return request.getfixturevalue("temp_storage")


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
    (None, "Table B3.1: Invented list of words"),
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


def test_an_attachment_titled_for_the_element_is_named_as_the_closest_section_with_its_page_when_on(
    tmp_path, monkeypatch
):
    row = h04(tmp_path, monkeypatch, on=True)
    assert row["state"] != "missing"
    assert "ATT02" in row["reason"] and "closest section" in row["reason"]
    assert (
        "page" in row["reason"]
        and "ATT02 - CRITERIA FOR NODE SELECTION" in row["reason"]
    )


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
            "indexed_heading": True,
            "heading_code": False,
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


def test_the_words_of_a_partial_hit_and_of_no_title_depend_on_the_switch(monkeypatch):
    monkeypatch.setattr(settings, "section_index_enabled", True)
    assert section_index.own_words() == "the closest section is at"
    assert section_index.none_words() == "no section titled for it"
    monkeypatch.setattr(settings, "section_index_enabled", False)
    assert section_index.own_words() == "a section of its own was found at"
    assert section_index.none_words() == "no section of its own"


# --- the review's four defects, end to end on a document whose paragraphs sit on DIFFERENT pages -----------------------


def fake_doc(pages, chunks):
    """A stored document with these page texts ({number: text}) and these passages: the real review path reads exactly
    these tables. Each chunk is (page_start, page_end, section, text)."""
    doc_id = "doc_fake_" + str(abs(hash(str(chunks))) % 10**8)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'x','ready',?,'2026-11-03T00:00:00Z')",
            (doc_id, "proc.docx", "sha-" + doc_id, len(pages)),
        )
        for number, text in pages.items():
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,1)",
                (doc_id, number, text, len(text)),
            )
        for n, (start, end, section, text) in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,token_count,"
                "content_hash,retrievable,context,locator) VALUES (?,?,?,?,?,?,?,'prose',?,1,?,1,?,?)",
                (
                    f"{doc_id}:{n}",
                    doc_id,
                    "proc.docx",
                    n,
                    start,
                    end,
                    section,
                    text,
                    f"h{n}",
                    section,
                    f"page {start}",
                ),
            )
    return doc_id


def review_of(doc_id, on, element="H04"):
    from tests.test_w5b_679_playbooks import by_id, run

    names = (
        "section_index_enabled",
        "playbook_section_presence_enabled",
        "playbook_presence_without_standard_enabled",
    )
    saved = {n: getattr(settings, n) for n in names}
    settings.section_index_enabled = on
    settings.playbook_section_presence_enabled = True
    settings.playbook_presence_without_standard_enabled = True
    try:
        playbook = "sil_procedure" if element.startswith("S") else "hazop_procedure"
        return by_id(run(doc_id, playbook))[element]
    finally:
        for n, v in saved.items():
            setattr(settings, n, v)


ATT = "5. ATTACHMENTS AND TEMPLATES"
NODES = "The plant is divided into nodes, each a section with a clear design intent."


def test_a_heading_printed_on_a_later_page_is_cited_at_that_page():
    pages = {
        1: "Cover\nThe procedure follows.",
        2: "More text of the body.",
        3: "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION\n" + NODES,
    }
    text = (
        "Cover\nThe procedure follows.\nMore text of the body.\nZX-77-ATT02 - CRITERIA FOR NODE SELECTION\n"
        + NODES
    )
    row = review_of(fake_doc(pages, [(1, 3, ATT, text)]), on=True)
    assert "page 3" in row["reason"] and row["cited_page"] == 3


def test_the_same_heading_printed_twice_gets_each_pass_the_page_of_its_own_print(
    monkeypatch,
):
    heading = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION"
    pages = {2: heading + "\nfirst text", 5: heading + "\nsecond text"}
    monkeypatch.setattr(settings, "section_index_enabled", True)
    doc = fake_doc(
        pages,
        [(2, 2, ATT, heading + "\nfirst text"), (5, 5, ATT, heading + "\nsecond text")],
    )
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=? order by ordinal", (doc,)
        )
    ]
    out = section_index.refine(body, doc)
    assert [c["page_start"] for c in out] == [2, 5]


def test_a_title_repeated_on_every_page_is_a_running_header_never_a_heading(
    monkeypatch,
):
    header = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION"
    pages = {n: f"{header}\nbody of page {n}" for n in range(1, 6)}
    text = "\n".join(pages.values())
    monkeypatch.setattr(settings, "section_index_enabled", True)
    doc = fake_doc(pages, [(1, 5, ATT, text)])
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=?", (doc,)
        )
    ]
    out = section_index.refine(body, doc)
    assert (
        len(out) == 1 and out[0]["section"] == ATT
    )  # not split into five pieces cited at page 1


def test_an_attachment_with_one_cue_word_in_its_title_is_the_closest_section_never_found():
    pages = {1: "Body.", 2: "ZX-77-ATT05 - NODE REGISTER FORMS\n" + NODES}
    row = review_of(
        fake_doc(
            pages, [(1, 2, ATT, "Body.\nZX-77-ATT05 - NODE REGISTER FORMS\n" + NODES)]
        ),
        on=True,
    )
    assert row["section_state"] != "present"
    assert row["reason"].startswith("unclear: the closest section is at page 2")


def test_a_contents_list_without_a_contents_heading_is_not_indexed():
    toc = (
        "List of attachments\nZX-77-ATT02 - CRITERIA FOR NODE SELECTION ........ 9\n"
        "ZX-77-ATT03 - GUIDEWORDS IN STUDY SESSIONS ........ 10"
    )
    doc = fake_doc({1: toc}, [(1, 1, ATT, toc)])
    off, on = review_of(doc, on=False), review_of(doc, on=True)
    assert on["section_state"] == off["section_state"]
    assert (
        "ATT02" not in on["reason"].split(":")[1][:60]
    )  # no section was made of a contents entry


def test_three_heading_like_lines_in_a_row_are_a_list_even_without_leaders_or_numbers(
    monkeypatch,
):
    toc = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION 9\nZX-77-ATT03 - GUIDEWORDS IN STUDY SESSIONS 10\nZX-77-ATT04 - STUDY METHOD 11"
    monkeypatch.setattr(settings, "section_index_enabled", True)
    doc = fake_doc({1: toc}, [(1, 1, ATT, toc)])
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=?", (doc,)
        )
    ]
    assert len(section_index.refine(body, doc)) == 1


def test_a_true_section_not_found_stays_not_found_when_only_a_contents_list_names_it():
    toc = "ZX-77-ATT09 - DEMAND MODE AND PROOF TEST ........ 9\nZX-77-ATT10 - FORMS ........ 10"
    doc = fake_doc({1: toc}, [(1, 1, ATT, toc)])
    row = review_of(doc, on=True, element="S08")
    assert (
        row["section_state"] == review_of(doc, on=False, element="S08")["section_state"]
    )


def test_a_closest_section_whose_own_text_states_nothing_is_cited_with_its_verified_title():
    title = "ZX-77-ATT05 - PROPOSED STUDY WORKSHEET"
    pages = {1: "Body.", 2: title}
    row = review_of(
        fake_doc(pages, [(1, 2, ATT, "Body.\n" + title)]), on=True, element="H08"
    )
    assert (
        f'"{title}"' in row["reason"]
        and "no quote could be verified" not in row["reason"]
    )


@pytest.mark.parametrize(
    "line",
    [
        "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION ........ 9",
        "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION\t12",
        "Table B3.1: Invented list of words .... 14",
    ],
)
def test_a_contents_entry_with_leaders_or_a_tab_and_a_page_number_is_never_a_heading(
    line,
):
    assert section_index.heading_of_line(line, in_attachment=True) is None


def test_the_same_heading_printed_twice_in_one_passage_is_cited_at_each_print(
    monkeypatch,
):
    heading = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION"
    pages = {2: heading + "\nfirst text", 5: heading + "\nsecond text"}
    monkeypatch.setattr(settings, "section_index_enabled", True)
    doc = fake_doc(
        pages, [(2, 5, ATT, heading + "\nfirst text\n" + heading + "\nsecond text")]
    )
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=?", (doc,)
        )
    ]
    out = section_index.refine(body, doc)
    assert [c["page_start"] for c in out] == [2, 5]
    assert out[0]["page_end"] == 5 and out[1]["page_start"] == 5


def test_a_list_of_attachments_printed_earlier_without_page_numbers_is_not_the_heading_page():
    listing = "ZX-77-ATT01 - FLOW OF THE METHOD\nZX-77-ATT02 - CRITERIA FOR NODE SELECTION\nZX-77-ATT03 - STUDY METHOD"
    real = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION\n" + NODES
    pages = {1: listing, 3: real}
    row = review_of(
        fake_doc(pages, [(1, 3, ATT, listing + "\nThe attachments follow.\n" + real)]),
        on=True,
    )
    assert row["cited_page"] == 3 and "page 3" in row["reason"]


def test_a_list_of_headings_on_an_earlier_page_is_not_the_heading_even_when_the_passage_holds_only_the_real_one(
    monkeypatch,
):
    monkeypatch.setattr(settings, "section_index_enabled", True)
    listing = "ZX-77-ATT01 - FLOW OF THE METHOD\nZX-77-ATT02 - CRITERIA FOR NODE SELECTION\nZX-77-ATT03 - STUDY METHOD"
    real = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION\n" + NODES
    doc = fake_doc({1: listing, 3: real}, [(1, 3, ATT, "Intro.\n" + real)])
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=?", (doc,)
        )
    ]
    out = section_index.refine(body, doc)
    assert [c["page_start"] for c in out if c.get("indexed_heading")] == [3]


def test_three_heading_like_lines_in_a_row_in_a_passage_are_not_split_into_sections(
    monkeypatch,
):
    monkeypatch.setattr(settings, "section_index_enabled", True)
    page = "Intro.\nZX-77-ATT01 - A TITLE\nbody one\nZX-77-ATT02 - B TITLE\nbody two\nZX-77-ATT03 - C TITLE\nbody three"
    run = "ZX-77-ATT01 - A TITLE\nZX-77-ATT02 - B TITLE\nZX-77-ATT03 - C TITLE"
    doc = fake_doc({1: page}, [(1, 1, ATT, run)])
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=?", (doc,)
        )
    ]
    assert len(section_index.refine(body, doc)) == 1


# --- review findings (PR 1688, round 2): contents entries with plain spaces, captions, the switch off -------------------


def _rows(doc):
    return review_of(doc, on=True), review_of(doc, on=False)


def test_a_contents_entry_with_a_page_number_after_plain_spaces_is_never_a_heading():
    toc = "Contents\nZX-77-ATT02 - CRITERIA FOR NODE SELECTION 5"
    doc = fake_doc({1: toc}, [(1, 1, ATT, toc)])
    on, off = _rows(doc)
    assert "the closest section is at" not in on["reason"]
    assert on["section_state"] == off["section_state"]
    assert "page 1" not in on["reason"].split(":")[1][:60]


def test_two_numbered_contents_entries_before_the_real_heading_do_not_hide_it():
    toc = "ZX-77-ATT03 - GUIDEWORDS IN STUDY SESSIONS 6\nZX-77-ATT04 - STUDY METHOD 7"
    real = "ZX-77-ATT02 - CRITERIA FOR NODE SELECTION\n" + NODES
    doc = fake_doc({1: toc, 2: real}, [(1, 2, ATT, toc + "\n" + real)])
    row = review_of(doc, on=True)
    assert "no section titled for it" not in row["reason"]
    assert "page 2" in row["reason"]
    assert '"ZX-77-ATT02 - CRITERIA FOR NODE SELECTION"' in row["reason"]


def test_a_table_caption_in_an_unrelated_attachment_is_never_the_found_section():
    caption = "Table 4: Plant nodes cost estimate"
    pages = {
        1: "Body.",
        2: "ZX-77-ATT07 - BUDGET FORMS\n" + caption + "\nThe cost is invented.",
    }
    text = "Body.\nZX-77-ATT07 - BUDGET FORMS\n" + caption + "\nThe cost is invented."
    doc = fake_doc(pages, [(1, 2, ATT, text)])
    row = review_of(doc, on=True)
    assert row["section_state"] != "present"
    assert "a section of its own was found" not in row["reason"]
    # the caption itself is never an indexed heading that is the element's section
    body = [
        dict(r)
        for r in db.connect().execute(
            "select * from chunks where document_id=?", (doc,)
        )
    ]
    settings.section_index_enabled = True
    try:
        out = section_index.refine(body, doc)
        cap = [c for c in out if c.get("section") == caption]
        assert cap and cap[0]["heading_caption"] is True
        el = next(
            e
            for e in playbooks.available()[0]["hazop_procedure"].elements
            if e.id == "H04"
        )
        assert section_index.title_hit(el, cap[0], caption, playbooks._hits) is False
    finally:
        settings.section_index_enabled = False


@pytest.mark.parametrize(
    "line",
    [
        "Fig. 3: Plant nodes layout",
        "Figure C2 - Plant nodes layout",
        "Tab. 5: Plant nodes list",
    ],
)
def test_caption_styles_are_recognised_as_captions(line):
    assert section_index.heading_of_line(line, in_attachment=False) == line
    assert section_index._is_caption(line)


#: The shape of one evidence entry with the switch off: no `near_section` key (the report matches main byte for byte).
EXPECTED_OFF_KEYS = [
    "groups",
    "in_text",
    "locator",
    "method",
    "ordinal",
    "own_section",
    "quote",
]


def test_with_the_switch_off_the_evidence_entries_have_exactly_the_stored_shape():
    doc = fake_doc({1: "Body.\n" + NODES}, [(1, 1, ATT, "Body.\n" + NODES)])
    row = review_of(doc, on=False)
    assert row
    entries = _all_evidence(doc)
    assert entries
    for e in entries:
        assert sorted(k for k in e if k != "heading_guess") == EXPECTED_OFF_KEYS
        assert "near_section" not in json.dumps(e)


def _all_evidence(doc):
    seen = []
    orig = playbooks._match

    def spy(element, body):
        result = orig(element, body)
        for key in ("evidence", "candidates"):
            seen.extend(result.get(key) or [])
        return result

    playbooks._match = spy
    try:
        review_of(doc, on=False)
    finally:
        playbooks._match = orig
    return seen
