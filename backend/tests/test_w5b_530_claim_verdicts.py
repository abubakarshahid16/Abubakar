"""W5b-06 (#530): a verdict per claim unit. INVENTED text. Stacked on #529.

Mutations: M5501-M5514, `python scripts/mutation_check.py --phase 5501`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import claim_units as cu, claim_verdicts as cv
from app.main import app
from tests.test_w5b_529_claim_units import PAGE1, PAGE2, _with_pages
from tests.test_standards_3b import _doc, _scope, temp_storage  # noqa: F401


def unit(kind="obligation", page=1, ident="u1", text="The operator shall confirm the permit before work."):
    return {"id": ident, "kind": kind, "page": page, "text": text,
            "citation": {"document_id": "d", "page": page}}


def ev(stance=cv.SUPPORTS, quote="a quoted line", page=3, **extra):
    return {"stance": stance, "quote": quote, "page": page, **extra}


# ---------------------------------------------------------------- the rules

def test_a_unit_with_no_evidence_is_a_query_with_no_confidence():
    v = cv.judge(unit(), [])
    assert v["verdict"] == cv.QUERY and v["confidence"] is None and v["evidence"] == []
    assert cv.judge(unit(), None)["verdict"] == cv.QUERY


def test_cited_supporting_evidence_passes_with_a_confidence_below_high():
    v = cv.judge(unit(), [ev()])
    assert v["verdict"] == cv.PASS and 0 < v["confidence"] <= cv.CONFIDENCE_CEILING
    assert v["evidence"][0]["quote"] == "a quoted line"


def test_the_confidence_is_never_above_the_ceiling_even_if_the_source_says_so():
    assert cv.judge(unit(), [ev(confidence=0.99)])["confidence"] == cv.CONFIDENCE_CEILING
    assert cv.judge(unit(), [ev(confidence=0.4)])["confidence"] == 0.4


def test_cited_contradicting_evidence_fails():
    v = cv.judge(unit(), [ev(cv.CONTRADICTS)])
    assert v["verdict"] == cv.FAIL and v["confidence"] is not None


def test_support_and_contradiction_together_is_a_query_for_an_engineer():
    v = cv.judge(unit(), [ev(cv.SUPPORTS), ev(cv.CONTRADICTS, quote="other line")])
    assert v["verdict"] == cv.QUERY and "engineer decides" in v["reason"]


def test_evidence_without_a_citation_is_not_evidence():
    for bad in ({"stance": cv.SUPPORTS, "quote": "a line"},                  # no page
                {"stance": cv.SUPPORTS, "page": 2},                            # no quote
                {"stance": cv.SUPPORTS, "quote": "  ", "page": 2}):
        v = cv.judge(unit(), [bad])
        assert v["verdict"] == cv.QUERY and "without a citation ignored" in v["reason"]
    assert cv.judge(unit(), [{"stance": cv.CONTRADICTS, "quote": "x"}])["verdict"] == cv.QUERY


def test_a_library_document_is_a_resolving_citation_without_a_quote():
    assert cv.judge(unit(), [{"stance": cv.SUPPORTS, "document_id": "std1"}])["verdict"] == cv.PASS


def test_uncited_evidence_beside_cited_evidence_is_counted_and_ignored():
    v = cv.judge(unit(), [ev(), {"stance": cv.CONTRADICTS, "quote": "no page"}])
    assert v["verdict"] == cv.PASS and "1 piece(s) of evidence without a citation ignored" in v["reason"]


def test_a_figure_is_always_a_query_marked_engineer_review_required():
    fig = unit(kind="figure", text="figure 1 on page 2")
    for evidence in (None, [ev()], [ev(cv.CONTRADICTS)]):
        v = cv.judge(fig, evidence)
        assert v["verdict"] == cv.QUERY and v["engineer_review_required"] is True
        assert cv.ENGINEER_REVIEW in v["reason"]
    assert cv.judge(unit(), [ev()])["engineer_review_required"] is False


# ----------------------------------------------------------- a whole document

def _pdf_with_a_picture(tmp_path):
    import pymupdf
    path = tmp_path / "fig.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(pymupdf.Rect(72, 72, 172, 172), pixmap=pix)
    page.insert_text((72, 300), "The operator shall confirm the work permit before starting the job.")
    doc.save(str(path)); doc.close()
    return str(path)


def test_every_picture_on_a_page_is_a_figure_unit_for_an_engineer(tmp_path):
    doc = _with_pages("f1", ["The operator shall confirm the work permit before starting the job."],
                      stored=_pdf_with_a_picture(tmp_path))
    figures = [u for u in cu.units_for_document(doc, allowed_document_ids=_scope(doc))["units"]
               if u["kind"] == "figure"]
    assert len(figures) == 1 and figures[0]["page"] == 1
    report = cv.verdicts_for_document(doc, allowed_document_ids=_scope(doc))
    assert report["engineer_review_required"] == 1


def test_a_standard_the_library_holds_passes_and_one_it_does_not_is_a_query():
    held = _doc("std610", "x.pdf", "API-610.pdf")
    doc = _with_pages("w1", ["The pump shall follow API 610 for design. The seal shall meet ISO 21049 as stated."])
    report = cv.verdicts_for_document(doc, allowed_document_ids=_scope(doc, held))
    by_text = {v["unit_id"]: v for v in report["verdicts"]}
    refs = {u["text"]: by_text[u["id"]] for u in cu.units_for_document(
        doc, allowed_document_ids=_scope(doc, held))["units"] if u["kind"] == "reference"}
    assert refs["API 610"]["verdict"] == cv.PASS and refs["API 610"]["evidence"][0]["document_id"] == held
    assert refs["ISO 21049"]["verdict"] == cv.QUERY and "not held" in refs["ISO 21049"]["reason"]


def test_obligations_and_table_rows_stay_query_until_a_baseline_is_compared():
    doc = _with_pages("w2", [PAGE1, PAGE2])
    report = cv.verdicts_for_document(doc, allowed_document_ids=_scope(doc))
    obligations = [v for v in report["verdicts"] if v["kind"] == "obligation"]
    assert obligations and all(v["verdict"] == cv.QUERY and "no baseline" in v["reason"] for v in obligations)
    assert report["counts"][cv.PASS] == 0 and report["counts"][cv.FAIL] == 0


def test_an_extra_evidence_source_can_pass_or_fail_an_obligation():
    doc = _with_pages("w3", [PAGE1])

    def source(u):
        if u["kind"] != "obligation":
            return []
        return [ev(cv.CONTRADICTS if "permit" in u["text"] else cv.SUPPORTS, page=1)]
    report = cv.verdicts_for_document(doc, allowed_document_ids=_scope(doc), evidence_for=source)
    kinds = {v["verdict"] for v in report["verdicts"] if v["kind"] == "obligation"}
    assert kinds == {cv.FAIL, cv.PASS}


def test_a_document_nobody_may_read_or_with_no_text_carries_the_units_state():
    doc = _with_pages("w4", ["", " "])
    assert cv.verdicts_for_document(doc, allowed_document_ids=_scope(doc))["state"] == "no_text"
    assert cv.verdicts_for_document(doc, allowed_document_ids=_scope())["state"] == "not_readable"


def test_the_route_returns_the_verdicts_and_404s_an_unreadable_document():
    held = _doc("std610", "x.pdf", "API-610.pdf")
    doc = _with_pages("w5", [PAGE1, PAGE2 + " Per API 610 only."])
    r = TestClient(app).get(f"/api/documents/{doc}/claim-verdicts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["units_total"] == len(body["verdicts"]) and body["counts"]["query"] > 0
    assert any(v["verdict"] == "pass" and v["kind"] == "reference" for v in body["verdicts"])
    assert TestClient(app).get("/api/documents/none/claim-verdicts").status_code == 404
    assert held
