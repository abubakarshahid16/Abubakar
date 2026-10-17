"""#967: the Sheet's datasheet page with every card's value underlined on it.

What must hold: the route draws the marks the screen asks for (ids and
states only in the URL), says how many it placed out of how many were asked,
re-renders when a card's state changes, refuses an id from another run or
another page, keeps a stranger out, and writes nothing. Invented PDFs only.
"""
from __future__ import annotations

import pymupdf
from fastapi.testclient import TestClient

from app import pageimage, review_jobs
from app.db import connect
from app.main import app
from tests.test_p3_review_jobs import W, _enqueue, _user, temp_storage, world  # noqa: F401 - fixtures

SUB_TEXT = "Pump shall comply with API 610. Noise level 95 dB(A)"


def _pdf(path, text):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=11)
        doc.save(str(path))
    return str(path)


def _reviewed(world, tmp_path):
    """The run and its findings on the datasheet's page 1, the page as an
    invented PDF whose text the review indexed."""
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    with connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                     (_pdf(tmp_path / "sub.pdf", SUB_TEXT), world["sub"]))
    rows = [dict(r) for r in connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND contractor_page = 1", (run_id,))]
    assert rows, "the invented review cites no datasheet page"
    return run_id, rows


def _get(run_id, headers, **params):
    return TestClient(app).get(f"/api/reviews/runs/{run_id}/page-image", headers=headers, params=params)


def test_every_asked_value_is_underlined_and_counted(world, tmp_path):
    run_id, rows = _reviewed(world, tmp_path)
    # a quote the page carries, on every finding: each one can be placed
    with connect() as conn:
        for row in rows:
            conn.execute("UPDATE review_findings SET contractor_evidence_text = ? WHERE id = ?",
                         ("Noise level 95 dB(A)", row["id"]))
    marks = ",".join(f"{r['id']}:open" for r in rows)
    r = _get(run_id, world["admin"], page=1, marks=marks)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert (r.headers["x-marks-located"], r.headers["x-marks-total"]) == (str(len(rows)), str(len(rows)))
    assert r.headers["x-evidence-page"] == "1"
    plain = TestClient(app).get(f"/api/documents/{world['sub']}/pages/1/image", headers=world["admin"])
    assert plain.status_code == 200 and plain.content != r.content, "the marks were not drawn"


def test_a_value_that_cannot_be_placed_gets_no_mark_and_the_count_says_so(world, tmp_path):
    run_id, rows = _reviewed(world, tmp_path)
    with connect() as conn:
        conn.execute("UPDATE review_findings SET contractor_evidence_text = ?, contractor_section = ?,"
                     " fact_id = NULL WHERE id = ?", ("not on this page at all", "Sound pressure", rows[0]["id"]))
    r = _get(run_id, world["admin"], page=1, marks=f"{rows[0]['id']}:open")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert (r.headers["x-marks-located"], r.headers["x-marks-total"]) == ("0", "1")


def test_answering_a_card_changes_the_render_not_the_cache_hit(world, tmp_path):
    run_id, rows = _reviewed(world, tmp_path)
    with connect() as conn:
        conn.execute("UPDATE review_findings SET contractor_evidence_text = ? WHERE id = ?",
                     ("Noise level 95 dB(A)", rows[0]["id"]))
    before = _get(run_id, world["admin"], page=1, marks=f"{rows[0]['id']}:open")
    after = _get(run_id, world["admin"], page=1, marks=f"{rows[0]['id']}:answered")
    assert before.status_code == after.status_code == 200
    assert before.content != after.content, "the grey mark was served the amber render"
    assert before.headers["x-marks-located"] == after.headers["x-marks-located"] == "1"


def test_an_id_from_another_run_or_page_is_refused(world, tmp_path):
    run_id, rows = _reviewed(world, tmp_path)
    assert _get("run-other", world["admin"], page=1, marks=f"{rows[0]['id']}:open").status_code == 404
    assert _get(run_id, world["admin"], page=1, marks="nope:open").status_code == 404
    assert _get(run_id, world["admin"], page=2, marks=f"{rows[0]['id']}:open").status_code == 422
    assert _get(run_id, world["admin"], page=1, marks=f"{rows[0]['id']}:green").status_code == 422
    assert _get(run_id, world["admin"], page=1, marks=f"{rows[0]['id']}:open", extra=1).status_code == 422


def test_a_stranger_gets_404_and_nothing_is_written(world, tmp_path):
    run_id, rows = _reviewed(world, tmp_path)
    stranger = _user("stranger", [])
    assert _get(run_id, stranger, page=1, marks=f"{rows[0]['id']}:open").status_code == 404
    audits = connect().execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    _get(run_id, world["admin"], page=1, marks=f"{rows[0]['id']}:open")
    assert connect().execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == audits


def test_the_render_draws_one_colour_per_state(tmp_path):
    """Unit: a page rendered with an open mark differs from the same page
    with an answered mark, and an unknown state is refused."""
    path = _pdf(tmp_path / "p.pdf", SUB_TEXT)
    doc = {"stored_path": path, "sha256": "a" * 64}
    rects = [(72.0, 90.0, 200.0, 104.0)]
    amber = pageimage.render_page_with_marks(doc, 1, [(rects, "open")]).read_bytes()
    grey = pageimage.render_page_with_marks(doc, 1, [(rects, "answered")]).read_bytes()
    plain = pageimage.render_page(doc, 1).read_bytes()
    assert amber != grey and amber != plain and grey != plain
    assert pageimage.render_page_with_marks(doc, 1, [([], "open")]).read_bytes() == plain
    try:
        pageimage.render_page_with_marks(doc, 1, [(rects, "green")])
    except ValueError as e:
        assert "green" in str(e)
    else:
        raise AssertionError("an unknown state was drawn")
