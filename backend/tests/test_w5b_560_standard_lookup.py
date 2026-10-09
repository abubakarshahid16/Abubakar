"""#560 (W5b-12): web search for standard identifiers, filtered and approved.

The filter whitelists: a query is sent whole or not at all. A value, a name,
a document number or a quoted sentence blocks it with a named reason and
nothing is sent. Each approval is used once. The lane is off by default and
also needs both market egress flags. No socket: the search is a spy.

Mutations: M6201-M6210 (scripts/mutations/w5b_560_standard_lookup.py).
"""
from __future__ import annotations

import pytest

from app import db, market_providers, market_transport, standard_lookup as sl
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b560.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


@pytest.fixture
def lane_on(monkeypatch):
    monkeypatch.setattr(settings, "standard_lookup_enabled", True)
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)


@pytest.fixture
def sent(monkeypatch):
    """Every phrase that would have left the machine."""
    calls: list[dict] = []

    def spy(phrase, *, fetch=None, **kw):
        calls.append({"phrase": phrase, "fetch": fetch})
        return {"rows": [{"title": "invented result"}], "tiers_answered": ["t"], "failure": None, "audit": []}

    monkeypatch.setattr(market_providers, "search_all", spy)
    monkeypatch.setattr(market_transport, "transport", lambda: "the-market-socket")
    return calls


# ------------------------------------------------------------------ the filter


@pytest.mark.parametrize("query, identifiers", [
    ("latest edition of API 610", ("API 610",)),
    ("Is ISO 12944-5 superseded", ("ISO 12944-5",)),
    ("API RP 14C free download", ("API RP 14C",)),
    ("IEC 61511-1 2016 edition", ("IEC 61511-1",)),
    ("ASME B31.3 publisher page", ("ASME B31.3",)),
    ("is API 610 superseded by ISO 13709", ("API 610", "ISO 13709")),
])
def test_an_identifier_query_is_sent_whole(query, identifiers):
    result = sl.check(query)
    assert result.sendable == query and result.blocked is None
    assert result.identifiers == identifiers


@pytest.mark.parametrize("query, reason", [
    ("API 610 23.5 barg", sl.BLOCKED_VALUE),
    ("API 610 650", sl.BLOCKED_VALUE),
    ("latest edition of API 610 by John Smith", sl.BLOCKED_NAME),
    ("SAES-B-014 latest edition", sl.BLOCKED_DOCUMENT_NUMBER),
    ("EF1975-DAS-M-03 edition", sl.BLOCKED_DOCUMENT_NUMBER),
    ('API 610 "the casing shall be hydrotested"', sl.BLOCKED_QUOTED),
    ("API 610 “witnessed by the purchaser”", sl.BLOCKED_QUOTED),
    ("latest edition", sl.BLOCKED_NO_IDENTIFIER),
    ("API latest edition", sl.BLOCKED_NO_IDENTIFIER),
    ("API 610 pump vendor list", sl.BLOCKED_WORD),
    ("", sl.BLOCKED_EMPTY),
    ("API 610 " + "edition " * 12, sl.BLOCKED_TOO_LONG),
])
def test_a_query_carrying_content_is_blocked_with_a_named_reason(query, reason):
    result = sl.check(query)
    assert result.sendable is None
    assert result.blocked == reason


def test_a_company_identifier_behind_a_public_body_is_blocked():
    assert sl.check("API SAES-B-014 edition").blocked is not None
    # Shaped like a designator, but a company marker: never public.
    assert sl.check("API KOC-123 edition").blocked == sl.BLOCKED_DOCUMENT_NUMBER


# ------------------------------------------------------------------ approval and sending


def test_a_blocked_query_cannot_be_approved_and_nothing_is_stored():
    with pytest.raises(sl.LookupRefused) as err:
        sl.approve("API 610 23.5 barg", approved_by="u1")
    assert err.value.code == sl.BLOCKED_VALUE
    sl.ensure_schema()
    assert db.connect().execute("SELECT COUNT(*) FROM standard_lookup_approvals").fetchone()[0] == 0


def test_an_approved_query_is_sent_once_through_the_market_socket(lane_on, sent):
    """THE MUTATION TARGET: only the approved, filtered query leaves."""
    approval = sl.approve("latest edition of API 610", approved_by="u1")
    result = sl.search(approval["approval_id"])
    assert sent == [{"phrase": "latest edition of API 610", "fetch": "the-market-socket"}]
    assert result["identifiers"] == ["API 610"] and result["rows"]
    with pytest.raises(sl.LookupRefused) as err:
        sl.search(approval["approval_id"])
    assert err.value.code == "already_used"
    assert len(sent) == 1


def test_the_lane_is_off_by_default_and_off_sends_nothing(sent):
    assert settings.standard_lookup_enabled is False
    approval = sl.approve("latest edition of API 610", approved_by="u1")
    with pytest.raises(sl.LookupRefused) as err:
        sl.search(approval["approval_id"])
    assert err.value.code == "off"
    assert sent == []
    # Refusing does not use up the approval.
    row = db.connect().execute("SELECT used_at FROM standard_lookup_approvals WHERE id = ?",
                               (approval["approval_id"],)).fetchone()
    assert row["used_at"] is None


def test_its_own_flag_without_the_market_egress_flags_sends_nothing(monkeypatch, sent):
    monkeypatch.setattr(settings, "standard_lookup_enabled", True)
    approval = sl.approve("latest edition of API 610", approved_by="u1")
    with pytest.raises(sl.LookupRefused):
        sl.search(approval["approval_id"])
    assert sent == []


def test_the_market_egress_flags_without_its_own_flag_send_nothing(monkeypatch, sent):
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    approval = sl.approve("latest edition of API 610", approved_by="u1")
    with pytest.raises(sl.LookupRefused) as err:
        sl.search(approval["approval_id"])
    assert err.value.code == "off"
    assert sent == []


def test_a_stored_query_changed_after_approval_is_not_sent(lane_on, sent):
    approval = sl.approve("latest edition of API 610", approved_by="u1")
    with db.connect() as conn:
        conn.execute("UPDATE standard_lookup_approvals SET query = ? WHERE id = ?",
                     ("latest edition of API 610 23.5 barg", approval["approval_id"]))
    with pytest.raises(sl.LookupRefused):
        sl.search(approval["approval_id"])
    assert sent == []


def test_an_unknown_approval_sends_nothing(lane_on, sent):
    with pytest.raises(sl.LookupRefused) as err:
        sl.search("sla_nope")
    assert err.value.code == "not_approved"
    assert sent == []
