# Access-control review — `access.py`, `admin.py`, `auth.py`, `Shell.tsx` (admin decision), and their tests

**This review is static.** I read the files on the user's machine read-only and ran nothing:
no pytest, no vitest, no server. Every claim below is traced through source; where a
runtime fact matters (argon2's parameters, SQLite's variable limit) I say where I read it
and what I did not measure. No file was modified.

Files read in full: `backend/app/access.py`, `backend/app/admin.py`, `backend/app/auth.py`,
`backend/tests/test_access_routes.py`, `backend/tests/test_admin.py`,
`backend/tests/test_auth.py`; `frontend/src/components/Shell.tsx` lines 1–100;
`backend/app/main.py` lines 1–300 and 1410–1570; `backend/app/db.py` roles/user_roles DDL
and the migration block; `backend/app/classification.py` `narrow_to_scope` / `restrict`;
`scripts/seed_access.py` (grep); test names of `test_auth_required_mode.py`,
`test_access_schema.py`, `test_seed_access.py`, `test_metrics_host_telemetry.py`.

Entry 15 itself is **fixed**: `main.py:193-201` now computes
`corpus_wide = scope.unrestricted or scope.is_admin` and passes `allowed` into
`metrics_mod.snapshot(...)`, and `main.py:126-131` retracts the false sentence in place
rather than deleting it. `test_access_routes.py:196` and `test_auth_required_mode.py:167`
hold it. That is not re-reported below.

---

## 1. The admin surface is gated on a role's NAME, not on the column that defines a capability

- **Severity:** high
- **File:** `backend/app/admin.py:193-194`, reached from every `/api/admin/*` route via
  `admin.py:222`; second instance at `backend/app/admin.py:372-373`

```python
def is_admin(user_id: str) -> bool:
    return ADMIN_ROLE in _role_names_of(user_id)
```

```python
        row = conn.execute("SELECT id, name FROM roles WHERE name = ?",
                           (ADMIN_ROLE,)).fetchone()      # create_user, no kind check
```

- **What is wrong:** the authorisation decision for the highest-privilege surface in the
  API is derived from `roles.name` — a mutable label — while `db.py:267` states that
  `roles.kind` exists to say exactly this ("The ONE thing this column exists to say:
  `admin` is a CAPABILITY"), and `access.scope_for_user` (`access.py:157-164`) derives
  `AccessScope.capabilities` from `kind = 'capability'`. `main.py:185-192` already names
  this divergence as a hazard and closes it for `/api/metrics` only:

  > `admin_mod.is_admin` answers the same question from `roles.name`, and the two agree
  > only because `init_db` re-asserts kind = 'capability' … **That re-assertion is not a
  > guarantee**: a role NAMED admin with kind = 'discipline' is an administrator to the
  > name predicate and an ordinary engineer to this one.

  The stronger predicate was applied to the metrics *counts* and left off the *routes*.
- **The failure:** `init_db`'s corrective `UPDATE roles SET kind = 'capability' WHERE
  name = 'admin'` (`db.py:648`) runs only at startup. A `roles` row named `admin` with
  `kind = 'discipline'` — written by hand, by a partial `seed_access.py` run, or existing
  on a database between restarts — makes its holder a **full administrator to every
  `/api/admin/*` route**: they can `POST /api/admin/users` (creating further admins),
  `PUT`/`DELETE /api/admin/grants` for any document and any discipline, and deactivate
  users, while `AccessScope.is_admin` for the same request is `False`. The reachable-
  through-the-API half needs no hand-edited database at all: `create_user` at line 372
  attaches whatever row is *named* `admin` regardless of kind, and `list_users:318`
  then reports `"is_admin": true` for a user the enforcement layer treats as an ordinary
  engineer — the admin screen makes a false statement about who holds the capability.
- **Rule:** access-control (and the audit's own pattern: a decision derived from
  something adjacent to the truth).
- **Smallest fix:** `is_admin` → `SELECT 1 FROM user_roles ur JOIN roles r ON r.id =
  ur.role_id WHERE ur.user_id = ? AND r.kind = 'capability' AND r.name = ?`, the same
  belt-and-braces predicate `grant_on_upload` already uses at `admin.py:588-590`; add
  `AND kind = 'capability'` to the `create_user` lookup at line 372.

---

## 2. The login rate limiter's refusal is itself an unauthenticated write, and its key is the attacker's own input

- **Severity:** high
- **File:** `backend/app/auth.py:280-287` (with `auth.py:209-219` and `auth.py:242-264`)

```python
    wait = _limiter.check(key, now)
    if wait is not None:
        _audit("login_failed", "rate_limited", key)      # <- a row, on every refusal
        raise AuthError(...)
```

- **What is wrong:** the limiter is keyed on `key = (email or "").strip().lower()`, a
  value the caller chooses per request, and the locked-out branch still performs an
  `INSERT INTO audit_events`, so neither the write volume nor the Argon2 work is bounded
  by anything an unauthenticated caller does not control.
- **The failure:** two concrete ones, both against the guarantee `auth.py:183-190` states
  in its own words ("A row per failed login turns an unauthenticated endpoint into an
  unauthenticated WRITER against the SQLite file ingestion is writing to, which is a
  denial-of-service primitive handed to anyone who can reach the port"):
  1. `POST /api/auth/login` with a **fresh email each time** never meets a full bucket
     (`settings.auth_max_attempts = 8` per email per `auth_lockout_seconds = 300`), so
     every request reaches `_hasher.verify(_DUMMY_HASH, …)`. The installed argon2-cffi
     25.1.0 defaults to `RFC_9106_LOW_MEMORY` — `time_cost=3`, `memory_cost=65536` KiB,
     `parallelism=4` (`.venv/Lib/site-packages/argon2/profiles.py:49-56`) — so each
     in-flight request allocates **64 MiB**. Twenty concurrent requests is ~1.3 GB on a
     machine that also runs local inference. I did not measure this; the parameters are
     read from the installed profile.
  2. `POST /api/auth/login` repeatedly with **one** email, after the eighth attempt,
     writes one `audit_events` row per request at request rate for no CPU cost — the
     lockout branch is the cheapest path to the write. `audit_events.actor_username`
     takes `username[:200]` straight from the request body (`auth.py:261`), so the rows
     also carry up to 200 bytes of attacker-chosen text into the table `admin.py:152`
     calls "the one most likely to be exported".
- **Rule:** access-control / honesty (the module docstring claims the design avoids
  precisely this).
- **Smallest fix:** move the `_audit` call for the `rate_limited` outcome behind a
  per-key once-per-window flag (record it when the bucket *fills*, not on every refusal),
  and add a second limiter bucket keyed on the client host so a varying email cannot
  reset the budget. Both are inside `_Limiter`.

---

## 3. The self-deactivation guard is keyed on the actor, and under the shipped default there is no actor

- **Severity:** high
- **File:** `backend/app/admin.py:442-446`, with `backend/app/admin.py:215-226`

```python
    if actor is not None and user_id == actor.get("id"):
        # Without this the last admin can lock every user, including
        # themselves, out of a system whose only other door is a terminal.
        raise _fail(409, CANNOT_DEACTIVATE_SELF, ...)
```

```python
    user_id = auth_mod.resolve_user_id(request)
    if user_id is None:
        if settings.auth_mode == AUTH_DISABLED:
            return None            # anonymous caller allowed through, actor = None
```

- **What is wrong:** the guard is derived from *who is asking* rather than from *whether
  an active administrator would remain*, and its `actor is not None` prefix disables it
  entirely for the caller who has no identity — which under `AUTH_MODE=disabled`, the
  shipped default (`config.py:51`, asserted by `test_access_routes.py:311`), is every
  anonymous caller.
- **The failure:** on a default deployment, `DELETE /api/admin/users/<id>` with no
  `Authorization` header at all reaches `deactivate_user(user_id, None)`, skips the
  refusal, and sets `is_active = 0` — **including for every account holding the admin
  capability**. The system then has zero active admins. Switch `AUTH_MODE=demo_required`
  afterwards (the documented hardening step) and `current_admin` 404s every caller:
  `/api/admin/*` is unreachable and the only remaining door is `scripts/seed_access.py`
  at a terminal. That is verbatim the outcome the comment above says the guard prevents.
  The same anonymous path also reaches `PUT`/`DELETE /api/admin/grants` and
  `POST /api/admin/users`, so an unauthenticated local caller can widen or remove other
  users' document access permanently — under a mode whose only stated concession is that
  *reads* are already unrestricted.
- **Rule:** access-control. The concession documented at `admin.py:206-213` is argued
  only for reads ("under that mode `unrestricted_scope()` already hands every caller
  every document"); it does not cover destructive writes to the grant and user tables,
  whose effect outlives the mode.
- **Smallest fix:** two lines. Make the refusal a property of the corpus rather than of
  the actor — refuse when the target holds the admin capability and is the last active
  holder of it (`SELECT COUNT(*) … WHERE r.kind='capability' AND r.name='admin' AND
  u.is_active = 1`) — and keep the existing self-check as well.

---

## 4. `_secret()` will sign and verify with a zero-length key

- **Severity:** medium
- **File:** `backend/app/auth.py:93-102`, consumed at `auth.py:147` and `auth.py:162`

```python
def _secret() -> bytes:
    raw = (settings.auth_secret or "").strip()
    return raw.encode("utf-8")
```

- **What is wrong:** the only thing standing between an absent `AUTH_SECRET` and a
  verifying HMAC is `check_secret_or_refuse()`, which returns immediately when
  `auth_mode == AUTH_DISABLED` (`auth.py:109-110`, asserted as correct by
  `test_auth.py:344`). The token path has no guard of its own; `hmac.new(b"", …)` is
  legal and `read_token` accepts the signature it produces.
- **The failure:** on the shipped default (`auth_mode = "disabled"`, `auth_secret = ""` —
  the combination `config.py:18` records as what a launch from the repo root gets), any
  caller who can reach the port can mint `Bearer <payload>.<hmac-with-empty-key>` naming
  any active user id. Scope is unaffected (everyone is unrestricted under that mode), but
  `admin.current_admin` calls `auth_mod.resolve_user_id` in **both** modes
  (`admin.py:215`), so the forged identity becomes `actor` and is written verbatim into
  `audit_events.actor_user_id` / `actor_username` for every grant, revoke, create and
  deactivate (`admin.py:162-164`). The durable record of who changed access is therefore
  forgeable by an unauthenticated caller in the default configuration — and `db.py:314`
  states that answering "who did this" is the reason that column exists.
- **Rule:** access-control / honesty.
- **Smallest fix:** in `issue_token` and `read_token`, return `None` / raise when
  `len(_secret()) < 32`. A token is then never valid under an unconfigured secret,
  regardless of which mode the check ran in.

---

## 5. `admin.py` decides what a discipline is from the role's name; `access.py` decides it from `roles.kind`

- **Severity:** medium
- **File:** `backend/app/admin.py:250-262` (and `admin.py:467-472`) versus
  `backend/app/access.py:179-190`

```python
    return [dict(r) for r in connect().execute(
        "SELECT id, name FROM roles WHERE name != ? ORDER BY name",
        (ADMIN_ROLE,))]                                   # admin.py: "not named admin"
```

```python
               WHERE dra.document_id = ? AND dra.permission = 'read'
                 AND r.kind = 'discipline'                # access.py: kind
```

- **What is wrong:** `_discipline_rows()` is the vocabulary the admin screen offers and
  the whitelist `_resolve_discipline` validates a grant against, and it defines
  "discipline" as "any role not called `admin`" — the same weaker predicate as finding 1,
  in the function whose docstring argues against a second source of truth.
- **The failure:** add a second capability (`roles.kind='capability'`, e.g. `auditor` —
  `admin.py:562` and `db.py` both anticipate one) and it appears in
  `GET /api/admin/disciplines` as a discipline, with a user count and a document count;
  `PUT /api/admin/grants` accepts it; `GET /api/admin/grants` lists it under a document's
  `disciplines[]`. The Documents screen, fed by `access.disciplines_for`, will not show
  it. The same document then reports two different sets of "who may read this" on two
  screens, and the discipline counts on the admin screen include a role that is not one.
- **Rule:** access-control / honesty.
- **Smallest fix:** `WHERE kind = 'discipline'` in `_discipline_rows`, and
  `AND r.kind = 'discipline'` in the `list_grants` subquery, replacing both name
  comparisons.

---

## 6. `test_the_admin_capability_is_not_a_discipline` never touches the column that makes admin a capability

- **Severity:** medium
- **File:** `backend/tests/test_admin.py:554-564`, with the fixture at
  `test_admin.py:84-90` and `test_admin.py:145`

```python
def make_role(name: str) -> str:
    ...
        conn.execute("INSERT INTO roles (id, name, description, created_at) "
                     "VALUES (?, ?, '', ?)", (role_id, name, _now()))   # no kind
```

- **What is wrong:** `db.init_db()` runs in `temp_storage` (`test_admin.py:71`) *before*
  `world` creates its roles, so `init_db`'s corrective
  `UPDATE roles SET kind = 'capability' WHERE name = 'admin'` (`db.py:648`) never sees
  them: the fixture's `admin` role carries `kind = 'discipline'` (the column default,
  `db.py:267`). Every assertion in the test is satisfied by the name predicate alone.
- **The failure:** the test passes today over a database in which `admin` is *not* a
  capability. Mutation that leaves it green: drop `roles.kind` from the schema entirely,
  or set every row to `'discipline'`. It is therefore not evidence for the property its
  name states, and it is the only test in `test_admin.py` that mentions the capability —
  so no test in this file would fail if finding 1 were fixed *or* if it got worse. The
  whole admin-route table (`ROUTES`, lines 43–51) is likewise driven only by users whose
  `admin` role has the wrong kind, so `test_an_admin_reaches_every_route` proves
  reachability under the name predicate and says nothing about the capability.
- **Rule:** vacuous-test.
- **Smallest fix:** `make_role` takes `kind` and inserts it; `world` creates `admin` as
  `'capability'`; then add one test that a role named `admin` with `kind='discipline'`
  gets 404 on the `ROUTES` table — which is the test that would have caught finding 1.
  `test_metrics_host_telemetry.py:419` is the model: it builds exactly that state and
  asserts `/api/metrics` refuses it.

---

## 7. Both audit writers swallow every exception without a log line

- **Severity:** medium
- **File:** `backend/app/auth.py:263-264` and `backend/app/admin.py:166-167`

```python
    except Exception:  # noqa: BLE001 - an unwritable audit must not block login
        pass
```

- **What is wrong:** the durable record of authentication attempts and of every
  administrative change fails silently. Nothing is logged, no counter moves, and the
  route returns 200.
- **The failure:** a locked database (SQLite writer contention with ingestion, which
  `auth.py:185` says is expected), a disk-full condition, or the schema drift the
  `user_setup_tokens` comment at `admin.py:110-113` anticipates, and every grant, revoke,
  create, deactivate and login proceeds with **no record at all** — and the only way to
  discover it is to notice the table has stopped growing. Entry 24's rule applies
  literally: a control whose absence is invisible is not a control.
- **Rule:** engineering / honesty.
- **Smallest fix:** `logging.getLogger("rag_intelligence").error("audit write failed:
  %s", exc)` in both handlers. Keep the swallow — the argument for not blocking the
  change is sound; only its silence is the defect.

---

## 8. Every request under the default mode reads the whole `documents` table; the admin listings are N+1

- **Severity:** medium
- **File:** `backend/app/access.py:132`, `backend/app/admin.py:306-330`,
  `admin.py:280-300`, `admin.py:462-482`

```python
    ids = frozenset(r["id"] for r in connect().execute("SELECT id FROM documents"))
```

- **What is wrong:** the scope is materialised as a Python id set rather than expressed
  as a join, so `unrestricted_scope()` scans `documents` on **every request on every
  route** under `AUTH_MODE=disabled`, and callers spread it back into
  `WHERE id IN (?, ?, …)` with one placeholder per document (`main.py:274-282`).
  `list_users` runs `_role_names_of` once per user; `list_disciplines` runs two counts per
  discipline; `list_grants` runs one query per document and returns the entire corpus
  unpaginated.
- **The failure:** at the stated target of thousands of documents this is a full-table
  scan plus a several-thousand-element frozenset per request, and a multi-thousand-
  parameter `IN` clause on the document list. Python's `sqlite3` refuses a statement past
  the host SQLite's `SQLITE_MAX_VARIABLE_NUMBER` (32766 on modern builds, 999 on older
  ones) with `OperationalError: too many SQL variables` — a 500 on `/api/documents`, not a
  slow response. I did not run this to find the crossover on the installed SQLite.
  `GET /api/admin/grants` is 1 + N queries and one unbounded response body.
- **Rule:** engineering (scale — the hazard `review.md` names explicitly).
- **Smallest fix:** for the listing routes, replace the id set in the `WHERE` clause with
  the grant join itself (`… WHERE EXISTS (SELECT 1 FROM user_roles ur JOIN
  document_role_access dra … WHERE dra.document_id = documents.id AND ur.user_id = ?)`),
  keeping `AccessScope` for the per-document `may_read` checks; batch `_role_names_of`
  into one grouped query for `list_users` and `list_grants`.

---

## 9. A setup token is issued, displayed and expired, and nothing can redeem it

- **Severity:** low
- **File:** `backend/app/admin.py:385-429`, with `admin.py:10-15` and `admin.py:86-88`

```
  * It never accepts or returns a PASSWORD. … A new user gets a hash of a random value
    nobody ever sees, so the account exists and cannot be signed into until the setup
    token is redeemed.
```

- **What is wrong:** no redemption route exists anywhere in the tree — `grep -rn
  "redeem"` across `backend/`, `frontend/` and `contracts/` returns only this module's
  own comments, the `redeemed_at` column, and one unrelated word in `ExcludedViewer.tsx`.
  Line 87 admits the route is not built; the module's opening paragraph and the response's
  `shown_once: true` read as though it is.
- **The failure:** an administrator creates a user, copies the token out of
  `AdminView.tsx:189` (which offers a clipboard button for it), gives it to the person,
  and that person can never sign in — the account's `password_hash` is a random value and
  there is no endpoint that will change it. The token expires 24 hours later having done
  nothing. The recoverable path is `scripts/seed_access.py` at a terminal, which the admin
  screen's own header says it replaces "for everything except setting a password".
- **Rule:** honesty.
- **Smallest fix:** one sentence in the `create_user` response contract and in the module
  docstring: the token is recorded for a redemption flow that is not built, and a password
  must be set with `scripts/seed_access.py` today. (Building the route is the larger fix
  and is not this finding.)

---

## 10. `access.py`'s docstring states a property of `AccessScope` that the class does not have

- **Severity:** low
- **File:** `backend/app/access.py:19-23` against `access.py:63-73`

```
  * It never defaults to "everything". `AccessScope` has no default constructor
    argument.
```

```python
    unrestricted: bool = False
    capabilities: frozenset[str] = frozenset()
```

- **What is wrong:** two of the four fields have defaults. The guarantee the sentence is
  reaching for — `allowed_document_ids` is required, so a scope cannot be constructed
  without stating what it may see — is real and is the load-bearing half; the sentence as
  written is false.
- **The failure:** a reader checking the claim finds it contradicted eight lines below and
  cannot tell which half was meant, on the one module whose docstring is the specification
  for the deny-by-default property. Both defaults are themselves deny-by-default, so
  nothing is currently unsafe — this is the comment, not the code.
- **Rule:** honesty (`review.md`: "A comment recording a false reason is a defect, not a
  nitpick").
- **Smallest fix:** "`allowed_document_ids` has no default: a scope cannot be constructed
  without saying what it may see."

---

# Verified clean

Checked, and sound. Stated so the review's boundary is visible.

**Scope reaches SQL, and nothing filters after the query.** In these modules every
authorisation question is a `WHERE` clause: `scope_for_user` (`access.py:144-153`) is one
join over `user_roles × document_role_access` with `permission = 'read'` and no Python
fallback; `disciplines_for` filters on `kind = 'discipline'` in SQL; `list_grants`,
`list_disciplines` and `_discipline_rows` filter in SQL. No `for`-loop drops a row a query
returned. `main.py:268-282` filters the document list in the query and says why.
`conversation_filter` (`access.py:112-119`) is `owns_conversation` spelled as a
`(owner, include_unowned)` pair precisely so the list route does not drop rows in Python
after a `LIMIT` — the two are asserted against each other by
`test_conversations_ownership.py`.

**Grant resolution, case by case.** No grants at all → `frozenset()` and
`test_access_schema.py:79`, `test_access_routes.py:180` hold it, including
`/api/metrics` reporting `documents == 0`. A role with no document grant → still nothing
(`test_access_schema.py:89`). A document with no discipline → readable by nobody, and the
admin screen surfaces it as `no_discipline_can_see_this` rather than leaving a zero for the
reader to notice (`admin.py:480`, `test_admin.py:580`). A discipline with no members →
`user_count: 0`, no effect on any scope. `AUTH_MODE=disabled` → a real
`unrestricted_scope()` object rather than a `None` short-circuit, so the enforcement path
is the same code in both modes (`access.py:122-133`, argued in the docstring and asserted
by `test_access_routes.py:317`). Unidentified caller under `demo_required` →
`empty_scope()`, never everything (`access.py:232-236`, `test_access_routes.py:232`).
No resolver installed → `empty_scope()`. **No unanswered question resolves to a yes** in
`access.py`; there is no `except` in the module and no default that grants.

**The admin capability grants no read bypass.** `scope_for_user` builds
`allowed_document_ids` from the grant join alone; `capabilities` is a second query for a
different question, not a fallback for the first (`access.py:154-164`), and an admin
therefore sees exactly the documents their disciplines grant. `main.py:176-182` names the
corpus-wide *counts* on `/api/metrics` as a new and deliberately narrow capability and puts
`corpus_wide` in the payload so the screen can say which kind of number it shows.

**404, never 403, and the bodies match.** `admin._not_found()` returns the same status,
code and message as an unknown id (`admin.py:178-184`), and
`test_admin.py:165` drives all seven admin routes with three different kinds of non-admin;
`test_an_admin_reaches_every_route` is the positive control that stops it passing against
an app with no admin routes. `test_access_routes.py:121` asserts hidden-vs-unknown
equality on code and message (not the whole body, and says why) across five document
routes plus one write route.

**Token handling.** HMAC-SHA256 over a canonical JSON body with `sort_keys` and no
algorithm field to negotiate; `hmac.compare_digest` for the signature
(`auth.py:165`) — the only comparison in these modules that needs to be constant-time, and
it is; version and expiry both checked; every malformed token returns `None` rather than an
error describing which part of the forgery failed (`auth.py:174-175` — fails closed).
`is_active` is re-read from the database on every request rather than trusted from the
token (`auth.py:379-382`), so deactivation and deletion both take effect on the next
request, and `auth.py:28-39` states plainly that revocation is next-request rather than
instant and that forced logout is not built. `test_auth.py:169-256` covers an altered
signature, a repackaged payload naming another user, an expired token, a token signed with
a different secret, and four ways of claiming an identity alongside a valid token.

**No secret is logged, returned or put in a URL.** `announce_mode` reports the secret as
present-or-absent with a length and never a prefix (`auth.py:424-429`), and logs through
`uvicorn.error` because the file handler does not exist yet at startup — both asserted by
`test_auth.py:463`. The setup token is stored only as SHA-256, has no column in any
listing, and `test_admin.py:275` asserts on the raw response body rather than on a key.
No token appears in any path or query string. `describe()` returns roles and never
document ids, with the reason given (`auth.py:329-335`).

**Password hashing.** Argon2id at the library's defaults with a per-user salt; the
placeholder hash for a new account is a real Argon2 hash of a fresh random value, so two
created accounts never share one (`admin.py:396-402`, `test_admin.py:522`). One failure
message for a wrong password, a missing account and a deactivated account, with
`_DUMMY_HASH` making the missing-account path cost the same work — and
`test_auth.py:373` measures it with interleaved medians, a relative bound, *and* a floor
assertion that fails if neither path hashed at all. That floor is the anti-vacuity control
this project's rule 14 asks for, and it is present.

**Classification cannot influence access.** `narrow_to_scope`
(`classification.py:451-503`) intersects the matched set with
`scope.allowed_document_ids` and returns a narrowed `AccessScope` via
`dataclasses.replace`, so widening is structurally unavailable; an empty match returns
empty rather than falling back to the corpus, and the difference from
`narrow_to_named` is argued at the point it differs. `test_classification_api.py:540-555`
asserts the capability survives narrowing *and* that the fixture's admin actually holds one
— the assertion that was previously `frozenset() == frozenset()`.

**`Shell.tsx` `hasAdminCapability` / `navFor` (lines 56-84).** The only input is
`Me.roles` from `/api/auth/me`; nothing is inferred from an email address or a display
name, `null` is not admin, and the admin entry is appended rather than rendered-and-hidden
so a non-admin's DOM does not contain it. The `required: false` branch returning `true`
mirrors `admin.current_admin`'s disabled-mode concession rather than inventing a client-
side decision, and is argued in the comment. One weakness, not raised as a finding because
the nav is not the boundary and every admin route is gated server-side: the guard is
`if (!auth) return false`, so a truthy `AuthStatus` object missing `required` yields `true`
— `contracts/types.ts:437-440` types `required` as non-optional, so this needs a response
that violates the contract to occur.

**Frozen scope, no module-level cache.** `AccessScope` is `frozen=True, slots=True`;
nothing in `access.py` holds a scope between requests; `test_access_routes.py:248` drives
two users through twelve requests each genuinely in parallel and asserts neither sees the
other's document.

**Grant/revoke semantics.** Both idempotent, both effective on the next request because
no scope is cached, and `test_admin.py:220` and `:242` prove it in both directions with a
token issued once and reused. `grant_on_upload` matches the admin role on `kind =
'capability'` **and** the name, which is the strongest predicate in the module, and writes
nothing when `user_id is None` with the reason stated so a later reader does not "make it
consistent".

**Validation before the first write.** `create_user` resolves every discipline before any
`INSERT`, so a refused create leaves no half-made user (`test_admin.py:483`). Deactivate
is never a delete, and the audit row denormalises `actor_username` so a removed user cannot
erase the record of what they did.

**CORS is not a hole here.** `main.py:85-91` allows only the two Vite dev origins, sets no
`allow_credentials`, and the frontend holds the token in a module variable rather than a
cookie — so finding 3's anonymous admin path is a local-caller problem, not a
drive-by-CSRF one.

---

# Not reviewed

- **`main.py`'s routes**, beyond the call sites needed to trace these findings — lines
  1–300 (health, metrics, upload, document list) and 1410–1570 (the admin routes), plus
  greps for every `scope`/`current_admin` occurrence. The other agent owns the sweep. In
  particular I did not verify each of the ~40 `require_document(document_id, scope)` call
  sites individually, nor `api_utils.require_document` itself.
- `metrics.py` / `metrics_mod.snapshot` — I confirmed `allowed` and `corpus_wide` are
  passed in, and did **not** read how `snapshot` applies them. Entry 15's fix lives half
  in that function.
- `reports.py`, `conversations`, `search.py`, `answer.py`, `analysis.py`, `market*.py` —
  scope consumers, not scope producers.
- `db.py` beyond the `roles`, `user_roles`, `document_role_access` and `audit_events` DDL
  and the migration block at lines 630-660. I did not audit `init_db`'s other migrations.
- `scripts/seed_access.py` — grepped for `kind`/`admin` to establish what a correctly
  seeded database looks like; not read in full. `test_seed_access.py` covers the
  capability/discipline split properly there, which is why finding 6 is scoped to
  `test_admin.py`.
- The frontend beyond `Shell.tsx:1-100`: `AdminView.tsx`, `AdminScreen.test.tsx` and
  `AdminView.test.tsx` were only grepped for `setup_token`.
- `test_conversations_ownership.py`, `test_metrics_host_telemetry.py`,
  `test_classification_api.py`, `test_auth_required_mode.py`, `test_access_schema.py`,
  `test_seed_access.py` — read by test name and by the specific passages quoted above, not
  line by line. `test_auth.py`, `test_admin.py` and `test_access_routes.py` were read in
  full.
- **Nothing was executed.** No test was run, no mutation was planted, no server was
  started. Findings 1, 3, 4 and 6 are the ones a run would settle fastest: for 6, set the
  fixture's `admin` role to `kind='capability'` and confirm `test_the_admin_capability_is_
  not_a_discipline` still passes (proving it never read the column); for 3, start with
  `AUTH_MODE=disabled` and `curl -X DELETE /api/admin/users/<the admin's id>` with no
  header.
