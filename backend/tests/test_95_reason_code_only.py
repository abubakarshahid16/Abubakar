"""Order 95 piece 6a (a): a removal may carry only its listed reason.

The sheet's Remove offers the five reasons of spec 1.2; the engineer picks one
and need not type a sentence. With nothing typed the server stores the reason's
own words; a note typed beside the code is kept as typed. Without a listed code, or on an accept, the 10-character
reason rule still holds.

Invented runs and findings only.
"""

from __future__ import annotations

from tests.test_885_crs_issue_gate import _fid, _run
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _submittal,
    temp_db,
)


def _decide(client, run, fid, decision, reason=None, code=None):
    body = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    if code is not None:
        body["reason_code"] = code
    return client.post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision", json=body
    )


def _setup():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    return _client(doc), run, _fid(run)


def test_a_removal_with_only_a_listed_reason_stores_the_reasons_words():
    client, run, fid = _setup()
    r = _decide(client, run, fid, "reject", code="duplicate")
    assert r.status_code == 200, r.text
    assert (r.json()["reason"], r.json()["reason_code"]) == ("Duplicate", "duplicate")


def test_a_short_note_with_a_listed_reason_is_kept_as_typed():
    client, run, fid = _setup()
    r = _decide(client, run, fid, "reject", reason="see 3", code="duplicate")
    assert r.status_code == 200, r.text
    assert (r.json()["reason"], r.json()["reason_code"]) == ("see 3", "duplicate")


def test_without_a_listed_reason_or_on_an_accept_the_sentence_is_still_required():
    client, run, fid = _setup()
    assert _decide(client, run, fid, "reject").status_code == 422
    assert _decide(client, run, fid, "reject", reason="short").status_code == 422
    assert _decide(client, run, fid, "accept", reason="ok").status_code == 422
    assert _decide(client, run, fid, "accept", code="duplicate").status_code == 422
    history = client.get(f"/api/reviews/runs/{run}/crs/decisions").json()
    assert history["decisions"] == []


def test_each_of_the_five_listed_reasons_saves_alone_and_an_unknown_code_is_refused():
    from app import crs_issue

    assert len(crs_issue.REMOVAL_REASONS) == 5
    doc = _submittal()
    client = _client(doc)
    for code, words in crs_issue.REMOVAL_REASONS.items():
        run = _run(doc)
        _finding(doc, run, "NON_COMPLIANT")
        r = _decide(client, run, _fid(run), "reject", code=code)
        assert r.status_code == 200, (code, r.text)
        assert (r.json()["reason"], r.json()["reason_code"]) == (words, code)
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    assert (
        _decide(client, run, _fid(run), "reject", code="not_a_code").status_code == 422
    )
