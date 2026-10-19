"""Order 127: one unread-pages count.

The comment sheet's header, its footer and "Before you sign" named a run's
unread pages from different keys of the same stored record and disagreed. One
definition (`page_ledger.run_unread_pages`) now feeds the run summary
(`how_reviewed.unread_pages`), the run detail / runs list (`unread_pages`) and
the issue gate (`unread_pages` left to tick + `checked_pages`), and the tick
route accepts exactly those pages.

Invented runs and pages only.
"""

from __future__ import annotations

import json
import uuid

from app import crs_issue, db, page_ledger
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    NOW,
    _client,
    _submittal,
    temp_db,
)

ELEVEN = list(range(1, 12))


def _run(doc_id: str, coverage: dict | None, reader: dict | None) -> str:
    run_id = str(uuid.uuid4())
    outcome: dict = {"recommended_code": "Manual Review Required", "reason": "r"}
    if coverage is not None:
        outcome["page_coverage"] = coverage
    if reader is not None:
        outcome["requirement_split"] = {"reader": reader}
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,"
            "engineer_final_code,created_at,updated_at) VALUES (?,?,'completed',?,?,?,?)",
            (run_id, doc_id, json.dumps(outcome), "Approved", NOW, NOW),
        )
    return run_id


def _unavailable_run(doc: str) -> str:
    """11 pages; the code readers missed 1-3, 5, 11; the AI reader was
    unavailable (so it read none) and its record names a time-out on 5."""
    return _run(
        doc,
        {
            "pages_total": 11,
            "fact_pages": [4, 6, 7, 8, 9, 10],
            "pages_not_read_into_fields": [1, 2, 3, 5, 11],
            "not_read_reasons": {str(p): "no value found" for p in (1, 2, 3, 5, 11)},
            "pages_ai_not_read": ELEVEN,
            "ai_not_read_reasons": {
                str(p): "the ollama reader was unavailable (off)" for p in ELEVEN
            },
        },
        {"engine": "ollama", "timed_out": [5]},
    )


def _summary(client, run):
    r = client.get(f"/api/reviews/runs/{run}/summary")
    assert r.status_code == 200, r.text
    return r.json()["how_reviewed"]


def _detail(client, run):
    r = client.get(f"/api/reviews/runs/{run}")
    assert r.status_code == 200, r.text
    return r.json()


def _gate(client, run):
    r = client.get(f"/api/reviews/runs/{run}/crs/issue-gate")
    assert r.status_code == 200, r.text
    return r.json()


def _tick(client, run, page):
    return client.post(
        f"/api/reviews/runs/{run}/crs/open-items/pages/{page}/decision",
        json={"reason": f"read page {page} by eye: a general note"},
    )


def test_summary_and_run_detail_name_every_page_the_ai_reader_did_not_read():
    doc = _submittal()
    run = _unavailable_run(doc)
    client = _client(doc)
    assert _summary(client, run)["unread_pages"] == ELEVEN
    assert _detail(client, run)["unread_pages"] == ELEVEN
    listed = client.get("/api/reviews/runs").json()["runs"]
    assert [r["unread_pages"] for r in listed if r["review_run_id"] == run] == [ELEVEN]


def test_the_gate_left_to_tick_plus_checked_is_the_summarys_list():
    doc = _submittal()
    run = _unavailable_run(doc)
    client = _client(doc)
    assert _tick(client, run, 4).status_code == 200
    gate = _gate(client, run)
    left = {u["page"] for u in gate["unread_pages"]}
    checked = set(gate["checked_pages"])
    assert left.isdisjoint(checked)
    assert sorted(left | checked) == _summary(client, run)["unread_pages"] == ELEVEN
    assert gate["checked_pages"] == [4] and gate["pages_total"] == 11
    # the code readers' reason wins over the AI reader's on the same page
    reasons = {u["page"]: u["reason"] for u in gate["unread_pages"]}
    assert reasons[1] == "no value found"
    assert reasons[6] == "the ollama reader was unavailable (off)"


def test_a_run_stored_before_pf3_counts_the_ai_readers_time_outs():
    doc = _submittal()
    run = _run(
        doc,
        {
            "pages_total": 12,
            "pages_not_read_into_fields": [4],
            "not_read_reasons": {"4": "no value found"},
        },
        {"engine": "ollama", "timed_out": [7]},
    )
    client = _client(doc)
    assert _summary(client, run)["unread_pages"] == [4, 7]
    assert _detail(client, run)["unread_pages"] == [4, 7]
    gate = _gate(client, run)
    assert gate["unread_pages"] == [
        {"page": 4, "reason": "no value found"},
        {"page": 7, "reason": "the AI reader timed out on this page"},
    ]
    assert _tick(client, run, 7).status_code == 200
    assert _gate(client, run)["checked_pages"] == [7]
    assert _tick(client, run, 8).status_code == 422  # not on the list


def test_no_page_coverage_is_not_known_never_none():
    doc = _submittal()
    run = _run(doc, None, {"engine": "ollama", "timed_out": [2]})
    client = _client(doc)
    assert _summary(client, run)["unread_pages"] is None
    assert _detail(client, run)["unread_pages"] is None
    gate = _gate(client, run)
    assert crs_issue.NO_PAGE_COVERAGE in gate["blockers"]
    assert gate["unread_pages"] == [] and gate["checked_pages"] == []
    assert gate["pages_total"] is None


def test_every_page_read_is_an_empty_list_not_null():
    doc = _submittal()
    run = _run(doc, {"pages_total": 3, "pages_not_read_into_fields": []}, None)
    client = _client(doc)
    assert _summary(client, run)["unread_pages"] == []
    gate = _gate(client, run)
    assert gate["unread_pages"] == [] and gate["checked_pages"] == []
    assert gate["pages_total"] == 3


def test_run_unread_pages_unions_sorts_dedupes_and_drops_pages_past_the_total():
    cov = {
        "pages_total": 6,
        "pages_not_read_into_fields": [5, 2],
        "pages_ai_not_read": [2, 3],
    }
    assert page_ledger.run_unread_pages(cov, {"timed_out": [6, 9, 3]}) == [2, 3, 5, 6]
    assert page_ledger.run_unread_pages(cov) == [2, 3, 5]
    assert page_ledger.run_unread_pages(None, None) == []
    # total not known: nothing is dropped
    assert page_ledger.run_unread_pages(
        {"pages_ai_not_read": [8]}, {"timed_out": [1]}
    ) == [1, 8]
    assert page_ledger.run_unread_pages_shown({"pages_ai_not_read": [8]}) is None
    assert page_ledger.run_unread_pages_shown(None) is None
    assert page_ledger.run_unread_pages_shown(cov) == [2, 3, 5]
    assert page_ledger.run_reader({"requirement_split": {"reader": None}}) is None
    assert page_ledger.run_reader(
        {"requirement_split": {"reader": {"engine": "x"}}}
    ) == {"engine": "x"}


def test_run_unread_reasons_prefers_the_code_readers_then_the_legacy_words():
    cov = {
        "pages_total": 6,
        "pages_not_read_into_fields": [2],
        "not_read_reasons": {"2": "blank page"},
        "pages_ai_not_read": [2, 3],
        "ai_not_read_reasons": {"2": "AI timed out", "3": "AI cut off"},
    }
    assert page_ledger.run_unread_reasons(cov, {"timed_out": [3, 4]}) == {
        "2": "blank page",
        "3": "AI cut off",
        "4": "the AI reader timed out on this page",
    }
    # pages_to_check keeps its one-argument form
    assert crs_issue.pages_to_check(cov) == [2, 3]


def test_the_gate_never_drops_a_code_reader_page_past_the_row_count():
    # `pages_total` counts ledger rows, not the highest page number: a ledger
    # holding pages 1, 2, 3 and 5 has a total of 4. Page 5 was not read, and
    # the gate asked a tick for it before order 127; it still must.
    cov = {
        "pages_total": 4,
        "pages_not_read_into_fields": [5],
        "pages_ai_not_read": [0],
    }
    assert page_ledger.run_unread_pages(cov) == [0, 5]
    assert crs_issue.pages_to_check(cov) == [0, 5]
