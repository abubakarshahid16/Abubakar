"""Two read-only fields of a query for its page's lower half (owner, 27 Nov 2026 00:02): the contractor code the subject's number holds,
and whether Claude may write the reply now, with the plain reason when it may not. Invented values only."""

from __future__ import annotations

from app import reasoning_provider
from app.api import technical_queries as api
from app.config import settings
from tests.test_g_tq_code_routing import SUBJECT


def test_the_subject_s_contractor_code_is_served_and_nothing_when_there_is_no_number():
    assert api._subject_codes({"subject": SUBJECT}) == {"contractor_code": "ABC"}
    assert api._subject_codes({"subject": "Coating question"}) == {"contractor_code": None}
    assert api._subject_codes({}) == {"contractor_code": None}


def test_claude_is_unavailable_with_a_plain_reason_while_the_draft_setting_is_local(monkeypatch):
    monkeypatch.setattr(settings, "technical_query_draft_engine", "local")
    assert api._draft_engines() == {"claude": {"available": False, "why": "Claude is switched off for query replies on this computer"}}


def test_claude_follows_the_lane_once_the_draft_setting_says_claude(monkeypatch):
    monkeypatch.setattr(settings, "technical_query_draft_engine", "claude")
    monkeypatch.setattr(reasoning_provider, "claude_unavailable_for_task", lambda engine: (reasoning_provider.UNAVAILABLE_KEY_MISSING, "x"))
    assert api._draft_engines() == {"claude": {"available": False, "why": "no Claude key is set on this computer"}}
    monkeypatch.setattr(reasoning_provider, "claude_unavailable_for_task", lambda engine: (None, "claude"))
    assert api._draft_engines() == {"claude": {"available": True, "why": None}}


def test_every_served_query_carries_both_fields():
    from app import access

    scope = access.AccessScope(user_id="u1", unrestricted=True, allowed_document_ids=frozenset()) if hasattr(access, "AccessScope") else None
    item = api._safe_item({"subject": SUBJECT, "messages": []}, scope)
    assert item["contractor_code"] == "ABC" and "claude" in item["draft_engines"]
