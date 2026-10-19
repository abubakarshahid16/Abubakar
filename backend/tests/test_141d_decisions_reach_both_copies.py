"""Order 141 D: the engineer's Keep / Edit / Remove reach BOTH Excel copies.

The owner reviewed a submittal on the workspace and the internal copy still
printed every row as "AI Review" / "Draft (not issued)". This guards the
server half of the chain: a decision sent through the real routes the
workspace uses (`saveCrsDecisions`: Keep = PATCH confirmed, Edit = PATCH
engineer_comment, Remove = the CRS decision route with a listed reason) is
what both copies print, built exactly as the export builds them
(`_crs_content` + `crs_export.build_crs_view`).

The review is numbered first, as a finished review is (`number_crs_rows`),
so the machine draft starts as "Draft (not issued)". Synthetic sheet only.

The server half already worked when this was written: no server change came
with order 141 D. BREAK PROOF (done once by hand): drop the route's
`confirmed_by` write and keep/edit fail; make `crs_mapping._by` print
"AI Review" for a confirmed row and keep fails.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, crs_export
from app.main import DRAFT_NOT_ISSUED, _crs_content, app, number_crs_rows
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in
from tests.test_review_screen import _first_comment

# The made-up reviewed sheet of test_review_screen, as the fixture `_world`.
from tests.test_review_screen import world as _world  # noqa: F401

EDITED = "Contractor to state the noise level at 1 m."
NOISE = "95 dB(A)"


def _copies(run: str, scope: frozenset[str]) -> dict[str, list[dict]]:
    """Both copies' rows, composed and shaped as the export composes them."""
    reader = access.AccessScope(user_id=None, allowed_document_ids=scope)
    out = {}
    for copy in ("internal", "issue"):
        rows, meta, _name, _stamp = _crs_content(run, reader, copy)
        out[copy] = crs_export.build_crs_view(rows, meta)["rows"]
    return out


def _about(rows: list[dict]) -> list[dict]:
    return [r for r in rows if NOISE in r["comment"] or EDITED in r["comment"]]


def _numbered_draft(request):
    _sub, run, scope = request.getfixturevalue("_world")
    number_crs_rows(run, access.AccessScope(user_id=None, allowed_document_ids=scope))
    [draft] = _about(_copies(run, scope)["internal"])
    assert draft["comment_by"] == "AI Review"
    assert draft["final_resolution"] == DRAFT_NOT_ISSUED
    assert not _about(_copies(run, scope)["issue"]), (
        "a machine draft is never in the issue copy"
    )
    return run, scope, draft


@pytest.mark.parametrize("decision", ["keep", "edit"])
def test_a_kept_or_edited_comment_is_the_engineers_in_both_copies(
    request, monkeypatch, decision
):
    run, scope, draft = _numbered_draft(request)
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    body = {"confirmed": True} if decision == "keep" else {"engineer_comment": EDITED}
    response = TestClient(app).patch(f"/api/reviews/findings/{finding_id}", json=body)
    assert response.status_code == 200, response.text

    copies = _copies(run, scope)
    for copy in ("internal", "issue"):
        [row] = _about(copies[copy])
        assert row["crs_ref"] == draft["crs_ref"], (
            f"{copy}: confirming issues the draft's own number"
        )
        assert row["final_resolution"] == "Open", (
            f"{copy}: a confirmed comment is not a draft"
        )
        assert row["final_resolution"] != DRAFT_NOT_ISSUED
        if decision == "edit":
            # The engineer's wording IS the COMPANY comment, in both copies.
            assert row["comment"] == EDITED, copy
    [internal] = _about(copies["internal"])
    expected = (
        "AI Review, confirmed by "
        if decision == "keep"
        else "AI Review, edited and confirmed by "
    )
    assert internal["comment_by"].startswith(expected), internal["comment_by"]
    assert internal["comment_by"] != "AI Review"
    assert internal["comment_by"].endswith("Engineer"), (
        "the engineer's name, not 'AI Review' alone"
    )


def test_a_removed_comment_is_in_neither_copy(request, monkeypatch):
    run, scope, _draft = _numbered_draft(request)
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    response = TestClient(app).post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{finding_id}/decision",
        json={"decision": "reject", "reason": "", "reason_code": "duplicate"},
    )
    assert response.status_code == 200, response.text

    copies = _copies(run, scope)
    assert not _about(copies["internal"]), (
        "a removed comment is not a row of the internal copy"
    )
    assert not _about(copies["issue"]), "nor of the copy issued to the contractor"
