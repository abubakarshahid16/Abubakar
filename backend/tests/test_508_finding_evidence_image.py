"""R21 / #508: the page each side of a finding cites, with the finding's own
stored text boxed on it - for the side-by-side evidence view.

What must hold: the text is the finding's stored quote, looked up by id (never
passed in the URL); a quote found on its page is boxed and says so; a quote
that cannot be placed safely (too short, or not on the page) returns the page
WITHOUT a box and says so; a side with no cited page is a named 404; the
standard side needs the standard's own grant; a stranger gets 404; the route is
read only. Invented PDFs only.
"""
from __future__ import annotations

import pymupdf
from fastapi.testclient import TestClient

from app import review_jobs
from app.db import connect
from app.main import app
from tests.test_p3_review_jobs import W, _enqueue, _user, temp_storage, world  # noqa: F401 - fixtures

STD_TEXT = "Equipment noise level shall not exceed 90 dB(A)."
SUB_TEXT = "Pump shall comply with API 610. Noise level 95 dB(A)"


def _pdf(path, text):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=11)
        doc.save(str(path))
    return str(path)


def _reviewed(world, tmp_path):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    # The pages the findings cite, as invented PDFs (after the run: the review
    # reads the indexed text, the image route reads the file).
    with connect() as conn:
        for doc_id, text in ((world["std"], STD_TEXT), (world["sub"], SUB_TEXT)):
            conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                         (_pdf(tmp_path / f"{doc_id}.pdf", text), doc_id))
    row = connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND standard_document_id = ?"
        " AND standard_page IS NOT NULL AND contractor_page IS NOT NULL", (run_id, world["std"])).fetchone()
    assert row is not None
    return dict(row)


def _get(finding_id, headers, **params):
    return TestClient(app).get(f"/api/reviews/findings/{finding_id}/evidence-image",
                               headers=headers, params=params)


def test_the_standard_sentence_is_boxed_on_its_page(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    assert finding["requirement_source_text"] and "90 dB(A)" in finding["requirement_source_text"]
    r = _get(finding["id"], world["admin"], side="standard")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert r.headers["x-answer-located"] == "1"


def test_a_value_too_short_to_place_safely_is_shown_without_a_box(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    r = _get(finding["id"], world["admin"], side="submittal")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert r.headers["x-answer-located"] == "0"      # the stored value "95" is under the safe length


def test_text_that_is_not_on_the_page_gets_no_box(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    with connect() as conn:
        conn.execute("UPDATE review_findings SET requirement_source_text = ? WHERE id = ?",
                     ("Bearing temperature shall not exceed 82 degrees.", finding["id"]))
    r = _get(finding["id"], world["admin"], side="standard")
    assert r.status_code == 200 and r.headers["x-answer-located"] == "0"


def test_a_side_with_no_cited_page_is_a_named_404(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    with connect() as conn:
        conn.execute("UPDATE review_findings SET standard_page = NULL WHERE id = ?", (finding["id"],))
    r = _get(finding["id"], world["admin"], side="standard")
    assert r.status_code == 404 and "cites no standard page" in r.text


def test_the_standard_side_needs_the_standards_own_grant(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    sub_only = _user("subonly", [world["sub"]])
    assert _get(finding["id"], sub_only, side="submittal").status_code == 200
    assert _get(finding["id"], sub_only, side="standard").status_code == 404
    stranger = _user("stranger", [])
    assert _get(finding["id"], stranger, side="submittal").status_code == 404


def test_unknown_or_bad_parameters_are_refused_and_nothing_is_written(world, tmp_path):
    finding = _reviewed(world, tmp_path)
    before = dict(connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding["id"],)).fetchone())
    assert _get(finding["id"], world["admin"], side="standard", q="anything").status_code == 422
    assert _get(finding["id"], world["admin"], side="both").status_code == 422
    assert _get("no-such-finding", world["admin"], side="standard").status_code == 404
    after = dict(connect().execute("SELECT * FROM review_findings WHERE id = ?", (finding["id"],)).fetchone())
    assert after == before
