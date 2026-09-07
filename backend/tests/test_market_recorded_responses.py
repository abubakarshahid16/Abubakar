"""The parsers, against REAL captured responses rather than my guesses.

WHY THIS FILE EXISTS. Every other provider test in this suite runs on JSON I
fabricated, which means a wrong guess about a real API's shape would leave the
parser broken and the suite green - a test proving only that my parser agrees
with my own invention. That is the same defect as a vacuous test, moved one
layer out.

So one real response was captured from each keyless tier, BY HAND and
out-of-band - not by the product, not with the live flag on, and not through
any code path a user can reach. The queries were "ISO 12944" and "corrosion
protection coatings": published standard designators and generic subject terms,
which say nothing about which documents any client holds.

THE FIXTURES ARE COMMITTED, so this runs air-gapped like everything else. That
is the whole trade: reality is captured once, then never needed again.

Captured 2026-09-07 from:
  https://en.wikipedia.org/w/api.php?action=query&list=search&format=json
      &srlimit=5&srsearch=ISO%2012944
  https://api.openalex.org/works?per-page=5&search=corrosion%20protection%20coatings

WHAT THE CAPTURE FOUND. Both guessed shapes were correct - `query.search[]`
with `title`/`snippet`/`timestamp`, and `results[]` with
`display_name`/`publication_date`/`primary_location.source.display_name`. Three
things I had NOT anticipated are asserted below, each with its own test:
the response size, the off-allowlist row URLs, and non-ASCII in titles.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import market_providers
from app.config import settings

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "market"
WIKIPEDIA = json.loads(
    (FIXTURES / "wikipedia_search.json").read_text(encoding="utf-8"))
OPENALEX = json.loads(
    (FIXTURES / "openalex_works.json").read_text(encoding="utf-8"))


def test_the_fixtures_are_the_real_thing_and_not_trimmed_to_fit():
    """A guard on the fixtures. If someone shrinks these to tidy the repo, the
    parsers go back to being tested against an invention."""
    assert set(WIKIPEDIA) >= {"query", "batchcomplete"}, list(WIKIPEDIA)
    assert len(WIKIPEDIA["query"]["search"]) == 5
    # The OpenAlex record carries fields no fabricated fixture would have
    # bothered with, which is how you can tell it is real.
    assert set(OPENALEX) >= {"meta", "results"}, list(OPENALEX)
    assert len(OPENALEX["results"]) == 5
    first = OPENALEX["results"][0]
    for real_only in ("abstract_inverted_index", "authorships",
                      "cited_by_count", "counts_by_year", "biblio"):
        assert real_only in first, (
            f"{real_only!r} is missing - this fixture has been trimmed and is "
            f"no longer a recording of a real response")


# ------------------------------------------------------- the parsers work


def test_the_wikipedia_parser_handles_the_real_response():
    rows = market_providers.WikipediaProvider._rows(WIKIPEDIA)

    assert len(rows) == 5, f"parsed {len(rows)} of 5 real results"
    for row in rows:
        assert set(row) == {
            "text", "provider_label", "publisher", "published", "retrieved",
            "url", "verification", "is_sample",
        }
        assert row["provider_label"] == "reference - background only"
        assert row["publisher"] == "Wikipedia"
        assert row["is_sample"] is False
        assert row["url"].startswith("https://en.wikipedia.org/wiki/")
        assert row["text"]

    top = rows[0]
    assert "ISO 12944" in top["text"], top["text"]
    assert top["url"] == "https://en.wikipedia.org/wiki/ISO_12944"
    assert top["published"] == "2023-09-26T17:05:28Z"


def test_the_wikipedia_snippet_markup_is_stripped_in_the_real_response():
    """The live API returns `<span class="searchmatch">` around the matched
    terms. Left in, that markup reaches the panel as literal angle brackets or,
    worse, gets rendered."""
    raw = json.dumps(WIKIPEDIA)
    assert "searchmatch" in raw, "the fixture no longer exercises markup"

    for row in market_providers.WikipediaProvider._rows(WIKIPEDIA):
        assert "<" not in row["text"], row["text"]
        assert "searchmatch" not in row["text"], row["text"]


def test_the_openalex_parser_handles_the_real_response():
    rows = market_providers.OpenAlexProvider._rows(OPENALEX)

    assert len(rows) == 5, f"parsed {len(rows)} of 5 real results"
    for row in rows:
        assert row["provider_label"] == "published literature"
        assert row["is_sample"] is False
        assert row["text"]
        assert row["url"]
        assert row["publisher"] and row["publisher"] != "OpenAlex", (
            "the real response carries a journal name in "
            "primary_location.source.display_name; falling back to 'OpenAlex' "
            "means that path was not read")

    top = rows[0]
    assert "corrosion protection" in top["text"].lower(), top["text"]
    assert top["publisher"] == "Progress in Organic Coatings"
    assert top["published"] == "2008-09-24"


# ------------------------------------- what the capture found that I had not


def test_the_openalex_response_is_enormous_for_five_results():
    """A FINDING, not a defect. 5 works is ~113 KB, because each record
    carries `abstract_inverted_index`, every authorship and a per-year citation
    series - none of which this feature uses.

    It matters twice. The per-tier timeout has to cover transferring and
    parsing that, which is the argument for `market_tier_timeout_seconds`
    being 6s rather than 2s. And if this tier is ever widened past
    `per-page=5`, the payload grows linearly and the timeout has to be
    revisited with it - so the number is pinned here where a future change
    will trip over it.
    """
    size = len((FIXTURES / "openalex_works.json").read_text(encoding="utf-8"))
    assert size > 50_000, size
    assert settings.market_tier_timeout_seconds >= 5, (
        f"the OpenAlex response is ~{size // 1000} KB for five results; a "
        f"timeout of {settings.market_tier_timeout_seconds}s is not enough to "
        f"transfer and parse it on a slow link")


def test_real_rows_link_off_the_allowlist_and_that_is_correct():
    """A FINDING WORTH STATING, because it looks like a bug.

    `primary_location.landing_page_url` is a **doi.org** URL, not an
    api.openalex.org one - the row cites the publisher, which is what a
    citation should do. So a row's `url` is routinely NOT in
    `market_allowed_hosts`.

    That is correct and must not be "fixed" by filtering rows to allowlisted
    hosts, which would discard every real citation. The allowlist governs what
    THIS PROCESS may connect to; a row's url is a link the reader's browser may
    follow, and the browser is not this process. The distinction is asserted
    here so nobody reconciles the two lists by breaking the useful one.
    """
    rows = market_providers.OpenAlexProvider._rows(OPENALEX)
    hosts = {row["url"].split("://", 1)[-1].split("/", 1)[0] for row in rows}
    assert any(h not in settings.market_allowed_hosts for h in hosts), hosts
    assert "doi.org" in hosts, hosts

    # ...and the REQUEST url is still checked, which is the control that counts.
    with pytest.raises(market_providers.HostNotAllowed):
        market_providers.check_host("https://doi.org/10.1016/x")


def test_a_real_title_carries_non_ascii_and_survives_intact():
    """"Sol-gel" in the real data is "Sol-gel" with an EN DASH between the
    syllables - the character is deliberately named rather than written here,
    because a linter that straightens it would silently defeat the test.
    Titles carry
    en dashes, accented author names and Greek letters, and the row text is
    passed through unchanged rather than being ASCII-folded - a folded title
    is a misquotation of a source."""
    rows = market_providers.OpenAlexProvider._rows(OPENALEX)
    non_ascii = [r["text"] for r in rows if any(ord(c) > 127 for c in r["text"])]
    assert non_ascii, (
        "the fixture no longer contains a non-ASCII title, so this no longer "
        "proves the text is passed through unfolded")
    assert any(ord(c) > 127 for c in non_ascii[0]), non_ascii[0]


# ------------------------------------------- end to end, still air-gapped


def test_a_full_search_over_the_recorded_responses(monkeypatch):
    """The whole path - tiers, rate limit, row shape, tier lists - driven by
    real recorded bytes. Still no socket: the transport is a function that
    returns the fixtures."""
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 0)
    monkeypatch.setattr(settings, "market_search_api_key", "")
    monkeypatch.setattr(settings, "market_search_provider", "")
    monkeypatch.setattr(settings, "market_search_endpoint", "")
    market_providers.reset_rate_limits()

    calls: list[str] = []

    def fetch(url, headers, timeout):
        calls.append(url)
        if "openalex" in url:
            return OPENALEX
        if "wikipedia" in url:
            return WIKIPEDIA
        raise AssertionError(f"unexpected host: {url}")

    result = market_providers.search_all(
        "iso 12944 corrosion coatings", fetch=fetch, now=lambda: 500.0)

    assert result["enabled"] is True
    assert result["failure"] is None, result["failure"]
    assert result["tiers_answered"] == [
        market_providers.TIER_LITERATURE, market_providers.TIER_REFERENCE]
    assert result["tiers_unconfigured"] == [market_providers.TIER_WEB]
    assert len(result["rows"]) == 10, len(result["rows"])

    # The phrase reached both real endpoints percent-encoded, and nothing else
    # did.
    assert len(calls) == 2
    for url in calls:
        assert "iso%2012944%20corrosion%20coatings" in url, url

    market_providers.reset_rate_limits()
