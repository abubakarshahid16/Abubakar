"""The older stored CRS files go through the completeness check (hard rule): a stored file whose rows differ from its run's lines is refused with
the plain sentence; a whole file is served; the page's counts come from the same check. Invented data only."""

from __future__ import annotations

import openpyxl
import pytest

from app import agent_review_jobs, crs_completeness
from tests.test_agent_review_routes import client, finished_run  # noqa: F401 - fixture


def _stored(run_id, copy="internal"):
    return agent_review_jobs.run_dir(run_id) / f"crs-{copy}.xlsx"


def _drop_evidence_row(path, row_index=0):
    wb = openpyxl.load_workbook(path)
    ws = wb["Evidence"]
    top = next(r for r in range(1, 40) if ws.cell(r, 1).value == "Item No")
    ws.delete_rows(top + 1 + row_index)
    wb.save(path)


def test_a_whole_stored_file_is_served_and_the_check_is_the_one_home(client):
    run_id = finished_run(client)
    assert client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=internal").status_code == 200
    assert client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=contractor").status_code == 200
    rep = crs_completeness.older_report(run_id, "internal", _stored(run_id).read_bytes())
    assert rep["ok"] and rep["rows_in_file"] == rep["expected"] > 0


def test_a_stored_file_with_a_row_removed_is_refused_with_the_plain_sentence(client):
    run_id = finished_run(client)
    _drop_evidence_row(_stored(run_id))
    r = client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=internal")
    assert r.status_code == 409
    text = r.text
    assert "not complete and was not given out" in text and "Missing: item" in text and "Use the one CRS" in text
    assert client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=contractor").status_code == 200  # only the cut file is refused


def test_a_file_from_before_the_layout_is_refused_not_called_complete(client):
    run_id = finished_run(client)
    wb = openpyxl.load_workbook(_stored(run_id))
    del wb["Evidence"]
    wb.save(_stored(run_id))
    r = client.get(f"/api/reviews/runs/{run_id}/agent/crs?copy=internal")
    assert r.status_code == 409 and "cannot be compared" in r.text


def test_the_counts_under_an_older_files_button_are_the_runs_lines_and_the_papers_points(client):
    run_id = finished_run(client)
    got = client.get(f"/api/reviews/runs/{run_id}/agent/crs/older").json()
    assert got["run_id"] == run_id and got["ai_lines"] > 0
    assert got["paper_points"] is None or got["paper_points"] > 0  # null when the page's list cannot be read: never 0
    assert client.get("/api/reviews/runs/nope/agent/crs/older").status_code == 404
