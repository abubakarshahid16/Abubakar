"""Standards beyond Saudi Aramco's: where to obtain a missing one (a fixed
publisher page, never a download), a request recorded under an engineer's
name, and an uploaded copy marked as obtained externally with its hash."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import standards_acquisition as acq
from app.main import app
from tests.test_model_matching import _signed_in
from tests.test_standards_inventory import _doc, _scope, temp_storage  # noqa: F401


def _submittal(text="Pump shall comply with API 610 and ASME B31.3 and SAES-L-105."):
    return _doc("sub1", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL", text=text,
                discipline="Mechanical")


# ------------------------------------------------------------ where to obtain

@pytest.mark.parametrize("identifier,publisher", [
    ("API 610", "American Petroleum Institute (API)"),
    ("ASME B31.3", "ASME"),
    ("ASTM A106", "ASTM International"),
    ("ISO 13709", "ISO"),
    ("IEC 60079-0", "IEC Webstore"),
    ("NFPA 70", "NFPA"),
    ("NACE MR0175", "AMPP (formerly NACE)"),
    ("NORSOK M-501", "Standards Norway (NORSOK)"),
])
def test_a_public_standard_points_at_its_publishers_own_catalogue(identifier, publisher):
    where = acq.where_to_obtain(identifier)
    assert where["publisher"] == publisher
    assert where["url"].startswith("https://")


def test_no_link_carries_the_identifier_or_any_query():
    """Following a link sends nothing from a document (CLAUDE.md rule 1)."""
    for _pattern, _pub, url, _note in acq.PUBLISHERS:
        assert "?" not in url and "#" not in url


@pytest.mark.parametrize("identifier", ["SAES-L-105", "01-SAMSS-016", "KOC-MP-010"])
def test_a_company_standard_is_never_pointed_at_a_web_site(identifier):
    where = acq.where_to_obtain(identifier)
    assert where["url"] is None and "custodian" in where["note"]


def test_an_unrecognised_publisher_gets_no_guessed_site():
    assert acq.where_to_obtain("XYZ 12")["url"] is None


# --------------------------------------------------------------- the list

def test_the_missing_list_is_the_cited_but_not_held_list_with_links():
    sub = _submittal()
    rows = {r["identifier"]: r for r in acq.missing_standards(allowed_document_ids=_scope(sub))}
    assert {"API 610", "ASME B31.3"} <= set(rows)
    assert rows["API 610"]["status"] == acq.MISSING_LOCALLY
    assert rows["API 610"]["obtain"]["publisher"] == "American Petroleum Institute (API)"


def test_a_standard_outside_the_callers_grants_is_not_listed():
    _submittal()
    assert acq.missing_standards(allowed_document_ids=_scope()) == []


# --------------------------------------------------------------- requests

def test_a_request_is_recorded_under_the_engineers_name(monkeypatch):
    sub = _submittal()
    _signed_in(monkeypatch, [sub])
    client = TestClient(app)
    r = client.post("/api/standards/missing/request",
                    json={"identifier": "API 610", "note": "PO 4411"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["requested_by"]) == (acq.REQUESTED, "eng-1")
    listed = {x["identifier"]: x for x in client.get("/api/standards/missing").json()}
    assert listed["API 610"]["status"] == acq.REQUESTED and listed["API 610"]["note"] == "PO 4411"
    assert listed["ASME B31.3"]["status"] == acq.MISSING_LOCALLY


def test_a_request_for_a_standard_nobody_cited_is_refused(monkeypatch):
    sub = _submittal()
    _signed_in(monkeypatch, [sub])
    r = TestClient(app).post("/api/standards/missing/request", json={"identifier": "API 999"})
    assert r.status_code == 404


def test_an_unsigned_request_is_refused(monkeypatch):
    _submittal()
    monkeypatch.setattr("app.config.settings.auth_mode", "disabled")
    r = TestClient(app).post("/api/standards/missing/request", json={"identifier": "API 610"})
    assert r.status_code == 401


# ------------------------------------------------------------- provenance

def test_an_uploaded_copy_is_marked_external_with_its_hash(monkeypatch):
    sub = _submittal()
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD", document_number="API 610",
               discipline="Mechanical")
    _signed_in(monkeypatch, [sub, std])
    client = TestClient(app)
    r = client.post(f"/api/standards/{std}/provenance",
                    json={"identifier": "API 610", "obtained_from": "API webstore, order 4411"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["source_type"], body["sha256"], body["recorded_by"], body["current"]) == \
        ("external", "sha-std_610", "eng-1", True)
    assert client.get(f"/api/standards/{std}/provenance").json()["provenance"]["obtained_from"] \
        == "API webstore, order 4411"
    # now held: off the missing list by itself
    assert "API 610" not in {x["identifier"] for x in client.get("/api/standards/missing").json()}


def test_a_replaced_file_does_not_inherit_the_record(monkeypatch):
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD", document_number="API 610")
    _signed_in(monkeypatch, [std])
    TestClient(app).post(f"/api/standards/{std}/provenance",
                         json={"identifier": "API 610", "obtained_from": "API webstore"})
    from app import db
    with db.connect() as conn:
        conn.execute("UPDATE documents SET sha256 = 'other' WHERE id = ?", (std,))
    assert acq.provenance_of(std)["current"] is False


def test_provenance_needs_a_source_and_a_readable_standard(monkeypatch):
    sub = _submittal()
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD", document_number="API 610")
    _signed_in(monkeypatch, [sub])  # no grant on std
    client = TestClient(app)
    assert client.post(f"/api/standards/{std}/provenance",
                       json={"identifier": "API 610", "obtained_from": "x"}).status_code == 404
    assert client.post(f"/api/standards/{sub}/provenance",   # a submittal is not a standard
                       json={"identifier": "API 610", "obtained_from": "x"}).status_code == 404
    with pytest.raises(acq.AcquisitionError, match="obtained from"):
        acq.record_external_copy(std, identifier="API 610", obtained_from="  ",
                                 user_id="eng-1", allowed_document_ids=_scope(std))


def test_no_provenance_recorded_reads_null_not_company(monkeypatch):
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD", document_number="API 610")
    _signed_in(monkeypatch, [std])
    assert TestClient(app).get(f"/api/standards/{std}/provenance").json() == {"provenance": None}
