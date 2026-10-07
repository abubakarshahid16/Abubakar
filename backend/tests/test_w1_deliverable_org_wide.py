"""W1: deleting a document must not turn its deliverables public.

`deliverables.document_id` is `ON DELETE SET NULL`, and a NULL document used to
mean "visible to every identified caller". So deleting a private document made
the deliverables tied to it, and the risks tied to those, public. The explicit
`org_wide` flag is written only at creation; a nulled row keeps 0.
"""

from __future__ import annotations

from app import deliverables, risks
from app.db import connect

from tests.r2_security_support import h, temp_storage, world  # noqa: F401


RISK = sorted(risks.RISK_TYPES)[0]


def _make(doc: str | None, **over) -> dict:
    payload = {"wbs_code": "1.1", "title": "Pack", "deliverable_type": "datasheet",
               "document_id": doc, **over}
    return deliverables.create(payload, created_by="u_admin")


def _titles(world, user: str) -> set[str]:
    r = world.get("/api/deliverables", headers=h(user))
    assert r.status_code == 200, r.text
    return {d["title"] for d in r.json()["deliverables"]}


def _delete_document(doc: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc,))


def test_org_wide_is_set_only_for_a_row_created_without_a_document(world):
    assert _make(None, title="Shared")["org_wide"] == 1
    assert _make("doc_std", title="Tied", wbs_code="2.1")["org_wide"] == 0


def test_a_deleted_documents_deliverable_does_not_become_public(world):
    _make("doc_std", title="Private pack", wbs_code="2.1")
    _make(None, title="Shared pack", wbs_code="3.1")
    before = _titles(world, "u_sub")
    assert "Private pack" not in before and "Shared pack" in before

    _delete_document("doc_std")

    after = _titles(world, "u_sub")
    assert "Private pack" not in after, \
        "deleting the document made its deliverable visible to a caller with no grant"
    assert "Shared pack" in after
    # Hidden is not destroyed: the row is still in the database (the admin
    # explorer shows it) and is simply out of every scoped list.
    kept = connect().execute(
        "SELECT document_id, org_wide FROM deliverables WHERE title = 'Private pack'"
    ).fetchone()
    assert kept is not None and kept["document_id"] is None and kept["org_wide"] == 0


def test_a_nulled_row_is_not_opened_through_workspace_or_risks(world):
    item = _make("doc_std", title="Private pack", wbs_code="2.1")
    risks.create({"risk_type": RISK, "title": "Late pack", "description": "x", "severity": "high",
                  "deliverable_id": item["id"]})
    _delete_document("doc_std")

    r = world.get(f"/api/deliverables/{item['id']}/workspace", headers=h("u_sub"))
    assert r.status_code == 404
    assert "Late pack" not in {x["title"] for x in risks.list_items(
        allowed_document_ids=frozenset({"doc_sub"}))}


def test_restarting_does_not_relabel_a_nulled_row_as_public(world):
    _make("doc_std", title="Private pack", wbs_code="2.1")
    _delete_document("doc_std")
    deliverables.ensure_schema()
    deliverables.ensure_schema()
    assert "Private pack" not in _titles(world, "u_sub")
