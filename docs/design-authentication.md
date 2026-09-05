# Design — authentication and login

Written against the real code. Every claim carries a file:line. Where the design
is uncertain it says so.

## The three holes this design found, before designing anything

All three are pre-existing, all three are invisible under `AUTH_MODE=disabled`,
and all three become confidentiality failures the moment `demo_required` is
switched on. **None was introduced by the access-control work; all were exposed
by looking at it.**

### 1. Page images bypass authentication entirely

`pageImageUrl` (`client.ts:199`) and `pageImageWithAnswerUrl` (`client.ts:211`)
return **URL strings** consumed by `<img src>`. A browser does not attach an
`Authorization` header to an image request.

`main.py:579` calls `require_document(document_id, scope)` — which is the only
thing gating a route that renders **actual client document content**. Under
`demo_required` that gate is unreachable, because no token arrives.

Every rendered page of every document is readable without a token.

The fix is to fetch images through `request()` as a blob and hand the view an
object URL. That touches every consumer plus URL revocation, and **it is the
largest single piece of frontend work in this feature.** The two alternatives
are both wrong: a query-token puts a credential in a URL that lands in logs and
`Referer`, and leaving images open is not an option.

### 2. Conversations cross role boundaries

- `GET /api/conversations` (`main.py:433-441`) takes `scope` and **never reads
  it** — `chat_mod.list_conversations` gets no filter.
- `DELETE /api/conversations/{id}` (`main.py:458`) has no scope parameter at all.
- `create_conversation` (`main.py:419`) never writes `owner_user_id`, despite
  the migration at `db.py:389-391` stating that NULL "must read as INACCESSIBLE
  rather than as unowned-and-therefore-public".

A conversation carries its title and its stored answer payload, and that payload
contains quoted document text. The 404-vs-403 discipline `require_document`
enforces for documents has no counterpart in `_require_conversation`
(`main.py:407-414`).

### 3. Upload has no scope, and an uploaded document is invisible to its uploader

`POST /api/documents` (`main.py:142-144`) carries no scope dependency. Under
`demo_required` an unauthenticated caller can upload.

Worse in the other direction: a document uploaded under `demo_required` lands
with **no `document_role_access` row**, so by deny-by-default the uploader
cannot see what they just uploaded. Correct by schema, wrong by experience.

The simplest honest fix is for the upload route to write a grant for one of the
uploader's roles — **but which role is undefined** for a user with three. That
rule does not exist yet and should not be invented in the auth commit.

---

## A. Schema delta

**For login itself, nothing is missing.** `users` (`db.py:178-188`) already has
`email UNIQUE`, `password_hash`, `is_active`, `last_login_at`. Its own comment
records the guarantee: *"There is no column a password could be stored in, which
is a cheaper guarantee than a rule saying not to."*

`audit_events` (`db.py:225-248`) already has `action`, `outcome` and the
denormalised actor, so `login` / `login_failed` rows need no change.

**Optional, one column:** `users.token_epoch INTEGER NOT NULL DEFAULT 0`, added
the additive way (`PRAGMA table_info`, matching `db.py:338-349`). It is the only
way to force a logout without a session table. **It is also the first thing to
drop under time pressure** — deletion and deactivation are already covered
without it.

**No table for rate limiting.** A row per failed login turns an unauthenticated
endpoint into an unauthenticated *writer* against the one SQLite file ingestion
is writing to. The durable record is `audit_events`; the counter is memory.

**A real blocker, not a design point:** `backend/requirements.txt` pins no
Argon2 library and `.venv` contains no `argon2`, `passlib`, `bcrypt`, `jwt` or
`cryptography`. `argon2-cffi` is a cffi package needing a matching Windows
wheel. **Pin and install it while the machine still has a network**, or the auth
commit bricks the app on an air-gapped target. HMAC needs nothing — stdlib.

**Also missing:** `.gitignore` re-includes `!.env.example` and **`.env.example`
does not exist.** The secret is otherwise undocumented and an operator discovers
it from a stack trace.

---

## B. Module layout

```
access.py   exists — WHAT a request may see
auth.py     new    — WHO the request is
main.py     every route, including the two new ones
```

**No `app/routers/` package.** `preflight-inventory.md:138-143` records that
every route lives in `main.py` and that introducing `APIRouter` "is a decision
rather than an existing convention to extend". Making that decision inside the
auth commit puts a new security boundary and a structural refactor in one diff,
and review of the first gets diluted by the second.

**`auth.py` must not import `access.py`.** The dependency runs one way:
`main.py` calls `auth.install()` at startup, which calls
`access.set_user_resolver(auth.resolve_user_id)`. That is the injection
`access.py:110-116` already describes, and it is why the concurrency test can
swap the resolver without touching auth.

---

## C. The token

**Signed opaque bearer token — HMAC-SHA256 over `{u, e, x}`, about 25 lines, no
JWT library.**

`requirements.txt` has no JWT library and the machine is air-gapped after setup.
A JWT parser buys algorithm negotiation, a `kid` header and the `alg: none`
family — for a threat model of a handful of known users on loopback. HMAC over a
JSON blob has one algorithm because there is no field to say otherwise. **This
is the simpler option, chosen deliberately.**

**Not a session table.** More conventional, and it would give instant revocation.
Rejected because it puts a row-insert on every login and a SELECT on every
request against the SQLite file ingestion is already writing to, and because an
uncollected expired-session table is a real operational wart on a machine nobody
administers.

**Lifetime: 8 hours.** One setting. Justified against *this* system: Tier 2
answers take ~50s and ingestion runs for many minutes. A 15-minute token means an
operator watching a login screen appear mid-demo. **No refresh token** — a
refresh flow exists to make short tokens tolerable, and a long token is the
alternative to it, not a companion.

**Storage.** Server: nothing. Client: a module-level variable in `client.ts`.
Never `localStorage` — it outlives the tab, and every XSS becomes credential
theft rather than a session-length nuisance. **A reload logs you out. Say so in
the UI rather than letting the user discover it.**

**Revocation, three layers, cheapest first, all inside `resolve_user_id`:**

| Case | Mechanism | Works today? |
|---|---|---|
| Deleted | `ON DELETE CASCADE` (`db.py:198`) removes `user_roles`, so the scope resolves to `frozenset()` | **Yes, no code** |
| Deactivated | Re-read `is_active` per request; return `None`, which lands on `empty_scope()` (`access.py:144`) | New, one lookup |
| Forced logout | Bump `token_epoch` | New, optional |

---

## D. The seeding command

`scripts/seed_access.py`, following `fetch_models.py` structure: module docstring
with invocations, `argparse` in `main()`, module-level data constants, a
`--verify-only` mode mirroring `fetch_models.py:206-210`, `raise SystemExit(main())`.

```
python scripts/seed_access.py --roles
python scripts/seed_access.py --user ali@x --role engineer
python scripts/seed_access.py --grant <role> --document <id>
python scripts/seed_access.py --verify-only
```

**Passwords: interactive `getpass.getpass()` only, with confirmation.** Never a
`--password` flag — it lands in shell history and in `ps`. Never a file, never an
environment variable, never a default.

### What stops a demo password reaching production

1. **There is no demo password in the repository to reach production.** No
   constant, no fixture credential, no `--demo` flag. Stronger than any scan.
2. **Refuse weak input** — minimum length, reject `password`, `demo`, `nabaa`,
   `changeme`, the email local-part. Fail loudly and non-zero.
3. **Refuse to re-seed an existing user under `demo_required` without `--force`.**
   Re-seeding is how a known password quietly replaces a real one.
4. **`--verify-only` reports users with no roles and roles with no grants**, so
   "seeded but useless" is visible before the demo rather than during it.

---

## E. The wiring

### `access.current_scope` changes by ZERO lines

```python
# access.py:139-146
if settings.auth_mode == AUTH_DISABLED:
    return unrestricted_scope()
if _resolve_user_id is None:
    return empty_scope()
user_id = _resolve_user_id(request)
if not user_id:
    return empty_scope()
return scope_for_user(user_id)
```

`demo_required` already falls to `empty_scope()` with no resolver, calls the
resolver, falls to `empty_scope()` on no identity, and derives the scope from the
grant tables. Both branches already have tests.

**The only wiring is one line at startup**, in `lifespan` (`main.py:35-51`),
after `init_db()`: `auth.install()`.

### Where the boundary sits, exactly

`auth.resolve_user_id(request)` is the **entire** client-influenced surface. The
boundary is its **return type**: it returns `str | None`, and `access.py:146`
spends it on `scope_for_user`, one SQL query against the grant tables.

**The client controls which row is looked up. It cannot control what the lookup
returns.**

Three rules that keep it there:

- `resolve_user_id` must never return an `AccessScope`, a set of ids, or a role
  name. If its signature widens beyond `str | None`, the boundary has moved into
  the request.
- Nothing in `auth.py` may import `search`, `answer` or `chat`.
- `AccessScope` stays `frozen=True, slots=True` (`access.py:47`).

### The error-code trap

`errors.safe_error` coerces silently:

```python
"code": code if code in ALL_CODES else INTERNAL   # errors.py:139
```

A login returning `code="invalid_credentials"` becomes `"internal"` — a client
mistake reported as a crash, exactly the failure `errors.py:12-14` was written to
prevent. **`UNAUTHENTICATED`, `INVALID_CREDENTIALS` and `RATE_LIMITED` must be
added to `CLIENT_ERROR_CODES` and `ALL_CODES` in the same commit.**

`/api/health` is untouched. It must not gain `auth_mode`, `login_required` or a
user count — the frontend discovers mode from a 401, and any of those re-widen
the surface just narrowed.

---

## F. Frontend

Token in a module-level `let` in `client.ts`, attached inside `request()` at the
single `fetch` (`client.ts:120`) — the module's own principle is "Every call goes
through here so two rules hold everywhere" (`client.ts:4`).

**On 401:** clear the token, fire a registered callback, render the login screen.
No auto-retry, no refresh, no redirect loop. `humanMessage` (`client.ts:63-75`)
currently lumps 401 with 403 and says *"Check whether the backend was started
with different settings"* — actively misleading to a logged-out user. Split them.

**Login screen above `Shell`, not inside it.** `useConnection` (`Shell.tsx:33`)
polls `/api/health` every 5s and health stays unauthenticated, so the connection
badge works on the login screen — which is exactly right: **"backend offline" and
"wrong password" must be distinguishable.**

**One error message for all credential failures.** A distinct 429 message is fine
and necessary — the user must know to wait — and 429 reveals nothing about which
half was wrong.

**Contract drift.** `preflight-inventory.md:147-168`: nothing generates
`contracts/types.ts`. In one commit — `LoginResult`, `Me`, and the three new
codes into the closed `ApiError.code` union (`types.ts:517-536`). That union is
compiler-enforced *only if the codes are added*; adding them to `errors.py` alone
compiles cleanly and fails at runtime.

---

## G. Negative tests — each must fail against the code as it stands

### The fixture asserts its own preconditions

Four recorded instances of a fixture that could not produce its condition,
including two byte-identical PDFs deduplicating so `visible` and `hidden` were
the same document and thirteen tests asserted a document cannot see itself
(`test_access_routes.py:98-101`).

```python
assert doc_a != doc_b,        "the two uploads deduplicated to one document"
assert scope_a and scope_b,   "a user with an empty scope proves nothing"
assert scope_a != scope_b,    "identical scopes - every cross-user test is vacuous"
assert not (scope_a & scope_b), "overlapping scopes - a leak would be invisible"
assert hash_a != hash_b,      "both users seeded with the same password"
```

### The assertions

**Credentials** — correct password 200, wrong 401; **the two 401s are
byte-identical**, compared with `_shape()`; hash starts `$argon2id$`, differs
between two users with the same password (per-user salt); no hash or `is_active`
in any response; a deactivated user's failure has the same shape (being
deactivated is not a fact for an anonymous caller).

**Token** — altered signature rejected; **re-base64'd payload with a different
`u` rejected** (forging another user); expired rejected as `unauthenticated`, not
500; **signed with a different secret rejected** (proves the secret is consumed);
`/api/me` never returns another user's email.

**The scope never comes from the request** — with A's valid token, add
`X-User-Id: ub`, `?user_id=ub`, a cookie, and a body field. All four return
exactly A's documents. *This is the one that catches a resolver that grew a
fallback.*

**Mid-session revocation** — deactivate A with a valid token in hand: next
request returns `[]`, and a document lookup returns **404, not 403**. Delete A:
same, and no 500 on the cascade.

**Rate limiting** — N+1 failures return 429; **a 429 for a non-existent email is
identical to one for a real email** (the limiter must not become the oracle the
constant-time verify just closed); user B is not blocked by A's exhausted budget.

**Health parity** — under `demo_required` with no token, key set is **exactly**
`{ok, embed_model_present, answer_model_present, ingestion}` and ingestion's is
exactly `{alive, stalled, busy}`. **Set equality, not `in`** — an `in` check
passes when a field is added. Same key set under both modes.

**Upload** — `POST /api/documents` under `demo_required` with no token **does not
create a document row**. Fails today.

### The timing test, made non-flaky on a 15 W CPU

**The mechanism first, the measurement second.** `verify_password` must run
against a **dummy Argon2 hash** computed once at import when the email is
unknown, so both paths do identical work. The test then confirms a property the
code has, rather than being the only thing enforcing it.

Then: parameters tuned to ~150–250 ms so the signal is above scheduler noise;
**medians, never means** (one GC pause destroys a mean); **interleave the
samples** — `unknown, known, unknown, known` — because CPU frequency scaling and
thermal throttling drift over seconds and a block design attributes that drift to
the branch; a **relative** bound, not absolute milliseconds, which would encode
this machine's speed into the assertion; and **assert the floor first** —
`min(median) > 0.05`, because if both paths are fast the hashing did not run and
the comparison is measuring nothing.

~120 hashes at 200 ms is ~25 seconds. Marking it `slow` means it never runs by
default, which is the silent-skip failure this project already recorded.
**Put it in the main suite. 25 seconds is cheap for the one test standing between
the login page and an account-enumeration oracle.**

---

## H. What could go wrong

**Scope becoming client-influenced.** A debug fallback in `resolve_user_id` —
`access.py:88` already names this class: *"A fallback branch in Python … is where
a deny-by-default schema turns into an allow-by-accident system."* Or someone
"optimising" `main.py:367` from `scope.allowed_document_ids` to `{document_id}`,
which would pass every existing test under `disabled`. Or a token payload
carrying roles — however well signed, that is a scope the client holds, and once
the secret leaks it is a scope the client writes. Or `@lru_cache` on
`scope_for_user`, which would serve stale grants after a revoke.

**Startup order.** `auth.install()` must run after `init_db()`. If missed,
`_resolve_user_id` stays `None` and every user sees an empty corpus with no error
anywhere — **failing closed, which is right, and silently, which is not.** Log
the active mode at startup.

**Missing secret.** `auth_secret: str = ""` would boot and sign every token with
the empty string — anyone forges any user. Hard startup failure under
`demo_required` only, in the style of `run.py:31-45`. **A generated-if-missing
secret is worse than either** — every restart silently logs everyone out
mid-demo and hides the misconfiguration.

**A 401 storm is the cheapest way to OOM this box.** Argon2 at ~200 ms and ~64 MB
× 40 threadpool slots is **~2.5 GB** of hashing memory on a machine `config.py:186`
describes as demoing at 92% RAM, beside a 3,247 MB ONNX arena and a 3.4 GB answer
model. **The limiter is the memory bound, not a nicety** — and it must reject
*before* hashing, or the throttle costs the same as the attack. Cap `parallelism`
explicitly and low, in the spirit of `ocr_threads: int = 2`.

With every slot in Argon2, a Tier 2 answer and the ingestion worker queue behind
it, and `/api/health` reports `stalled` — **"Queue not moving" during a login
flood, true and completely misleading about the cause.**

**Per-IP limiting is useless here.** Loopback-only means every request is
`127.0.0.1`. Key on the submitted email, plus a global ceiling on concurrent
in-flight hashes, or an attacker rotates emails and the budget never trips.

---

## I. The smallest honest version — 75 minutes

Build: `auth.py` (Argon2id with the **dummy-hash uniform-failure path** — 4 lines,
not optional; HMAC sign/verify; `resolve_user_id` re-checking `is_active`; a
per-email limiter with a lock); two routes with `response_model`; one
`auth.install()` line; two config settings plus a startup refusal on a weak
secret under `demo_required`; **three error codes into `errors.py`**;
`seed_access.py`; `LoginResult`/`Me`/three codes into **both** `schemas.py` and
`contracts/types.ts`; `client.ts` bearer plus the 401 split; `LoginView.tsx`;
`test_auth.py` **including the timing test**; `.env.example`; pin `argon2-cffi`.

**Not built:** `token_epoch` and forced logout — deletion and deactivation are
already covered, and this is the first thing to drop. No refresh tokens. No
per-user grants. No admin UI. No `APIRouter`. **No change to `access.py`.**

### What it does not claim

- **It does not claim `demo_required` is production-safe.** Upload has no scope.
  Conversations are unscoped and their stored payloads contain quoted document
  text.
- **It does not claim page images are protected.** `<img src>` cannot carry a
  bearer header. Every rendered page of every document is reachable without a
  token until the blob refactor lands. **This is the biggest single hole and it
  is invisible under `disabled`.**
- **It does not claim revocation is instant.** Next request, not immediate.
- **It does not claim the limiter survives a restart.** In-process memory on one
  worker; the durable record is `audit_events`.
- **It does not claim constant time in general.** It proves the two login failure
  paths are indistinguishable at this sample size on this machine. Argon2 is
  data-independent by design; the dummy-hash path is what makes the claim true,
  and the test is what makes it watched.
- **It does not claim `disabled` changed.** That is the point: every existing
  test passes unchanged, the enforced path runs in both modes, and rollback is a
  config change rather than a revert.
