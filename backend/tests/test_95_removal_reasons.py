"""Order 95 piece 6a: why a comment was left off the CRS, and the history.

A removal (reject) may name its reason from the closed list (spec 1.2); a code
outside the list, or a code on an accept, is refused and nothing is stored.
`GET .../crs/decisions` lists every decision on the run, newest first, with who,
when, why and the code - an earlier decision is never overwritten - and is read
only: a stranger sees nothing, and listing creates nothing.

Invented runs and findings only.
"""

from __future__ import annotations

from app import crs_issue, db
from tests.test_885_crs_issue_gate import _fid, _run
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _submittal,
    temp_db,
)


def _decide(client, run, fid, decision, reason, code=None):
    body = {"decision": decision, "reason": reason}
    if code is not None:
        body["reason_code"] = code
    return client.post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision", json=body
    )


def _history(client, run):
    r = client.get(f"/api/reviews/runs/{run}/crs/decisions")
    assert r.status_code == 200, r.text
    return r.json()["decisions"]


def test_a_removal_keeps_its_listed_reason_and_the_history_lists_it():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc)
    r = _decide(
        client, run, _fid(run), "reject", "same point as comment 3", "duplicate"
    )
    assert r.status_code == 200, r.text
    assert r.json()["reason_code"] == "duplicate"
    [entry] = _history(client, run)
    assert (entry["decision"], entry["reason_code"], entry["decided_by"]) == (
        "reject",
        "duplicate",
        "eng",
    )
    assert entry["reason"] == "same point as comment 3" and entry["decided_at"]


def test_a_code_outside_the_list_or_on_an_accept_is_refused_and_nothing_is_stored():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc)
    fid = _fid(run)
    assert (
        _decide(
            client, run, fid, "reject", "not wanted on this one", "made_up"
        ).status_code
        == 422
    )
    assert (
        _decide(
            client, run, fid, "accept", "breach confirmed by eye", "duplicate"
        ).status_code
        == 422
    )
    assert _history(client, run) == []
    assert (
        crs_issue.REMOVAL_REASONS["not_applicable"]
        == "Not applicable to this equipment"
    )


def test_every_decision_stays_newest_first_and_an_old_one_without_a_code_says_null():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc)
    fid = _fid(run)
    assert (
        _decide(client, run, fid, "accept", "breach confirmed by eye").status_code
        == 200
    )
    assert (
        _decide(
            client,
            run,
            fid,
            "reject",
            "contractor shows it on sheet 2",
            "already_complies",
        ).status_code
        == 200
    )
    history = _history(client, run)
    assert [(h["decision"], h["reason_code"]) for h in history] == [
        ("reject", "already_complies"),
        ("accept", None),
    ]


def test_the_history_is_read_only_and_shows_a_stranger_nothing():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc)
    assert _history(client, run) == []
    exists = (
        db.connect()
        .execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'crs_issue_decisions'"
        )
        .fetchone()
    )
    assert exists is None  # listing created nothing
    stranger = _client("other-doc")
    assert stranger.get(f"/api/reviews/runs/{run}/crs/decisions").status_code == 404
