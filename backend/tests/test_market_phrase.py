"""The whitelist that decides what may leave, and the three tiers, offline.

`market_phrase` is the only thing between a user's question and a third-party
search engine. Its contract is small and unforgiving: return a phrase built
ONLY from tokens affirmatively judged safe, or return None meaning DO NOT
SEARCH - and never, on any path, return the question it was given.

The provider tests in the second half run entirely on FABRICATED responses.
There is no network call in this file and no transport is constructed, which
is what lets the suite pass air-gapped - the deployment target.
"""

from __future__ import annotations

import pytest

from app import market, market_providers
from app.config import settings
from app.market_phrase import MAX_PHRASE_CHARS, MAX_TOKENS, market_phrase

CORPUS = (
    "doc13.pdf", "doc16.pdf", "doc18.pdf",
    "book2-Differential-Equations.pdf",
    "civil-Design-and-Construction.pdf",
    "NORSOK-M-501.pdf",
)


# ------------------------------------------------------------ what is removed


@pytest.mark.parametrize("question", [
    "compare design requirements in doc13.pdf and doc16.pdf",
    "compare design requirements in DOC13.PDF and Doc16.pdf",
    "what does doc13 require",
    "summarise book2-Differential-Equations",
    "look at civil-Design-and-Construction.pdf",
])
def test_no_corpus_filename_survives_in_any_case_or_form(question):
    """Full name, bare stem, and any capitalisation. A filename is corpus
    metadata - it tells an outside service which documents exist here - and
    the stem is the form a blacklist usually misses, because a user who types
    "doc13" never typed an extension."""
    phrase = market_phrase(question, CORPUS)
    text = (phrase or "").lower()
    for name in CORPUS:
        stem = name.rsplit(".", 1)[0].lower()
        assert name.lower() not in text, f"{name!r} survived: {phrase!r}"
        assert stem not in text, f"stem {stem!r} survived: {phrase!r}"
        assert "pdf" not in text.split(), f"an extension survived: {phrase!r}"

    # THE DISTINCTIVE tokens - the ones that identify a document rather than
    # describe a subject. Asserted individually because `doc13` alone is the
    # same inventory disclosure as `doc13.pdf`.
    #
    # NOT every word inside a filename. `civil-Design-and-Construction.pdf`
    # contains "design", and banning "design" would gut a product whose users
    # search for design requirements all day. That was this test's first
    # version and it failed correctly: the assertion has to be about tokens
    # that IDENTIFY a document, not about English words that happen to appear
    # in one's name.
    for identifying in ("doc13", "doc16", "doc18", "differential",
                        "equations", "book2"):
        assert identifying not in text.split(), (
            f"{identifying!r} identifies a document and survived: {phrase!r}")


def test_a_quoted_clause_is_removed_because_it_is_the_users_own_document():
    """Quotation marks in this context mean "I am quoting my specification".
    The span goes as a whole, before tokenising, so the words inside it never
    reach the whitelist to be judged as ordinary subject words."""
    phrase = market_phrase(
        'is "a draft submission (usually at least a 50% design submission)" '
        'an industry norm', CORPUS)
    text = (phrase or "").lower()
    for leaked in ("draft", "submission", "usually", "50"):
        assert leaked not in text, f"{leaked!r} escaped the quotes: {phrase!r}"


@pytest.mark.parametrize("question", [
    "p.125", "pp. 12-14", "page 7", "pages 3-9",
    "section 7.2", "clause 3.2", "table 1", "figure 4b",
    "appendix A", "annex B", "rev 2", "revision 3.1",
    "doc13", "document 4",
])
def test_a_bare_reference_leaves_nothing_to_search_for(question):
    """These carry no subject at all, so the honest answer is None - DO NOT
    SEARCH - rather than a phrase made of punctuation and digits."""
    assert market_phrase(question, CORPUS) is None, question


@pytest.mark.parametrize("question", [
    "in section 7.2 what is the NDFT", "on p.125 what is required",
    "see table 1 for the coating system",
])
def test_a_reference_inside_a_real_question_is_removed_but_the_subject_stays(
        question):
    phrase = market_phrase(question, CORPUS)
    assert phrase is not None, question
    for leaked in ("7.2", "125", "p.125", "table 1", "section"):
        assert leaked not in phrase, f"{leaked!r} survived: {phrase!r}"


# --------------------------------------------------------- what is kept

@pytest.mark.parametrize("question,expected", [
    ("what is ISO 12944", "12944"),
    ("explain NIST SP 800-207 zero trust", "800-207"),
    ("NORSOK M-501 holiday detection", "M-501"),
    ("does IEC 61511 apply", "61511"),
])
def test_a_public_standard_designator_survives(question, expected):
    """THE REASON TIER 3 EXISTS. ISO 12944, NORSOK M-501 and NIST SP 800-207
    are not DOI-registered works, so a scholarly index cannot answer "what is
    this standard" and a general reference source has to. Naming a published
    standard discloses nothing about the client: the standard exists whether
    or not they hold a copy."""
    phrase = market_phrase(question, CORPUS)
    assert phrase is not None, question
    assert expected.lower() in phrase.lower(), (question, phrase)


def test_subject_terms_a_person_would_type_are_kept():
    phrase = market_phrase(
        "compare design requirements for offshore coatings", CORPUS)
    assert phrase is not None
    for kept in ("design", "requirements", "offshore", "coatings"):
        assert kept in phrase, (kept, phrase)
    # ...and the instruction verb is not a subject term.
    assert "compare" not in phrase


# ------------------------------------------------- the whitelist fails CLOSED


#: Internal identifiers. None of these was anticipated by a pattern; every one
#: must be dropped anyway, because a token reaches the output only by matching
#: something affirmatively judged safe. An equipment tag or a project code is
#: precisely the kind of identifier that means something to a competitor and
#: nothing to anybody else.
IDENTIFIERS = ("PRJ-4471-B", "21-PV-1043A", "WO-99812", "1234567890",
               "A-123-XYZ", "4471", "1043a")


@pytest.mark.parametrize("question", [
    "PRJ-4471-B",
    "tag 21-PV-1043A",
    "WO-99812",
    "attachment F rev 2",
    "1234567890",
    "$$$ ###",
    "   ",
    "",
])
def test_an_unrecognised_input_yields_nothing_rather_than_passing_through(
        question):
    """THE WHOLE ARGUMENT FOR A WHITELIST. None of these was anticipated by a
    pattern; every one is dropped anyway, because a token reaches the output
    only by matching something affirmatively judged safe.

    A blacklist would have passed all of them - and an equipment tag or a
    project code is precisely the kind of internal identifier that means
    something to a competitor and nothing to anyone else.
    """
    assert market_phrase(question, CORPUS) is None, question


@pytest.mark.parametrize("question", [
    "PRJ-4471-B corrosion coatings",
    "tag 21-PV-1043A coating system",
    "WO-99812 offshore design",
    "A-123-XYZ protective coating",
])
def test_an_identifier_is_dropped_even_when_the_question_has_a_real_subject(
        question):
    """THE SECURITY PROPERTY, separated from the cosmetic one.

    The test above asserts these questions produce nothing when the identifier
    is all there is. This one is the sharper case: a real subject alongside an
    identifier. The subject may survive - that is the feature working - and
    the identifier may not, under any circumstances.
    """
    phrase = market_phrase(question, CORPUS)
    assert phrase is not None, question
    lowered = phrase.lower()
    for identifier in IDENTIFIERS:
        assert identifier.lower() not in lowered, (
            f"{identifier!r} survived in {phrase!r}")
    # no digit-bearing token at all, since none of these is a standard
    for token in lowered.split():
        assert not any(ch.isdigit() for ch in token), (
            f"a digit-bearing token {token!r} survived from a question with no "
            f"standard designator: {phrase!r}")


def test_none_never_degrades_into_the_raw_question():
    """The one failure that would void the promise entirely: a caller getting
    the question back because nothing safe survived."""
    for question in ("p.125", "doc13.pdf", "PRJ-4471-B", '"quoted clause"'):
        result = market_phrase(question, CORPUS)
        assert result is None or result != question
        assert result is None or question.lower() not in result.lower()


def test_the_phrase_is_bounded_in_length_and_token_count():
    long_question = " ".join(["coatings"] + [f"term{i}word" for i in range(400)]
                             + ["corrosion"] * 200)
    phrase = market_phrase(long_question, CORPUS)
    assert phrase is not None
    assert len(phrase) <= MAX_PHRASE_CHARS
    assert len(phrase.split()) <= MAX_TOKENS


def test_an_empty_corpus_list_still_strips_references():
    """The function must not depend on being handed filenames to be safe. With
    no corpus names at all, the reference and quote removal and the whitelist
    still apply."""
    assert market_phrase("p.125 section 7.2", []) is None
    phrase = market_phrase("what is ISO 12944", [])
    assert phrase is not None and "12944" in phrase


# ============================ providers, offline ============================


@pytest.fixture
def live(monkeypatch):
    """Flags on, no transport constructed. Every response below is fabricated."""
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 0)
    monkeypatch.setattr(settings, "market_search_api_key", "")
    monkeypatch.setattr(settings, "market_search_provider", "")
    monkeypatch.setattr(settings, "market_search_endpoint", "")
    market_providers.reset_rate_limits()
    yield
    market_providers.reset_rate_limits()


OPENALEX = {"results": [{
    "display_name": "Corrosion protection of steel structures",
    "publication_date": "2019-04-02",
    "primary_location": {
        "landing_page_url": "https://api.openalex.org/works/W123",
        "source": {"display_name": "Journal of Protective Coatings"}},
}]}

WIKIPEDIA = {"query": {"search": [{
    "title": "ISO 12944",
    "timestamp": "2024-02-01T00:00:00Z",
    "snippet": 'ISO <span class="searchmatch">12944</span> is a standard.',
}]}}


def _fetch_both(url, headers, timeout):
    if "openalex" in url:
        return OPENALEX
    if "wikipedia" in url:
        return WIKIPEDIA
    raise AssertionError(f"unexpected host: {url}")


# ------------------------------------------------------------ the row shape


def test_every_row_carries_the_full_provenance_set(live):
    result = market_providers.search_all(
        "iso 12944", fetch=_fetch_both, now=lambda: 10.0)
    assert result["rows"], result
    for row in result["rows"]:
        assert set(row) == {
            "text", "provider_label", "publisher", "published", "retrieved",
            "url", "verification", "is_sample",
        }, row
        assert row["provider_label"] in market_providers.TIER_LABELS.values()
        assert row["publisher"]
        assert row["retrieved"].endswith("Z"), row["retrieved"]
        assert row["url"].startswith("https://")
        assert row["verification"] == "source_not_verified"
        assert row["is_sample"] is False


def test_the_reference_tier_is_labelled_background_only(live):
    result = market_providers.search_all(
        "iso 12944", fetch=_fetch_both, now=lambda: 11.0)
    labels = {r["provider_label"] for r in result["rows"]}
    assert "reference - background only" in labels, labels


def test_wikipedia_search_markup_is_stripped_from_the_text(live):
    result = market_providers.search_all(
        "iso 12944", fetch=_fetch_both, now=lambda: 12.0)
    texts = [r["text"] for r in result["rows"]]
    assert any("12944" in t for t in texts), texts
    for text in texts:
        assert "<" not in text and "searchmatch" not in text, text


# --------------------------------------------- dropping a tier is VISIBLE


def test_attempted_and_answered_are_reported_separately(live):
    """"Never configured" and "tried and returned nothing" mean different
    things, and one list would conflate them."""
    result = market_providers.search_all(
        "iso 12944", fetch=_fetch_both, now=lambda: 13.0)
    # Tier 1 is unconfigured in this fixture, so it was never CONTACTED. It
    # belongs in `tiers_unconfigured`, not in `tiers_attempted` - otherwise a
    # UI is forced to tell the reader it was tried when nothing was sent.
    assert result["tiers_attempted"] == [
        market_providers.TIER_LITERATURE, market_providers.TIER_REFERENCE]
    assert result["tiers_unconfigured"] == [market_providers.TIER_WEB]
    assert market_providers.TIER_WEB not in result["tiers_attempted"]
    assert result["tiers_answered"] == [
        market_providers.TIER_LITERATURE, market_providers.TIER_REFERENCE]


def test_one_tier_failing_does_not_take_the_search_down(live):
    def fetch(url, headers, timeout):
        if "openalex" in url:
            raise TimeoutError("too slow")
        return WIKIPEDIA

    result = market_providers.search_all("iso 12944", fetch=fetch,
                                         now=lambda: 14.0)
    assert market_providers.TIER_REFERENCE in result["tiers_answered"]
    assert market_providers.TIER_LITERATURE not in result["tiers_answered"]
    assert result["failure"] is None, "one tier answered, so this did not fail"
    assert result["rows"]


# --------------------------------- all tiers failing NEVER returns samples


def test_all_tiers_failing_says_so_and_returns_no_rows(live):
    """THE ASSERTION THAT MATTERS MOST HERE. A sample row returned in place of
    a failed live search is a fabricated finding wearing a real feature's
    label, and the reader has no way to tell."""
    def fetch(url, headers, timeout):
        raise TimeoutError("network unreachable")

    result = market_providers.search_all("iso 12944", fetch=fetch,
                                         now=lambda: 15.0)
    assert result["enabled"] is True
    assert result["rows"] == [], result["rows"]
    assert result["failure"], "a total failure must say so"
    assert result["tiers_answered"] == []
    sample_texts = {r["claim"] for r in market.findings()["findings"]}
    for row in result["rows"]:
        assert row["text"] not in sample_texts


def test_no_transport_is_a_failure_not_a_sample(live):
    """`fetch=None` with the flags on: nothing can be sent, so nothing is
    claimed. Specifically NOT the samples."""
    result = market_providers.search_all("iso 12944", fetch=None,
                                         now=lambda: 16.0)
    assert result["rows"] == []
    assert result["failure"]


def test_no_results_is_a_real_answer_and_is_not_a_failure(live):
    """Zero rows from a tier that answered is information. It is not padded,
    not fabricated, and not reported as a failure."""
    def fetch(url, headers, timeout):
        return {"results": [], "query": {"search": []}}

    result = market_providers.search_all("iso 12944", fetch=fetch,
                                         now=lambda: 17.0)
    assert result["rows"] == []
    assert result["failure"] is None, (
        "the tiers answered and found nothing; that is an answer")
    assert result["tiers_answered"], result


def test_a_phrase_of_none_is_not_reported_as_a_retrieval_failure(live):
    """None means nothing safe survived. The search was never attempted, which
    is a different fact from retrieval failing."""
    result = market_providers.search_all(None, fetch=_fetch_both,
                                         now=lambda: 18.0)
    assert result["rows"] == []
    assert result["tiers_attempted"] == []
    # THE NULL-PHRASE STATE, not a failure. `failure` used to carry both
    # meanings, so a refused phrase and a total retrieval failure reached the
    # UI identically. `phrase: None` is now the single signal, and it matches
    # what the preview returns for the same input, so both screens can use one
    # form of words.
    assert result["phrase"] is None
    assert result["failure"] is None, (
        "a phrase that could not be safely built is not a retrieval failure")


# -------------------------------------------------- hosts, timeout, throttle


def test_a_host_outside_the_allowlist_is_refused():
    with pytest.raises(market_providers.HostNotAllowed):
        market_providers.check_host("https://evil.test/search?q=x")


def test_every_shipped_tier_url_is_inside_the_allowlist():
    for url in (market_providers.OpenAlexProvider.BASE,
                market_providers.WikipediaProvider.BASE):
        assert market_providers.check_host(url) == url


def test_the_configured_timeout_reaches_the_transport(live, monkeypatch):
    monkeypatch.setattr(settings, "market_tier_timeout_seconds", 2.5)
    seen: list[float] = []

    def fetch(url, headers, timeout):
        seen.append(timeout)
        return WIKIPEDIA if "wikipedia" in url else OPENALEX

    market_providers.search_all("iso 12944", fetch=fetch, now=lambda: 19.0)
    assert seen and all(t == 2.5 for t in seen), seen


def test_the_rate_limit_refuses_a_second_call_inside_the_interval(monkeypatch):
    """An injected clock, so the throttle is proved without sleeping."""
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 5.0)
    market_providers.reset_rate_limits()

    market_providers.check_rate("literature", now=lambda: 100.0)
    with pytest.raises(market_providers.RateLimited):
        market_providers.check_rate("literature", now=lambda: 102.0)
    # ...and is allowed again once the interval has passed.
    market_providers.check_rate("literature", now=lambda: 106.0)


def test_the_rate_limit_is_per_tier(monkeypatch):
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 5.0)
    market_providers.reset_rate_limits()
    market_providers.check_rate("literature", now=lambda: 200.0)
    market_providers.check_rate("reference", now=lambda: 200.0)


# ------------------------------------------- FLAG OFF: identical to today


def test_with_the_flag_off_the_result_is_the_labelled_samples():
    """WHAT MAKES THIS SAFE TO MERGE BEFORE ANYONE HAS APPROVED ANYTHING.

    Default settings, no monkeypatching: the search path returns the existing
    samples, every row still marked `is_sample` with a `sample://` URL, and
    `failure` is None because nothing failed - the feature is simply off.
    """
    assert settings.market_live_enabled is False
    assert settings.market_allow_public_egress is False

    result = market_providers.search_all("iso 12944")
    assert result["enabled"] is False
    assert result["failure"] is None
    assert result["tiers_attempted"] == []
    assert result["rows"], "the flag-off answer is still the samples"
    for row in result["rows"]:
        assert row["is_sample"] is True
        assert row["url"].startswith("sample://")
        assert row["verification"] == "source_not_verified"


def test_with_the_flag_off_no_transport_is_ever_consulted():
    """Even handed a transport, the flag-off path must not call it."""
    def explode(url, headers, timeout):
        raise AssertionError("the flag is off; nothing may be fetched")

    result = market_providers.search_all("iso 12944", fetch=explode)
    assert result["enabled"] is False


def test_with_the_flag_off_egress_state_is_unchanged():
    """`market.egress_state()` is what drives the panel's banner. It must read
    exactly as it did before any of this existed."""
    assert market.egress_state() == {
        "web_search_enabled": False, "allow_public_egress": False}


def test_with_the_flag_off_live_enabled_is_false_and_needs_both_flags(
        monkeypatch):
    """Two flags, and one is not enough. Turning the feature on in a build
    must not by itself open egress on a client machine."""
    assert market_providers.live_enabled() is False
    monkeypatch.setattr(settings, "market_live_enabled", True)
    assert market_providers.live_enabled() is False, (
        "market_live_enabled alone must not permit egress")
    monkeypatch.setattr(settings, "market_live_enabled", False)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    assert market_providers.live_enabled() is False, (
        "allow_public_egress alone must not enable the feature")


def test_no_tier_one_host_is_allowlisted_by_default():
    """No tier-1 vendor is chosen, so no tier-1 host is permitted. The list
    grows when a decision is made, not in advance of one."""
    assert set(settings.market_allowed_hosts) == {
        "api.openalex.org", "en.wikipedia.org"}


# --------------------------------------------------------------- the preview


def test_the_preview_sends_nothing_and_shows_exactly_what_would_leave():
    phrase = "iso 12944 coatings"
    preview = market_providers.preview(phrase)
    assert preview["phrase"] == phrase
    assert isinstance(preview["tiers_configured"], list)
    # ONE ENTRY PER CONFIGURED TIER, because that is what leaves.
    assert [e["tier"] for e in preview["payloads"]] ==         preview["tiers_configured"]
    for entry in preview["payloads"]:
        assert set(entry["payload"]) == set(
            market_providers.ALLOWED_PAYLOAD_FIELDS)
        assert entry["payload"]["phrase"] == phrase
        assert entry["provider_label"] ==             market_providers.TIER_LABELS[entry["tier"]]


def test_the_preview_shows_the_scope_fields_that_actually_get_sent():
    """DEFECT 1, the half that a reader would notice. `country` and
    `freshness_days` appear in every real payload; a preview without them
    showed an object that was never sent."""
    preview = market_providers.preview(
        "iso 12944", country="NO", freshness_days=30)
    assert preview["payloads"]
    for entry in preview["payloads"]:
        assert entry["payload"]["country"] == "NO"
        assert entry["payload"]["freshness_days"] == 30


def test_the_previewed_payloads_are_exactly_the_payloads_sent(live,
                                                              monkeypatch):
    """DEFECT 1, THE ASSERTION THAT MATTERS.

    Not "the preview has the same fields" - the same OBJECTS. Every
    `build_payload` call made during a real search is captured and compared
    against what the preview showed for the same inputs. If a tier ever grows
    its own payload construction, or a scope field reaches one path and not
    the other, this fails.

    The client-facing claim is "you approve exactly what leaves". This is that
    sentence as a test.
    """
    previewed = [e["payload"] for e in market_providers.preview(
        "iso 12944", country="NO", freshness_days=30)["payloads"]]

    sent: list[dict] = []
    real_build = market_providers.build_payload

    def spy(phrase, **kwargs):
        payload = real_build(phrase, **kwargs)
        sent.append(payload)
        return payload

    monkeypatch.setattr(market_providers, "build_payload", spy)
    market_providers.search_all("iso 12944", fetch=_fetch_both,
                                country="NO", freshness_days=30,
                                now=lambda: 30.0)

    assert sent, "no payload was built during the search"
    assert sent == previewed, (
        f"what was sent differs from what was previewed.\n"
        f"  previewed: {previewed}\n  sent     : {sent}"
    )


def test_a_null_phrase_previews_as_null_with_no_payload():
    """`phrase: null` is the contract's way of saying nothing safe survived
    and no search is possible."""
    preview = market_providers.preview(None)
    assert preview["phrase"] is None
    assert preview["payloads"] == []
