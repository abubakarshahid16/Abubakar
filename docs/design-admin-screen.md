# Admin screen — the route contract

**Written before the routes exist, on purpose.** Contract drift cost this
project an hour today: `analysis.py` emitted `claim` where the frontend read
`text`, and `facet` was a string on one side and a list on the other. Both were
found by a 500 in front of a live request rather than by a test. This document
exists so the admin routes are agreed once and implemented once.

**Implement to this file. If a shape here is wrong, change this file first and
say so — do not diverge silently.**

---

## What the screen is for

Today a client cannot add a user, assign a discipline, or grant a document
without opening a terminal and running `scripts/seed_access.py`. That is not
deliverable software. This screen replaces the script for everything except
setting a password.

**It is also the only place the "seeded but useless" state is visible.** A user
with no discipline logs in successfully and sees an empty corpus — during a
demo that looks exactly like broken search. `seed_access.py --verify-only`
already reports it; the screen must too.

---

## The model

`admin` is a **capability**, not a discipline. A person who administers the
system also works somewhere — an IT administrator is IT *and* admin. Modelling
admin as a fifth discipline forces a false choice and means an admin cannot see
their own documents.

| | |
|---|---|
| **Disciplines** | Civil Engineering · Mechanical · Chemical-Process · IT |
| **Capability** | `admin` — orthogonal to discipline |
| **Grants** | document ↔ discipline. Never document ↔ user. |

Grants are per-discipline so that adding a person to a team gives them the
team's documents automatically. A per-user grant would drift out of date the
first time somebody changed role.

---

## Rules every route obeys

1. **Admin-only. A non-admin gets `404`, never `403`.** A 403 confirms the
   route exists and what it guards. This is the same rule the document routes
   already follow, and it must not be relaxed here because the admin surface is
   the most interesting one to probe.
2. **A revoke takes effect immediately** — the document must leave that user's
   search results on their *next request*, not their next login. If any scope
   is cached per session, revoke invalidates it. Say in the implementation
   where that happens.
3. **No secret is ever returned twice.** A setup token is shown once, on
   creation, and never again. The response must say so.
4. **No password is set through the browser.** See "The password decision".
5. Errors use the existing `errors.safe_error` envelope and the codes below.

---

## Routes

| Method | Path | Purpose | Idempotent |
|---|---|---|---|
| `GET` | `/api/admin/users` | List users with disciplines | yes |
| `POST` | `/api/admin/users` | Create a user | no |
| `DELETE` | `/api/admin/users/{user_id}` | Deactivate a user | yes |
| `GET` | `/api/admin/disciplines` | List disciplines + counts | yes |
| `GET` | `/api/admin/grants` | Documents × disciplines | yes |
| `PUT` | `/api/admin/grants` | Grant a document to a discipline | **yes** |
| `DELETE` | `/api/admin/grants` | Revoke | **yes** |

`PUT`/`DELETE` on grants are idempotent so the UI can retry a failed click
without a double-grant, and so a revoke of something already revoked is not an
error.

### `GET /api/admin/users`

```json
{
  "users": [
    {
      "user_id": "usr_a1b2c3d4",
      "email": "ali@example.com",
      "disciplines": ["Civil Engineering"],
      "is_admin": false,
      "active": true,
      "created_at": "2026-09-05T18:12:04Z",
      "last_login_at": null,
      "warning": null
    },
    {
      "user_id": "usr_e5f6a7b8",
      "email": "new@example.com",
      "disciplines": [],
      "is_admin": false,
      "active": true,
      "created_at": "2026-09-05T21:40:00Z",
      "last_login_at": null,
      "warning": "no_discipline"
    }
  ]
}
```

`warning` is `"no_discipline"` or `null`. **Never a string the UI has to parse
for meaning** — the UI switches on the enum and owns the wording.

`last_login_at` is `null` for a user who has never signed in, and **renders as
nothing**, not as a dash or "never".

### `POST /api/admin/users`

```json
{ "email": "new@example.com", "disciplines": ["Mechanical"], "is_admin": false }
```

→ `201`

```json
{
  "user_id": "usr_e5f6a7b8",
  "email": "new@example.com",
  "setup_token": "one-time-value",
  "setup_token_expires_at": "2026-09-06T21:40:00Z",
  "shown_once": true
}
```

`shown_once: true` is the contract that the token is not retrievable again.
The UI must say so beside it, and must not store it.

Errors: `email_in_use` (409) · `unknown_discipline` (422) · `invalid_email`
(422).

### `DELETE /api/admin/users/{user_id}`

Deactivates. **Does not delete.** A user's conversations and reports reference
them, and a hard delete would orphan evidence a report depends on.

→ `200 {"user_id": "...", "active": false}`

An admin cannot deactivate themselves: `cannot_deactivate_self` (409). Without
that rule the last admin can lock everyone out of the system.

### `GET /api/admin/disciplines`

```json
{
  "disciplines": [
    { "name": "Civil Engineering", "user_count": 2, "document_count": 5, "warning": null },
    { "name": "IT",                "user_count": 1, "document_count": 0, "warning": "no_documents" }
  ]
}
```

### `GET /api/admin/grants`

```json
{
  "documents": [
    {
      "document_id": "doc_626b1a92bf6d",
      "filename": "NORSOKM501Rev5.pdf",
      "disciplines": ["Civil Engineering"],
      "warning": null
    },
    {
      "document_id": "doc_a728541bbdc5",
      "filename": "doc13.pdf",
      "disciplines": [],
      "warning": "no_discipline_can_see_this"
    }
  ]
}
```

That third warning matters: a document nobody can see is invisible in every
search and looks like a broken upload.

### `PUT` / `DELETE /api/admin/grants`

```json
{ "document_id": "doc_626b1a92bf6d", "discipline": "Civil Engineering" }
```

→ `200 {"document_id": "...", "discipline": "...", "granted": true|false}`

Errors: `unknown_document` (404) · `unknown_discipline` (422).

**A revoke returns 200 whether or not the grant existed.** The client asked for
a state, and the state is now true.

---

## Error codes the UI switches on

`email_in_use` · `unknown_discipline` · `invalid_email` ·
`cannot_deactivate_self` · `unknown_document` · `not_found`

Anything else renders as a generic failure. **A failed request and an offline
backend must not look the same** — that is a recorded defect in this project.

---

## The password decision

**Passwords are not set through the browser.** Creating a user returns a
one-time setup token; the user redeems it at first sign-in.

Reasons, in order:

1. `seed_access.py` already guarantees *"a password can only ever arrive by
   being typed, interactively, twice"*. Adding a browser path weakens a
   guarantee the repo makes about itself.
2. An admin who types someone's password knows it.
3. A password in a request body is a password in a log — and this project found
   exactly that defect today, in the 422 handler that echoed the submitted
   body back.

The token is single-use, expires in 24 hours, and is shown once.

**Out of scope for this screen and deliberately so:** password reset. It needs
a redemption route and rate limiting of its own. Name it as a gap rather than
half-building it.

---

## What the screen shows

**Users** — email, disciplines, admin flag, created, last login. Row-level
warning for no discipline. Create, and deactivate.

**Disciplines** — name, user count, document count. Warning for a discipline
with no documents.

**Documents** — filename, which disciplines see it, grant and revoke. Warning
for a document nobody can see.

**At the top: the "seeded but useless" summary.** *"2 users have no discipline.
1 discipline has no documents."* This is the state that looks like broken
search, and it should be the first thing an admin sees, not something they find
by scanning three tables.

### Interaction rules

- **Revoke is destructive and must not look neutral.** Quiet until hovered,
  then danger-coloured, and it confirms before acting. Same for deactivate.
- A null renders as **nothing**. Never a zero, never a dash, never "N/A".
- The setup token is shown once, in a block that says it will not be shown
  again, with a copy action.
- One user's data never appears in another's row.

---

## Tests that must exist, each proven red first

| | |
|---|---|
| 1 | A non-admin gets **404** on every admin route — not 403, not 200 |
| 2 | A revoked grant removes the document from that user's search results on the **next request**, not the next login |
| 3 | `setup_token` appears in the create response and in **no** subsequent `GET /api/admin/users` |
| 4 | An admin cannot deactivate themselves |
| 5 | `last_login_at: null` renders as nothing — assert the DOM contains no dash, no zero, no "never" |
| 6 | `PUT` twice on the same grant is not an error and does not double-grant |

Rule 5 is the one most likely to be written vacuously. Assert on a fixture
where the value *is* null, and confirm the test fails if the component renders
a placeholder.

---

## Known gaps this screen does not close

Turning authentication on activates five documented holes in
`docs/design-access-holes.md`: page images bypass the bearer token,
conversations are unscoped, upload is unscoped and its deduplication is an
oracle, `/api/metrics` declares a scope and discards it, and
`DELETE /api/conversations/{id}` takes no scope at all.

**None of these are fixed by this screen.** Fine for a demo you control. Not
fine on a client's machine.
