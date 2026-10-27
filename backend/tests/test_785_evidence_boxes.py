"""#785 (planner's live check on the PSV run, 12 Oct 05:53 UTC): the side-by-
side view boxed nothing on a checklist row's submittal page and showed no
standard page at all. Now:

- the submittal side falls back from the stored quote to the value's stored
  position, the fact's source line, the value when it occurs once on the page,
  then the field's label - and says which kind of box it drew;
- a checklist row's standard side is the cited clause's page in the held
  standard (from its stored requirements, or a chunk that starts the clause),
  with the clause boxed; a standard not held, or not readable by the caller,
  is said in words, never shown as another page.

Invented PDFs only (the #508 world)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import evidence_boxes
from app.db import connect
from app.main import app
from tests.test_508_finding_evidence_image import _get, _pdf, _reviewed
from tests.test_p3_review_jobs import _user, temp_storage, world  # noqa: F401 - fixtures


def _evidence(finding_id, headers):
    return TestClient(app).get(f"/api/reviews/findings/{finding_id}/evidence", headers=headers)


def _set(finding_id, **cols):
    with connect() as conn:
        conn.execute(f"UPDATE review_findings SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                     (*cols.values(), finding_id))


def _fact_id(world):
    return connect().execute("SELECT id FROM submittal_facts WHERE submittal_document_id = ?",
                             (world["sub"],)).fetchone()["id"]


# ------------------------------------------------------------ submittal side

def test_the_values_stored_position_is_boxed_when_the_quote_is_too_short(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    fact = _fact_id(world)
    with connect() as conn:
        conn.execute("UPDATE submittal_facts SET bbox = ? WHERE id = ?",
                     (json.dumps({"reader": "geometry_reader", "value_bbox": [150, 88, 175, 102]}), fact))
    _set(finding["id"], fact_id=fact)
    r = _get(finding["id"], world["admin"], side="submittal")
    assert r.status_code == 200
    assert (r.headers["x-answer-located"], r.headers["x-evidence-box"]) == ("1", "value_position")


def test_the_facts_source_line_is_boxed_next(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    fact = _fact_id(world)
    with connect() as conn:
        conn.execute("UPDATE submittal_facts SET bbox = NULL, source_text = ? WHERE id = ?",
                     ("Noise level 95 dB(A)", fact))
    _set(finding["id"], fact_id=fact)
    assert _get(finding["id"], world["admin"], side="submittal").headers["x-evidence-box"] == "source_line"


def test_a_short_value_is_boxed_only_when_it_occurs_once_on_the_page(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _set(finding["id"], fact_id=None, contractor_evidence_text="95 dB(A)", contractor_section="Sound")
    assert _get(finding["id"], world["admin"], side="submittal").headers["x-evidence-box"] == "value_once"
    # The same value twice on the page: either could be it, so no box.
    with connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (_pdf(tmp_path / "twice.pdf", "Noise level 95 dB(A); at 3 m 95 dB(A)"), world["sub"]))
    r = _get(finding["id"], world["admin"], side="submittal")
    assert (r.headers["x-answer-located"], r.headers["x-evidence-box"]) == ("0", "none")


def test_the_label_is_boxed_last_and_named_as_the_label(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _set(finding["id"], fact_id=None, contractor_evidence_text="95", contractor_section="Noise level")
    r = _get(finding["id"], world["admin"], side="submittal")
    assert (r.headers["x-answer-located"], r.headers["x-evidence-box"]) == ("1", "label")
    body = _evidence(finding["id"], world["admin"]).json()
    assert body["submittal"]["box"] == "label" and body["submittal"]["page"] == 1


# ------------------------------------------------------------- standard side

def _checklist_row(world, finding, clause="API 610 6.1.14"):
    _set(finding["id"], origin="datasheet_check", standard_document_id=None, standard_page=None,
         standard_clause=clause, requirement_source_text="Datasheet check PSV-03: noise is stated")


def test_a_checklist_clause_is_found_in_the_held_standard_and_boxed(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _checklist_row(world, finding)
    with connect() as conn:
        conn.execute("UPDATE standard_requirements SET clause = '6.1.14' WHERE standard_document_id = ?",
                     (world["std"],))
    body = _evidence(finding["id"], world["admin"]).json()
    assert body["standard"].pop("scan") is None  # #505: a text-layer page has no scan record
    assert body["standard"] == {"document_id": world["std"], "filename": body["standard"]["filename"],
                                "page": 1, "box": "clause_text", "reason": None}
    r = _get(finding["id"], world["admin"], side="standard")
    assert (r.status_code, r.headers["x-answer-located"], r.headers["x-evidence-page"]) == (200, "1", "1")


def test_a_clause_with_no_stored_requirement_is_found_by_its_heading(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _checklist_row(world, finding)
    heading = "6.1.14 Equipment noise level shall not exceed 90 dB(A)."
    with connect() as conn:
        conn.execute("UPDATE standard_requirements SET clause = NULL WHERE standard_document_id = ?",
                     (world["std"],))
        conn.execute("UPDATE chunks SET text = ? WHERE document_id = ?", (f"Section 6\n{heading}", world["std"]))
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (_pdf(tmp_path / "heading.pdf", heading), world["std"]))
    body = _evidence(finding["id"], world["admin"]).json()
    assert (body["standard"]["page"], body["standard"]["box"]) == (1, "clause_heading")


def test_a_standard_not_held_is_said_and_never_shown_as_another_page(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _checklist_row(world, finding, clause="API 999 1.2")
    body = _evidence(finding["id"], world["admin"]).json()
    assert body["standard"]["document_id"] is None and body["standard"]["page"] is None
    assert "API 999 1.2: the standard is not in the library" in body["standard"]["reason"]
    assert _get(finding["id"], world["admin"], side="standard").status_code == 404


def test_the_resolved_standard_still_needs_the_callers_grant(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _checklist_row(world, finding)
    with connect() as conn:
        conn.execute("UPDATE standard_requirements SET clause = '6.1.14' WHERE standard_document_id = ?",
                     (world["std"],))
    sub_only = _user("subonly", [world["sub"]])
    assert _evidence(finding["id"], sub_only).json()["standard"]["document_id"] is None
    assert _get(finding["id"], sub_only, side="standard").status_code == 404
    assert _evidence(finding["id"], _user("stranger", [])).status_code == 404


def test_a_cited_clause_splits_into_standard_and_clause_number():
    assert evidence_boxes.split_clause("API 520-I 3.16") == ("API 520-I", "3.16")
    assert evidence_boxes.split_clause("API 610 6.1.14a") == ("API 610", "6.1.14a")
    assert evidence_boxes.split_clause("no clause here") is None


def test_resolving_the_evidence_writes_nothing(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _checklist_row(world, finding)
    before = dict(connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding["id"],)).fetchone())
    _evidence(finding["id"], world["admin"])
    _get(finding["id"], world["admin"], side="submittal")
    after = dict(connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding["id"],)).fetchone())
    assert after == before


# ------------------------------------------- no value found: where to look

def _pages_pdf(path, *texts):
    import pymupdf
    with pymupdf.open() as doc:
        for text in texts:
            page = doc.new_page()
            if text:
                page.insert_text((72, 100), text, fontsize=11)
        doc.save(str(path))
    return str(path)


def _no_value_row(world, finding, tmp_path, *pages, field="Noise level"):
    """A checklist row the reader found no value for (like PSV-11): no page,
    no value, no fact - only the field's name."""
    _set(finding["id"], origin="datasheet_check", contractor_page=None, contractor_evidence_text=None,
         fact_id=None, contractor_section=field, compliance_status="MISSING_INFORMATION")
    with connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (_pages_pdf(tmp_path / "sheet.pdf", *pages), world["sub"]))


def test_no_value_found_boxes_the_label_printed_once_as_where_to_look(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _no_value_row(world, finding, tmp_path, "Service: water", "Noise level:      Tag: P-101")
    side = _evidence(finding["id"], world["admin"]).json()["submittal"]
    assert (side["page"], side["box"], side["reason"]) == (2, "where_to_look", None)
    r = _get(finding["id"], world["admin"], side="submittal")
    assert (r.status_code, r.headers["x-answer-located"], r.headers["x-evidence-box"],
            r.headers["x-evidence-page"]) == (200, "1", "where_to_look", "2")


def test_no_value_found_with_the_label_printed_twice_draws_no_box_and_names_the_pages(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _no_value_row(world, finding, tmp_path, "Noise level:", "Service: water", "Noise level at 1 m:")
    side = _evidence(finding["id"], world["admin"]).json()["submittal"]
    assert (side["page"], side["box"], side["document_id"]) == (None, None, None)
    assert "printed 2 times (pages 1, 3), so no box is drawn" in side["reason"]
    assert _get(finding["id"], world["admin"], side="submittal").status_code == 404


def test_no_value_found_with_the_label_not_printed_says_where_to_check_in_words(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _no_value_row(world, finding, tmp_path, "Service: water", "Tag: P-101")
    side = _evidence(finding["id"], world["admin"]).json()["submittal"]
    assert (side["page"], side["box"]) == (None, None)
    assert side["reason"] == ("no value was found for Noise level, and its label is not printed on the "
                              "datasheet (pages 1, 2 searched) - check the section where Noise level "
                              "would be given, or ask the contractor for it")


def test_a_page_with_no_text_layer_means_the_label_found_once_is_not_proven_once(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _no_value_row(world, finding, tmp_path, "Noise level:", "")
    side = _evidence(finding["id"], world["admin"]).json()["submittal"]
    assert (side["page"], side["box"]) == (None, None)
    assert "page 2 has no text layer, so check it by eye" in side["reason"]


def test_a_row_that_is_not_a_checklist_row_still_cites_no_page(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _no_value_row(world, finding, tmp_path, "Noise level:")
    _set(finding["id"], origin="comparison")
    side = _evidence(finding["id"], world["admin"]).json()["submittal"]
    assert (side["page"], side["reason"]) == (None, "this finding cites no submittal page")


def test_showing_where_to_look_writes_nothing(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    _no_value_row(world, finding, tmp_path, "Noise level:")
    before = dict(connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding["id"],)).fetchone())
    _evidence(finding["id"], world["admin"])
    _get(finding["id"], world["admin"], side="submittal")
    after = dict(connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding["id"],)).fetchone())
    assert after == before
