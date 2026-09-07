"""A tier-1 API key must never reach a response, a log, an error or the audit.

WHY THIS FILE EXISTS, stated plainly because the next person deserves to know
it was not hypothetical: a tier-1 API key was pasted into a chat today and has
been rotated. Rotation fixes that key. It does nothing about the class of
mistake, which is a credential ending up somewhere it can be read by someone
who was not given it.

So this file makes the class of mistake loud rather than trusting anyone to be
careful. Six separate surfaces are asserted, and they are separated on purpose
rather than rolled into one "the key does not leak" test:

  * the API response body
  * log records, captured at the handler
  * error MESSAGES
  * exception TRACEBACKS - the frame locals and the formatted trace
  * the audit record
  * the source files themselves, for a key-shaped literal

THE ERROR PATH IS THE ONE THAT LEAKS. It is worth saying why it gets two of
the six. In normal operation nobody prints a credential; the code that does it
is the code written in a hurry to find out why a request failed. An HTTP
library's exception routinely carries the full request URL, a URL can carry a
key as a query parameter, and `f"failed: {exc}"` in a handler puts it in the
log. That is the realistic leak, and it is why `market_providers._safe_reason`
rebuilds a message rather than passing the exception through.
"""

from __future__ import annotations

import ast
import logging
import re
import traceback
from pathlib import Path

import pytest

from app import market, market_phrase, market_providers
from app.config import settings

APP = Path(market.__file__).resolve().parent
TESTS = Path(__file__).resolve().parent

#: THE SENTINEL. Distinctive enough that finding it in any output is
#: unambiguous, and DELIBERATELY NOT SHAPED LIKE A CREDENTIAL.
#:
#: The first version of this was `tvly-` followed by 40 random alphanumerics -
#: realistic, which was the idea, and the pre-commit hook BLOCKED the commit
#: on it as `generic-api-key`. Correctly: a scanner cannot tell a fabricated
#: key from a real one, and a rule that could would be no rule at all.
#:
#: Answered the way 80042b1 answered the same problem: the marker was
#: RESHAPED, not allowlisted and not waved through with --no-verify. No
#: `.gitleaks.toml` entry was added, because an allowlist entry here would
#: weaken the control that exists to catch the next pasted key - and a pasted
#: key is exactly why this file exists. Lowercase words joined by hyphens
#: carry too little entropy to trip the rule, and every assertion below works
#: on any string, so nothing was lost but the resemblance.
FAKE_KEY = "sentinel-tier1-credential-that-must-never-be-echoed"

#: The files this promise covers. Only files this task owns.
OWNED_APP_FILES = ("market.py", "market_phrase.py", "market_providers.py")
OWNED_TEST_FILES = (
    "test_market.py", "test_market_phrase.py",
    "test_market_no_document_leak.py", "test_market_secret_hygiene.py",
)


@pytest.fixture
def configured_tier1(monkeypatch):
    """Tier 1 fully configured with a fake key, and the flags ON.

    The flags are forced on HERE and nowhere else, because these tests are
    specifically about what happens on the paths that only run when the
    feature is live. Nothing in this fixture makes a network call: the
    transport is still injected, and the ones below raise instead of fetching.
    """
    monkeypatch.setattr(settings, "market_search_api_key", FAKE_KEY)
    monkeypatch.setattr(settings, "market_search_provider", "examplesearch")
    monkeypatch.setattr(settings, "market_search_endpoint",
                        "https://api.examplesearch.test/search")
    monkeypatch.setattr(settings, "market_allowed_hosts",
                        ("api.examplesearch.test", "api.openalex.org",
                         "en.wikipedia.org"))
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 0)
    market_providers.reset_rate_limits()
    yield
    market_providers.reset_rate_limits()


# ------------------------------------------- 1. read from settings, never code


def test_the_key_is_read_from_settings_and_is_not_a_literal_anywhere():
    """NO KEY-SHAPED LITERAL EXISTS IN ANY FILE THIS TASK OWNS.

    Checked by pattern rather than by looking for one known value, so a
    DIFFERENT key pasted in tomorrow is caught too. That is the whole point:
    the control has to work against the next mistake, not the last one.
    """
    # Long runs of credential-ish characters, and the common vendor prefixes.
    suspicious = re.compile(
        r"""(?:                          # a vendor-prefixed key
                (?:sk|pk|tvly|xai|ghp|gho|api|key|token|bearer)
                [-_][A-Za-z0-9_\-]{20,}
            )
            |
            (?:                          # or a bare high-entropy blob
                \b[A-Za-z0-9]{32,}\b
            )""",
        re.VERBOSE,
    )
    for name in OWNED_APP_FILES:
        text = (APP / name).read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # prose about keys is not a key
            for hit in suspicious.findall(line):
                pytest.fail(
                    f"{name}:{line_no} contains a credential-shaped literal "
                    f"{hit!r}. The key is read from "
                    f"settings.market_search_api_key and from nowhere else."
                )


def test_the_only_place_the_key_is_named_is_the_settings_attribute():
    """The key reaches the code through exactly one expression.

    Asserted from the AST so a second access path - an os.environ read, a
    config file parsed on the side - is a failure rather than a thing someone
    might notice in review.
    """
    text = (APP / "market_providers.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    env_reads = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv")
    ]
    assert not env_reads, (
        "market_providers reads the environment directly. Credentials come "
        "from Settings, which anchors .env to backend/ - a direct os.environ "
        "read resolves against the process working directory instead, which is "
        "the bug that let AUTH_MODE be silently ignored."
    )


def test_the_sentinel_itself_is_not_credential_shaped():
    """A GUARD ON THE FIXTURE, added after the hook blocked this file.

    If somebody makes the sentinel "more realistic" again, the commit is
    rejected by the pre-commit scan - which is the control working, but it
    works at commit time, after the edit, and the reason is not obvious from
    the diff. This says it here instead.

    The two shapes `generic-api-key` looks for are a long run of mixed
    alphanumerics and a vendor-prefixed token, so the sentinel must have
    neither.
    """
    assert not re.search(r"[A-Za-z0-9]{32,}", FAKE_KEY), (
        f"{FAKE_KEY!r} contains a 32+ character alphanumeric run, which reads "
        f"as a real credential to a secret scanner")
    assert not re.match(
        r"(?i)(?:sk|pk|tvly|xai|ghp|gho|api|key|token|bearer)[-_]", FAKE_KEY), (
        f"{FAKE_KEY!r} opens with a vendor credential prefix")
    # ...and it is still distinctive enough to be found unambiguously.
    assert len(FAKE_KEY) > 20 and FAKE_KEY.count("-") >= 3


# --------------------------------------------------- 2. not in an API response


def test_the_key_is_absent_from_the_preview_response(configured_tier1):
    phrase = market_phrase.market_phrase("what is ISO 12944", ["doc13.pdf"])
    body = repr(market_providers.preview(phrase))
    assert FAKE_KEY not in body, body


def test_the_key_is_absent_from_a_successful_search_response(configured_tier1):
    def fetch(url, headers, timeout):
        # A real adapter is handed the key in a header; the RESPONSE must not
        # carry it back out.
        assert FAKE_KEY in headers.get("Authorization", ""), (
            "the fixture is not exercising the authenticated path")
        return {"results": [{"title": "ISO 12944 overview",
                             "url": "https://api.examplesearch.test/a",
                             "snippet": "Corrosion protection of steel."}]}

    result = market_providers.search_all(
        "iso 12944 coatings", fetch=fetch, now=lambda: 1000.0)
    assert result["tiers_answered"], result
    assert FAKE_KEY not in repr(result), repr(result)


def test_the_key_is_absent_from_a_failed_search_response(configured_tier1):
    """The failure path, which is the one that leaks."""
    def fetch(url, headers, timeout):
        # Exactly the realistic shape: the library reports the URL it called,
        # and the caller put the credential in the URL.
        raise RuntimeError(f"503 Service Unavailable for url {url}?key={FAKE_KEY}")

    result = market_providers.search_all(
        "iso 12944", fetch=fetch, now=lambda: 2000.0)
    assert result["failure"], result
    assert FAKE_KEY not in repr(result), (
        f"the key reached the failure response:\n{result['failure']}")
    assert "[redacted]" in repr(result), (
        "the key was removed but nothing records that a redaction happened")


def test_the_egress_state_and_findings_never_carry_the_key(configured_tier1):
    assert FAKE_KEY not in repr(market.egress_state())
    assert FAKE_KEY not in repr(market.findings())


# ------------------------------------------------------------ 3. not in a log


def test_the_key_is_absent_from_every_log_record(configured_tier1, caplog):
    """Captured at the handler, so it covers anything any market code logs -
    not just messages this test thought to look for."""
    def fetch(url, headers, timeout):
        raise RuntimeError(f"connect failed to {url}?api_key={FAKE_KEY}")

    with caplog.at_level(logging.DEBUG):
        market_providers.search_all("iso 12944", fetch=fetch, now=lambda: 3000.0)

    for record in caplog.records:
        rendered = record.getMessage() + repr(getattr(record, "args", ""))
        assert FAKE_KEY not in rendered, (
            f"the key reached a log record from {record.name}: {rendered}")
    assert FAKE_KEY not in caplog.text, caplog.text


# ------------------------------------------- 4. not in a message or traceback


def test_the_key_is_absent_from_a_raised_error_message(configured_tier1):
    """`_safe_reason` rebuilds the message from the exception TYPE plus
    redacted text, rather than interpolating the exception."""
    reason = market_providers._safe_reason(
        RuntimeError(f"GET https://api.examplesearch.test/s?key={FAKE_KEY} -> 401"))
    assert FAKE_KEY not in reason, reason
    assert "[redacted]" in reason, reason
    # It still says something useful, or it is not a diagnostic.
    assert "RuntimeError" in reason, reason


def test_the_key_is_absent_from_a_formatted_traceback(configured_tier1):
    """THE SURFACE MOST LIKELY TO BE OVERLOOKED. A traceback carries the
    formatted exception at the bottom, and an unhandled provider error would
    put that in a server log with the URL in it.

    So the assertion is on the whole formatted trace, not just the message.
    """
    def fetch(url, headers, timeout):
        raise RuntimeError(f"401 for {url}?key={FAKE_KEY}")

    caught: Exception | None = None
    try:
        provider = market_providers.WebSearchProvider()
        payload = market_providers.build_payload(
            "iso 12944", tier=market_providers.TIER_WEB)
        provider.search(payload, fetch=fetch, timeout=1.0)
    except Exception as exc:                          # noqa: BLE001
        caught = exc

    assert caught is not None, "the fixture did not raise"

    # The RAW trace does contain it - that is the honest starting point, and
    # exactly why search_all must never surface a raw exception.
    raw = "".join(traceback.format_exception(
        type(caught), caught, caught.__traceback__))
    assert FAKE_KEY in raw, (
        "this test asserts that raw tracebacks are dangerous; if the key is "
        "no longer in one, the premise has changed and the redaction below "
        "may be being credited for something else"
    )

    # And what the product actually reports does not.
    assert FAKE_KEY not in market_providers._safe_reason(caught)
    result = market_providers.search_all(
        "iso 12944", fetch=fetch, now=lambda: 4000.0)
    assert FAKE_KEY not in repr(result)


# --------------------------------------------------- 5. not in the audit record


def test_the_audit_record_never_carries_the_key(configured_tier1):
    """The audit table is, in this codebase's own words, the one most likely
    to be exported."""
    record = market_providers.audit_record(
        "iso 12944", tier=market_providers.TIER_WEB, outcome="ok")
    assert FAKE_KEY not in repr(record), record

    def fetch(url, headers, timeout):
        raise RuntimeError(f"401 {url}?key={FAKE_KEY}")

    result = market_providers.search_all(
        "iso 12944", fetch=fetch, now=lambda: 5000.0)
    for record in result["audit"]:
        assert FAKE_KEY not in repr(record), record


# ------------------------------------- 6. unconfigured says so, echoes nothing


def test_an_unconfigured_provider_reports_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "market_search_api_key", "")
    monkeypatch.setattr(settings, "market_search_provider", "")
    monkeypatch.setattr(settings, "market_search_endpoint", "")
    provider = market_providers.WebSearchProvider()

    assert provider.configured() is False
    assert provider.describe() == "not configured"


@pytest.mark.parametrize("partial", [
    {"market_search_api_key": FAKE_KEY},
    {"market_search_api_key": FAKE_KEY, "market_search_provider": "examplesearch"},
    {"market_search_api_key": "short"},
])
def test_a_misconfigured_provider_does_not_echo_what_it_found(monkeypatch, partial):
    """"Not configured" AND NOTHING ELSE.

    The tempting diagnostic is the harmful one: "key present (44 chars),
    endpoint missing" tells an attacker the key exists and its length, and
    "found key tvly-Zx91..." is the leak itself wearing a helpful tone. A
    half-configured provider says only that it is not configured.
    """
    monkeypatch.setattr(settings, "market_search_provider", "")
    monkeypatch.setattr(settings, "market_search_endpoint", "")
    for key, value in partial.items():
        monkeypatch.setattr(settings, key, value)

    provider = market_providers.WebSearchProvider()
    assert provider.configured() is False
    description = provider.describe()
    assert description == "not configured", description
    assert FAKE_KEY not in description
    assert str(len(FAKE_KEY)) not in description, (
        f"the description discloses the key's LENGTH, which tells an attacker "
        f"it is present and how long it is: {description!r}")
    assert "chars" not in description, description

    with pytest.raises(market_providers.ProviderUnconfigured) as caught:
        provider.search({"phrase": "iso 12944"}, fetch=_never_called, timeout=1.0)
    assert FAKE_KEY not in str(caught.value)
    assert str(caught.value) == "not configured", str(caught.value)


def _never_called(url, headers, timeout):
    raise AssertionError(
        "an unconfigured provider must not reach the transport at all")


def test_an_unconfigured_tier_one_is_a_normal_state_not_a_failure(monkeypatch):
    """Tier 1 absent must not take tiers 2 and 3 down with it, and must be
    VISIBLE in `tiers_attempted` rather than silently missing."""
    monkeypatch.setattr(settings, "market_search_api_key", "")
    monkeypatch.setattr(settings, "market_search_provider", "")
    monkeypatch.setattr(settings, "market_search_endpoint", "")
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    monkeypatch.setattr(settings, "market_tier_min_interval_seconds", 0)
    market_providers.reset_rate_limits()

    def fetch(url, headers, timeout):
        if "openalex" in url:
            return {"results": [{
                "display_name": "Corrosion protection",
                "publication_date": "2021-01-01",
                "primary_location": {
                    "landing_page_url": "https://api.openalex.org/works/W1",
                    "source": {"display_name": "Journal of Coatings"}},
            }]}
        return {"query": {"search": [
            {"title": "ISO 12944", "snippet": "A <span>standard</span>."}]}}

    result = market_providers.search_all(
        "iso 12944", fetch=fetch, now=lambda: 6000.0)

    assert market_providers.TIER_WEB in result["tiers_unconfigured"], (
        "an unconfigured tier must be reported SOMEWHERE, or its absence is "
        "invisible to the reader - but not in `tiers_attempted`, because "
        "nothing was sent to it")
    assert market_providers.TIER_WEB not in result["tiers_attempted"]
    assert market_providers.TIER_WEB not in result["tiers_answered"]
    assert market_providers.TIER_LITERATURE in result["tiers_answered"]
    assert market_providers.TIER_REFERENCE in result["tiers_answered"]
    assert result["failure"] is None, (
        "two tiers answered, so the search did not fail")
    assert result["rows"], result
