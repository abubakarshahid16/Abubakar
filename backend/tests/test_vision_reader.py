"""Issue #180: page routing, and a vision model on the REAL extraction path.

EVERY TEST GOES THROUGH `datasheets.extract_facts` where the property is about
the pipeline - which pages reach the model, what becomes a fact - and asserts
something positive before an absence (honesty-audit entries 6, 11, 13).

No network and no model: the provider is a stub that records every packet it
is handed, so "the model was never asked" is an observation, not an inference.
No client content: every page below is drawn by the test, with invented labels
and numbers.

Mutations: M430-M439, `python scripts/mutation_check.py --phase 55`.
"""
from __future__ import annotations

import json

import pytest

from app import datasheets, db, submittal_review, vision_reader
from app.config import settings
from app.reasoning_provider import ProviderRefused, Response

STUB_TAG = "stub-vl:1b-q4"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "vr.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


class StubProvider:
    """Records every packet; answers with `rows` as the model's JSON."""

    name = "ollama"

    def __init__(self, rows=None, *, finish="stop", refuse=None):
        self.rows = rows or []
        self.finish = finish
        self.refuse = refuse
        self.packets = []

    def reason(self, packet):
        self.packets.append(packet)
        if self.refuse:
            raise ProviderRefused(self.refuse)
        return Response(text=json.dumps(self.rows), provider="ollama",
                        model_tag=STUB_TAG, digest="d", finish_reason=self.finish,
                        prompt_sha256=packet.sha256, tokens_in=100, tokens_out=50)


@pytest.fixture
def stub(monkeypatch):
    holder = {"provider": StubProvider()}
    monkeypatch.setattr(vision_reader, "make_provider", lambda: holder["provider"])
    return holder


# Label, Rated, Normal. The rule reader reads the first column of this grid and
# leaves the second unread - the pump-sheet defect, reproduced in miniature.
GRID = [("Capacity", "120.5", "100.2"), ("Differential head", "85.5", "80.1"),
        ("NPSH available", "7.25", "6.75"), ("Suction pressure", "2.35", "1.95")]

# A plain two-column form the rule reader reads completely.
FORM = [("Design pressure", "23.5 barg"), ("Design temperature", "85.5 C"),
        ("Corrosion allowance", "3.15 mm"), ("Test pressure", "35.25 barg")]


def _draw_grid(page):
    page.insert_text((300, 80), "Rated", fontsize=9)
    page.insert_text((400, 80), "Normal", fontsize=9)
    y = 110
    for label, rated, normal in GRID:
        page.insert_text((60, y), label, fontsize=9)
        page.insert_text((300, y), rated, fontsize=9)
        page.insert_text((400, y), normal, fontsize=9)
        y += 22


def _draw_form(page):
    y = 80
    for label, value in FORM:
        page.draw_rect((40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect((300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26


def _pdf(path, *drawers):
    import pymupdf
    doc = pymupdf.open()
    for draw in drawers:
        draw(doc.new_page(width=600, height=500))
    doc.save(str(path)); doc.close()
    return str(path)


def _ingest(path, doc_id="doc_vr", text=None):
    import pymupdf
    doc = pymupdf.open(path); pages = len(doc)
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,?)""",
            (doc_id, "DS-TEST.pdf", f"sha-{doc_id}", str(path), pages,
             "2026-09-24T00:00:00Z"))
        for page in range(1, pages + 1):
            body = text if text is not None else doc[page - 1].get_text()
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)""",
                (f"{doc_id}-c{page}", doc_id, "DS-TEST.pdf", page, page, page,
                 body or " ", f"h{doc_id}{page}"))
    doc.close()
    return doc_id


def _scope(doc):
    return frozenset([doc])


def _routes(doc):
    return {r["page_no"]: r for r in db.connect().execute(
        "SELECT * FROM page_routes WHERE document_id = ?", (doc,)).fetchall()}


def _facts(doc):
    return datasheets.list_facts(doc, allowed_document_ids=_scope(doc))


# ================================================================== routing

def test_180_every_page_gets_a_recorded_route_and_reason(tmp_path):
    doc = _ingest(_pdf(tmp_path / "two.pdf", _draw_form, _draw_grid))
    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    routes = _routes(doc)
    assert set(routes) == {1, 2}
    assert routes[1]["route"] == vision_reader.ROUTE_NATIVE_TEXT
    assert routes[2]["route"] == vision_reader.ROUTE_NEEDS_LAYOUT
    assert all(r["reason"] for r in routes.values())
    assert "4 of 8" in routes[2]["reason"], routes[2]["reason"]


def test_180_a_native_text_page_the_rule_reader_read_never_reaches_the_model(
        tmp_path, monkeypatch, stub):
    """#180 acceptance test 1. Flag ON, a stub that would answer anything -
    and a fully read form page is still never sent."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    doc = _ingest(_pdf(tmp_path / "form.pdf", _draw_form))

    out = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    assert out["facts"] >= len(FORM), "the rule reader did not read the form"
    assert _routes(doc)[1]["route"] == vision_reader.ROUTE_NATIVE_TEXT
    assert stub["provider"].packets == [], "a native-text page reached the model"


def test_180_only_the_routed_page_is_sent(tmp_path, monkeypatch, stub):
    """The call happens for the needs_layout page and ONLY for it."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    doc = _ingest(_pdf(tmp_path / "two.pdf", _draw_form, _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    packets = stub["provider"].packets
    assert len(packets) == 1, f"expected one call, got {len(packets)}"
    assert "page 2" in packets[0].prompt and "page 1" not in packets[0].prompt
    assert packets[0].images, "a vision call without an image"
    assert packets[0].think is False
    assert _routes(doc)[2]["vision_called"] == 1
    assert _routes(doc)[1]["vision_called"] == 0


def test_180_flag_off_means_no_call_and_the_route_is_still_recorded(tmp_path, stub):
    assert settings.vision_enabled is False, "the flag must ship OFF"
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    assert _routes(doc)[1]["route"] == vision_reader.ROUTE_NEEDS_LAYOUT
    assert stub["provider"].packets == []
    assert not [f for f in _facts(doc) if f["extraction_method"] == "vision"]


def test_180_read_page_refuses_a_route_that_is_not_a_vision_route(tmp_path, stub):
    path = _pdf(tmp_path / "form.pdf", _draw_form)
    route = vision_reader.PageRoute(vision_reader.ROUTE_NATIVE_TEXT, "read by rules")
    with pytest.raises(ValueError, match="never sent"):
        vision_reader.read_page(path, 1, route)
    assert stub["provider"].packets == []


# ========================================================= validation -> facts

def test_180_a_validated_value_is_a_fact_with_model_route_and_region(
        tmp_path, monkeypatch, stub):
    """The unread Normal column, proposed under its heading, found in the
    label's row under that heading: a fact, carrying what read it and where."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Capacity", "Normal", "100.2", "m3/h"]])
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    vision = [f for f in _facts(doc) if f["extraction_method"] == "vision"]
    assert len(vision) == 1, vision
    fact = vision[0]
    assert fact["field_label"] == "Capacity"
    assert fact["field_value"] == "100.2 m3/h"
    assert fact["validation_state"] is None, "a validated value was held back"
    assert fact["model_tag"] == STUB_TAG, "the ENGINE-reported tag was not recorded"
    assert fact["page_route"] == vision_reader.ROUTE_NEEDS_LAYOUT
    assert fact["page"] == 1
    x0, y0, x1, y1 = json.loads(fact["bbox"])
    assert x0 < 100 and x1 > 400 and y0 < 90 and y1 > 100, "region does not cover label, heading and value"
    assert "100.2" in fact["source_text"] and "Capacity" in fact["source_text"]
    assert "Normal" in fact["validation_note"]


def test_180_a_value_the_page_does_not_print_never_becomes_a_fact(
        tmp_path, monkeypatch, stub):
    """The invented number is dropped outright - not stored, not queued."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Capacity", "Normal", "100.2", ""],
                                     ["Capacity", "Maximum", "999.9", ""]])
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    # EVERY vision row, review ones included: the claim is that the invented
    # value is not stored AT ALL, not merely that it is not a validated fact
    # (the first draft filtered on "vision" only and M435 proved it vacuous).
    values = [f["field_value"] for f in _facts(doc)
              if f["extraction_method"].startswith("vision")]
    assert "100.2" in values, "the control value was not stored"
    assert "999.9" not in values, "a value the page does not print was stored"


def test_180_a_printed_value_under_the_wrong_column_is_review_never_a_fact(
        tmp_path, monkeypatch, stub):
    """100.2 IS printed, in Capacity's row - under Normal. Proposed as Rated,
    it is the wrong answer to the slot, so it goes to an engineer."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Capacity", "Rated", "100.2", ""]])
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    vision = [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert len(vision) == 1, vision
    assert vision[0]["validation_state"] == datasheets.NEEDS_ENGINEER_REVIEW
    assert vision[0]["bbox"] is None, "an unvalidated value was given a region"
    assert vision[0]["validation_note"]


def test_180_a_second_column_value_with_no_heading_named_is_review(
        tmp_path, monkeypatch, stub):
    """Without a heading the value must be the NEAREST to its label. 80.1 has
    85.5 between it and its label, so the model picked a column silently."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Differential head", "", "80.1", ""]])
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    vision = [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert len(vision) == 1, vision
    assert vision[0]["validation_state"] == datasheets.NEEDS_ENGINEER_REVIEW


def test_180_a_value_in_another_row_is_review_never_a_fact(tmp_path, monkeypatch, stub):
    """7.25 is printed - in NPSH available's row, not Capacity's."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Capacity", "Rated", "7.25", ""]])
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    vision = [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert [f["validation_state"] for f in vision] == [datasheets.NEEDS_ENGINEER_REVIEW]


def test_180_a_provider_refusal_leaves_the_page_in_review_and_extraction_whole(
        tmp_path, monkeypatch, stub):
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider(refuse="ollama: ConnectError: refused")
    doc = _ingest(_pdf(tmp_path / "two.pdf", _draw_form, _draw_grid))

    out = datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    assert out["facts"] >= len(FORM), "the rule facts were lost with the model"
    assert not [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert "provider_refused" in (_routes(doc)[2]["vision_outcome"] or "")


def test_180_a_truncated_answer_is_refused_whole(tmp_path, monkeypatch, stub):
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Capacity", "Normal", "100.2", ""]], finish="length")
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    assert not [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert "truncated" in _routes(doc)[1]["vision_outcome"]


def test_180_a_schema_invalid_row_is_refused_not_coerced(tmp_path, monkeypatch, stub):
    """A row the schema refuses (an empty value) is never stored; a valid
    row beside it is."""
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Capacity", "Normal", "100.2", ""],
                                     ["NPSH available", "Normal", "", ""]])
    doc = _ingest(_pdf(tmp_path / "grid.pdf", _draw_grid))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    vision = [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert [f["field_value"] for f in vision] == ["100.2"]


# ======================================================== recognised pages

def test_180_a_value_read_from_a_recognised_page_is_never_a_fact(
        tmp_path, monkeypatch, stub):
    """An image page whose OCR text the OCR tier could not pair is routed
    needs_layout and sent; a value found beside its label in the recognised
    text reaches REVIEW with no region, because OCR boxes are not stored."""
    import pymupdf
    monkeypatch.setattr(settings, "vision_enabled", True)
    stub["provider"] = StubProvider([["Casing material", "", "A216 WCB", ""]])
    doc_pdf = pymupdf.open(); doc_pdf.new_page(width=600, height=500)
    path = tmp_path / "scan.pdf"; doc_pdf.save(str(path)); doc_pdf.close()
    doc = _ingest(path, doc_id="doc_scan", text=" ")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO page_ocr (document_id, page_no, text, char_count, engine,
               model, dpi, box_count, seconds, recognised_at, batch_no)
               VALUES (?,1,?,40,'rapidocr-3.9.2','m',150,2,0.1,'2026-09-24T00:00:00Z',0)""",
            (doc, "Casing material A216 WCB\nImpeller material CA6NM"))

    datasheets.extract_facts(doc, allowed_document_ids=_scope(doc))

    assert _routes(doc)[1]["route"] == vision_reader.ROUTE_NEEDS_LAYOUT
    assert len(stub["provider"].packets) == 1
    vision = [f for f in _facts(doc) if f["extraction_method"].startswith("vision")]
    assert len(vision) == 1, vision
    assert vision[0]["validation_state"] == datasheets.NEEDS_ENGINEER_REVIEW
    assert vision[0]["bbox"] is None
    assert "no region" in vision[0]["validation_note"]
