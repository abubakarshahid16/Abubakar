# Egress review — the market lane

**Static review only.** Nothing was executed: no test was run, no request was made, no
mutation was proven. Every claim below is from reading the source on the user's machine
(`Rag_chatbot`, working tree as of 2026-09-08). Where I say a test "would still pass", that is
read off the assertion, not observed.

Boundary of this review: `backend/app/market_phrase.py`, `market_providers.py`,
`market_transport.py`, `market.py`, the market block of `config.py`, the `/api/market/*` routes
in `main.py`, the market schemas, all six `backend/tests/test_market*.py`,
`frontend/src/components/analysis/MarketPanel.tsx` and `MarketPanel.test.tsx`. I also traced
outbound clients across the whole of `backend/app/` (finding 2) because socket containment
cannot be judged inside four files.

**Counts:** 5 high, 6 medium, 4 low. No critical.

---

## 1. HIGH — the product tells the client the machine is offline, in five places, including with egress on

**file:line** `frontend/src/components/analysis/MarketPanel.tsx:96`, `backend/app/market.py:54`,
`backend/app/analysis.py:46`, `backend/app/schemas.py:869`,
`frontend/src/views/AnalysisModeScreen.tsx:1543`

**What is wrong** Shipped user-visible copy asserts "This machine is offline" — a claim
ADR-0002 explicitly forbids — and it is a fixed literal that keeps saying so when both egress
flags are true.

```tsx
const SAMPLE_BANNER_TAIL =
  "This machine is offline. Every row below is an illustrative sample and must not be described as live market data.";
```
```python
NOTICE = (
    "SAMPLE DATA - NOT LIVE. This machine is offline. Every row is an "
```
```python
    "public market research (this machine is offline; the panel shows a "
    "labelled sample)",
```

**The failure** ADR-0002: *"This is a locally-inferencing system on a networked machine. It is
not an air-gapped system. The client must never be told otherwise. Describing this as
air-gapped would be a false security claim."* The banner is a false security claim about the
one property the product is sold on. It is worse than stale: `MarketPanel` renders
`SampleBanner()` in the `search.s === "idle"` state unconditionally, so on a machine with
`market_live_enabled=true` and `market_allow_public_egress=true` — a build that will make
outbound calls the moment the reader presses Confirm — the screen still reads "SAMPLE DATA —
NOT LIVE. This machine is offline." `/api/market/findings` sends the same sentence in
`notice`, and `/api/analysis/...` sends it in `NOT_IMPLEMENTED` where market research is
described as unavailable "because this machine is offline". This is exactly the shape
`egress_state()` was fixed for — a privacy claim restated as a literal instead of derived from
the flags — reintroduced one layer out, in the sentence a client reads.

**Smallest fix** Derive the tail from `egress`: with either flag off say "web search is off in
this build" / "public egress is blocked in this build"; with both on and `enabled:false`
impossible, say "these are illustrative samples". Delete the word "offline" from all five
sites. `MarketPanel.test.tsx:612` and `test_market.py:196` pin the current string and must be
updated with it.

---

## 2. HIGH — socket containment is enforced over four hand-listed files, and the largest outbound lane is outside all of them

**file:line** `backend/tests/test_market_no_document_leak.py:57`,
`backend/app/config.py:106`, `backend/app/analysis.py:666-667`, `backend/app/answer.py:403`,
`backend/app/metrics.py:270`

**What is wrong** The AST guard iterates a hardcoded tuple of three filenames plus the
transport, so it cannot see a market module added tomorrow, and no test anywhere asserts that
`market_transport.py` is the only module in the application that can open a socket — three
others hold an `httpx.Client` pointed at an operator-settable URL with no host check.

```python
MARKET_MODULES = ("market.py", "market_phrase.py", "market_providers.py")
```
```python
    ollama_url: str = "http://127.0.0.1:11434"
```
```python
    with httpx.Client(timeout=180.0) as client:
        response = client.post(f"{settings.ollama_url}/api/generate", json=body)
```

**The failure** Two concrete failures. (a) `market_scoring.py` added next week is covered by
nothing: `test_market_modules_import_no_http_client` and
`test_the_transport_is_the_only_module_here_with_a_client` both parametrise over the tuple
above, so a new file importing `httpx` and `from . import search` passes the whole suite
green. (b) `settings.ollama_url` is a `BaseSettings` field, so `OLLAMA_URL` in the environment
or in `backend/.env` redirects it. `analysis.py:667` POSTs `{"prompt": ...}` built from the
question **and the retrieved passages** to `{ollama_url}/api/generate`. Setting
`OLLAMA_URL=http://collector.example.net:11434` sends the client's document text, verbatim, to
that host — no allowlist, no both-flags gate, no audit row, no preview, and no test would
notice (`test_metrics.py:188` is the only test that touches the setting and it only points it
at a dead port). The market lane is the reviewed, gated, audited lane; the ungated lane
carrying actual passages is the model call.

**Smallest fix** (a) Build the module list by globbing `APP.glob("market*.py")` and assert the
glob found at least the four known names, so a new file is covered by default and a renamed
one fails loudly. (b) Add a startup guard that refuses a non-loopback `ollama_url` unless an
explicit `allow_remote_inference` flag is set, and a test that asserts the refusal — a remote
inference host is the ADR's forbidden "hosted inference API", reachable today by one
environment variable.

---

## 3. HIGH — the last gate before the socket checks a host it parses by hand, and a URL can lie to it

**file:line** `backend/app/market_providers.py:282-303`

**What is wrong** `check_host` extracts the host with string splits rather than a URL parser,
so a URL whose authority contains `?` or `#` before an `@` is approved under an allowlisted
host and then requested against a different one.

```python
def _host_of(url: str) -> str:
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].split("@")[-1].split(":", 1)[0].lower()
```

**The failure** With `market_search_endpoint = "https://evil.test?@api.openalex.org/search"`
(or `...#@api.openalex.org/...`), `_host_of` returns `api.openalex.org` — the `?` is not a
delimiter it knows, and `split("@")[-1]` then hands back the decoy tail. Both gate 2 in
`market_transport._fetch` and the provider's own `check_host(endpoint)` pass, and
`httpx.Client.get` requests `evil.test` with the phrase in the query string and
`Authorization: Bearer <key>` in the header. So the code-level allowlist — described in
`config.py` as the thing that "makes an accident loud" — can be silently satisfied by a single
mistyped or malicious config value, and both the key and the phrase leave to an unlisted host.
`test_a_host_outside_the_allowlist_never_reaches_the_client` uses a plain `https://evil.test/`
and would still pass; nothing in the suite feeds `check_host` a URL whose parse is ambiguous.

**Smallest fix** `host = (httpx.URL(url).host or "").lower()` inside the transport (which
already imports httpx), and have `check_host` take the parsed host rather than re-splitting a
string; add the `?@` and `#@` forms as test cases.

---

## 4. HIGH — the previewed payload is not what leaves: an operator email is added, and two approved fields are never sent

**file:line** `backend/app/market_providers.py:477-480`, `:536`, `:497`,
`frontend/src/components/analysis/MarketPanel.tsx:472`

**What is wrong** The approval dialog shows the five-field payload dict, while the bytes that
leave are a URL built from `payload["phrase"]` only — plus `mailto=<operator email>`,
`per-page` and `srlimit` that the preview never shows — and the payload's `country` and
`freshness_days` are shown as leaving when no provider ever sends them.

```python
        url = f"{self.BASE}?search={quote(str(payload['phrase']))}&per-page=5"
        contact = (settings.market_openalex_contact_email or "").strip()
        if contact:
            url = f"{url}&mailto={quote(contact)}"
```
```tsx
          This is the exact text that would leave the machine. Nothing else.
```

**The failure** With `market_openalex_contact_email` set, the reader approves
`{"phrase": "iso 12944", "tier": "literature", ..., "country": "NO", "freshness_days": 90}`
and what leaves is
`https://api.openalex.org/works?search=iso%2012944&per-page=5&mailto=ops@…` — an email address
that appeared nowhere in the approval, and no `country` or `freshness_days` at all. Both
directions are false: an identity field leaves unapproved (the exact disclosure
`config.py:414`'s comment says the empty default exists to prevent, now silently
re-enabled by one setting), and the dialog claims two scope fields leave that do not, which is
the same defect class as the shipped preview that omitted them — inverted. `outbound_payloads`
closes the drift between *preview* and *search* but neither is compared against the URL the
provider actually builds, so no test covers this:
`test_a_full_search_over_the_recorded_responses:218-222` asserts the phrase is in each URL and
never asserts what else is.

**Smallest fix** Make the provider build its URL only from fields in
`ALLOWED_PAYLOAD_FIELDS` — put the contact email into the `payload` (so it is previewed and
audited) or drop the polite pool — and add a test that, for every tier, the set of query
parameters in the built URL is exactly derivable from the previewed payload. Until
`country`/`freshness_days` are actually sent, remove them from the payload rather than
displaying them as outbound.

---

## 5. HIGH — the "whitelist" is a character class, not a vocabulary, so the identifiers its docstring promises to drop leave intact

**file:line** `backend/app/market_phrase.py:137`, docstring `:20-27`

**What is wrong** A token is admitted for being three-or-more ASCII letters, not for being a
known-safe word, so any letters-only internal identifier passes — while the module's own
docstring names those identifiers as the thing a blacklist would leak and a whitelist would
not.

```python
_SUBJECT_WORD = re.compile(r"^[a-z]{3,}$")
```
> a document title typed without its extension, a project code, **a client's internal name for
> a facility**, a rev number in a format we did not pattern-match, an equipment tag, **a
> person's name**. Every one of those reaches the network

**The failure** Type `Khursaniyah tie-in corrosion` and the phrase is
`khursaniyah tie corrosion`; type `what did Al-Mansouri approve` and `mansouri` leaves (the
letter-hyphen-letter split at `_tokenise` breaks the surname into passing tokens); a
letters-only project or facility codename (`NABAA`, `ZULU`, `SEAHORSE`) leaves verbatim. All
of these are corpus/organisation metadata by the file's own definition, and the fail-closed
argument holds only for tokens carrying digits or non-ASCII. It is invisible in the tests
because every fixture identifier has a digit in it — `IDENTIFIERS = ("PRJ-4471-B",
"21-PV-1043A", "WO-99812", "1234567890", "A-123-XYZ", "4471", "1043a")` — and the strict
assertion in `test_an_identifier_is_dropped_even_when_the_question_has_a_real_subject:191` is
literally *"no digit-bearing token"*. A letters-only identifier would pass every test in
`test_market_phrase.py` and `test_market_no_document_leak.py`.

**Smallest fix** Either honour the docstring — check surviving subject words against a bundled
common-English word list, dropping unknown ones — or, if that is judged too blunt, rewrite the
docstring's claim: say plainly that any letters-only token survives and that the preview is the
only control over a letters-only internal name. Add a test with a letters-only codename so the
chosen answer is pinned. (Related and correct: unicode look-alikes fail closed here —
`[a-z]` is ASCII-only, so a Cyrillic homoglyph is dropped, not passed.)

---

## 6. MEDIUM — the search route's docstring says it cannot open a socket, three lines above the line that opens one

**file:line** `backend/app/main.py:982-985`, contradicted by `:1010-1011`; also `:874`

```python
    `fetch` is left unset deliberately, so this route cannot open a socket in
    this build even with both flags on: `search_all` refuses with "no
    transport supplied" and reports a failure.
```
```python
    result = market_providers_mod.search_all(
        safe, fetch=market_transport_mod.transport(),
```

**What is wrong** A comment records a false reason for the current code: the transport is now
wired, so with both flags on this route does open a socket.

**The failure** A reviewer reading the route — the review path this project mandates — is told
the route is inert, and reasons about the change in front of them on that basis. The section
header at `:874` compounds it: "No network call exists in this build. Both routes are scoped"
sits above four routes, one of which calls out. Audit entry 15 is exactly this: a justification
adjacent to the truth, later cited as a verified property.

**Smallest fix** Replace both comments with what is true: the transport is wired and
`transport()` returns `None` unless both flags are set, so the off state is the absence of a
client.

---

## 7. MEDIUM — `preview_query` states the egress posture as a literal, and its test pins the literal

**file:line** `backend/app/market.py:175-180`; test `backend/tests/test_market.py:146-151`

```python
        "reason": (
            "Public egress is disabled in this build. This is what would be "
            "sent if it were enabled; nothing left this machine."
        ),
```
```python
def test_the_preview_is_never_sent_and_says_so():
    p = market.preview_query("offshore coating cost per square metre", "SA", 365)
    assert p["sent"] is False
    ...
    assert "nothing left this machine" in p["reason"]
```

**What is wrong** `/api/market/preview-query` asserts "Public egress is disabled in this build"
regardless of the two flags that decide it.

**The failure** With both flags on, this route returns a body telling the caller egress is
disabled while `/api/market/search` will make outbound calls — the identical defect
`egress_state()` was rewritten to remove, in the same module, one function below the docstring
that describes that fix. The `sent: False` and `would_be_sent_to: None` halves are true (this
route sends nothing); only the posture sentence is false. The test asserts the substring, so it
passes in every flag state and would not catch the change.

**Smallest fix** Build `reason` from `egress_state()`; parametrise the test over all four flag
combinations as `test_the_banner_tracks_both_flags_in_both_directions` already does.

---

## 8. MEDIUM — `tiers_attempted` and the audit row are derived from entering the loop, not from a request being made

**file:line** `backend/app/market_providers.py:736`, `:742-753`;
`backend/app/schemas.py:1030`

```python
        attempted.append(tier)
        try:
            check_rate(tier, now=now)
            if fetch is None:
                raise ProviderUnconfigured("no transport supplied")
```
```python
        description="tiers actually CONTACTED. Never includes an unconfigured "
```

**What is wrong** A tier is recorded as attempted, and an audit row with
`action="market.outbound_query"` is written, in cases where nothing was sent.

**The failure** Three reachable states produce a false record: no transport (flags on, wiring
absent), rate-limited (second click inside `market_tier_min_interval_seconds`), and a refused
host (`HostNotAllowed` from `check_host`). In each, `tiers_attempted` reports the tier as
"actually CONTACTED" — the panel prints "Tiers attempted: literature, reference" — and
`audit_events` gains a row saying an outbound query for that phrase occurred, outcome `error`,
indistinguishable from a request that left and failed. So the table that exists to answer "what
exactly left this machine" over-reports, and a reviewer counting outbound queries counts
refusals. `test_a_failed_tier_is_audited_as_an_error_not_omitted` asserts two error rows from an
HTTP 500 and would pass unchanged if every refusal also wrote one.

**Smallest fix** Move `attempted.append(tier)` and the audit row to after the point of no
return — inside the provider, immediately before `fetch(...)`, or by having the transport signal
back — and give pre-flight refusals a distinct outcome (`refused`) or no row at all. The gap
`main.py:920-923` already admits (rows written after the call, so a crash between loses one)
stays; a write-ahead row with a completion update would close both at once.

---

## 9. MEDIUM — Confirm is gated on one of the two flags that gate the request

**file:line** `frontend/src/components/analysis/MarketPanel.tsx:410`, `:551-556`

```tsx
  const blocked = egress.allow_public_egress === false;
```

**What is wrong** The dialog's block state and its only blocked sentence read
`allow_public_egress` alone, while the backend requires
`market_live_enabled AND market_allow_public_egress`.

**The failure** In the real state `(web_search_enabled=false, allow_public_egress=true)` — one
of the four the backend's own test insists is meaningful — the dialog shows no notice, Confirm
is live and titled as sendable, and pressing it returns `enabled:false` and sample rows under
"SAMPLE DATA — NOT LIVE. This machine is offline." The reader is offered a send that cannot
happen and is then shown fixtures as the outcome of pressing it. `MarketPanel.test.tsx:671`
tests only `OFFLINE` (both false), so the one-flag derivation is not covered.

**Smallest fix** `const blocked = egress.allow_public_egress === false || egress.web_search_enabled === false;`
with a separate sentence for the web-search-off case, and a test for each of the four
combinations.

---

## 10. MEDIUM — the quoted-span guard has a silent 400-character ceiling and needs a closing quote

**file:line** `backend/app/market_phrase.py:84-88`

```python
_QUOTED = re.compile(
    r"""["'‘’“”«»]"""      # opening
    r"""[^"'‘’“”«»]{0,400}"""
    r"""["'‘’“”«»]"""      # closing
)
```

**What is wrong** The control that treats a quotation as document text stops applying above 400
characters between the marks, or when the paste carries only an opening mark.

**The failure** A user pastes a 600-character clause between quotes — the ordinary shape of
"is this normal:" followed by a pasted paragraph. No span is removed, the text falls through to
the token whitelist, and up to twelve of its ordinary subject words leave in document order;
`nominal dry film thickness` and similar contiguous runs survive as document four-grams. The
same paste at 300 characters yields nothing. The only test of this control,
`test_words_inside_a_quotation_never_reach_a_payload`, uses a seven-word quotation and cannot
reach either edge. The leak test's n-gram net does not compensate: its own docstring at
`:324-333` records that an unstripped quotation does **not** produce a matching four-gram once
the whitelist has thinned it, which is why this property is asserted directly — and the direct
assertion is the one with the narrow fixture.

**Smallest fix** Make the body `{0,4000}` (or unbounded with a non-greedy match), and treat a
lone opening mark as opening a span that runs to end of input. Add fixtures at 401 and 4001
characters and one with a single opening quote.

---

## 11. MEDIUM — the filename strip list is scope-bound, so a caller can send the name of a document they were not granted

**file:line** `backend/app/main.py:970-971`, `:1002-1003`;
`backend/app/analysis.py:137-145`

```python
    safe = market_phrase_mod.market_phrase(
        phrase, analysis_mod._corpus_filenames(scope))
```

**What is wrong** Filenames are removed only for documents in the caller's own scope, so a
filename outside it is not on the strip list and (per finding 5) leaves intact if it is made of
letters.

**The failure** A user granted nothing types `Khursaniyah Gas Plant Spec` — a filename they
know from a meeting and are not granted — and it leaves as `khursaniyah gas plant spec` to
OpenAlex and Wikipedia. The docstring's reason, *"a name they cannot see is not a name they can
ask about"*, is the false step: they can type anything. It also makes the guard's strength vary
by grant, so the same question leaks for one user and not another. (The `doc\d+` shapes are
still caught by `_REFERENCES` regardless of scope, which is why the existing tests do not see
this.)

**Smallest fix** Scrub against every filename in the corpus — the strip list never leaves the
machine and is not returned to the caller, so using the unscoped list discloses nothing while
scoping it creates the hole. If enumeration of the list is the worry, hash-compare tokens
rather than shrinking the list.

---

## 12. LOW — a null publication date renders as an em dash on the fixture row

**file:line** `frontend/src/components/analysis/MarketPanel.tsx:200`

```tsx
        <dd className="text-slateish-300">{f.published_at ?? "—"}</dd>
```

**What is wrong** `FindingRow` prints a dash for a null date, against Rule 1 ("Null renders as
nothing… never as a dash that reads like a measurement") and against this file's own docstring
("NULLS RENDER AS NOTHING… not a dash").

**The failure** The shipped fixture's second row has `published_at: null`, so the panel's
default state shows a dash under "published" — a reader takes it as "reported and withheld"
rather than "no date". `SearchRow:245-252` does it correctly, and the test that pins the
behaviour (`MarketPanel.test.tsx:462`) is scoped to a search row, so the dash on the fixture row
is asserted by nothing.

**Smallest fix** Withhold the `<dt>`/`<dd>` pair when `published_at === null`, as `SearchRow`
does; extend the null-date test to the `findings` prop.

---

## 13. LOW — the token cap truncates where the payload builder refuses, and the loop's own cap is unreachable

**file:line** `backend/app/market_phrase.py:280`, `:286`

```python
        if len(kept) >= MAX_TOKENS:
            break
```
```python
    phrase = " ".join(kept[:MAX_TOKENS])[:MAX_PHRASE_CHARS].strip()
```

**What is wrong** Every accepting branch above `continue`s, so the `break` is only reached by a
*dropped* token and can never stop an accumulating phrase — dead code that reads as the cap.
The real cap is the slice, and the `[:MAX_PHRASE_CHARS]` half truncates mid-token where
`market_providers._check_phrase` explicitly refuses rather than truncating.

**The failure** Twelve long tokens (e.g. hyphen-split compounds) exceed 200 characters and the
phrase ends in a fragment of a word, which is then sent and audited as the approved phrase. No
correctness break — the reader still previews the fragment — but the two modules state opposite
policies for the same limit.

**Smallest fix** Delete the unreachable `break` (or hoist the check to the top of the loop), and
drop whole tokens until the phrase fits rather than slicing characters.

---

## 14. LOW — redaction covers one secret, and the literal scan covers three of four files

**file:line** `backend/app/market_providers.py:815-821`,
`backend/tests/test_market_secret_hygiene.py:63`

```python
    for secret in ((settings.market_search_api_key or "").strip(),):
        if secret and len(secret) >= 4:
            out = out.replace(secret, "[redacted]")
```

**What is wrong** `redact()` removes only the tier-1 key, and only if it is four characters or
longer; the credential-shaped-literal scan iterates `OWNED_APP_FILES`, which omits
`market_transport.py`.

**The failure** `market_openalex_contact_email` is interpolated into a URL
(`market_providers.py:480`) and is therefore in exactly the exception text `_safe_reason`
exists to sanitise, so a failing OpenAlex call can put the operator's address into a
`failure` string and a log line. A three-character key is passed through unredacted. And a
key pasted into `market_transport.py` — the file that holds the client and is the natural place
to "just try a header" — is scanned by nothing in this suite.

**Smallest fix** Add the contact email to `redact`'s tuple, drop the `>= 4` floor to `>= 1`,
and add `market_transport.py` to `OWNED_APP_FILES`.

**No API key was found in the tree.** `market_search_api_key` defaults to `""` in
`config.py:392`; the only key-shaped string in the market tests is the deliberately
non-credential-shaped sentinel at `test_market_secret_hygiene.py:60`. I did not open
`backend/.env` (it is not in the working tree listing and reading it is not needed for this
review); if a real key is present there it should be confirmed gitignored and rotated on
suspicion, not quoted anywhere.

---

## 15. LOW — "from `.env` and from nowhere else" is not what `BaseSettings` does

**file:line** `backend/app/config.py:344-349`

```python
    #: FROM `.env` AND FROM NOWHERE ELSE, for the same reason as
    #: `watch_owner_email`: a request that could set this could turn on
    #: outbound network access for the process holding the client's corpus.
    market_live_enabled: bool = False
```

**What is wrong** `Settings` is a `pydantic_settings.BaseSettings`, which reads process
environment variables ahead of the `.env` file, so `MARKET_LIVE_ENABLED=1` in the environment
also sets it.

**The failure** The property the comment is defending — no caller can set it through a request —
holds. The stated mechanism does not, and a reader auditing "where can egress be switched on"
from this comment would not check the service's environment or launch script.

**Smallest fix** Reword to "from the environment or `backend/.env`, never from a request".

---

# Verified clean

Each item names the guarantee and the assertion that would go red if it were removed. All read,
none run.

- **The scrubbed phrase is the only free text in a payload, and the field set is closed.**
  `ALLOWED_PAYLOAD_FIELDS` is five fields; `MarketOutboundPayload` closes the same shape in the
  contract, so an added field is both a test failure and a serialisation change.
  `test_the_payload_field_set_is_closed` (per tier) fails on any added key;
  `test_the_allowed_field_set_contains_nothing_that_could_hold_a_passage` fails on a
  passage-shaped *name*. Removing either guard is caught.
- **Passages are refused, not sanitised.** `build_payload(**forbidden)` raises `PassageRefused`
  naming the field; `test_passing_passages_to_the_builder_is_refused_not_sanitised` is
  parametrised over ten field names, and the char and word limits each have a test that only
  that limit can satisfy (`test_the_character_limit_refuses_on_its_own`,
  `test_the_word_limit_refuses_on_its_own`) — the mutation-found pair. `None` is refused
  (`test_none_is_refused_because_none_means_do_not_search`), and `market_phrase` has no code
  path returning its input (`test_none_never_degrades_into_the_raw_question`).
- **The phrase cannot inject URL parameters.** `quote()` percent-encodes everything outside
  RFC 3986 unreserved, so `&`, `=`, `?` and `#` in a phrase cannot add a parameter or change
  the authority; `test_a_full_search_over_the_recorded_responses` asserts the encoded form
  reaches both URLs.
- **The market modules cannot reach the corpus.** AST inspection over `db`, `search`,
  `keyword`, `chunker`, `passages`, `claims`, `analysis`, with
  `test_the_import_guard_would_actually_catch_a_forbidden_import` proving the scanner is not
  parsing nothing. Holds for the four listed files; see finding 2 for what it does not cover.
- **No redirects, no cookies, no ambient proxy, bounded response.**
  `follow_redirects=False`, `cookies=None`, `trust_env=False`, `MAX_RESPONSE_BYTES`, all four
  asserted against a fake client in `test_the_client_follows_no_redirects_and_carries_no_cookies`
  and `test_an_oversized_response_is_refused_rather_than_read`. A provider response therefore
  cannot redirect this process off the allowlist, and `HTTP_PROXY` in the environment is
  ignored. The fake's `request.url` carries the real query string, which is what lets
  `test_an_http_error_names_the_host_and_never_the_url` catch a URL-in-error mutation.
- **Off is the absence of a client.** `transport()` returns `None` unless both flags are true,
  re-checked inside `_fetch` for a retained reference;
  `test_no_transport_exists_unless_both_flags_are_true` covers all three not-both combinations
  and `test_a_retained_fetch_refuses_after_the_flags_go_off` covers the stale-reference path.
  `test_the_route_sends_nothing_with_the_flags_off` makes `httpx.Client` construction an
  assertion error and drives the real route — a positive control, not an absence check.
- **The banner is computed from the flags that gate the request.** `egress_state()` reads both
  settings; `test_the_banner_tracks_both_flags_in_both_directions` asserts all four
  combinations *and* that `live_enabled()` equals their conjunction, and
  `test_the_banner_is_not_a_hardcoded_literal` reads the source so a literal cannot come back.
  The panel receives it from the API (`AnalysisModeScreen.tsx:1567`, `d.egress`), with
  `AnalysisModeScreen.test.tsx:379` recording the hardcoded-prop regression. This is the one
  place the flags reach the UI correctly — findings 1, 7 and 9 are the same claim restated
  elsewhere as literals or from one flag.
- **Failure never falls back to samples.** `search_all` returns `rows: []` with a `failure`
  string; `_disabled_result` is the only path that returns fixtures and only when
  `live_enabled()` is false. Backend: `test_all_tiers_failing_says_so_and_returns_no_rows`,
  `test_no_transport_is_a_failure_not_a_sample`. Frontend: `SearchOutcome` checks `failure`
  before any row can render, and
  `"shows the failure and NO rows - not even the samples the payload carried"` feeds a payload
  that *carries* sample rows alongside a failure — a fixture that can actually produce the
  condition.
- **A sample is never describable as live.** `is_sample` and the `sample://` scheme are
  enforced at load time with five refusal tests; `Literal[True]` in `MarketFinding` means a row
  that lost the flag cannot serialise; `SAMPLE_LABEL` distinguishes a fixture from tier 3, with
  `"gives a sample row its own provenance, not the reference row's"` pinning it. `provider_label`
  is printed on every row from the backend's own string, never inferred, and the reference
  caption is text rather than colour.
- **No secret in a response, log, message, traceback or audit row.** Six surfaces, separately
  asserted, with `test_the_key_is_absent_from_a_formatted_traceback` first proving the raw trace
  *does* contain the key (so the redaction is not credited for something else) — the strongest
  test in the market suite. `_safe_reason` rebuilds from the exception type plus redacted text.
  An unconfigured provider says `"not configured"` and nothing about length or endpoint.
- **The parsers are tested against real captured bytes**, not fabricated JSON
  (`test_market_recorded_responses.py`), with a fixture-integrity test that fails if the
  recordings are trimmed. `test_real_rows_link_off_the_allowlist_and_that_is_correct` correctly
  separates "a host this process may connect to" from "a link in a row".
- **The send path is one explicit click.** `marketApi.search` is called only from `send()`,
  which is only wired to Confirm; no debounce, blur or effect dispatches it; Enter submits the
  preview. `"dispatches no search after typing, after Enter and after blur"` covers the three
  ways it used to be possible, and `"sends nothing when the payload was never shown"` covers the
  unshown-payload state. The dialog renders the backend's `payloads`, not a client-side
  re-serialisation, and the mock fixtures use `country: "SE"`/`freshness_days: 7` — values the
  form cannot produce — so a panel that rendered its own guess would fail. The panel's mocks are
  of the API client, not of the panel, so they are not the mocked-the-type-under-test pattern.
- **The phrase is re-scrubbed server-side** rather than trusted from the POST body
  (`main.py:1002`), so the only text that can reach a provider is text this server derived.

# Not reviewed

- **Nothing was executed.** No pytest, no vitest, no mutation, no request. Every "would still
  pass" above is read off an assertion.
- `backend/.env` was not opened, and no live configuration was inspected — findings 3, 4 and 15
  turn on values I cannot see from the source.
- `market_phrase` idempotence: the frontend approves the preview's phrase and the backend
  scrubs it *again* before sending. I found no input where the second pass differs, and any
  difference could only shorten it, but I did not enumerate the designator-window cases and no
  test asserts `market_phrase(market_phrase(q)) == market_phrase(q)`. Worth one test.
- The rest of the analysis screen, `AnalysisModeScreen.tsx` beyond the `MarketPanel` wiring, and
  `AnalysisView.tsx` (which is not rendered anywhere I could find).
- `access.current_scope` itself, and the classification/grants logic the market routes depend on
  for `_corpus_filenames`.
- Whether the OS-level firewall or egress proxy that `config.py:360-369` names as the real
  control exists on the target machine. Every code-level allowlist finding above assumes it does
  not.
- The pre-commit hook and gitleaks configuration (audit entry 24), beyond noting that the
  sentinel in `test_market_secret_hygiene.py` was reshaped rather than allowlisted.
