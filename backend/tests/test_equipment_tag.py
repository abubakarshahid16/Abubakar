"""Which equipment a fact describes.

A DATASHEET CAN COVER MORE THAN ONE THING. `DS-0000-DAS-I-01` is four pressure
safety valves on four pages - PSV-4301, PSV-4303, PSV-4360, PSV-4306 - each
with its own set pressure, its own relieving temperature, its own everything.
Without a tag those fifty-five facts are one undifferentiated pile, and a
finding against "the set pressure" names a quantity four different valves
state differently.

THE TAG IS READ, NEVER GUESSED, AND NEVER CLEANED. `PSV-4301 A/B (for GC-9,
10 & 19) & PSV-3301 A/B (for GC-21)` is stored exactly as the sheet wrote it,
because it is an identifier somebody will read off a P&ID or type into a
search box, and a tidied version matches nothing.

TWO SHAPES, BOTH REAL. The drum sheet writes `Tag number :` in one cell and
`2003-47-V-0001A/B` in the next; the PSV sheet puts the key and the tag in one
text block with nothing beside it. A reader that understood only the first
would find no tag on any page of the second.

AND THE IDENTITY RULE IS THE CAREFUL PART. The tag joins `fact_key` only when
the document carries two or more, because identity is what tells things apart
and a tag that is the same everywhere tells nothing apart. On the drum sheet -
one vessel, one tag, every fact stamped with it - putting the tag in the key
would change every key and silently retire every rejection ever recorded
against that document. Measured: with the tag forced into the key, 0 of 4
stored rejections still match; under the rule as built, they match exactly as
they did before.

Mutations: M199-M205, `python scripts/mutation_check.py --phase 16`.
"""

from __future__ import annotations

import pytest

from app import comparison, datasheets, db, submittal_review
from app.config import settings


# ========================================================== the reader

@pytest.mark.parametrize("label,value,expected", [
    # The drum sheet: key in one cell, tag in the next.
    ("Tag number :", "2003-47-V-0001A/B", "2003-47-V-0001A/B"),
    ("Tag No", "V-101", "V-101"),
    ("Item No.", "E-2201 A/B", "E-2201 A/B"),
    # The PSV sheet: the whole row is one cell and there is no value.
    ("Tag No. PSV-4301 A/B (for GC-9, 10 & 19)", "",
     "PSV-4301 A/B (for GC-9, 10 & 19)"),
    ("Tag Number PSV-4360 A/B", "", "PSV-4360 A/B"),
])
def test_a_tag_row_yields_its_tag_verbatim(label, value, expected):
    assert datasheets.tag_from_pair(label, value) == expected


@pytest.mark.parametrize("label,value", [
    # NAMES WHAT THE EQUIPMENT IS, not which one it is.
    ("Tag description :", "Sour Water Drums"),
    ("Set pressure", "340 psig"),
    ("Design pressure", "23.5 barg"),
    # A key with nothing after it and nothing beside it states no tag, and
    # an empty string is not a tag.
    ("Tag No.", ""),
    ("", ""),
])
def test_what_is_not_a_tag_row(label, value):
    assert datasheets.tag_from_pair(label, value) is None


def test_the_tag_is_not_tidied():
    """The brackets, the `A/B` and the service note are part of the
    identifier. A reader that stripped them would produce a tag that matches
    nothing anybody searches for."""
    tag = datasheets.tag_from_pair(
        "Tag No.  PSV-4301 A/B   (for GC-9, 10 & 19) & PSV-3301 A/B", "")

    assert tag == "PSV-4301 A/B (for GC-9, 10 & 19) & PSV-3301 A/B", \
        "only runs of whitespace may be collapsed"


# ========================================================= the stamping

def test_one_tag_in_a_document_stamps_every_page():
    """THE DRUM'S SHAPE. The vessel is named once, on the data page, and
    every fact in the document is about that vessel - including the facts on
    pages that name nothing."""
    pages = {1: [("Title", "")], 2: [("Tag number :", "V-0001A/B")],
             3: [("Set pressure", "3 bar")]}

    assert datasheets.stamp_tags(pages) == {
        1: "V-0001A/B", 2: "V-0001A/B", 3: "V-0001A/B"}


def test_several_tags_stay_on_their_own_pages():
    """THE PSV'S SHAPE, and the rule that keeps one valve's numbers off
    another's. Page 3 states no tag, so page 3 gets NULL - carrying page 1's
    tag onto it would file one valve's set pressure against another."""
    pages = {1: [("Tag No. PSV-4301", "")], 2: [("Tag No. PSV-4303", "")],
             3: [("Set pressure", "3 bar")]}

    assert datasheets.stamp_tags(pages) == {
        1: "PSV-4301", 2: "PSV-4303", 3: None}


def test_a_document_with_no_tag_row_stamps_nothing():
    assert datasheets.stamp_tags({1: [("Set pressure", "3 bar")]}) == {1: None}


def test_a_page_whose_tag_rows_disagree_states_no_tag():
    """"Which equipment is this page about" has no answer there, and NULL is
    a better answer than whichever one happened to be read first."""
    pages = {1: [("Tag No. A-1", ""), ("Tag No. B-2", "")],
             2: [("Tag No. A-1", "")], 3: [("Tag No. A-1", "")]}

    assert datasheets.stamp_tags(pages)[1] is None


# ================================================ through the pipeline

def _datasheet_pdf(path, pages) -> str:
    """One page per entry, each a list of label-value rows."""
    import pymupdf

    doc = pymupdf.open()
    for rows in pages:
        page = doc.new_page(width=600, height=500)
        y = 60
        for index, (label, value) in enumerate(rows, start=1):
            page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6),
                           color=(0, 0, 0), width=0.7)
            page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6),
                           color=(0, 0, 0), width=0.7)
            page.insert_text((44, y), f"{index}", fontsize=9)
            page.insert_text((64, y), label, fontsize=9)
            page.insert_text((304, y), value, fontsize=9)
            y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _ingest(path, doc_id="doc_tag"):
    import pymupdf

    doc = pymupdf.open(path)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',?,?)",
            (doc_id, "TAG-TEST.pdf", f"sha-{doc_id}", str(path),
             len(doc), "2026-09-19T00:00:00Z"))
        for page in range(1, len(doc) + 1):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,"
                "page_start,page_end,section,kind,text,token_count,"
                "content_hash,retrievable) VALUES (?,?,?,?,?,?,NULL,'prose',"
                "?,1,?,1)",
                (f"{doc_id}-c{page}", doc_id, "TAG-TEST.pdf", page, page, page,
                 doc[page - 1].get_text(), f"h{doc_id}{page}"))
    doc.close()
    return doc_id


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "tag.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _facts(doc):
    return datasheets.list_facts(doc, allowed_document_ids=frozenset({doc}))


def test_the_tag_row_never_becomes_a_fact(temp_storage, tmp_path):
    """IT NAMES THE EQUIPMENT, it is not a fact about it. Recorded as one it
    would be a field called `tag number` whose value is an identifier, and a
    matcher could pair a requirement with it."""
    doc = _ingest(_datasheet_pdf(tmp_path / "a.pdf", [[
        ("Tag number :", "V-0001A/B"),
        # A TAG THAT PARSES AS A QUANTITY is what makes this rule load-bearing.
        # `V-0001A/B` is refused by the value gate anyway - it reads as an
        # identifier - so a fixture using only that shape tests the gate and
        # not the skip. Four digits, because a one-to-three digit cell reads
        # as the next row's line number and never reaches the fact path.
        # field called `item no` holding the value 2003, which a matcher can
        # then pair with a requirement.
        ("Item No.", "2003"),
        ("Design pressure", "23.5 barg")]]))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    names = {f["field_name"] for f in _facts(doc)}

    assert "tag number" not in names
    assert "item no" not in names, "a numeric tag was recorded as a fact"
    # AND THE REAL ROW ON THE SAME PAGE IS STILL A FACT, so this is not
    # passing because the page yielded nothing.
    assert "design pressure" in names


def test_facts_are_stamped_with_the_documents_only_tag(temp_storage, tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "b.pdf", [
        [("Tag number :", "V-0001A/B"), ("Design pressure", "23.5 barg")],
        [("Set pressure", "340 psig")],
    ]))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))

    tags = {f["field_name"]: f["equipment_tag"] for f in _facts(doc)}
    assert tags["design pressure"] == "V-0001A/B"
    assert tags["set pressure"] == "V-0001A/B", \
        "a page that names no tag still belongs to the document's only tag"


def test_a_multi_tag_document_keeps_each_page_on_its_own_tag(
        temp_storage, tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "c.pdf", [
        [("Tag No. PSV-4301 A/B", ""), ("Set pressure", "340 psig")],
        [("Tag No. PSV-4360 A/B", ""), ("Set pressure", "130 psig")],
        [("Design pressure", "10 barg")],
    ]))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    by_page = {(f["page"], f["field_name"]): f["equipment_tag"]
               for f in _facts(doc)}

    assert by_page[(1, "set pressure")] == "PSV-4301 A/B"
    assert by_page[(2, "set pressure")] == "PSV-4360 A/B"
    assert by_page[(3, "design pressure")] is None, \
        "a tag was inherited across pages that name different equipment"


# ======================================== identity: the careful part

def test_a_single_tag_document_keeps_todays_key(temp_storage, tmp_path):
    """THE STOP CONDITION, AS A TEST.

    Six rejections are stored against the drum sheet, which carries one
    vessel tag. If the tag joined the key there, every one of them would stop
    applying at the next re-extraction - silently, which is the exact failure
    `fact_key` was re-keyed onto sha256 identity to prevent. Measured on the
    real corpus: with the tag forced into the key, 0 of 4 stored rejection
    keys still match.
    """
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", [[
        ("Tag number :", "V-0001A/B"), ("Design pressure", "23.5 barg")]]))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = _facts(doc)

    assert comparison.facts_are_tag_scoped(facts) is False
    fact = next(f for f in facts if f["field_name"] == "design pressure")
    assert fact["equipment_tag"] == "V-0001A/B", "the tag IS recorded"
    # ...and the key is what it would have been before tags existed.
    assert comparison.fact_key(fact) == comparison.fact_key(
        {"submittal_document_id": doc, "field_name": "design pressure"})


def test_a_rejection_survives_re_extraction_of_a_single_tag_sheet(
        temp_storage, tmp_path):
    """END TO END, BECAUSE THAT IS WHERE THE KEY IS ACTUALLY USED."""
    doc = _ingest(_datasheet_pdf(tmp_path / "e.pdf", [[
        ("Tag number :", "V-0001A/B"),
        ("Internal design pressure", "23.5 barg")]]))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    requirement = {
        "id": "req-1", "standard_document_id": "std", "clause": "5.1",
        "requirement_text": "The internal design pressure shall not exceed.",
        "requirement_type": "numeric_limit", "raw_value": "20",
        "raw_unit": "barg",
        "subject": "the internal design pressure shall not exceed",
    }
    facts = _facts(doc)
    assert comparison.match_by_containment(requirement, facts)["fact"]

    comparison.reject_pair(requirement, next(
        f for f in facts if f["field_name"] == "internal design pressure"),
        rejected_by=None, reason="different vessel")

    # Re-extract: every fact id changes, and the rejection must still apply.
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}),
                             replace=True)
    assert comparison.match_by_containment(
        requirement, _facts(doc))["fact"] is None, \
        "re-extraction retired a rejection on a single-tag sheet"


def test_rejecting_one_tag_does_not_suppress_the_same_field_on_another(
        temp_storage, tmp_path):
    """THE REASON THE TAG IS IN THE KEY AT ALL.

    Four valves, four set pressures. An engineer who says "this clause is not
    about PSV-4301's set pressure" has said nothing whatever about PSV-4360's,
    and a key that could not tell them apart would suppress both.
    """
    doc = _ingest(_datasheet_pdf(tmp_path / "f.pdf", [
        [("Tag No. PSV-4301 A/B", ""), ("Set pressure", "340 psig")],
        [("Tag No. PSV-4360 A/B", ""), ("Set pressure", "130 psig")],
    ]))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    facts = _facts(doc)
    assert comparison.facts_are_tag_scoped(facts) is True

    requirement = {
        "id": "req-1", "standard_document_id": "std", "clause": "5.1",
        "requirement_text": "The set pressure shall not exceed 300 psig.",
        "requirement_type": "numeric_limit", "raw_value": "300",
        "raw_unit": "psig", "subject": "the set pressure shall not exceed",
    }
    first = next(f for f in facts if f["equipment_tag"] == "PSV-4301 A/B")
    comparison.reject_pair(requirement, first, rejected_by=None,
                           reason="not this valve")

    remaining = [f for f in _facts(doc)
                 if f["field_name"] == "set pressure"]
    refused = comparison._rejected_keys_for(requirement)
    scoped = comparison.facts_are_tag_scoped(_facts(doc))
    suppressed = {f["equipment_tag"] for f in remaining
                  if comparison.fact_key(f, tag_scoped=scoped) in refused}

    assert suppressed == {"PSV-4301 A/B"}, (
        "rejecting one valve's field suppressed another valve's: "
        f"{suppressed}")


# ============================================= the finding carries it

def test_a_finding_records_the_equipment_it_is_about(temp_storage, tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "g.pdf", [[
        ("Tag number :", "V-0001A/B"), ("Design pressure", "23.5 barg")]]))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    fact = next(f for f in _facts(doc)
                if f["field_name"] == "design pressure")

    finding = comparison.create_finding(
        review_run_id=None, submittal_document_id=doc,
        requirement={"requirement_text": "r", "standard_document_id": "std",
                     "clause": "5.1"},
        fact=fact, verdict={"status": comparison.COMPLIANT, "rationale": "ok"},
        matched_phrase="design pressure", match_method="containment")

    assert finding["equipment_tag"] == "V-0001A/B"


def test_a_finding_with_no_fact_names_no_equipment(temp_storage, tmp_path):
    """NULL RENDERS AS NOTHING. A MISSING_INFORMATION finding has no value
    and therefore no equipment; guessing the document's tag onto it would
    claim the sheet said something about that vessel when it did not."""
    doc = _ingest(_datasheet_pdf(tmp_path / "h.pdf", [[
        ("Tag number :", "V-0001A/B"), ("Design pressure", "23.5 barg")]]))

    finding = comparison.create_finding(
        review_run_id=None, submittal_document_id=doc,
        requirement={"requirement_text": "r", "standard_document_id": "std",
                     "clause": "5.1"},
        fact=None,
        verdict={"status": comparison.MISSING_INFORMATION, "rationale": "x"})

    assert finding["equipment_tag"] is None
