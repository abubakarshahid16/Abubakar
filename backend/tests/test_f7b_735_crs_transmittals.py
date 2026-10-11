"""#725 F7 (#735), part 2: the CRS transmittal numbers are editable.

The CRS header's "COMPANY Transmittal No." and "CONTRACTOR Transmittal No."
were hard-coded blank: nothing could fill them. Now a signed-in reviewer
enters them per review run (PUT .../crs/transmittals); the sheet and the
preview print exactly what was entered, and nothing when nothing was - never
an invented number. Invented values only.

Mutations: M7201-M7205 (scripts/mutations/f7b_735_crs_transmittals.py).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import access
from app.crs_export import HEADER_FIELDS
from app.main import app
from tests.test_crs_endpoint import _client, _run, _sheet, _submittal, temp_db  # noqa: F401


def _row(key):
    return 3 + [k for _, k in HEADER_FIELDS].index(key)


def test_entered_transmittal_numbers_are_printed_on_the_sheet():
    """THE MUTATION TARGET."""
    doc = _submittal()
    run_id = _run(doc)
    client = _client(doc)
    saved = client.put(f"/api/reviews/runs/{run_id}/crs/transmittals",
                       json={"company_transmittal": "CT-0001", "contractor_transmittal": "  XT-0042  "})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"company_transmittal": "CT-0001", "contractor_transmittal": "XT-0042"}
    ws = _sheet(client.get(f"/api/reviews/runs/{run_id}/crs"))
    assert ws.cell(row=_row("company_transmittal"), column=3).value == "CT-0001"
    assert ws.cell(row=_row("contractor_transmittal"), column=3).value == "XT-0042"
    header = {h["label"]: h["value"] for h in client.get(f"/api/reviews/runs/{run_id}/crs/preview").json()["header"]}
    assert "CT-0001" in header.values() and "XT-0042" in header.values()


def test_an_empty_value_clears_a_number_and_the_cell_prints_nothing():
    doc = _submittal()
    run_id = _run(doc)
    client = _client(doc)
    client.put(f"/api/reviews/runs/{run_id}/crs/transmittals",
               json={"company_transmittal": "CT-0001", "contractor_transmittal": "XT-0042"})
    client.put(f"/api/reviews/runs/{run_id}/crs/transmittals",
               json={"company_transmittal": "", "contractor_transmittal": "XT-0042"})
    ws = _sheet(client.get(f"/api/reviews/runs/{run_id}/crs"))
    assert ws.cell(row=_row("company_transmittal"), column=3).value in (None, "")
    assert ws.cell(row=_row("contractor_transmittal"), column=3).value == "XT-0042"


def test_a_run_the_caller_may_not_read_is_404_and_unchanged():
    doc = _submittal()
    run_id = _run(doc)
    response = _client("doc_other").put(f"/api/reviews/runs/{run_id}/crs/transmittals",
                                        json={"company_transmittal": "CT-9", "contractor_transmittal": ""})
    assert response.status_code == 404
    ws = _sheet(_client(doc).get(f"/api/reviews/runs/{run_id}/crs"))
    assert ws.cell(row=_row("company_transmittal"), column=3).value in (None, "")


def test_an_unnamed_caller_cannot_enter_one():
    doc = _submittal()
    run_id = _run(doc)
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({doc}))
    response = TestClient(app).put(f"/api/reviews/runs/{run_id}/crs/transmittals",
                                   json={"company_transmittal": "CT-1", "contractor_transmittal": ""})
    assert response.status_code == 401


def test_an_unknown_field_or_an_over_long_value_is_refused():
    doc = _submittal()
    run_id = _run(doc)
    client = _client(doc)
    assert client.put(f"/api/reviews/runs/{run_id}/crs/transmittals",
                      json={"company_transmittal": "x", "submittal_number": "y"}).status_code == 422
    assert client.put(f"/api/reviews/runs/{run_id}/crs/transmittals",
                      json={"company_transmittal": "x" * 81}).status_code == 422
