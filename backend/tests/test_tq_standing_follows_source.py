"""A kept passage's revision standing follows its SOURCE document (F's live check, 26 Nov 2026: a kept passage stayed "unknown" after
its source was confirmed and re-prepared, so no query could ever reach "Generate draft"). Invented documents; no model, no network."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import db
from app import technical_queries as tq
from app.api import technical_queries as api
from tests.test_tq_g_feature_off import (  # noqa: F401 - helper, fixture
    draft_ready,
    storage,
)


def _stored_unknown(item_id: str) -> None:
    """The kept passages as live has them: kept, standing "unknown" (the screen sends the standing it shows)."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE query_evidence SET supersession_state='unknown' WHERE query_id=?",
            (item_id,),
        )


def _confirm(document_id: str, superseded_by: str | None = None) -> None:
    if superseded_by:
        from tests.test_technical_queries import hold_contract

        hold_contract(superseded_by)  # the newer revision is a held document too
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET confirmed_by='u1', superseded_by=? WHERE document_id=?",
            (superseded_by, document_id),
        )


def test_the_standing_rule():
    assert tq.passage_standing("unknown", "current") == "current"
    assert tq.passage_standing("unknown", "unknown") == "unknown"
    assert (
        tq.passage_standing("current", "unknown") == "current"
    )  # a reviewer's own choice stands
    assert tq.passage_standing("current", "superseded") == "superseded"
    assert tq.passage_standing("superseded", "current") == "superseded"


def test_confirming_the_source_makes_a_kept_passage_current_at_once_with_no_re_prepare(
    monkeypatch,
):
    item, _scope = draft_ready(monkeypatch, docs=("d1",))
    _stored_unknown(item["id"])
    assert [
        e["supersession_state"]
        for e in tq.get(item["id"], "u1", True, False)["evidence"]
    ] == ["unknown"]
    _confirm("d1")
    assert [
        e["supersession_state"]
        for e in tq.get(item["id"], "u1", True, False)["evidence"]
    ] == ["current"]


def _claude_lane(monkeypatch):
    """The Claude draft lane, as the owner's setting opens it: its evidence rule is unchanged (kept, current passages only)."""
    from app.config import settings

    monkeypatch.setattr(settings, "technical_query_draft_engine", "claude")
    return api.GenerateDraftIn(engine="claude", document_ids=["d1"])


def _stop_at_the_model(monkeypatch, seen):
    monkeypatch.setattr("app.answer.answer", lambda *a, **k: seen.append(k.get("allowed_document_ids")) or (_ for _ in ()).throw(RuntimeError("stop here")))


def test_a_claude_draft_is_refused_with_what_to_do_and_passes_once_the_source_is_confirmed(monkeypatch):
    item, scope = draft_ready(monkeypatch, docs=("d1",))
    _stored_unknown(item["id"])
    with pytest.raises(HTTPException) as refused:
        api.generate_query_draft(item["id"], scope, _claude_lane(monkeypatch))
    detail = str(refused.value.detail)
    assert "verified, current evidence is required before drafting" in detail
    assert "counts as current once its source document is confirmed" in detail and "contract.pdf" in detail
    _confirm("d1")
    seen = []
    _stop_at_the_model(monkeypatch, seen)
    with pytest.raises((HTTPException, RuntimeError)) as later:
        api.generate_query_draft(item["id"], scope, _claude_lane(monkeypatch))
    assert "current evidence is required" not in str(getattr(later.value, "detail", later.value))  # past the evidence check


def test_a_local_draft_rests_on_a_kept_passage_whose_source_is_not_confirmed_and_says_so(monkeypatch):
    """No gate in the middle (owner, 26 Nov 2026 21:36): the local model drafts from the kept passage, and the draft marks the revision."""
    item, scope = draft_ready(monkeypatch, docs=("d1",))
    _stored_unknown(item["id"])
    monkeypatch.setattr("app.answer.answer", lambda *a, **k: {
        "answer_type": "generated", "answer": "It applies [S1].", "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 1, "page_end": 1, "text": "q"}]})  # fmt: skip
    drafted = api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    marks = __import__("json").loads(drafted["drafts"][-1]["unresolved_json"])
    assert "The revision of contract is not confirmed yet (Documents, Details, Save metadata)." in marks  # named as the page labels it


def test_keeping_a_passage_stores_its_sources_standing_not_the_stale_one_the_screen_sent(
    monkeypatch,
):
    item, _scope = draft_ready(monkeypatch, docs=("d1",))
    _stored_unknown(item["id"])
    _confirm("d1")
    tq.update_evidence(
        item["id"],
        "e0",
        "verified",
        "unknown",
        None,
        "u1",
        "u1",
        True,
        False,
        reviewer=True,
    )
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT supersession_state FROM query_evidence WHERE id='e0'"
            ).fetchone()[0]
            == "current"
        )


def test_a_superseded_source_makes_its_passage_superseded_and_no_draft_rests_on_it(
    monkeypatch,
):
    item, scope = draft_ready(monkeypatch, docs=("d1",))
    _confirm("d1", superseded_by="d1-new")
    assert [
        e["supersession_state"]
        for e in tq.get(item["id"], "u1", True, False)["evidence"]
    ] == ["superseded"]
    with pytest.raises(HTTPException) as local:  # the local model never drafts from a superseded source either
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    assert "no passage was found" in str(local.value.detail)
    with pytest.raises(HTTPException) as refused:
        api.generate_query_draft(item["id"], scope, _claude_lane(monkeypatch))
    assert "every kept passage's source has been superseded" in str(
        refused.value.detail
    )


def test_no_kept_passage_a_claude_draft_says_to_keep_one_and_a_local_draft_uses_what_the_system_found(monkeypatch):
    item, scope = draft_ready(monkeypatch, docs=("d1",))
    from app.technical_query_auto import key

    with db.connect() as conn:
        conn.execute(
            "UPDATE query_evidence SET evidence_state='proposed', found_for=? WHERE query_id=?",
            (key("What applies?"), item["id"]),
        )
    with pytest.raises(HTTPException) as refused:
        api.generate_query_draft(item["id"], scope, _claude_lane(monkeypatch))
    assert "keep at least one passage as evidence first" in str(refused.value.detail)
    seen = []
    _stop_at_the_model(monkeypatch, seen)
    with pytest.raises((HTTPException, RuntimeError)):
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    assert seen == [frozenset({"d1"})]  # the local model was given the passage the system found for this wording
