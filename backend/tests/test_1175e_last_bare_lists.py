"""Order 117 item 5, last part: the remaining bare-list routes (the standards
missing, cited-but-not-held, conflicts and revisions lists, and a submittal's
applicability list) take an optional page and always state their total in
`X-Total-Count`.

The list stays a list; without `limit`/`offset` it is the whole list, as
before. The total counts only what the caller may read (rule 4, rule 5).
Invented documents only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, paging, standards
from app.main import app
from tests.test_standards_inventory import _doc, temp_storage  # noqa: F401

CITES = "Pump shall comply with API 610, ASME B31.3, ISO 13709 and NFPA 70."


@pytest.fixture(autouse=True)
def _no_scope_left_behind():
    yield
    app.dependency_overrides.pop(access.current_scope, None)


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def _paged(client: TestClient, path: str, whole: list, size: int = 2):
    """Every page of `path`, joined, and the totals the pages stated."""
    sep = "&" if "?" in path else "?"
    pages = [
        client.get(f"{path}{sep}limit={size}&offset={o}")
        for o in range(0, max(len(whole), 1), size)
    ]
    for page in pages:
        assert page.status_code == 200, page.text
    return [row for p in pages for row in p.json()], {
        p.headers[paging.TOTAL_HEADER] for p in pages
    }


def _check(client: TestClient, path: str) -> list:
    whole = client.get(path)
    assert whole.status_code == 200, whole.text
    rows = whole.json()
    assert isinstance(rows, list) and len(rows) >= 3
    assert whole.headers[paging.TOTAL_HEADER] == str(len(rows))
    joined, totals = _paged(client, path, rows)
    assert joined == rows
    assert totals == {str(len(rows))}
    one = client.get(f"{path}{'&' if '?' in path else '?'}limit=1&offset=1")
    assert one.json() == rows[1:2]
    return rows


def test_the_cited_but_not_held_and_missing_lists_page_within_the_grants():
    sub = _doc("sub1", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES)
    _doc("sub_hidden", "other.pdf", "CONTRACTOR_SUBMITTAL", text="Per IEC 60079-0.")
    client = _client(sub)
    for path in ("/api/standards/cited-but-not-held", "/api/standards/missing"):
        rows = _check(client, path)
        assert "IEC 60079-0" not in {r["identifier"] for r in rows}, path


def _limit(doc: str, field: str, value: float) -> None:
    standards.create_requirement(
        standard_document_id=doc,
        chunk_id=f"{doc}-c1",
        requirement_text="t",
        source_text="t",
        clause="5.1",
        page=1,
        structured={
            "field": field,
            "operator": ">=",
            "value": value,
            "unit": "um",
            "requirement_type": "numeric_limit",
        },
    )


def test_the_conflicts_list_pages_and_a_hidden_standards_conflict_is_uncounted():
    a = _doc("std_a", "A.pdf", "COMPANY_STANDARD")
    b = _doc("std_b", "B.pdf", "COMPANY_STANDARD")
    hidden = _doc("std_hidden", "H.pdf", "COMPANY_STANDARD")
    for i, field in enumerate(("thickness", "depth", "width", "gap")):
        _limit(a, field, 10.0 + i)
        _limit(b, field, 20.0 + i)
    _limit(a, "height", 1.0)
    _limit(hidden, "height", 9.0)
    rows = _check(_client(a, b), "/api/standards/conflicts")
    assert {r["field"] for r in rows} == {"thickness", "depth", "width", "gap"}
    full = _client(a, b, hidden).get("/api/standards/conflicts")
    assert full.headers[paging.TOTAL_HEADER] == "5"


def test_the_revisions_list_pages_and_counts_only_readable_revisions():
    revs = [
        _doc(f"std_r{i}", f"R{i}.pdf", "COMPANY_STANDARD", document_number="STD-9")
        for i in range(4)
    ]
    hidden = _doc("std_rh", "RH.pdf", "COMPANY_STANDARD", document_number="STD-9")
    client = _client(*revs)
    rows = _check(client, f"/api/standards/{revs[0]}/revisions")
    assert hidden not in {r["id"] for r in rows}
    assert len(rows) == 4


def test_the_applicability_list_pages_and_counts_only_readable_standards():
    stds = [_doc(f"std_p{i}", f"P{i}.pdf", "COMPANY_STANDARD") for i in range(4)]
    hidden = _doc("std_ph", "PH.pdf", "COMPANY_STANDARD")
    sub = _doc("sub_p", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES)
    client = _client(sub, *stds)
    rows = _check(client, f"/api/documents/{sub}/applicability")
    assert hidden not in {r.get("standard_document_id") for r in rows}
    assert len(rows) == 4


def test_a_good_page_is_accepted_and_a_bad_one_refused():
    sub = _doc("sub1", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES)
    std = _doc("std_a", "A.pdf", "COMPANY_STANDARD")
    client = _client(sub, std)
    for path in (
        "/api/standards/cited-but-not-held",
        "/api/standards/missing",
        "/api/standards/conflicts",
        f"/api/standards/{std}/revisions",
        f"/api/documents/{sub}/applicability",
    ):
        assert client.get(f"{path}?limit=1&offset=0").status_code == 200, path
        for query in ("limit=0", "limit=1001", "offset=-1"):
            assert client.get(f"{path}?{query}").status_code == 422, (path, query)
