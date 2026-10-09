"""W5b-05 (#529): claim units for written documents. INVENTED procedure.

Mutations: M5301-M5312, `python scripts/mutation_check.py --phase 5301`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import claim_units as cu, db
from app.main import app
from tests.test_standards_3b import _doc, _ruled_table_pdf, _scope, temp_storage  # noqa: F401

PAGE1 = ("Line Isolation Procedure.\n"
         "The operator shall confirm the work permit before starting.\n"
         "The supervisor must sign the isolation certificate in accordance with API 520 Part 1.\n"
         "This procedure applies to all process lines.")
PAGE2 = ("Valves shall be locked in the closed position after isolation is verified by the operator.\n"
         "Records are kept by the area authority.\n"
         "Relief design follows API 520 Part 1 and ASME B31.3 as stated.")


def _with_pages(doc_id, pages, stored="proc.pdf", flow=False):
    doc = _doc(doc_id, stored)
    with db.connect() as conn:
        if flow:
            conn.execute("UPDATE documents SET pagination = 'flow' WHERE id = ?", (doc,))
        for no, text in enumerate(pages, start=1):
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,0)",
                         (doc, no, text, len(text)))
    return doc


def _units(doc, kind=None):
    out = cu.units_for_document(doc, allowed_document_ids=_scope(doc))
    return out if kind is None else [u for u in out["units"] if u["kind"] == kind]


def test_each_shall_and_must_sentence_is_one_unit_with_its_page():
    doc = _with_pages("p1", [PAGE1, PAGE2])
    obligations = _units(doc, "obligation")
    by_text = {u["text"]: u["page"] for u in obligations}
    assert by_text["The operator shall confirm the work permit before starting."] == 1
    assert any("must sign" in t and p == 1 for t, p in by_text.items())
    assert any("locked in the closed position" in t and p == 2 for t, p in by_text.items())
    assert len(obligations) == 3                  # the two plain statements are not obligations
    assert all(u["citation"] == {"document_id": doc, "page": u["page"]} for u in obligations)


def test_a_sentence_without_an_obligation_word_is_not_a_unit():
    doc = _with_pages("p1", [PAGE1])
    assert not any("applies to all process lines" in u["text"] for u in _units(doc, "obligation"))


def test_a_running_footer_inside_a_sentence_is_not_part_of_it():
    page = ("The operator shall confirm the work permit before\nPage 4 of 12\nstarting any isolation work.\n")
    doc = _with_pages("p2", [page, page.replace("Page 4", "Page 5")])
    texts = [u["text"] for u in _units(doc, "obligation")]
    assert texts and not any("Page 4" in t or "Page 5" in t for t in texts)


def test_each_standard_a_page_names_is_one_reference_unit_with_its_page():
    doc = _with_pages("p1", [PAGE1, PAGE2])
    refs = {(u["text"], u["page"]) for u in _units(doc, "reference")}
    assert ("API 520 Part 1", 1) in refs and ("API 520 Part 1", 2) in refs     # per page
    assert any(t.startswith("ASME B31.3") and p == 2 for t, p in refs)
    assert len([r for r in refs if r[1] == 1]) == 1                            # named twice? once per page


def test_a_standard_named_twice_on_one_page_is_one_unit():
    page = "The pump shall follow API 610 for design. The seal shall also meet API 610 as stated."
    doc = _with_pages("p3", [page])
    assert [u["text"] for u in _units(doc, "reference")] == ["API 610"]


def test_a_ruled_table_gives_one_unit_per_row_with_its_page(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", ["Valve tag", "Test pressure", "Hold time"],
                           [["PSV-101", "15.5 bar", "10 min"], ["PSV-102", "21.0 bar", "15 min"]])
    doc = _with_pages("p4", ["Test schedule\nValve tag Test pressure Hold time"], stored=pdf)
    rows = _units(doc, "table_row")
    assert [r["label"] for r in rows] == ["PSV-101", "PSV-102"]
    assert rows[0]["page"] == 1 and rows[0]["row"] == 1
    assert "Test pressure: 15.5 bar" in rows[0]["text"]


def test_a_word_files_tables_are_not_rows_here_and_it_says_so(tmp_path):
    pdf = _ruled_table_pdf(tmp_path / "w.pdf", ["Valve tag", "Test pressure"],
                           [["PSV-101", "15.5 bar"], ["PSV-102", "21.0 bar"]])
    doc = _with_pages("p5", [PAGE1], stored=pdf, flow=True)
    out = cu.units_for_document(doc, allowed_document_ids=_scope(doc))
    assert out["table_rows_unavailable"] is True
    assert _units(doc, "table_row") == []
    # the same stored geometry in a paginated document does give rows
    plain = _with_pages("p5b", [PAGE1], stored=pdf)
    assert len(_units(plain, "table_row")) == 2


def test_a_numbered_list_of_obligations_is_one_unit_per_item():
    page = ("Before isolation the following steps apply:\n"
            "1) The operator shall confirm the work permit with the supervisor\n"
            "2) The operator shall tag the valve with the isolation label provided\n"
            "3) The supervisor shall countersign the permit before work starts")
    doc = _with_pages("p12", [page])
    texts = [u["text"] for u in _units(doc, "obligation")]
    assert len(texts) == 3, texts
    assert all("shall" in t and len(t) < 90 for t in texts)


def test_a_short_fragment_with_shall_in_it_is_not_a_unit():
    doc = _with_pages("p13", ["Contractor shall comply.\nSee the schedule."])
    assert _units(doc, "obligation") == []


def test_pages_with_no_text_are_counted_not_skipped():
    doc = _with_pages("p6", [PAGE1, "   ", ""])
    out = cu.units_for_document(doc, allowed_document_ids=_scope(doc))
    assert out["pages_read"] == 1 and out["pages_unread"] == 2 and out["state"] == "ok"


def test_a_document_with_no_readable_page_is_no_text_not_clean():
    doc = _with_pages("p7", ["", " "])
    assert cu.units_for_document(doc, allowed_document_ids=_scope(doc))["state"] == "no_text"


def test_a_readable_document_with_no_unit_is_no_units_not_clean():
    doc = _with_pages("p8", ["A page of plain description with nothing to check in it at all."])
    out = cu.units_for_document(doc, allowed_document_ids=_scope(doc))
    assert out["state"] == "no_units" and out["units"] == []


def test_a_document_the_caller_may_not_read_yields_nothing():
    doc = _with_pages("p9", [PAGE1])
    other = _doc("pother", "x.docx")
    out = cu.units_for_document(doc, allowed_document_ids=_scope(other))
    assert out["state"] == "not_readable" and out["units"] == []


def test_unit_ids_are_stable_and_distinct():
    doc = _with_pages("p10", [PAGE1, PAGE2])
    a = [u["id"] for u in _units(doc)["units"]]
    b = [u["id"] for u in _units(doc)["units"]]
    assert a == b and len(set(a)) == len(a)


def test_the_route_returns_the_units_and_404s_an_unreadable_document():
    doc = _with_pages("p11", [PAGE1, PAGE2])
    r = TestClient(app).get(f"/api/documents/{doc}/claim-units")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ok" and body["counts"]["obligation"] == 3
    assert TestClient(app).get("/api/documents/none/claim-units").status_code == 404
