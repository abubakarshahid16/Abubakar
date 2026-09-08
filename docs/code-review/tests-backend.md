# Backend test sweep — tests that pass while the thing they claim to test is not held

Boundary stated first, because an unstated one is itself a defect here.
**23 of the 76 files in `backend/tests/` were opened.** 11 read in full, 12 read
in targeted sections. The rest were not opened at all and are listed under
*Not reviewed*. Every finding below is anchored to a line I read.

## What I ran, and what it returned

Only python3.10 is available on the machine I could reach the repo from
(`$HOME/mnt/Rag_chatbot` is mounted into a Linux VM; the repo's `.venv` is the
Windows one). `app/classification.py:54` does `from datetime import UTC`, which
needs 3.11, so **every test file that imports `app.main` could not be collected
here**. That is an environment limit, not a repo defect.

| command | result |
|---|---|
| `python -m pytest tests/test_seed_access.py -q` | **20 passed in 24.89s** (observed) |
| `python -m pytest tests/test_access_schema.py tests/test_source_hygiene.py tests/test_assertions.py -q` | **32 passed in 7.26s** (observed) |
| `python -m pytest tests/test_recommendation_gate.py -q` | **1 collection error** — `ImportError: cannot import name 'UTC' from 'datetime'` (py3.10) |
| `python -m pytest tests/test_market_no_document_leak.py tests/test_access_schema.py -q` | **1 collection error**, same cause |
| `python -c` probe: `market_phrase.market_phrase(q, CORPUS_FILENAMES)` for all 11 `QUESTIONS` | 3 returned `None` (output quoted in F8) |
| `python -c` probe: load `scripts/seed_access.py`, check attributes | `has upsert_user: False`, `has seed_user: True` |

I did **not** run the whole suite and I did **not** mutate any source, so every
"would stay green" below is reasoned from the code plus, where noted, a
directly observed fact. Nothing here is a claimed pass I did not see.

---

## F1 — critical — the assertion the test was rewritten to add never executes

**`backend/tests/test_seed_access.py:180-192`**,
`test_granting_a_document_to_the_admin_capability_reaches_its_holders`

```python
    # THE HALF THE OLD TEST NEVER CHECKED: does it actually reach anybody?
    from app import access
    seed.upsert_user(conn, "boss@x", "pw-not-used-here", ["IT", "admin"]) \
        if hasattr(seed, "upsert_user") else None
    holder = conn.execute(
        """SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id
           WHERE r.name = 'admin' LIMIT 1""").fetchone()
    if holder is not None:
        assert "doc_x" in access.scope_for_user(holder["user_id"]).allowed_document_ids, (
            "a document granted to the admin capability did not reach a user "
            "holding it - which is what the refusal this replaced assumed")
```

**What it claims.** By its own comment, that a document granted to the `admin`
capability actually reaches a user who holds that capability — the half the
previous version of this test never checked.

**What it actually asserts.** Nothing. `scripts/seed_access.py` has no
`upsert_user`; the function is `seed_user` (`scripts/seed_access.py:167`).
Measured directly: `has upsert_user: False`. So the conditional expression
evaluates to `None`, **no user is ever created**, `holder` is `None`, and the
`if holder is not None:` body — the entire point of the test — is skipped. The
test's remaining assertions cover only `seed.grant()`'s return code, the row
count and the word "capability" in stderr. Observed: the file reports
**20 passed**.

This is the recorded pattern in its purest form: a fixture that cannot produce
the condition, wearing a comment that says it now can. It is worse than the
`_hit`-factory case in the audit, because a reader who checks the diff sees the
missing half being added.

**Mutation that should turn it red.** Make `access.scope_for_user` drop
capability-role grants — e.g. add `AND r.kind = 'discipline'` to the
`document_role_access` join. **It would not**, because `scope_for_user` is
never called: `holder` is `None`. Nor would deleting the `access` import.

**Smallest fix.** Call the function that exists and drop the guard:

```python
    seed.seed_user(conn, "boss@x", ["IT", "admin"], force=True)
    holder = conn.execute(...).fetchone()
    assert holder is not None, "the fixture created no admin-capability holder"
    assert "doc_x" in access.scope_for_user(holder["user_id"]).allowed_document_ids
```

The `assert holder is not None` is the cheap form of the rule — make the
fixture prove it produced the condition, in the fixture.

---

## F2 — critical — the "never certifies" guarantee is asserted against the test's own stub, and the guard that really holds it has no test at all

**`backend/tests/test_analysis_routes.py:274-283`**,
`test_a_recommendation_never_says_a_design_is_compliant_or_approved`

```python
def test_a_recommendation_never_says_a_design_is_compliant_or_approved():
    """The system advises what to verify. It does not certify."""
    ingest()
    out = analysis.recommendation(
        "is the coating compliant", access.unrestricted_scope(),
        generate=fake_generate("The coating is 280 um [S1]."),
    )
    text = (out["recommendation"] or {}).get("text", "")
    for word in ("is compliant", "is approved", "is safe", "certified"):
        assert word not in text.lower()
```

**What it claims.** A product-level honesty invariant: the advisory layer never
tells an engineer a design is compliant, approved, safe or certified.

**What it actually asserts.** That four literal strings are absent from
`"The coating is 280 um [S1]."` — a string this test wrote itself. The only
text that can reach `text` is the stub's own reply, and the stub's reply
contains none of the four phrases. The test asserts the shape of its own mock.
It fails question 2 and question 1 together.

It also fails question 5: `(out["recommendation"] or {}).get("text", "")` means
that if the advisory gate refuses (which `analysis.recommendation` legitimately
does — see `test_recommendation_gate.py`), `text` is `""` and the loop asserts
the absence of words from an empty string. There is no positive control that
anything rendered.

**Mutation that should turn it red.** Delete the rule from the prompt —
`app/synthesis.py:232`, `"Never state that a design is compliant, safe or
approved."` — which is the *only* place in `app/` that addresses this wording
(grep for `compliant|certif|approved|is safe` across `app/*.py` returns that
line, one historical comment at `synthesis.py:600`, and `app/assertions.py`).
The test **would not** go red: no code reads that prompt line, and the stub
never emits the words.

**And the real guard is untested end to end.** `app/synthesis.py:602-605` is
the mechanism that actually holds this invariant:

```python
        asserted = sorted(assertions.unsupported(sentence, spans))
        if asserted:
            dropped.append((sentence, assertions.reason(asserted[0])))
            continue
```

`tests/test_assertions.py` tests `assertions.unsupported()` as a pure function
and nothing else. Grepping the whole test tree for `assertions.reason`,
`REASONS`, `"claims compliance"` or `"no cited span claims"` finds only
`test_assertions.py:96-100`. `test_synthesis.py:610-627` looks like it covers
the case — it feeds `Stub("The design is compliant.")` — but it passes for a
different reason: that sentence cites no source, so `out.text is None` comes
from the citation rule, not from `assertions`. **Delete `synthesis.py:602-605`
and the backend suite stays green**, and the live defect the module exists for
("quality-controlled data COMPLIANT WITH RELEVANT STANDARDS" over a span that
says only that data went through quality control) returns.

**Smallest fix.** Make the stub emit the claim, over evidence that does not
support it, and assert the drop with its reason plus a positive control:

```python
    out = analysis.recommendation(
        "is the coating compliant", access.unrestricted_scope(),
        generate=fake_generate(
            "The coating is compliant with relevant standards [S1]. "
            "Verify the thickness against the datasheet [S1]."),
    )
    rec = out["recommendation"]
    assert rec is not None, out.get("recommendation_refusal")   # positive control
    assert "compliant" not in rec["text"].lower()
    assert "Verify the thickness" in rec["text"]                # the honest half survived
```

Neither `COATING` nor `VIBRATION` span asserts conformance, so the fixture can
produce the condition. This version goes red the moment `synthesis.py:602-605`
is removed.

---

## F3 — high — the counter test reimplements the production increment it is testing

**`backend/tests/test_audit_findings.py:115-149`**,
`test_documents_completed_counts_documents_not_stage_invocations`

```python
    def cycle(target: str) -> None:
        before = worker._is_finished(target)
        worker.process(target)
        if not before and worker._is_finished(target):
            worker._completed.add(target)
```

**What it claims.** That `documents_completed` counts documents rather than
stage invocations — the field "added to fix that class of dishonesty", per its
docstring.

**What it actually asserts.** That the four lines the test itself wrote count
documents. `worker.process()` never touches `_completed`; the only production
site is the worker loop, `app/ingest.py:222-226`:

```python
                before = self._is_finished(doc_id)
                self.process(doc_id)
                if not before and self._is_finished(doc_id):
                    self.last_progress = time.time()
                    self._completed.add(doc_id)
```

`cycle()` is a line-for-line copy of it minus `last_progress`. The test
exercises its own copy, not the worker's.

**Mutation that should turn it red.** Delete the `if not before and
self._is_finished(doc_id)` guard from `ingest.py` and unconditionally
`self._completed.add(doc_id)` — the original 2→8→12 defect, restored. The test
**would not** go red. Grep confirms `documents_completed` / `_completed` appear
in no other test except `test_health.py:59`, which only asserts the field is
*absent* from `/api/health`. So nothing in the suite watches the real
increment, and `last_progress` — the field the audit calls "the honest progress
signal" — is set on the same line and equally uncovered.

**Smallest fix.** Drive the loop instead of the stage. Either run the worker
thread over a queue of one document, or extract `ingest.py:222-226` into a
`_process_and_count(doc_id)` method and have both `_run` and the test call
*that*. Then delete `cycle()`.

---

## F4 — high — the admin-route table promises an enumeration guard that does not exist

**`backend/tests/test_admin.py:39-51`**

```python
# Method, path, and a body where the route takes one. The 404 test walks this
# table so a route added later without an admin check cannot slip past it by
# not being listed - adding a route to main.py and forgetting it here is
# visible as a route this table does not mention.
ROUTES = [ ... 7 hand-written entries ... ]
```

**What it claims.** That forgetting to add a new admin route to this table is
*visible*. Both `test_non_admin_gets_404_on_every_admin_route` and
`test_an_admin_reaches_every_route` are parametrised over it, and the file's
docstring is otherwise a model of the anti-vacuity discipline.

**What it actually asserts.** Only that these seven specific routes behave. No
test compares `ROUTES` with the app's actual route table — grep for
`app.routes` / `openapi()` in `test_admin.py`, `test_auth.py`,
`test_auth_required_mode.py`, `test_api_contract.py`, `test_runtime_contract.py`
returns nothing. `app/main.py` currently declares exactly seven
`/api/admin/*` routes, so the table happens to be complete today — the claim is
true and unenforced, which is entry 15's shape: *a comment without a test reads
as a guarantee*.

**Mutation that should turn it red.** Add `@app.get("/api/admin/audit")` to
`main.py` with `scope: AccessScope = Depends(access.current_scope)` instead of
`Depends(admin_mod.current_admin)` — a new admin route readable by any
authenticated caller. Nothing goes red, and the comment says something would.
(The one admin-gated route already outside the prefix,
`PUT /api/documents/{document_id}/classification` at `main.py:842`, *is*
covered — `test_classification_api.py:262` and `:280` drive both halves — so
this is about the next route, not a present hole.)

**Smallest fix.** Derive the table, or assert it covers the app:

```python
def test_the_route_table_names_every_admin_route_on_the_app():
    live = {(m, r.path) for r in app.routes
            for m in getattr(r, "methods", set())
            if r.path.startswith("/api/admin")}
    assert live == {(m, p) for m, p, _ in ROUTES}, live ^ {(m, p) for m, p, _ in ROUTES}
```

---

## F5 — high — deny-by-default is asserted against a re-typed copy of the production resolver

**`backend/tests/test_access_schema.py:58-74`**, used by
`test_a_user_with_no_grant_sees_nothing` (:79),
`test_a_user_with_a_role_but_no_document_grant_still_sees_nothing` (:89),
`test_a_grant_is_visible_only_to_the_role_that_holds_it` (:103),
`test_two_users_never_share_scope` (:117)

```python
def _visible_to(conn, user_id) -> set[str]:
    """The scope resolver, as the auth layer will express it.
    ...
    """
    return {r["document_id"] for r in conn.execute(
        """SELECT DISTINCT dra.document_id
           FROM user_roles ur
           JOIN document_role_access dra ON dra.role_id = ur.role_id
           WHERE ur.user_id = ? AND dra.permission = 'read'""", (user_id,))}
```

**What it claims.** The file docstring: *"The one thing this schema is for:
absence of a grant means no access."* Four tests named for that property,
including "THE property. Not 'sees less' - sees nothing."

**What it actually asserts.** That SQLite joins correctly. `_visible_to` is a
character-for-character duplicate of the query inside
`app/access.py:144-153` (`scope_for_user`), retyped in the test file. Nothing
in this file imports `app.access`.

The docstring's defence — *"NO AUTHENTICATION IS WIRED INTO ANY ROUTE by this
schema, and these tests do not pretend otherwise ... they are written first,
before anything reads these tables"* — was true when written and is now stale:
`access.scope_for_user` exists, is used by `access.current_scope`, and
`test_classification_independence.py:89-91` already calls it. So the file is a
spec that outlived the implementation it was specifying, which is question 7.

**Mutation that should turn it red.** Replace the body of
`access.scope_for_user` with
`AccessScope(user_id=user_id, allowed_document_ids=frozenset(r["id"] for r in conn.execute("SELECT id FROM documents")), ...)`
— deny-by-default deleted at the source. All four tests **stay green**.
(`test_access_routes.py` would catch it at route level, which is why this is
high and not critical — but the four tests named for the property would not.)

**Smallest fix.** Call the real thing:

```python
from app import access
def _visible_to(conn, user_id) -> set[str]:
    return set(access.scope_for_user(user_id).allowed_document_ids)
```

and delete the duplicated SQL. Nothing else in the file needs to change.

---

## F6 — high — "an unsigned or absent token reaches no documents", asserted against a database with no documents

**`backend/tests/test_auth.py:209-213`**,
`test_an_unsigned_or_absent_token_reaches_no_documents`

```python
def test_an_unsigned_or_absent_token_reaches_no_documents():
    client = TestClient(app)
    for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "nonsense"},
                    {"Authorization": "Bearer not.a.token"}):
        assert client.get("/api/documents", headers=headers).json() == []
```

**What it claims.** That four malformed-or-absent credentials reach nothing.

**What it actually asserts.** That an empty corpus lists nothing. The test calls
neither `make_user` nor `grant_document`, and `temp_storage` (`:31-45`) builds a
fresh `t.sqlite` per test with `db.init_db()` and creates no rows. `[]` is the
only possible answer for **any** scope, including `unrestricted_scope()`.

**Mutation that should turn it red.** Add a development-convenience fallback to
`access.current_scope` — `if "authorization" not in request.headers: return
unrestricted_scope()`, or make `auth.read_token` return a default subject on a
parse failure. The test **would not** go red: there is no document to leak.
(`test_deleting_a_user_cascades_and_does_not_crash` at `:273` and the
deactivation test at `:255` do create `doc_aaa` and would catch the
`resolve_user_id`→`None` fallback; the *unparseable-token* branch is caught by
nothing.)

**Smallest fix.** One line before the loop, and one after:

```python
    a, role_a = make_user("a@x.test", PASSWORD_A)
    grant_document(role_a, "doc_aaa")
    ...
    # positive control: the same route with a valid token DOES return it
    ok = client.get("/api/documents",
                    headers={"Authorization": f"Bearer {auth.issue_token(a)}"})
    assert [d["id"] for d in ok.json()] == ["doc_aaa"]
```

---

## F7 — medium — the answer-route scoping test cannot fail, and its sibling has no positive control

**`backend/tests/test_access_routes.py:161-167`**

```python
def test_answer_cannot_quote_a_hidden_document(two_documents):
    client, visible, hidden = two_documents
    body = client.get("/api/answer", params={"q": "coating dry film thickness"}).json()
    passage = body.get("passage")
    if passage:
        assert passage["document_id"] == visible
```

Two independent ways this passes without holding anything:

1. **`if passage:`** — if `/api/answer` returns no passage (relevance floor,
   refusal, no vectors, a 4xx body with no `passage` key), the assertion never
   runs. No positive control asserts a passage was produced.
2. **The query favours the visible document even unscoped.** `visible.pdf`
   carries *"Coating system no. 1 shall have a nominal DFT of 280 um"* ×6;
   `hidden.pdf` carries *"Stripe coating shall be applied to every weld
   seam"* (`_upload`, `:96-97`). For `q="coating dry film thickness"` the
   visible document is the better match on three of four terms.

**Mutation that should turn it red.** Delete the scope argument from the answer
path so it retrieves over the whole corpus. Neither route to failure fires:
the top passage is still `visible`, and if it is `None` the assertion is
skipped.

**Smallest fix.** Assert the passage exists, and aim the query at the hidden
document so the fixture can produce the condition:

```python
    body = client.get("/api/answer", params={"q": "stripe coating weld seam"}).json()
    passage = body.get("passage")
    assert passage is not None, body      # positive control
    assert passage["document_id"] == visible
```

**Same file, `test_search_cannot_reach_a_hidden_document` (:152-158)** asserts
`hidden not in got` and `got <= {visible}` — both true of an empty hit list. Add
`assert got, "search returned nothing; this proved nothing"`. Everything else in
this file is sound, including the `assert visible != hidden` fixture guard the
audit describes and the genuinely-parallel concurrency test.

---

## F8 — medium — measured: 5 of 17 parametrised leak cases run zero assertions, including the bare-filename one

**`backend/tests/test_market_no_document_leak.py:178-186`**

```python
def _all_payloads_for(question: str) -> list[dict]:
    phrase = market_phrase.market_phrase(question, CORPUS_FILENAMES)
    if phrase is None:
        return []
    return [market_providers.build_payload(phrase, tier=tier)
            for tier in market_providers.TIERS]
```

Every caller is `for payload in _all_payloads_for(question):`. When the phrase
is `None`, the list is empty and the loop body — the whole assertion — is
skipped silently.

**Measured on the repo, not inferred.** Running `market_phrase.market_phrase`
over the file's own 11 `QUESTIONS`:

```
None <-- p.125 and pp. 12-14 and page 7
None <-- doc13.pdf
None <-- book2-Differential-Equations
```

So `test_the_payload_adds_no_document_text_of_its_own` and
`test_no_opaque_corpus_filename_or_stem_ever_reaches_a_payload` each report
**11 green cases of which 3 assert nothing**, and
`test_a_question_carrying_no_document_phrasing_leaks_nothing_at_all` reports 6
of which 2 assert nothing (`"p.125 and pp. 12-14 and page 7"`, `"doc13.pdf"`).

The sharpest instance: `[doc13.pdf]` — a question that is *nothing but a corpus
filename*, the single most on-point input for "no opaque filename ever reaches a
payload" — is one of the three that runs no assertion. `None` is the correct
*behaviour* here; the defect is that the test reports it as coverage.

This file is otherwise the best in the suite, and it already knows the rule: two
of its tests write `assert payloads` (`:311`, `:342`) and one asserts the
fixture's own weight (`:161`). The inconsistency is the finding.

**Mutation that should turn it red.** Add an `original_question` field to
`build_payload`. It is caught — by the other 8 questions. What is *not* caught
is any change specific to the filename-only or page-reference-only input path,
because those cases never reach `build_payload`.

**Smallest fix.** Split the lists and assert the intent of each:

```python
#: These deliberately yield no phrase - None means DO NOT SEARCH.
NO_PHRASE_QUESTIONS = ("p.125 and pp. 12-14 and page 7", "doc13.pdf",
                       "book2-Differential-Equations")

@pytest.mark.parametrize("question", NO_PHRASE_QUESTIONS)
def test_a_question_that_is_only_corpus_metadata_yields_no_phrase(question):
    assert market_phrase.market_phrase(question, CORPUS_FILENAMES) is None
```

and in `_all_payloads_for`, `assert phrase is not None, question` for the
remaining lists so a future narrowing of the whitelist cannot silently empty
the leak sweep.

---

## F9 — medium — the "every GET route" leak sweep substitutes only two of the five path parameters

**`backend/tests/test_no_internal_leaks.py:101-117`**

```python
    for path in routes:
        for ident in HOSTILE_IDS + [doc_id]:
            url = path.replace("{document_id}", ident).replace("{page_no}", "1")
```

**What it claims.** Docstring: *"this file does not test one endpoint. It
enumerates EVERY route on the app ... A new endpoint is covered the moment it
is added."*

**What it actually asserts.** Only `{document_id}` and `{page_no}` are
substituted. `app/main.py` also declares
`/api/progress/{progress_id}`, `/api/reports/{report_id}/verify`,
`/api/reports/{report_id}/download` and
`/api/conversations/{conversation_id}`. For those four the URL keeps its literal
brace text, so each is exercised with exactly one non-hostile value — never
with any of the 8 `HOSTILE_IDS`, and never with a *valid* id, which is the
branch where a handler formats real data and where `last_error` leaked in the
first place. The existing guard (`assert routes`, `:104`) checks the sweep found
routes, not that it reached them — standing rule 14 applied one level short.

**Mutation that should turn it red.** Have
`GET /api/reports/{report_id}/verify` include the report's absolute path in its
404 detail, or return a traceback for a malformed `report_id`. The sweep
**would not** go red for any of the 8 hostile ids, because none is ever
substituted into that path.

**Smallest fix.** Substitute generically and add the positive control the
docstring implies:

```python
    reached = set()
    for path in routes:
        for ident in HOSTILE_IDS + [doc_id]:
            url = re.sub(r"\{[^}]+\}", ident, path).replace(f"/{ident}/image", "/1/image")
            r = client.get(url)
            if r.status_code != 404 or "detail" in r.text:
                reached.add(path)
            assert_clean(r.text, f"GET {url} -> {r.status_code}")
    assert reached == set(routes), f"never actually reached: {sorted(set(routes) - reached)}"
```

---

## F10 — medium — two loop-only tests over runtime output with no non-empty guard

Both are the neighbour-inconsistency shape: adjacent tests in the same files
carry the guard and these do not.

**a. `backend/tests/test_facet_identity.py:240-263`**,
`test_every_emitted_facet_has_rows_and_a_name` — *"The invariant behind the
three cases above, asserted over all of them."*

```python
    for question, evidence in corpora:
        out = _clusters(question, evidence)
        names = [c.facet for c in out]
        assert len(names) == len(set(names)), f"two facets with one name: {names}"
        for c in out:
            assert c.rows, ...
```

If `_clusters()` returns `[]` for all three corpora, `names` is empty,
`len([]) == len(set([]))` holds, and the four inner assertions never run.
**Mutation:** make `claims.cluster` return `[]` whenever the question has more
than three terms — the third corpus is a 12-word question. Green.
**Fix:** `assert out, f"{question!r} produced no clusters"` inside the loop.

**b. `backend/tests/test_analysis_routes.py:460-465`**,
`test_without_a_baseline_nothing_claims_to_be_met_or_a_gap`

```python
    for item in _items("coating thickness", BURIAL):
        assert item["status"] not in ("met", "possible_gap"), item
```

An empty item list passes. Two tests below it (`:470` and `:530`) write
`assert items, "no items produced"` / `assert addition, "the fixture produced
no addition cluster; this test would be vacuous"` — the discipline is present in
the file and missing here.
**Fix:** `items = _items(...); assert items, "no items produced"` then loop.

---

## F11 — low — the copy sweep blanks every triple-quoted string, not only docstrings

**`backend/tests/test_copy_matches_reality.py:81-88`**

```python
_PY_DOC = '\"\"\".*?\"\"\"'
_BLOCK = re.compile(_JSX_BLOCK + '|' + _PY_DOC, re.S)
```

`_without_block_comments` blanks *all* triple-quoted regions before scanning,
so a denial phrase inside a triple-quoted **message string** — not a docstring
— is exempt. The file's own reasoning is that a comment may say a claim used to
be made, and that exemptions must be per-phrase rather than per-file; a blanket
triple-quote exemption is a per-syntax file-level exemption by another door.

**Mutation:** in `app/metrics.py`, write
`message = """These pages are not searchable: OCR is not implemented."""`.
The sweep stays green while the Dashboard renders the exact string the file was
written to catch.
**Fix:** only blank a triple-quoted region when it is the first statement of a
module, class or function (use `ast`), or scan the value of every string literal
via `ast.walk` instead of blanking text.

Everything else here is sound, including `test_the_scan_covers_more_than_zero_files`
(the guard-the-guard) and the empty `EXEMPTIONS` with a live expiry mechanism.

---

## F12 — low — a `pytest.skip` that is unconditional in practice

**`backend/tests/test_analysis_routes.py:534-548`**,
`test_an_unnormalisable_unit_is_insufficient_evidence_not_a_gap`

```python
    unresolved = [c for c in clusters if c.label == "unresolved"]
    if not unresolved:
        pytest.skip("this corpus fixture produced no unresolvable unit; "
                    "the mapping is asserted directly below instead")
```

The fixture is a single fixed sentence (`"Torque shall be 40 klbf-ft at the
flange."`), so the skip is deterministic — it either always fires or never
does, and the test name promises a behaviour the run may never check. It is
honestly reasoned and the mapping *is* asserted directly at `:551`
(`test_the_label_to_status_mapping_is_exhaustive_and_honest`), which is why this
is low. But conftest prints skips as "these proved nothing", and a permanent
entry in that list is noise that trains people to ignore it.
**Fix:** either assert `unresolved` is non-empty (making `klbf-ft` a pinned
unnormalisable unit) or delete the test and keep the direct mapping assertion.

---

## F13 — low — the OCR ordering test asserts an answerable end state, not a finished one

**`backend/tests/test_ocr.py:356-366`** — this is the *fixed* version of audit
entry 7 and it is now correct about the thing that bit: it asserts
`row["status"] != states.FAILED` and that recognised text reached a chunk.
One notch remains: `assert row["status"] in states.ANSWERABLE_STATES` admits
`partially_searchable`, which is **not terminal**, and `indexed_at` — the field
the audit names as "the field to trust for 'did this finish'" — is not read.
**Fix:** add `assert states.is_terminal(row["status"])` and
`assert row["indexed_at"] is not None`, matching
`test_worker_health.py:82`'s discipline.

---

# Coverage of this sweep

## Read in full (11 files)

`conftest.py`, `test_access_routes.py`, `test_access_schema.py`,
`test_classification_independence.py`, `test_market_no_document_leak.py`,
`test_market_transport.py`, `test_recommendation_gate.py`,
`test_synthesis_honest_gate.py`, `test_no_internal_leaks.py`,
`test_copy_matches_reality.py`, `test_assertions.py`.

## Read in targeted sections (12 files)

`test_admin.py` (1-320), `test_auth.py` (1-340), `test_auth_required_mode.py`
(300-348), `test_seed_access.py` (1-40, 170-215),
`test_upload_requires_identity.py` (150-200), `test_ocr.py` (assertion index +
288-380), `test_analysis_routes.py` (1-60, 200-300, 440-562),
`test_synthesis.py` (140-175, 608-640), `test_synthesis_map_reduce.py`
(280-312), `test_market_phrase.py` (185-215), `test_market_secret_hygiene.py`
(230-300), `test_audit_findings.py` (108-175), plus small windows in
`test_facet_identity.py` (240-270), `test_api_contract.py` (40-75),
`test_worker_health.py` (60-110). `test_watch_folder.py`,
`test_classification_api.py` and `test_conversations_ownership.py` were read
only as function-name/docstring listings and greps, not line by line — treat
them as **not reviewed** for the seven questions.

I also ran an AST pass over all 76 files for the mechanical shapes: asserts
inside `if`, loop-only assertions with no function-level assert, `assert True`,
`assert isinstance` as the sole assertion, `except Exception` inside a test,
`hasattr`/`getattr` probes, and every `xfail`/`skip`/`skipif`. F1, F10 and F12
came out of that pass; the remaining hits were assertions over static
parametrised constants, which cannot be empty.

## Guarantees I checked that ARE properly held

| Guarantee | Test | Mutation it catches |
|---|---|---|
| A hidden document is indistinguishable from a missing one on 5 read routes and the stage-write route | `test_access_routes.py:122`, `:170` — compares status, code *and* message against an unknown id, and asserts the **allowed** read is 200 in the same test | returning 403 instead of 404 for a scoped-out document, or dropping the scope check on any one of the six routes |
| `/api/metrics` is scoped (audit entry 15) | `test_access_routes.py:180` — `assert client.get("/api/metrics").json()["corpus"]["documents"] == 0` for a user with no grants; `:199` asserts a filename never reaches `warnings()` for `no_searchable_content`, with the state manufactured rather than waited for | reverting `metrics_mod.snapshot(...)` to ignore the resolved `AccessScope` |
| A scope is never shared between concurrent requests | `test_access_routes.py:248` — two real threads, 12 requests each, identity per request | caching the scope in module state or a mutable default |
| The shipped default `auth_mode` is `disabled` | `test_access_routes.py:293` — `Settings(_env_file=None)`, not the conftest-pinned singleton | flipping the shipped default, or reading the developer's `backend/.env` |
| Classification cannot move an access decision, in both directions, at read *and* write level | `test_classification_independence.py:112`, `:167`, `:187`, `:266` — the write-level one uses `set_trace_callback` and asserts the tracer saw `document_classification`, so "no access table appeared" cannot be true of an empty list | adding a FK from `document_classification` to `roles`, or an `INSERT INTO document_role_access` inside `classification.confirm` |
| Only the typed phrase leaves the machine | `test_market_no_document_leak.py:230/259/278` (content), `:413/430` (closed field set + reviewed field names), `:452/464/473/484` (refusal, not sanitisation), `:519/551/564/579` (AST import split), with `:161` asserting the corpus fixture's own n-gram weight and `:541` proving the AST scanner finds a known import | adding a `context` field to the payload, importing `search` into `market.py`, truncating an over-long phrase instead of raising, or moving the HTTP client out of `market_transport.py` |
| The character limit and the word limit each refuse on their own | `test_market_no_document_leak.py:357`, `:375` — each input is constructed to be refusable by exactly one guard, because a mutation showed the other was covering it | deleting either check independently |
| Egress is inert unless both flags are true | `test_market_transport.py:62` (all three not-both combinations), `:81` (real route, `httpx.Client` construction made an error), `:99` (a retained fetch refuses after the flags drop) | building a transport on one flag, or a cached client surviving a settings change |
| A refused host never reaches the socket; no redirects, no cookies, no `trust_env`; the error names the host and not the URL | `test_market_transport.py:168`, `:186`, `:209` — with `_FakeResponse` carrying the **real** requested URL, documented as the fix for a fake that had hidden a mutation | putting the full URL in the HTTP error message, or following a 302 out of the allowlist |
| A reference numeral is not a measurement, and a measurement still is | `test_synthesis_honest_gate.py:141` (24 cases) and `:171` (14 cases), each asserted at unit level *and* end to end through `summarise` | widening the reference patterns until they swallow "50 mm", or narrowing them until "Document 17" is a claim again |
| A summary never opens with a dangling fragment, and one made only of fragments is refused | `test_synthesis_honest_gate.py:267`, `:286`, `:303` — asserts the promoted order and `api["summary"] is None` | deleting the promotion pass, or rendering the fragment alone as the live defect did |
| Four model failures are four different sentences, and the raw completion is kept | `test_synthesis_honest_gate.py:329-410` — including `assert len({...}) == 5` | collapsing "the model returned nothing" into "the model declined" |
| Every finding carries a resolving citation, over 7 shapes of model output | `test_synthesis.py:139-161` — with `assert produced >= 6, "the fixtures never produced findings; this proved nothing"` | letting an uncited sentence through `_cite`, or citing an evidence id not in `positional_evidence_ids` |
| A non-admin gets 404 on every admin route **and** an admin reaches every one | `test_admin.py:165` + `:182` over one shared table, with the unknown-id placeholder swapped for a real user in the reachability run | deleting the admin dependency (404 test red), or refusing admins (reachability test red) — neither half can pass alone |
| Revoke, grant and deactivation all take effect on the **next request**, not the next login | `test_admin.py:220`, `:242`, `:255` — one token issued before the change and reused after, with a before-assertion so an always-empty scope cannot pass | adding a scope cache with no invalidation |
| A setup token is shown once and stored only as a hash | `test_admin.py:275` — asserted on the raw body, plus the DB column, plus `:311` proving two users get different tokens | storing plaintext, or returning a constant token |
| A token cannot be forged, repackaged, expired-and-reused, or signed with another secret | `test_auth.py:224-262` | dropping the signature check, or trusting the `u` claim without re-verifying |
| The scope never comes from the request | `test_auth.py:219` — a valid token for user A plus a header, query parameter, cookie and role header all claiming user B | a resolver that reads a header "just for the admin UI" |
| Login refusals are one shape, and the rate limiter does not reintroduce the enumeration oracle it closed | `test_auth.py:107`, `:124`, `:307` | a distinct message for an unknown address, or a limiter that engages only for real accounts |
| A fully scanned PDF is never called `ready`; nor is one whose every chunk is excluded | `test_no_internal_leaks.py:235`, `:252` — asserts status, terminality, non-answerability, error code *and* a stated reason | reporting `ready` on `chunk_count == 0`, or leaving `error_message` empty |
| No client mistake is reported as `internal`, and every 2xx is typed | `test_no_internal_leaks.py:193`, `:214`, `:285` — the typed-response test reads whichever 2xx the route declares, not just "200", after that exact narrowness made it lie both ways | returning `internal` for a bad parameter, or shipping a route whose 201 body is undeclared |
| The document status enum in the contract matches the state machine | `test_no_internal_leaks.py:343` | advertising a status the system cannot produce, or omitting one it can |
| OCR runs only while the document is answerable **and** the document survives it (audit entry 7) | `test_ocr.py:300` — `assert seen, "OCR never ran"`, then every observed status, then the **end** state and that recognised text reached a chunk | restoring the illegal `partially_searchable -> chunking` transition |
| Every non-terminal status resumes to a terminal one without a restart | `test_worker_health.py:65` (4 statuses) and `:86` (partial embedding) — asserts terminality and `indexed_at` | a guard that leaves a resumed document stuck |
| A vacuous *run* cannot pass | `conftest.py:75` (missing models are a `UsageError`, not 90 failures), `:160` (skips printed with reasons), `:199` (`MINIMUM_TESTS` floor on a full run, overridable via `RAGINTEL_MIN_TESTS` so the guard itself can be proven) | a broken conftest or a testpath typo collapsing the run to two tests and exiting 0 |
| Unimplemented specification announces its own completion | `test_recommendation_gate.py:68` — `xfail(strict=True)`; `test_synthesis_map_reduce.py:297` — same, with the measured numbers in the reason | implementing the feature and forgetting to unmark the tests (they go red on xpass) — this is the mechanism that produced audit entry 23 |

The `test_recommendation_gate.py` docstring (`:39-67`) is, as the audit records,
now corrected: the prose describes the eleven that XPASSed and the thirteen
still marked, and the file carries 13 `@PENDING` decorators against 19 test
functions. I could not run it (py3.10), so I did not verify the *counts* the
prose implies against a live collection — flagged here as an unverified claim,
not as a finding.

# Not reviewed

Stated plainly, since an unstated boundary is itself a defect in this project.
**53 of the 76 files** in `backend/tests/` were not opened. I read no line of:

`test_acronyms.py`, `test_advice_refusal.py`, `test_analysis_accuracy.py`,
`test_answer.py`, `test_api_contract.py` (except 40-75), `test_chat.py`,
`test_chunker.py`, `test_claims.py`, `test_clause_headings.py`,
`test_classification_api.py` (greps only), `test_classification_suggest.py`,
`test_context_budget.py`, `test_conversations_ownership.py` (greps and one
window only), `test_correctness_fixes.py`, `test_coverage_report.py`,
`test_embedder.py`, `test_eval_provenance.py`, `test_eval_scoring.py`,
`test_extract.py`, `test_facet_identity.py` (240-270 only), `test_health.py`,
`test_highlight.py`, `test_intent.py`, `test_keyword.py`, `test_ligatures.py`,
`test_market.py`, `test_market_phrase.py` (185-215 only),
`test_market_recorded_responses.py`, `test_market_secret_hygiene.py` (230-300
only), `test_metrics.py`, `test_metrics_host_telemetry.py`,
`test_named_documents.py`, `test_progress.py`, `test_quality_gate.py`,
`test_rates.py`, `test_recommendation_from_gaps.py`, `test_register_import.py`,
`test_relevance_floor.py`, `test_reports.py`,
`test_reports_suppressed_count.py`, `test_rerank_scale.py`,
`test_runtime_contract.py`, `test_search.py`, `test_settle_guard.py`,
`test_source_hygiene.py` (ran, not read), `test_stage_atomicity.py`,
`test_symbols.py`, `test_typo_tolerance.py`, `test_upload.py`,
`test_upload_requires_identity.py` (150-200 only), `test_vectorcache.py`,
`test_watch_folder.py` (function/docstring listing only), `test_worker_health.py`
(60-110 only).

Two priority-1 and priority-2 files in particular deserve a second pass that
this sweep did not give them: **`test_watch_folder.py`** (979 lines, an
ingestion state machine plus an admin path-disclosure boundary — I read only its
test names and docstrings) and **`test_reports.py`** (833 lines, the
citation-resolution and suppressed-count honesty invariants — unopened).

What I could not check without running the code: whether any of the
`@PENDING`-marked tests in `test_recommendation_gate.py` now XPASS (a strict
xfail that passes is a failure, so a live run would settle it in one command),
and whether `_clusters`/`_items` in F10 are in fact non-empty today. Running
`python -m pytest tests/test_recommendation_gate.py tests/test_facet_identity.py
tests/test_analysis_routes.py -q` on a Python 3.11+ interpreter would settle
both. F1 and F3 need no run: `upsert_user` does not exist, and `cycle()` is a
verbatim copy of `ingest.py:222-226`.
