"""Owner order 2d-2: the public web standards check (kind D).

Minimum-testing mode (owner decision, 2026-09-27): a few tests only, for the
new behaviour and the safety rules - a company identifier is NEVER searched
(privacy), the flag is off by default (permissions/off-by-default), an
unverified quote is never kept (no fabricated finding), and a kept item is a
pending draft that never counts in the review code (AI never sets pass/fail).
No client text: every identifier and quote here is made up.
"""
from __future__ import annotations

import pytest

from app import comparison, db, market_providers, web_standards
from app.config import settings
from tests.test_b3_page_ledger import _review, _sheet, temp_storage  # noqa: F401 - autouse


# --------------------------------------------------------- identifier gate

@pytest.mark.parametrize("identifier", [
    "API 610", "ASME B31.3", "ISO 9001", "ASTM A106", "IEC 60079",
])
def test_a_public_body_s_own_numbering_is_searchable(identifier):
    assert web_standards.is_public_identifier(identifier) is True


@pytest.mark.parametrize("identifier", [
    "SAES-A-004", "SAMSS-035", "KOC-STD-01", "KOC-EPS-123",
    "", "  ", "PROJECT-999000-SP-001",
])
def test_a_company_or_project_identifier_is_never_searchable(identifier):
    assert web_standards.is_public_identifier(identifier) is False


def test_a_company_marker_refuses_even_alongside_a_public_looking_prefix():
    """The block-list is a SECOND gate, not the only one."""
    assert web_standards.is_public_identifier("API SAES-A-004") is False


# ---------------------------------------------------------------- gating

def test_the_flag_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    ok, why = web_standards.available()
    assert ok is False and "switched off" in why


def test_on_its_own_the_flag_sends_nothing_without_the_market_lane(monkeypatch):
    monkeypatch.setattr(settings, "review_web_standards_enabled", True)
    ok, why = web_standards.available()
    assert ok is False and "outbound" in why


@pytest.fixture
def world(tmp_path):
    sub = _sheet(tmp_path, notes_page=False)
    from app import datasheets
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    run, scope = _review(sub)
    comparison.run_comparison(run, allowed_document_ids=scope)
    return sub, run, scope


@pytest.fixture(autouse=True)
def _rates():
    market_providers.reset_rate_limits()
    yield
    market_providers.reset_rate_limits()


@pytest.fixture
def lane_on(monkeypatch):
    monkeypatch.setattr(settings, "review_web_standards_enabled", True)
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)


TITLE = "API 610 pump design requirements"
URL = "https://example.org/api-610"
PAGE_TEXT = (
    "Background material. " + TITLE + " state the design pressure margin. "
    "Nothing else on this made-up page matters for the test."
)


def _fetch_search(url, headers, timeout):
    if "openalex" in url:
        return {"results": [{
            "display_name": TITLE, "publication_date": "2024-01-01",
            "primary_location": {"landing_page_url": URL,
                                 "source": {"display_name": "Example Publisher"}}}]}
    return {}


def test_a_company_identifier_is_never_searched(world, lane_on):
    """Privacy: a company identifier is refused before anything is sent."""
    _sub, run, scope = world
    calls: list[str] = []

    def spy(url, headers, timeout):
        calls.append(url)
        return _fetch_search(url, headers, timeout)

    result = web_standards.run_check(
        run, allowed_document_ids=scope,
        missing_identifiers=["SAES-A-004", "API 610"],
        fetch_search=spy, fetch_text=lambda u, t: PAGE_TEXT)
    assert result["checked"] == 1, "the company identifier is not even attempted"
    assert all("SAES" not in c for c in calls)


def test_an_unverified_quote_is_never_kept(world, lane_on):
    """No fabricated finding: a snippet that cannot be found on the fetched
    page itself is dropped, never stored."""
    _sub, run, scope = world
    result = web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: "a page with unrelated text")
    assert result == {"ran": True, "reason": None, "checked": 1, "kept": 0, "edition_confirmed": 0,
                      "edition_differs": 0, "edition_unconfirmed": 0}
    [n] = db.connect().execute(
        "SELECT COUNT(*) c FROM review_findings WHERE review_run_id = ?"
        " AND origin = 'web_standard_check'", (run,))
    assert n["c"] == 0


def test_a_kept_item_is_a_never_counted_pending_draft(world, lane_on):
    """AI (the web lane) never sets pass/fail: no compliance_status; a
    pending, unconfirmed draft that does not move the recommended code."""
    _sub, run, scope = world
    before = comparison.run_outcome(run, allowed_document_ids=scope)["recommended_code"]

    result = web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: PAGE_TEXT)

    assert (result["checked"], result["kept"]) == (1, 1)
    [row] = [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = 'web_standard_check'",
        (run,))]
    assert (row["compliance_status"], row["confirmed_by"], row["approval_status"]) == (
        None, None, "pending")
    assert row["confidence"] == "low"
    assert URL in row["ai_rationale"] and TITLE in row["ai_rationale"]
    assert comparison.run_outcome(run, allowed_document_ids=scope)["recommended_code"] == before


def test_a_rerun_replaces_drafts_but_never_an_engineers_confirmation(world, lane_on):
    _sub, run, scope = world
    web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: PAGE_TEXT)
    [row] = [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = 'web_standard_check'",
        (run,))]
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET confirmed_by = 'u1', confirmed_at = ?"
                     " WHERE id = ?", ("2026-01-01T00:00:00+00:00", row["id"]))
    web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: PAGE_TEXT)
    rows = [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = 'web_standard_check'",
        (run,))]
    assert any(r["id"] == row["id"] and r["confirmed_by"] == "u1" for r in rows)


# --------------------------------------------------------------- edition

def test_a_differing_edition_is_never_compared():
    assert web_standards.edition_differs("API 610, 11th edition (2010)", "2024-01-01") is True
    assert web_standards.edition_differs("API 610 (2024)", "2024-06-01") is False
    # False on a missing side means "not proven different", NOT "the same":
    assert web_standards.edition_differs(None, "2024-01-01") is False
    assert web_standards.edition_confirmed_same(None, "2024-01-01") is False
    assert web_standards.edition_confirmed_same("11th edition", "2024-01-01") is False
    assert web_standards.edition_confirmed_same("2024", None) is False
    assert web_standards.edition_confirmed_same("API 610 (2024)", "2024-06-01") is True


@pytest.mark.parametrize(("text", "expected"), [
    ("Pumps per API 610, 11th edition (2010).", "11th edition (2010)"),
    ("API 610 (2024) applies", "2024"),
    ("API610-2010", "2010"),
    ("API 610 11th edition only", "11th edition"),
    ("API 610 as amended", None),
    ("API 610:2015 applies", "2015"),
    ("API 610 Rev. 2014 applies", "Rev. 2014"),
    ("API 610 (11th Edition, 2010)", "11th Edition, 2010"),
    # A speed, a pressure, a flow - NOT an edition:
    ("API 610, 1950 rpm driver", None),
    ("API 610 - 2000 kPa design", None),
    ("API 610 (2000 kPa) casing", None),
    ("API 610 2000% margin", None),
    ("API 610, 2000.5 m3/h", None),
    ("API 610, 2000,000 units", None),
    ("API 610 20001 serial", None),
    ("API610-2000 kPa", None),
    ("API610-2000 m3/h", None),
    ("API 610, 2010 and more", None),
    # Two citations naming DIFFERENT years: ambiguous, never a guess.
    ("API 610 (2010) here and API 610 (2014) there", None),
])
def test_the_cited_edition_is_read_from_the_submittal_s_own_citation(text, expected):
    assert web_standards.cited_edition(text, "API 610") == expected


def _cite(sub: str, text: str) -> None:
    """Add one retrievable chunk carrying a made-up citation to the submittal."""
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,99,1,1,NULL,'prose',?,1,?,1)""",
            (f"cite-{sub}", sub, f"{sub}.pdf", text, f"h-cite-{sub}"))


def _web_rows(run):
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = 'web_standard_check'",
        (run,))]


@pytest.fixture
def compare_spy(monkeypatch):
    calls: list[str] = []
    real = web_standards.compare

    def spy(requirement, facts, **kw):
        calls.append(requirement["identifier"])
        return real(requirement, facts, **kw)

    monkeypatch.setattr(web_standards, "compare", spy)
    return calls


def test_the_check_path_never_compares_a_differing_edition(world, lane_on, compare_spy):
    """THROUGH `run_check`: the submittal cites the 2010 edition, the web page
    is dated 2024 - stored as "edition differs", both named, never compared,
    no verdict, a pending draft like every other kind D item."""
    sub, run, scope = world
    _cite(sub, "Pump to API 610, 11th edition (2010) throughout.")
    result = web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: PAGE_TEXT)

    assert (result["kept"], result["edition_differs"], result["edition_confirmed"],
            result["edition_unconfirmed"]) == (1, 1, 0, 0)
    assert compare_spy == [], "a differing edition must never reach compare"
    [row] = _web_rows(run)
    assert row["finding"].startswith("Edition differs - not compared")
    assert "11th edition (2010)" in row["finding"] and "2024-01-01" in row["finding"]
    assert (row["compliance_status"], row["confirmed_by"], row["approval_status"]) == (
        None, None, "pending")
    assert row["contractor_page"] is None and row["contractor_evidence_text"] is None


def test_an_unknown_edition_is_not_a_match(world, lane_on, compare_spy):
    """The submittal names no edition: unknown is not the same - stored as
    "edition not confirmed", never compared."""
    sub, run, scope = world
    _cite(sub, "Pump to API 610 throughout.")
    result = web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: PAGE_TEXT)

    assert (result["kept"], result["edition_unconfirmed"], result["edition_confirmed"],
            result["edition_differs"]) == (1, 1, 0, 0)
    assert compare_spy == []
    [row] = _web_rows(run)
    assert row["finding"].startswith("Edition not confirmed - not compared")
    assert "(no edition stated)" in row["finding"]


def test_only_a_confirmed_same_edition_is_compared(world, lane_on, compare_spy):
    """...and even then, with no field named, it is a question - the count
    is `edition_confirmed`, never a count of verdicts."""
    sub, run, scope = world
    _cite(sub, "Pump to API 610 (2024) throughout.")
    result = web_standards.run_check(
        run, allowed_document_ids=scope, missing_identifiers=["API 610"],
        fetch_search=_fetch_search, fetch_text=lambda u, t: PAGE_TEXT)

    assert (result["kept"], result["edition_confirmed"]) == (1, 1)
    assert "compared" not in result, "no count may claim a comparison that gave no verdict"
    assert compare_spy == ["API 610"]
    [row] = _web_rows(run)
    assert row["finding"] == web_standards.LABEL_TEMPLATE.format(name="API 610")
    assert row["compliance_status"] is None
