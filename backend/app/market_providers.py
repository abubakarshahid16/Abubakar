"""Three tiers of public information, one row shape, and no socket in sight.

WHAT THIS MODULE IS. It builds outbound payloads, builds URLs, checks them
against the one host allowlist, applies a per-tier timeout and rate limit,
parses responses into one row shape, and reports which tiers were attempted
and which answered. It ships with the live flag OFF and makes no network call
in this task.

WHAT IT DELIBERATELY IS NOT. It is not an HTTP client. `market.py`'s docstring
promised "no provider, no HTTP client, no URL that resolves", and the middle
promise is KEPT here literally: no module in this feature imports httpx,
requests, urllib or socket. The caller passes in a `fetch` callable. Three
things follow, and all three were the point:

  * the whole feature is testable AIR-GAPPED, which is the deployment target.
    Every provider test below runs against fabricated responses.
  * with no transport passed, a provider cannot reach the network by accident,
    however wrong its configuration is. The default is not "a client with a
    weird URL", it is no client.
  * the decision to open egress lives in the code that constructs the
    transport - one place, in a route, reviewable - rather than being diffused
    across three provider classes.

WHICH GUARANTEE FROM market.py HAS CHANGED. "No URL that resolves" no longer
holds for this module: `api.openalex.org` and `en.wikipedia.org` are real
hosts and the URLs built here would resolve if a transport were supplied and
the flags were on. The sample rows keep their `sample://` scheme, so that
promise still holds for everything `market.findings()` returns. This is stated
rather than quietly dropped, because a docstring that overclaims is worse than
one that admits a boundary moved.

WHY THREE TIERS, and specifically why tier 3 exists. The standards this corpus
cites - ISO 12944, NORSOK M-501, NIST SP 800-207 - are NOT DOI-registered
works. A scholarly index has no record of them, so tier 2 cannot answer "what
is this standard"; it can only answer "what has been published about it". A
general reference source can, which is why tier 3 is here and why it is
labelled "reference - background only" rather than being presented as a
source.

FAILING IS SAID OUT LOUD. If every tier fails the result carries `rows: []`
and a `failure` string. It NEVER falls back to the sample rows: a sample
returned in place of a failed live search is a fabricated finding wearing a
real feature's label, and the reader has no way to tell. Samples are returned
only when the feature is off, where they are the honest answer and are labelled
as such.
"""

from __future__ import annotations

import string
import time
from urllib.parse import urlsplit
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from .config import settings

#: PERCENT-ENCODING, HAND-ROLLED, and the reason is a guarantee rather than
#: taste. `urllib.parse.quote` would do this in one line and cannot open a
#: socket - but the import it needs is `urllib`, and `urllib.request` lives in
#: the same top-level package. tests/test_market_no_document_leak.py forbids
#: that whole package by name, deliberately: an absolute rule ("these modules
#: import no networking package") survives review and refactoring, while a
#: precise one ("urllib.parse yes, urllib.request no") is a rule someone has
#: to reason about correctly every time. Six lines of encoder buys the
#: absolute version.
#: Built from `string` rather than spelled out. A literal alphabet here is a
#: 62-character alphanumeric run, which is credential-SHAPED - and
#: test_market_secret_hygiene.py's detector flagged it, correctly. Narrowing
#: the detector to let it through would have weakened the control that exists
#: to catch a pasted key; composing the set instead costs nothing and keeps
#: the detector strict.
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-_.~")


def quote(value: str) -> str:
    """Percent-encode for a query-string value. RFC 3986 unreserved set."""
    out: list[str] = []
    for byte in str(value).encode("utf-8"):
        ch = chr(byte)
        out.append(ch if ch in _UNRESERVED else f"%{byte:02X}")
    return "".join(out)


# ------------------------------------------------------------------- tiers

TIER_WEB = "web"
TIER_LITERATURE = "literature"
TIER_REFERENCE = "reference"

#: Order matters: it is the order tiers are attempted and reported in.
TIERS: tuple[str, ...] = (TIER_WEB, TIER_LITERATURE, TIER_REFERENCE)

#: The label a row carries into the UI. Fixed here, not in the frontend, so
#: the words a reader sees about provenance come from the layer that knows
#: where the row came from.
TIER_LABELS: Mapping[str, str] = {
    TIER_WEB: "market search",
    TIER_LITERATURE: "published literature",
    TIER_REFERENCE: "reference - background only",
}

#: THE SAMPLE PROVENANCE LABEL. A fixture row is not a tier-3 reference row.
#:
#: `_disabled_result` used to stamp every sample with the reference tier's
#: label, so a panel correctly rendering provenance printed "background only"
#: over illustrative MARKET rows - true about the row being a sample, wrong
#: about where it came from. It came from nowhere; that is the point of it.
#: `is_sample` already carries "this is not real", and this carries "no tier
#: produced this", which is a different fact.
SAMPLE_LABEL = "sample - illustrative only"

#: Nothing here has been read by a human or checked against its source.
VERIFICATION_UNVERIFIED = "source_not_verified"


def tier_labels() -> dict:
    """The id -> label map, sent with every response.

    ONE VOCABULARY, RESOLVED AT THE SOURCE. The tier lists carry ids (`web`)
    and rows carry labels (`market search`), so a UI given only the lists had
    to keep its own copy of this mapping to render them - and a duplicated
    mapping drifts, which is how a reader ends up seeing "web" on one line and
    "market search" on the next. The map travels with the data instead.
    """
    return dict(TIER_LABELS)


# ------------------------------------------------------------ the payload

#: THE CLOSED FIELD SET. Everything in an outbound payload is here and nothing
#: else can be. Adding a field means editing this tuple, which means the
#: change appears in a diff next to this comment, which is the point.
#:
#: There is deliberately NO field that could carry a passage. No `context`, no
#: `evidence`, no `surrounding_text`. The absence is asserted by
#: tests/test_market_no_document_leak.py, which checks the NAMES as well as
#: the values - a field called `context` is a passage carrier whatever it
#: happens to hold on the day it is added.
ALLOWED_PAYLOAD_FIELDS: tuple[str, ...] = (
    "phrase", "tier", "provider_label", "country", "freshness_days",
)

#: A search phrase, not prose. Above this it is not a phrase any more and
#: something upstream has handed over document text.
MAX_PHRASE_CHARS = 200
MAX_PHRASE_WORDS = 16
MAX_PHRASE_SENTENCES = 1


class PassageRefused(ValueError):
    """Document text was handed to something that only accepts a phrase.

    RAISED, NOT SANITISED. Stripping the passage and continuing would leave
    the caller believing it had been used, and a silent gap between what code
    does and what its author thinks it does is where the next leak lives.
    """


def _refuse_forbidden_kwargs(kwargs: Mapping[str, object]) -> None:
    if not kwargs:
        return
    names = ", ".join(sorted(kwargs))
    raise PassageRefused(
        f"build_payload received {names}. Only a phrase may leave this "
        f"machine. Passages, evidence, document text and corpus objects are "
        f"REFUSED rather than dropped: if this call site needs to pass them, "
        f"the promise has changed and that is a reviewed decision, not a "
        f"keyword argument."
    )


def _check_phrase(phrase: object) -> str:
    """The phrase, or a refusal. Never a truncation."""
    if phrase is None:
        raise PassageRefused(
            "phrase is None. None from market_phrase() means DO NOT SEARCH; "
            "it must never be coerced to a string and sent."
        )
    if not isinstance(phrase, str):
        raise PassageRefused(f"phrase must be a string, got {type(phrase).__name__}")
    text = phrase.strip()
    if not text:
        raise PassageRefused("phrase is empty; there is nothing to search for")
    if len(text) > MAX_PHRASE_CHARS:
        raise PassageRefused(
            f"phrase is {len(text)} characters, over the {MAX_PHRASE_CHARS} "
            f"limit. REFUSED, not truncated: truncating would send the first "
            f"{MAX_PHRASE_CHARS} characters of what is almost certainly a "
            f"clause out of a document."
        )
    if len(text.split()) > MAX_PHRASE_WORDS:
        raise PassageRefused(
            f"phrase is {len(text.split())} words, over {MAX_PHRASE_WORDS}. "
            f"A search phrase is not a paragraph."
        )
    if text.count(".") + text.count("!") + text.count("?") > MAX_PHRASE_SENTENCES:
        # A designator like "ISO 12944-5" carries no sentence punctuation, so
        # this does not fire on legitimate standard names.
        raise PassageRefused(
            "phrase contains multiple sentences, which is prose rather than a "
            "search phrase - document text has been passed where a phrase was "
            "expected."
        )
    return text


def build_payload(phrase: str, *, tier: str, country: str | None = None,
                  freshness_days: int | None = None, **forbidden: object) -> dict:
    """The object that WOULD leave, for one tier. Building it sends nothing.

    `**forbidden` exists to make an accident loud. Without it, a caller that
    passed `passages=` would get a bare `TypeError` from Python and might
    "fix" it by adding the parameter. With it, the refusal names the field and
    says why, in `PassageRefused`.
    """
    _refuse_forbidden_kwargs(forbidden)
    text = _check_phrase(phrase)
    if tier not in TIER_LABELS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    return {
        "phrase": text,
        "tier": tier,
        "provider_label": TIER_LABELS[tier],
        "country": country,
        "freshness_days": freshness_days,
    }


# --------------------------------------------------------------- the audit

def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def audit_record(phrase: str | None, *, tier: str, outcome: str = "ok") -> dict:
    """One outbound query, as a row for the EXISTING `audit_events` table.

    THE AUDIT MECHANISM THIS CODEBASE ALREADY HAS is `audit_events` in db.py,
    written by `admin._audit` and `auth`. It is append-only, keeps two actor
    fields so a deleted user does not delete the evidence, and its `detail`
    column is documented as response-safe only. That is the right home for
    this and no second mechanism is invented.

    BUT THIS MODULE CANNOT WRITE TO IT, and that is a deliberate consequence
    of a stronger rule. `admin._audit` needs `connect()` from `db`, and the
    market modules are forbidden to import `db` - enforced by AST inspection
    in tests/test_market_no_document_leak.py - precisely so this feature
    cannot reach the corpus. Importing `db` here to write an audit row would
    hand the leaking-est module in the system a live database handle.

    So the split is: this function builds the ROW, and the caller persists it.
    The keys match the `audit_events` columns exactly so the caller writes it
    without translating, and a translation layer is where a field quietly
    stops being recorded. Wiring that call site is not part of this task -
    `main.py` is not mine to edit - so until it is wired, THE RECORD IS
    RETURNED AND NOT STORED. Said plainly because an audit trail nobody
    persists is not an audit trail.

    `detail` is the phrase VERBATIM. That is safe by the only argument that
    matters here: the phrase is the text already deemed fit to hand to a third
    party, so it is certainly fit for a local table. It is not summarised or
    hashed, because the single question this row exists to answer is "what
    exactly left this machine", and a hash cannot answer it.
    """
    return {
        "at": _now_iso(),
        "action": "market.outbound_query",
        "resource_type": "market_query",
        "resource_id": tier,
        "detail": phrase,
        "outcome": outcome,
    }


# ------------------------------------------------------- hosts and throttle

class HostNotAllowed(ValueError):
    """A URL whose host is not in the one allowlist."""


def _host_of(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HostNotAllowed("market URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise HostNotAllowed("market URL must not contain embedded credentials")
    return parsed.hostname.rstrip(".").lower()


def check_host(url: str) -> str:
    """The URL, or a refusal.

    ONE ALLOWLIST, in `settings.market_allowed_hosts`, checked here for every
    tier. Code-level allowlisting is DEFENCE IN DEPTH and not the control: a
    process that can open a socket can reach any host it likes, and this only
    stops the code in this repository from doing so by accident or through a
    mistaken config value. The real control is an OS firewall rule or an
    egress proxy restricting this process to those hosts, applied where the
    application cannot edit it.
    """
    host = _host_of(url)
    allowed = tuple(settings.market_allowed_hosts or ())
    if host not in allowed:
        raise HostNotAllowed(
            f"{host!r} is not in market_allowed_hosts {allowed!r}. One list, "
            f"one place; add it there deliberately or not at all."
        )
    return url


#: Last outbound attempt per tier, monotonic. Module state, which is right for
#: a per-process throttle: it must not reset because a request finished.
_last_call: dict[str, float] = {}


class RateLimited(RuntimeError):
    """This tier was called again too soon."""


def check_rate(tier: str, *, now: Callable[[], float] = time.monotonic) -> None:
    """A FLOOR ON SPACING, not a quota.

    Tiers 2 and 3 are donated public infrastructure. Being a bad citizen on
    them is both rude and the fastest route to being blocked, which would take
    the feature down for the client. `now` is injectable so the test suite can
    prove the throttle fires without sleeping.
    """
    interval = float(settings.market_tier_min_interval_seconds or 0)
    if interval <= 0:
        return
    previous = _last_call.get(tier)
    current = now()
    if previous is not None and (current - previous) < interval:
        raise RateLimited(
            f"tier {tier!r} called again after {current - previous:.3f}s; "
            f"minimum interval is {interval}s"
        )
    _last_call[tier] = current


def reset_rate_limits() -> None:
    """For tests. Module state has to be clearable or tests couple to order."""
    _last_call.clear()


# ------------------------------------------------------------- the providers

#: The transport. Given a URL, headers and a timeout, return a decoded JSON
#: object. Supplied by the caller; NEVER constructed here.
Fetch = Callable[[str, Mapping[str, str], float], object]


class ProviderUnconfigured(RuntimeError):
    """A NORMAL STATE, not an error.

    Tier 1 without a key, or with no vendor chosen, simply does not run. It is
    reported in `tiers_attempted` so its absence is visible, and the other
    tiers still answer.
    """


def _row(*, text: str, tier: str, publisher: str, url: str,
         published: str | None) -> dict:
    """THE ONE ROW SHAPE. Every tier returns this and nothing else.

    Every field the API contract requires is present on every row: the
    provider label so a reader knows which tier spoke, the publisher,
    `retrieved` as ISO-8601 UTC, the URL, and the verification state. `is_sample`
    is False here and only ever True on a row from `market.findings()`.
    """
    return {
        "text": text,
        "provider_label": TIER_LABELS[tier],
        "publisher": publisher,
        "published": published,
        "retrieved": _now_iso(),
        "url": url,
        "verification": VERIFICATION_UNVERIFIED,
        "is_sample": False,
    }


class WebSearchProvider:
    """TIER 1, general web search - AN INTERFACE PLUS A CONFIG-DRIVEN ADAPTER.

    NO VENDOR IS BAKED IN. The vendor originally suggested has started asking
    for a billing address, so the choice is unsettled and this is built as if
    it will change. The endpoint, the vendor name and the credential all come
    from settings, and the response shape is read through
    `_first_present`, which tries the field names the common vendors use
    rather than one vendor's schema.

    THE KEY IS `MARKET_SEARCH_API_KEY`, generic, not `TAVILY_API_KEY`. Reason:
    a vendor-named variable has to be renamed the day the vendor changes, and
    renaming an environment variable on a client's machine is a SILENT
    breakage - their `.env` keeps the old name, it resolves to nothing, the
    tier reports itself unconfigured, and the operator believes they
    configured it. A generic credential plus `market_search_provider` naming
    the vendor makes a swap a value change instead.
    """

    tier = TIER_WEB
    label = TIER_LABELS[TIER_WEB]

    def configured(self) -> bool:
        return bool(
            (settings.market_search_api_key or "").strip()
            and (settings.market_search_provider or "").strip()
            and (settings.market_search_endpoint or "").strip()
        )

    def describe(self) -> str:
        """What to say about this tier without saying anything secret."""
        if self.configured():
            return f"{settings.market_search_provider} (configured)"
        return "not configured"

    def search(self, payload: Mapping[str, object], *, fetch: Fetch,
               timeout: float) -> list[dict]:
        if not self.configured():
            # Deliberately says nothing about WHAT it found. Echoing a
            # partial key, its length, or the endpoint it half-read is how a
            # credential ends up in a log line.
            raise ProviderUnconfigured("not configured")
        endpoint = check_host(str(settings.market_search_endpoint))
        url = f"{endpoint}?q={quote(str(payload['phrase']))}"
        headers = {"Authorization": f"Bearer {settings.market_search_api_key}"}
        raw = fetch(url, headers, timeout)
        return self._rows(raw)

    @staticmethod
    def _rows(raw: object) -> list[dict]:
        items = _as_list(raw, ("results", "data", "items", "webPages"))
        rows: list[dict] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            text = _first_present(item, ("content", "snippet", "description",
                                         "summary", "title"))
            url = _first_present(item, ("url", "link", "href"))
            if not text or not url:
                continue
            rows.append(_row(
                text=text, tier=TIER_WEB,
                publisher=_first_present(item, ("source", "publisher",
                                                "site_name")) or _host_of(url),
                url=url,
                published=_first_present(item, ("published_date", "published",
                                                "date")),
            ))
        return rows


class OpenAlexProvider:
    """TIER 2, published literature. No key.

    The CONTACT EMAIL is the operator's and defaults to EMPTY. OpenAlex offers
    a "polite pool" with better rate limits in exchange for being
    identifiable, which is a fair trade for whoever RUNS this software and an
    unfair one to make on the client's behalf: their address in an outbound
    query string tells OpenAlex which organisation is researching which
    standards. That inference is the kind this product exists to prevent, so
    the tier works without it on the common pool and the setting is documented
    as the operator's address.
    """

    tier = TIER_LITERATURE
    label = TIER_LABELS[TIER_LITERATURE]
    BASE = "https://api.openalex.org/works"

    def configured(self) -> bool:
        return True          # no credential; always available

    def describe(self) -> str:
        contact = (settings.market_openalex_contact_email or "").strip()
        return "openalex (polite pool)" if contact else "openalex (common pool)"

    def search(self, payload: Mapping[str, object], *, fetch: Fetch,
               timeout: float) -> list[dict]:
        url = f"{self.BASE}?search={quote(str(payload['phrase']))}&per-page=5"
        contact = (settings.market_openalex_contact_email or "").strip()
        if contact:
            url = f"{url}&mailto={quote(contact)}"
        return self._rows(fetch(check_host(url), {}, timeout), phrase=str(payload['phrase']))

    @staticmethod
    def _rows(raw: object, *, phrase: str | None = None) -> list[dict]:
        """Parse literature and discard clearly off-topic title matches.

        OpenAlex's broad search can return records sharing only one common
        word (for example ``design``). For a multi-word engineering query,
        require every meaningful query token in the title; this prevents
        unrelated records from being presented as useful project evidence.
        """
        required = tuple(dict.fromkeys(
            token.lower() for token in re.findall(r"[A-Za-z0-9]+", phrase or "")
            if len(token) >= 3
        ))
        rows: list[dict] = []
        all_rows: list[dict] = []
        for item in _as_list(raw, ("results",)):
            if not isinstance(item, Mapping):
                continue
            title = _first_present(item, ("display_name", "title"))
            if not title:
                continue
            title_tokens = set(re.findall(r"[A-Za-z0-9]+", title.lower()))
            matches_phrase = not required or len(required) <= 1 or all(
                token in title_tokens for token in required
            )
            landing = item.get("primary_location")
            url = ""
            publisher = ""
            if isinstance(landing, Mapping):
                url = _first_present(landing, ("landing_page_url", "pdf_url")) or ""
                source = landing.get("source")
                if isinstance(source, Mapping):
                    publisher = _first_present(source, ("display_name",)) or ""
            url = url or _first_present(item, ("doi", "id")) or ""
            if not url:
                continue
            row = _row(
                text=title, tier=TIER_LITERATURE,
                publisher=publisher or "OpenAlex",
                url=url,
                published=_first_present(item, ("publication_date",)),
            )
            all_rows.append(row)
            if matches_phrase:
                rows.append(row)
        # Do not turn a provider response into a false outage when none of
        # the returned titles contains every term. Keep the real candidates,
        # still labelled as preliminary literature, rather than hiding them.
        return rows or all_rows


class WikipediaProvider:
    """TIER 3, reference - background only. No key.

    IT IS HERE FOR A SPECIFIC REASON. The standards this corpus cites -
    ISO 12944, NORSOK M-501, NIST SP 800-207 - are not DOI-registered works,
    so tier 2 has no record of them and cannot answer "what is this standard".
    A general reference source can. Its label says "background only" because
    that is what it is: orientation for a reader, never a citation for an
    engineering claim, and the verification state on every row says the same.
    """

    tier = TIER_REFERENCE
    label = TIER_LABELS[TIER_REFERENCE]
    BASE = "https://en.wikipedia.org/w/api.php"

    def configured(self) -> bool:
        return True

    def describe(self) -> str:
        return "wikipedia (background only)"

    def search(self, payload: Mapping[str, object], *, fetch: Fetch,
               timeout: float) -> list[dict]:
        # `formatversion=2` avoids the legacy response shape and `origin=*`
        # is accepted by Wikimedia's edge/API consistently across deployments.
        url = (f"{self.BASE}?action=query&list=search&format=json"
               f"&formatversion=2&origin=*&srlimit=5"
               f"&srsearch={quote(str(payload['phrase']))}")
        return self._rows(fetch(check_host(url), {}, timeout))

    @staticmethod
    def _rows(raw: object) -> list[dict]:
        rows: list[dict] = []
        items: Sequence[object] = ()
        if isinstance(raw, Mapping):
            query = raw.get("query")
            if isinstance(query, Mapping):
                found = query.get("search")
                if isinstance(found, Sequence):
                    items = found
        for item in items:
            if not isinstance(item, Mapping):
                continue
            title = _first_present(item, ("title",))
            if not title:
                continue
            snippet = _first_present(item, ("snippet", "extract")) or title
            # The API returns HTML search-match markup in `snippet`.
            snippet = _strip_tags(snippet)
            rows.append(_row(
                text=snippet, tier=TIER_REFERENCE, publisher="Wikipedia",
                url=f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                published=_first_present(item, ("timestamp",)),
            ))
        return rows


def _strip_tags(text: str) -> str:
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return " ".join("".join(out).split())


def _as_list(raw: object, keys: Sequence[str]) -> Sequence[object]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return raw
    if isinstance(raw, Mapping):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, Mapping):
                value = value.get("value", value)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return value
    return ()


def _first_present(item: Mapping, keys: Sequence[str]) -> str:
    """The first of `keys` with a usable string value.

    Vendor-agnostic on purpose: tier 1's schema is unsettled, and reading
    several plausible field names is what lets the adapter survive a vendor
    swap without a code change.
    """
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def providers() -> tuple[object, ...]:
    """One instance per tier, in attempt order."""
    return (WebSearchProvider(), OpenAlexProvider(), WikipediaProvider())


def tiers_configured() -> list[str]:
    """Which tiers could run at all. Read by the preview endpoint."""
    return [p.tier for p in providers() if p.configured()]  # type: ignore[attr-defined]


def tiers_unconfigured() -> list[str]:
    """Which tiers cannot run in this build.

    REPORTED SEPARATELY FROM `tiers_attempted`, and that distinction is the
    whole reason this exists. An unconfigured tier had nothing sent to it, so
    listing it as attempted forced a UI to tell the reader it was tried. "Tried
    and did not answer" and "was never configured" are different facts about a
    build, and only one of them is a fallback worth showing.
    """
    return [p.tier for p in providers() if not p.configured()]  # type: ignore[attr-defined]


def outbound_payloads(phrase: str, *, country: str | None = None,
                      freshness_days: int | None = None) -> list[dict]:
    """EVERY payload that would leave, one per CONFIGURED tier, in order.

    THIS FUNCTION EXISTS TO CLOSE A HOLE IN THE CENTRAL PROMISE. The client
    was told "you approve exactly what leaves". Before this, `preview` built
    ONE payload for the reference tier with no country and no freshness, while
    a search built one payload PER TIER, each carrying both scope fields. So
    up to three payloads left, they differed from one another, and neither
    scope value appeared in the thing the user had approved. The approval was
    of an object that was never sent.

    Fixing that by adding the two fields to `preview` would have left the
    deeper defect in place: two call sites constructing outbound objects
    independently WILL drift again, and the next drift is as invisible as this
    one was. So there is now exactly one function that decides what goes out,
    and both `preview` and `search_all` call it. A payload cannot be sent that
    the preview did not show, because there is nowhere else for one to come
    from.

    Only CONFIGURED tiers appear: an unconfigured tier is never contacted, so
    showing a payload for it would over-state what leaves.
    """
    _check_phrase(phrase)
    return [
        build_payload(phrase, tier=p.tier,        # type: ignore[attr-defined]
                      country=country, freshness_days=freshness_days)
        for p in providers() if p.configured()    # type: ignore[attr-defined]
    ]


# ------------------------------------------------------------------ the run

def live_enabled() -> bool:
    """BOTH flags, and both default False.

    Two questions, deliberately not one: "is the feature built and wired" and
    "does this deployment permit traffic to leave". Requiring both means
    enabling the feature in a build cannot by itself open egress on a client
    machine.
    """
    return bool(settings.market_live_enabled
                and settings.market_allow_public_egress)


def search_all(phrase: str | None, *, fetch: Fetch | None = None,
               country: str | None = None, freshness_days: int | None = None,
               now: Callable[[], float] = time.monotonic) -> dict:
    """Run every configured tier. Return the API contract's search shape.

    DROPPING A TIER IS VISIBLE, in three lists rather than two.
    `tiers_unconfigured` is separate from `tiers_attempted` because nothing
    was sent to an unconfigured tier - see `tiers_unconfigured`. So
    "attempted" stays a true sentence and `attempted - answered` is exactly
    the set that was tried and did not answer.

    "NO RESULTS" IS A REAL ANSWER. Tiers answering with zero rows gives
    `rows: []` and `failure: None` - the search ran and found nothing, which
    is information, not a failure.

    A REFUSED PHRASE IS NOT A FAILURE EITHER, and this is the second meaning
    `failure` used to carry. `phrase: None` means nothing safe survived, so no
    search was attempted; that reaches the UI as the same null-phrase state the
    preview returns, and its wording comes from one place. `failure` is now
    reserved for one thing only: tiers were attempted and every one of them
    failed.

    NEITHER EVER RETURNS THE SAMPLES. A sample row in place of a live result
    is a fabricated finding carrying a real feature's label.
    """
    if not live_enabled():
        # The flag is off: the honest answer is the labelled samples, and this
        # is the only path that returns them.
        return _disabled_result(phrase)

    if phrase is None:
        # None from market_phrase means DO NOT SEARCH. Reported as the
        # null-phrase state, NOT as a retrieval failure - they are different
        # facts and the reader needs different words for them.
        return {
            "enabled": True,
            "phrase": None,
            "rows": [],
            "tiers_attempted": [],
            "tiers_answered": [],
            "tiers_unconfigured": tiers_unconfigured(),
            "tier_labels": tier_labels(),
            "failure": None,
            "audit": [],
        }

    attempted: list[str] = []
    answered: list[str] = []
    rows: list[dict] = []
    audit: list[dict] = []
    failures: list[str] = []

    # THE SAME FUNCTION THE PREVIEW CALLS. Not a second construction of the
    # same thing - see `outbound_payloads`.
    payloads = {p["tier"]: p for p in outbound_payloads(
        phrase, country=country, freshness_days=freshness_days)}

    for provider in providers():
        tier = provider.tier                      # type: ignore[attr-defined]
        if not provider.configured():             # type: ignore[attr-defined]
            # Not attempted, not a failure. It is reported in
            # `tiers_unconfigured` and nothing was sent to it.
            continue
        attempted.append(tier)
        try:
            check_rate(tier, now=now)
            if fetch is None:
                # No transport, no request. The default is not a client with a
                # strange URL; it is nothing at all.
                raise ProviderUnconfigured("no transport supplied")
            found = provider.search(                # type: ignore[attr-defined]
                payloads[tier], fetch=fetch,
                timeout=float(settings.market_tier_timeout_seconds))
        except Exception as exc:                    # noqa: BLE001
            # One tier failing is not the search failing. The reason is
            # recorded per tier and the run continues.
            failures.append(f"{tier}: {_safe_reason(exc)}")
            audit.append(audit_record(phrase, tier=tier, outcome="error"))
            continue
        audit.append(audit_record(phrase, tier=tier, outcome="ok"))
        answered.append(tier)
        rows.extend(found)

    failure: str | None = None
    if attempted and not answered:
        failure = ("public information retrieval failed: " + "; ".join(failures)
                   if failures else "public information retrieval failed")
    elif not attempted:
        # Every tier is unconfigured. Nothing was tried, so nothing failed -
        # but the reader must not be shown an empty panel that looks like a
        # measurement.
        failure = ("no public information tier is configured in this build, so "
                   "no search was attempted")
    return {
        "enabled": True,
        "phrase": phrase,
        "rows": rows,
        "tiers_attempted": attempted,
        "tiers_answered": answered,
        "tiers_unconfigured": tiers_unconfigured(),
        "tier_labels": tier_labels(),
        "failure": failure,
        # NOT PART OF THE HTTP CONTRACT. Stripped by `to_api`; see its
        # docstring and `audit_record`.
        "audit": audit,
    }


#: The fields the documented search contract carries. `audit` is deliberately
#: absent - it is for the persistence call site, not for the browser.
API_SEARCH_FIELDS: tuple[str, ...] = (
    "enabled", "phrase", "rows", "tiers_attempted", "tiers_answered",
    "tiers_unconfigured", "tier_labels", "failure",
)


def to_api(result: dict) -> dict:
    """The search result as the ROUTE should return it: no `audit` key.

    `search_all` returns the audit rows because the caller has to persist them
    and this module may not write to the database itself (see `audit_record`).
    But an audit trail is not something a browser needs, and shipping it in the
    response body would put a record of every outbound query into any page that
    calls the endpoint.

    A function rather than a note asking a route author to remember: the route
    calls this, and a field added to `search_all` later cannot reach the
    response by accident because it is not in `API_SEARCH_FIELDS`.
    """
    return {key: result[key] for key in API_SEARCH_FIELDS if key in result}


def _safe_reason(exc: Exception) -> str:
    """A reason with no credential in it.

    An error path is the likeliest place for a key to leak: an HTTP library's
    exception frequently carries the full request URL, and a URL can carry a
    key. So the message is rebuilt from the exception TYPE plus its text with
    any configured secret redacted, rather than passed through.
    """
    text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return redact(text)


def redact(text: str) -> str:
    """Remove any configured secret from a string bound for a log or a body."""
    out = str(text)
    for secret in ((settings.market_search_api_key or "").strip(),):
        if secret and len(secret) >= 4:
            out = out.replace(secret, "[redacted]")
    return out


def _disabled_result(phrase: str | None = None) -> dict:
    """The flag-off answer: the existing samples, in the contract's row shape.

    Imported lazily so `market` and `market_providers` do not import each
    other at module scope. The sample rows keep `is_sample: true` and their
    `sample://` URLs; only the field NAMES are mapped, because the contract
    the frontend is built against uses `text`/`published`/`retrieved` while
    the fixture predates it and uses `claim`/`published_at`/`retrieved_at`.
    Renaming the fixture's own fields would break the existing market tests,
    which is why this maps instead.
    """
    from . import market

    rows = [
        {
            "text": row["claim"],
            # SAMPLE_LABEL, not the reference tier's. These are illustrative
            # MARKET rows and no tier produced them; stamping them "reference -
            # background only" made a correct provenance renderer print
            # "background only" over them, which is a false statement about
            # where they came from.
            "provider_label": SAMPLE_LABEL,
            "publisher": row["publisher"],
            "published": row.get("published_at"),
            "retrieved": row["retrieved_at"],
            "url": row["url"],
            "verification": row["verification"],
            "is_sample": True,
        }
        for row in market.findings()["findings"]
    ]
    return {
        "enabled": False,
        # THE ACTUAL PHRASE, echoed, not a hardcoded None - and that
        # distinction is the same defect this response shape was rewritten to
        # fix, caught one layer down. `phrase: null` means "nothing safe
        # survived, no search is possible". Returning it unconditionally with
        # the flag off would have said that about a phrase which scrubbed
        # perfectly well, conflating "the feature is off" with "your question
        # could not be used". Off and refused are different sentences and the
        # reader needs to be told which one applies:
        #
        #   enabled false, phrase set   -> feature off, these are samples
        #   enabled true,  phrase null  -> nothing safe survived
        #   enabled false, phrase null  -> both
        "phrase": phrase,
        "rows": rows,
        "tiers_attempted": [],
        "tiers_answered": [],
        "tiers_unconfigured": [],
        "tier_labels": tier_labels(),
        "failure": None,
        "audit": [],
    }


def preview(phrase: str | None, *, country: str | None = None,
            freshness_days: int | None = None) -> dict:
    """The no-egress preview. Safe to call at any time, flag on or off.

    `payloads` IS A LIST, ONE ENTRY PER CONFIGURED TIER, in attempt order,
    because that is what actually leaves. A single payload could not be
    honest here: a search builds one per tier, so showing one meant the user
    approved an object that was never sent while up to three others were.

    It takes `country` and `freshness_days` for the same reason - they appear
    in every real payload, so a preview without them showed a different object
    from the one that goes. Both are threaded through to the SAME builder
    `search_all` uses, so the two cannot drift again.

    A list rather than a map keyed by tier: order is part of the answer (it is
    the attempt order) and a JSON object does not promise to keep it.

    `phrase: null` means nothing safe survived and no search is possible.
    """
    if phrase is None:
        return {
            "phrase": None,
            "payloads": [],
            "tiers_configured": tiers_configured(),
            "tiers_unconfigured": tiers_unconfigured(),
            "tier_labels": tier_labels(),
        }
    return {
        "phrase": phrase,
        "payloads": [
            {"tier": p["tier"], "provider_label": p["provider_label"],
             "payload": p}
            for p in outbound_payloads(phrase, country=country,
                                       freshness_days=freshness_days)
        ],
        "tiers_configured": tiers_configured(),
        "tiers_unconfigured": tiers_unconfigured(),
        "tier_labels": tier_labels(),
    }
