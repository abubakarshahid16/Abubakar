"""Order 165 item E: a page two readers read and found no field on is READ.

A cover (title block, revision table), a hold list and a contents page hold no
datasheet value. The code readers gave them no fact, and the ledger said
`no_facts` - "not read into fields" - so every missing value on the sheet was
qualified UNREAD_PAGES ("the value may be on the unread page") and the unread
pages blocked the contractor copy. Now a page the AI reader READ without error
and put nothing forward on is `no_fields`: read, no field found. A page the AI
reader did not read, failed on, or proposed something refused on stays unread,
with its reason.

Invented text only; the model is a fake callable (no network, no Ollama).
"""

from __future__ import annotations

import pytest

from app import comparison, datasheets, db, form_reader_run, page_ledger
from app.config import settings
from tests.test_datasheet_ai import (  # noqa: F401 - the autouse temp_storage
    FakeModel,
    _fact,
    _ingest,
    _use,
    temp_storage,
)

COVER = [
    "MECHANICAL DATASHEET",
    "INVENTED SERVICE DRUMS",
    "DOCUMENT NO 0001-XX",
    "Rev. Date Status Description",
    "00 01/01/2024 IFF Issued for Final",
]
ROWS = [("Design pressure", "23.5 barg"), ("Design temperature", "120 C")]


def _pdf(path, cover_pages=1) -> str:
    import pymupdf

    doc = pymupdf.open()
    for _ in range(cover_pages):
        page = doc.new_page(width=600, height=500)
        y = 60
        for line in COVER:
            page.insert_text((44, y), line, fontsize=10)
            y += 22
    page = doc.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(ROWS, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(
            pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7
        )
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _coverage(doc):
    return page_ledger.coverage(doc)


def test_a_cover_page_both_readers_found_nothing_on_is_read_not_unread(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = _coverage(doc)
    assert cov["pages_not_read_into_fields"] == []
    assert cov["pages_read_no_field"] == [1]
    assert cov["fact_pages"] == [2]
    row = page_ledger.rows(doc)[0]
    assert row["facts_status"] == page_ledger.READ_NO_FIELD
    assert row["facts_reason"].startswith("Read, no checklist field found")


def test_with_the_ai_reader_off_the_cover_page_stays_unread(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = _coverage(doc)
    assert cov["pages_not_read_into_fields"] == [1]
    assert cov["pages_read_no_field"] == []


def test_a_page_the_ai_reader_failed_on_stays_unread(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel(raises=RuntimeError("engine down")))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = _coverage(doc)
    assert 1 in cov["pages_not_read_into_fields"]
    assert cov["pages_read_no_field"] == []


def test_a_page_the_ai_reader_proposed_something_refused_on_stays_unread(
    tmp_path, monkeypatch
):
    # a value whose quote is not on the page: refused by the code, so the
    # model did say something about this page and the page is not "empty"
    invented = _fact(
        "Design pressure", "99", "barg", "Design pressure 99 barg printed nowhere"
    )
    _use(monkeypatch, FakeModel([invented]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = _coverage(doc)
    assert 1 in cov["pages_not_read_into_fields"]
    assert cov["pages_read_no_field"] == []


def test_an_absent_value_is_no_longer_called_unread_when_every_page_was_read(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    verdict = {"status": comparison.MISSING_INFORMATION, "rationale": "no value found"}
    out = comparison.qualify_by_pages(verdict, _coverage(doc))
    assert "UNREAD_PAGES" not in out["rationale"]
    assert (
        out["status"] != comparison.NEEDS_ENGINEER_REVIEW
        or "page reader" in out["rationale"]
    )
    assert "page 1 read, no checklist field found" in out["rationale"]


def test_the_rationale_never_says_fields_were_read_from_a_page_that_held_none():
    pages = {
        "pages_total": 3,
        "fact_pages": [2, 3],
        "pages_not_read_into_fields": [],
        "pages_read_only_by_page_reader": [],
        "pages_read_no_field": [1],
    }
    out = comparison.qualify_by_pages(
        {"status": comparison.MISSING_INFORMATION, "rationale": "x"}, pages
    )
    assert "fields were read from every page" not in out["rationale"]
    plain = {**pages, "fact_pages": [1, 2, 3], "pages_read_no_field": []}
    again = comparison.qualify_by_pages(
        {"status": comparison.MISSING_INFORMATION, "rationale": "x"}, plain
    )
    assert "fields were read from every page" in again["rationale"]


@pytest.mark.parametrize(
    "change",
    [
        {"error": "engine failed"},
        {"accepted": [{"field": "x"}]},
        {"counts": {"quote_not_on_page": 1}},
        {"rejected": [{"reason": "x"}]},
        {"partial": "part 2 not read"},
        {"cut_off": [1]},
        {"stopped": "time_budget"},
    ],
)
def test_only_a_clean_empty_reading_counts_as_empty(change):
    clean = {
        "pages": {1: {"accepted": [], "rejected": [], "counts": {}}},
        "reasons": {},
    }
    assert page_ledger.read_page_empty(clean, 1) is True
    dirty = {
        "pages": {1: {"accepted": [], "rejected": [], "counts": {}, **change}},
        "reasons": {},
    }
    assert page_ledger.read_page_empty(dirty, 1) is False


def test_a_page_with_a_recorded_reason_or_no_reading_or_unread_parts_is_not_empty():
    page = {"accepted": [], "rejected": [], "counts": {}}
    assert (
        page_ledger.read_page_empty({"pages": {}, "reasons": {1: "no text"}}, 1)
        is False
    )
    assert (
        page_ledger.read_page_empty(
            {"pages": {1: page}, "reasons": {1: "timed out"}}, 1
        )
        is False
    )
    assert (
        page_ledger.read_page_empty(
            {"pages": {1: page}, "reasons": {}, "partly_read": {1: "part 2"}}, 1
        )
        is False
    )
    assert page_ledger.read_page_empty({"pages": {1: page}}, 2) is False


def test_a_whole_page_refusal_beside_a_clean_form_page_keeps_the_page_unread():
    """Form mode (the default): the form read the page cleanly and found nothing;
    the whole-page reader proposed a value the code refused. Merging keeps that
    refusal apart, so the page is not 'empty'."""
    form = {
        "pages": {1: {"accepted": [], "rejected": [], "counts": {}}},
        "reasons": {},
        "partly_read": {},
        "stopped": None,
        "seconds": 0,
    }
    merge = {
        "pages": {
            1: {
                "accepted": [],
                "rejected": [{"reason": "quote_not_on_page"}],
                "counts": {"quote_not_on_page": 1},
            }
        }
    }
    assert page_ledger.read_page_empty(form, 1) is True
    merged = form_reader_run.add_merge_reading(form, merge)
    assert page_ledger.read_page_empty(merged, 1) is False
    assert merged["pages"][1]["counts"] == {}  # the form's own tallies are as before


def test_a_sheet_where_no_page_gave_a_field_does_not_count_its_pages_as_read(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    import pymupdf

    path = tmp_path / "blank.pdf"
    pdf = pymupdf.open()
    for _ in range(2):
        page = pdf.new_page(width=600, height=500)
        page.insert_text((44, 60), "MECHANICAL DATASHEET INVENTED", fontsize=10)
    pdf.save(str(path))
    pdf.close()
    doc = _ingest(str(path))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = _coverage(doc)
    assert cov["pages_read_no_field"] == []
    assert cov["pages_not_read_into_fields"] == [1, 2]
    assert "not counted as read" in cov["not_read_reasons"]["1"]


def test_a_page_whose_text_layer_was_not_usable_is_not_counted_as_read(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    with db.connect() as conn:
        conn.execute(
            "UPDATE page_ledger SET ocr_status = 'failed' WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    cov = _coverage(doc)
    assert cov["pages_read_no_field"] == []
    assert 1 in cov["pages_not_read_into_fields"]
    assert "text layer was not usable" in cov["not_read_reasons"]["1"]


def test_a_page_the_picture_reader_could_not_be_asked_about_is_not_counted_as_read(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    with db.connect() as conn:
        conn.execute(
            "UPDATE page_ledger SET vision_status = 'not_attempted', vision_reason = ? "
            "WHERE document_id = ? AND page_no = 1",
            ("routed: ..., but the vision reader is unavailable (down)", doc),
        )
    cov = _coverage(doc)
    assert 1 in cov["pages_not_read_into_fields"] and cov["pages_read_no_field"] == []
    assert "picture reader" in cov["not_read_reasons"]["1"]


def test_the_readiness_strip_names_the_pages_read_with_no_field_apart_from_the_read_and_unread(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    strip = page_ledger.readiness_pages(doc)
    assert strip["pages_total"] == 2
    assert strip["pages_read"] == 1  # fields were read from one page
    assert strip["pages_read_no_field"] == [1]
    assert strip["unread_pages"] == []


def test_a_page_a_code_reader_failed_on_is_not_counted_as_read():
    """A reader that crashed has not read the page: 'the code readers found
    nothing' would be false. The failure record (`datasheets._PAGE_FAILURES`)
    keeps the page unread even when the AI reader read it clean."""
    ai = {"pages": {1: {"accepted": [], "rejected": [], "counts": {}}}, "reasons": {}}
    token = datasheets._PAGE_FAILURES.set({1: {"geometry"}})
    try:
        assert page_ledger.no_fact(ai, 1, "why", {})[0] == "no_facts"
    finally:
        datasheets._PAGE_FAILURES.reset(token)
    assert page_ledger.no_fact(ai, 1, "why", {})[0] == page_ledger.READ_NO_FIELD
    assert (
        page_ledger.no_fact(ai, 2, "why", {})[0] == "no_facts"
    )  # no reading of page 2


def test_end_to_end_a_crashing_code_reader_keeps_the_cover_page_unread(
    tmp_path, monkeypatch
):
    from app import geometry_reader

    def boom(*_a, **_k):
        raise RuntimeError("reader crashed")

    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(geometry_reader, "upright_blocks", boom)
    monkeypatch.setattr(geometry_reader, "upright_words", boom)
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    cov = _coverage(doc)
    assert cov["pages_read_no_field"] == []
    assert 1 in cov["pages_not_read_into_fields"]
