"""B7: the vision reader reads only what the text readers could not.

Before B7 the vision reader (behind GEOMETRY_READER_ENABLED) was asked about
EVERY page, including pages the rule and geometry readers had already read.
Now extraction plans first (rule + geometry readers, rolled back), and only a
page that recorded no fact AND has a text layer to prove readings against is
sent - within a per-document page budget, outside any write transaction.
Every page's routing reason is recorded.

Synthetic PDFs only; the model is a fake. Mutations M812-M817.
"""
from __future__ import annotations

import pymupdf
import pytest

from app import datasheets, db, page_ledger
from app.config import settings
from tests.test_b4_quality import NOW, VisionFake, _facts, _with_vision, world  # noqa: F401

READABLE = [(50, 100, "DESIGN PRESSURE:"), (180, 100, "10 barg")]     # rule reader reads it
UNREAD = [(50, 100, "VOLTAGE"), (220, 100, "440")]                     # no reader records it


def _store_pages(tmp_path, pages, doc_id="doc_b7") -> str:
    """One PDF page per entry: a list of (x, y, text), or None for an
    image-only page (a drawn box, no text layer)."""
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    for items in pages:
        page = pdf.new_page(width=595, height=842)
        if items is None:
            page.draw_rect(pymupdf.Rect(50, 50, 300, 300), color=(0, 0, 0))
        else:
            for x, y, text in items:
                page.insert_text((x, y), text, fontsize=10)
    pdf.save(str(path))
    texts = [p.get_text() for p in pdf]
    pdf.close()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',?,?)",
                     (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), len(pages), NOW))
        for n, text in enumerate(texts, start=1):
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                         " VALUES (?,?,?,?,0,0)", (doc_id, n, text, len(text)))
            conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                         "section,kind,text,token_count,content_hash,retrievable) VALUES "
                         "(?,?,?,?,?,?,NULL,'prose',?,1,?,1)",
                         (f"{doc_id}-c{n}", doc_id, f"{doc_id}.pdf", n, n, n,
                          text or "image-only page", f"h-{doc_id}-{n}"))
    return doc_id


@pytest.fixture
def vision_on(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "geometry_reader_enabled", True)
    monkeypatch.setattr(datasheets, "_geometry_rows_from_pdf_page", lambda *_a: [])
    return world


# ------------------------------------------------------------ the rule itself

@pytest.mark.parametrize("kw, expected", [
    (dict(facts_on_page=3, geometry_on_page=0, text_words=50), (False, datasheets.VISION_NOT_NEEDED)),
    (dict(facts_on_page=0, geometry_on_page=2, text_words=50), (False, datasheets.VISION_NOT_NEEDED)),
    (dict(facts_on_page=0, geometry_on_page=0, text_words=0), (False, datasheets.VISION_NO_TEXT_LAYER)),
    (dict(facts_on_page=0, geometry_on_page=0, text_words=40), (True, datasheets.VISION_ROUTED)),
])
def test_the_routing_rule(kw, expected):
    assert datasheets.vision_route(**kw, routed_so_far=0, budget=10) == expected


def test_the_budget_is_a_ceiling():
    assert datasheets.vision_route(facts_on_page=0, geometry_on_page=0, text_words=40,
                                   routed_so_far=10, budget=10) == (False, datasheets.VISION_BUDGET)


# ---------------------------------------------------------------- end to end

def test_only_the_page_no_text_reader_could_read_is_sent_to_the_model(vision_on, monkeypatch):
    doc = _store_pages(vision_on, [READABLE, UNREAD, None])
    fake = VisionFake([{"label": "VOLTAGE", "value": "440", "unit": None}])
    _with_vision(monkeypatch, fake)
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert fake.calls == 1
    assert result["vision_routing"] == {1: datasheets.VISION_NOT_NEEDED,
                                        2: datasheets.VISION_ROUTED,
                                        3: datasheets.VISION_NO_TEXT_LAYER}
    vision = [f for f in _facts(doc) if f["extraction_method"] == "vision"]
    assert [(f["page"], f["field_label"], f["raw_value"]) for f in vision] == [(2, "VOLTAGE", "440")]


def test_the_ledger_says_why_a_page_was_not_sent(vision_on, monkeypatch):
    doc = _store_pages(vision_on, [READABLE, UNREAD, None])
    _with_vision(monkeypatch, VisionFake([{"label": "VOLTAGE", "value": "440"}], kind="table"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    reasons = {int(k): v for k, v in page_ledger.coverage(doc)["not_read_reasons"].items()}
    assert "OCR tier" in reasons[3]
    # Page 2 was read by the vision reader: read (entry 68), and its ledger
    # row still says what the vision reader did.
    ledger = {r["page_no"]: r for r in page_ledger.rows(doc)}
    assert ledger[2]["facts_status"] == "facts"
    assert "vision reader: page kind 'table'" in ledger[2]["facts_reason"]


def test_the_model_is_never_called_inside_a_write_transaction(vision_on, monkeypatch):
    doc = _store_pages(vision_on, [UNREAD])
    seen = []

    class Watching(VisionFake):
        def reason(self, packet):
            seen.append(db.connect().in_transaction)
            return super().reason(packet)
    _with_vision(monkeypatch, Watching([{"label": "VOLTAGE", "value": "440"}]))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert seen == [False]


def test_the_plan_pass_leaves_nothing_behind(vision_on, monkeypatch):
    """One extraction writes one set of facts: the rolled-back plan pass
    supersedes nothing and stores nothing."""
    doc = _store_pages(vision_on, [READABLE, UNREAD])
    _with_vision(monkeypatch, VisionFake([{"label": "VOLTAGE", "value": "440"}]))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    total = db.connect().execute(
        "SELECT COUNT(*) FROM submittal_facts WHERE submittal_document_id = ?", (doc,)).fetchone()[0]
    assert total == len(_facts(doc)) > 0


def test_the_page_budget_bounds_the_calls(vision_on, monkeypatch):
    monkeypatch.setattr(settings, "vision_max_pages_per_document", 1)
    doc = _store_pages(vision_on, [UNREAD, UNREAD])
    fake = VisionFake([{"label": "VOLTAGE", "value": "440"}])
    _with_vision(monkeypatch, fake)
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert fake.calls == 1
    assert result["vision_routing"] == {1: datasheets.VISION_ROUTED, 2: datasheets.VISION_BUDGET}
