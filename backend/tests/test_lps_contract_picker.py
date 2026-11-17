"""Order 14 LPS S1 (17 Nov 2026): the review picker offers contract papers and whole contract packages. Invented papers and numbers.

The picker's list (`review_start.contract_choices`, `GET /api/reviews/contract-papers`) reads only: every contract paper the caller
may read, and the packages they form by `contract_package.package_papers` (the same labelled cover number). It starts nothing; each
paper still starts through the one pre-start step, so rule 1 (Automatic never sends a contract) is untouched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access, db
from app.api import review_start
from app.config import settings
from app.main import app
from tests.test_lpc_contract_crs import NUMBER, _paper, package  # noqa: F401 - fixture
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture


def test_every_contract_paper_is_offered_and_a_package_is_its_papers_with_the_same_cover_number(package):  # noqa: F811
    _paper("memo_1", [(1, "An invented memo with no number on its cover.\n")], n=86)  # a contract paper with no package
    _paper("sub_1", [(1, "An invented datasheet\n")], role="CONTRACTOR_SUBMITTAL", n=87)  # not a contract: not offered here
    got = review_start.contract_choices(db.connect(), {*package["all"], "memo_1", "sub_1"})
    assert {p["document_id"] for p in got["papers"]} == {*package["all"], "memo_1"}
    assert [p["filename"] for p in got["papers"]] == sorted(p["filename"] for p in got["papers"])  # file-name order
    assert got["packages"] == [
        {"number": NUMBER, "papers": sorted([package["agreement"], package["sched_p"], package["att_p"]], key=lambda d: f"{d} invented.pdf")}
    ]  # the foreign agreement (another cover number) and the memo (no number) form no package
    assert got["boundary"] == "5 contract papers you may read"


def test_the_list_only_narrows_to_what_the_caller_may_read(package):  # noqa: F811
    got = review_start.contract_choices(db.connect(), {package["agreement"], package["att_p"]})
    assert {p["document_id"] for p in got["papers"]} == {package["agreement"], package["att_p"]}
    assert got["packages"] == [{"number": NUMBER, "papers": [package["agreement"], package["att_p"]]}]  # rule 5: never sch_p
    assert review_start.contract_choices(db.connect(), set()) == {"boundary": "0 contract papers you may read", "papers": [], "packages": []}


def test_the_route_answers_the_callers_list(package, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset({package["foreign"]})
    )
    try:
        r = TestClient(app).get("/api/reviews/contract-papers")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert r.json() == {
        "boundary": "1 contract paper you may read",
        "papers": [{"document_id": package["foreign"], "filename": f"{package['foreign']} invented.pdf"}],
        "packages": [],
    }
