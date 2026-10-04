"""r2 S3: rows with NO document, and rows whose SOURCE document is out of scope.

 * A deliverable with a NULL document_id was open to every identified caller,
   including one with no grant at all, to rewrite its stakeholders or fields.
 * An inferred expectation, and an overdue-deliverable risk, carry the source
   document; a caller who may not read it must not be handed the row.
Admin sees everything. Mutations: scripts/mutations/r2_security.py M1983-M1984,
M1989.
"""

from __future__ import annotations

from app import deliverables, risks
from app.db import connect

from tests.r2_security_support import h, temp_storage, world  # noqa: F401


def _deliverable(doc: str | None, **over) -> dict:
    payload = {"wbs_code": "1.1", "title": "Datasheet pack", "deliverable_type": "datasheet",
               "document_id": doc, **over}
    return deliverables.create(payload, created_by="u_admin")


def test_a_caller_with_no_grants_cannot_write_a_document_less_deliverable(world):
    item = _deliverable(None, title="ORIGINAL")
    r = world.patch(f"/api/deliverables/{item['id']}", json={"title": "CHANGED"},
                    headers=h("u_none"))
    assert r.status_code == 404
    assert deliverables.get(item["id"])["title"] == "ORIGINAL"

    r = world.put(f"/api/deliverables/{item['id']}/stakeholders",
                  json={"assignments": [{"user_id": "u_none", "role": "owner"}]},
                  headers=h("u_none"))
    assert r.status_code == 404
    assert deliverables.stakeholders(item["id"]) == [], \
        "a caller with no grant made themselves owner of a shared row"
    for path in ("history", "stakeholders", "workspace"):
        assert world.get(f"/api/deliverables/{item['id']}/{path}",
                         headers=h("u_none")).status_code == 404, path


def test_a_caller_with_a_grant_and_the_admin_can_still_use_it(world):
    item = _deliverable(None)
    ok = world.patch(f"/api/deliverables/{item['id']}", json={"title": "NEW"},
                     headers=h("u_sub"))
    assert ok.status_code == 200, ok.text
    ok = world.put(f"/api/deliverables/{item['id']}/stakeholders",
                   json={"assignments": [{"user_id": "u_admin", "role": "owner"}]},
                   headers=h("u_admin"))
    assert ok.status_code == 200, ok.text


def test_an_expectation_inferred_from_a_hidden_document_is_not_returned(world):
    deliverables.configure_expectation({"wbs_code": "2.1", "deliverable_type": "report",
                                        "title": "Manual", "required": 1})
    deliverables.configure_expectation({"wbs_code": "9.9", "deliverable_type": "drawing",
                                        "title": "Inferred from the standard", "required": 1,
                                        "inferred": 1, "source_document_id": "doc_std"})
    titles = lambda user: {d["title"] for d in world.get(  # noqa: E731
        "/api/deliverables/expected", headers=h(user)).json()["deliverables"]}
    assert titles("u_sub") == {"Manual"}
    assert titles("u_full") == {"Manual", "Inferred from the standard"}
    assert titles("u_admin") == {"Manual", "Inferred from the standard"}


def test_the_expectation_status_does_not_reveal_a_hidden_deliverable(world):
    deliverables.configure_expectation({"wbs_code": "3.1", "deliverable_type": "report",
                                        "title": "Manual", "required": 1})
    _deliverable("doc_std", wbs_code="3.1", deliverable_type="report", status="approved")
    [row] = world.get("/api/deliverables/expected", headers=h("u_sub")).json()["deliverables"]
    assert row["state"] == "missing" and row["deliverable_id"] is None, \
        "the registered status of a deliverable on a hidden document leaked"


def test_an_overdue_risk_carries_its_source_document(world):
    item = _deliverable("doc_std", due_date="2020-01-01")
    full = world.get("/api/risks", headers=h("u_full")).json()["risks"]
    [risk] = [r for r in full if r["deliverable_id"] == item["id"]]
    assert risk["document_id"] == "doc_std"
    seen = world.get("/api/risks", headers=h("u_sub")).json()["risks"]
    assert [r for r in seen if r["deliverable_id"] == item["id"]] == [], \
        "a caller who may not read the source document was handed its overdue risk"
    admin_view = world.get("/api/risks", headers=h("u_admin")).json()["risks"]
    assert any(r["deliverable_id"] == item["id"] for r in admin_view)


def test_a_risk_row_written_without_a_document_follows_its_deliverable(world):
    """Rows written before `document_id` was carried have it NULL."""
    item = _deliverable("doc_std")
    risks.create({"risk_type": "schedule", "title": "legacy", "description": "d",
                  "deliverable_id": item["id"]})
    assert connect().execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 1
    assert world.get("/api/risks", headers=h("u_sub")).json()["risks"] == []
    assert len(world.get("/api/risks", headers=h("u_full")).json()["risks"]) == 1
