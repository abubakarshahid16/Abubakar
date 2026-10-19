# Retrieval layer review — search / keyword / lexical / vectorcache / intent / chat / eval

Static review of the files named in the brief, plus their tests and `eval/`.
Nothing was run on the device (read-only, as instructed) and **no test suite was
executed**. Two claims below were verified by *executing FTS5 in the cloud
container* against a reconstruction of `keyword.build_match_query` and the same
tokenizer string; those are marked **(measured here)** and the transcript is
reproducible from the quoted regex alone. Everything else is read from the code.

Counts: 1 critical, 3 high, 8 medium, 3 low.

---

## 1. CRITICAL — a dotted clause number is truncated to its first digit and then REQUIRED, so clause lookups return zero keyword hits and the wrong table is credited with declaring the designator

**`backend/app/keyword.py:71-77`**, consumed at `keyword.py:205-210` and
`search.py:325-338`.

```python
DESIGNATOR = re.compile(
    r"\b(" + "|".join(DESIGNATOR_WORDS) + r")\b"
    r"(?:\s+(?:no\.?|number|nr\.?))?"
    r"\s*[:.]?\s*"
    r"(\d+[A-Za-z]?)\b",          # <- matches "5" out of "clause 5.3.2"
    re.IGNORECASE,
)
```

**What is wrong** The designator value group `(\d+[A-Za-z]?)` cannot span a dot,
so `clause 5.3.2` yields the designator `clause 5`, and `build_match_query`
then makes that truncated phrase a **required** conjunct — while the index
stores `5.3.2` as one token because `.` is a `tokenchar`.

**The failure** (measured here) With one indexed row
`"NORSOK M-501 clause 5.3.2 surface preparation shall apply"`, the query built
from the question `clause 5.3.2 of NORSOK M-501` is

```
"5.3.2" AND ("clause 5" OR "clause no. 5" OR "clause no 5" OR "clause number 5") AND ("clause")
```

and returns **0 rows**. Dropping only the designator conjunct returns 1.
`"clause 5"` alone returns 0; `"5.3.2"` alone returns 1. Same for
`section 7.1 requirements` → requires `"section 7"`, `table 3.4 values` →
`"table 3"`, `grade 5.8 bolts` → `"grade 5"`, `rev 2.1` → `"rev 2"`.
So the *entire keyword side* returns nothing for the clause-and-table lookup
class that `keyword.py`'s own docstring says lexical search exists to get right
("clause `5.3.2` … destroying exactly the lookups lexical search exists to get
right"). Before embedding finishes — the state the module is built for, "a
1,200-page specification is therefore answerable seconds after upload" — that
is a refusal on a question the document answers, with `keyword_candidates: 0`
and no recorded reason.

Second, worse consequence: `search.apply_identifier_boost` decides heading
authority on the same truncated value.

```python
declared = {m.group(2).upper() for m in keyword.DESIGNATOR.finditer(heading)
            if m.group(1).lower() == word}
if value.upper() in declared:
    c.heading_declares = True
```

For the question `table 3.4`, a passage headed **`Table 3.9`** yields
`declared = {"3"}` and `value = "3"`, so it is marked `heading_declares=True`
and gains precedence *and* escapes `conflicts`/`penalty`. Table 3.9's numbers
are then quoted as table 3.4's — the "confidently wrong, reads perfectly
plausible" failure the designator machinery was written to prevent
(`keyword.py:61-66`).

**Smallest fix** Widen the value group to carry the whole dotted number and
keep it one token: `(\d+(?:\.\d+)*[A-Za-z]?)`. That makes the required phrase
`"clause 5.3.2"` (which matches — measured) and makes `Table 3.9` declare
`table 3.9`, not `table 3`.

---

## 2. HIGH — the lexical gate counts term occurrences across the WHOLE corpus, so its verdict and its user-visible refusal are derived from documents the caller may not read

**`backend/app/keyword.py:289-311`** and **`backend/app/lexical.py:192-251`**;
reached from `answer.py:513`.

```python
def term_occurrences(term: str, document_id: str | None = None) -> int:
    ...
    where = "chunks_fts MATCH ?"
    if document_id:
        where += " AND document_id = ?"
```

There is no `allowed_document_ids` parameter — the one parameter `keyword.search`
in the same file calls "REQUIRED and keyword-only … A default would eventually
come to mean 'every document', which is the one thing this parameter exists to
prevent". `indexed_count()` is the same shape.

**What is wrong** `lexical.assess` decides answerability, and the text of the
refusal, from a corpus-wide presence test that never sees the request's scope.

**The failure** Two halves, both concrete.

*Confidentiality.* User B holds a grant on `doc1` only; `doc2` (no grant)
contains "Inconel 625". B asks "what is the coating for Inconel 625".
`term_occurrences("Inconel")` counts `doc2`'s chunks, so the term is **not**
placed in `absent_from_corpus` and the decisive refusal is not produced. For a
term absent everywhere, it is. `base["lexical"]` ships `absent_from_corpus` on
every answer *including every refusal* (`answer.py:514-517`), so B has a
one-term-per-request presence oracle over documents `/api/documents` correctly
hides from them. This is entry 15's shape: a scope resolved at the route and not
carried into the query that decides what the caller is told.

*Honesty.* The refusal reads

```python
reason = f"{joined} {verb} not appear anywhere in the indexed documents"
```

"anywhere in the indexed documents" is a count with an unstated boundary
(standing rule 7): its population is the whole corpus, and its reader is a
caller who may see four documents of twelve.

And the comment that made this look safe is already in the tree —
**`backend/app/coverage.py:26-33`**:

> "The gate runs exactly once, before any per-document reasoning, **on the
> scope the request already had**, and its verdict is final."

The gate runs on the corpus. That sentence is a justification derived from
something adjacent to the truth.

**Smallest fix** Give `term_occurrences` and `indexed_count` a required
`allowed_document_ids` frozenset, bound into the same
`AND document_id IN (...)` clause `keyword.search:259-261` already uses, and
thread the scope from `answer.answer` through `_assess_candidates` into
`lexical.assess`. Correct the coverage.py comment in the same change.

---

## 3. HIGH — `example_questions()` names documents and clause headings outside the caller's scope, and a greeting is enough to read them

**`backend/app/intent.py:212-253`**, called at **`answer.py:457`**.

```python
rows = connect().execute(
    """SELECT c.filename, c.section, COUNT(*) AS n
       FROM chunks c JOIN documents d ON d.id = c.document_id
       WHERE c.retrievable = 1 AND c.section IS NOT NULL
         AND d.status IN ('ready', 'partially_searchable')
       GROUP BY c.document_id, c.section ...
...
question = f"What does {r['filename']} say about {title}?"
```

**What is wrong** The only filter is document status. The function takes no
scope, and `answer()` calls it with none.

**The failure** `GET /api/answer?q=hi` (or any greeting, thanks, "ok", empty
string, or advice request) from a caller granted **nothing** returns
`examples: ["What does <another team's file>.pdf say about <its clause
heading>?", …]`, and `intent.guidance()` embeds the same strings in `answer`,
which `chat._insert_message` then persists into the conversation transcript.
Filename *and* clause title of unreadable documents, from the one input class
that never touches retrieval — "nothing was searched, so nothing may be shown
as considered" is true of passages and false of filenames. No test asserts a
scope here: `test_intent.py:183-202` only checks the examples are non-empty and
answerable.

**Smallest fix** Give `example_questions(allowed_document_ids)` a required
scope, add `AND c.document_id IN (...)`, and pass
`allowed_document_ids` from `answer()` (it already has it, keyword-only).

---

## 4. HIGH — the identifier boost is added to the rerank score, on the RRF scale, with a comment claiming it protects the result

**`backend/app/search.py:743-751`**

```python
for c in shortlist:
    # the identifier boost still applies on top of the rerank,
    # so a semantically plausible passage that omits the
    # identifier cannot displace the one that names it
    c.rerank_score = by_id.get(c.chunk_id, float("-inf")) + c.boost
```

`c.boost = IDENTIFIER_BOOST * top_rrf * (len(hits)/len(wanted))` (`search.py:307`),
i.e. at most `0.5 × (1/61 + 1/61) ≈ 0.0164`.

**What is wrong** This is defect 4 from `scores.py`'s own header —
"IDENTIFIER_BOOST * top_rrf * 2 = 0.0313, computed on the RRF scale (~0.03) and
added to the rerank scale (~±10). It fired on every query and could never change
an outcome" — still live at the sibling call site. Only the *heading* half was
converted to precedence; the identifier half was left adding RRF units to
cross-encoder units.

**The failure** On a scale `RerankScore` documents as "-11 to +10", and against
the 0.15-point margin `search.py:559-561` records as the real-world gap, a
0.0164 addend can never reorder anything. So the stated protection — "a
semantically plausible passage that omits the identifier cannot displace the one
that names it" — does not exist, and the comment is what makes a reader believe
it does. It is also invisible in the response: `to_dict` reports `boost` as a
separate field while `rerank_score` already contains it, so a reader adding them
double-counts.

**Smallest fix** Wrap the two operands in `RrfScore`/`RerankScore` so the
addition raises (that is what `scores.py` exists for), and express the identifier
rule as precedence within the noise band, as `apply_heading_precedence` already
does — or delete the addend and the comment together. Do not leave the comment.

---

## 5. MEDIUM — heading authority cannot fire on the reranked path when the field has two or three scored candidates, and the tiebreak that would cover it is dropped by the post-rerank sort

**`backend/app/search.py:762`** and **`search.py:582-591`**, against
`scores.spread` at **`scores.py:147-161`**.

```python
        pool = shortlist
        ...
        pool.sort(key=lambda c: -c.score)          # line 762 — no tiebreak
```
versus the pre-rerank sort at line 715, which has one:
```python
    pool.sort(key=lambda c: (-c.score, not c.heading_declares))
```

**What is wrong** `spread()` is `top − median`, and for a field of 2 or 3 the
median **is** the second element, so `separation(top, second, field)` is exactly
`1.0` by construction. `apply_heading_precedence` guards only `len(field) < 2`,
so it computes `apart.value == 1.0 > INDISTINGUISHABLE` and `break`s — it can
never fire. `_MIN_FIELD_FOR_SEPARATION = 5` exists for exactly this ("with three
candidates the median is the second one, so every second-place separation
computes to exactly 1.0. The relative rules stand down") and is applied to the
`separation` field at line 785 but not to precedence.

**The failure** A question scoped to one document, or asked against a small
corpus, that yields three reranked candidates: annex A.4 (mentions "coating
system no. 1" in passing) at −1.20 and annex A.1 (whose heading declares it) at
−1.35. Line 762 sorts on score alone, precedence returns `None` without
examining anything, and A.4's film thickness is quoted as system 1's — the
named defect of `search.py:46-53`, on the path the reranker is mandatory on
(ADR-0001). `heading_precedence` is `None`, so nothing says a rule stood down.

**Smallest fix** Give line 762 the same tiebreak as line 715
(`key=lambda c: (-c.score, not c.heading_declares)`), and have
`apply_heading_precedence` return early with a stated reason when
`len(field) < _MIN_FIELD_FOR_SEPARATION` instead of silently computing 1.0.

---

## 6. MEDIUM — every `sqlite3.OperationalError` in the keyword path is reported as "nothing matched"

**`backend/app/keyword.py:264-275`**

```python
    except sqlite3.OperationalError:
        # a malformed MATCH expression must not 500 the API
        return []
```

**What is wrong** The handler is far broader than its stated reason.
`OperationalError` is also "database is locked", "no such table: chunks_fts",
"database disk image is malformed".

**The failure** During ingestion of a large document (this project writes and
reads one SQLite file, and `docs/…` records contended runs), a locked database
makes `keyword.search` return `[]`. `search()` then reports
`keyword_candidates: 0`, `mode: "hybrid"` if any vector exists, and — because no
candidate entered the pool — `shortlist_excluded: []` and an empty
`document_census`. `coverage._classify` files every document as
`searched_no_match`: "Searched, and nothing in it matched the question." A
storage error is rendered to the reader as a statement about the documents.
`term_occurrences` has the honest form of this two functions later (`return -1`,
"tells us nothing either way"); `search` does not.

**Smallest fix** Catch only the parse case — re-raise unless the message starts
`fts5:` / contains `syntax error` — or return a `(rows, error)` pair so
`search()` can carry `keyword_error` into the response and coverage can decline
to classify.

---

## 7. MEDIUM — the test for "filtering happens before selection" would still pass if the filter moved into Python

**`backend/tests/test_search.py:370-396`**

```python
    assert len(scoped["hits"]) == len(direct["hits"]), (
        "scoped search returned fewer hits than the same document asked "
        "directly - out-of-scope rows are consuming candidate slots"
    )
```

**What is wrong** The condition the docstring names — out-of-scope rows
consuming candidate slots — requires more matching rows than the candidate
limit. The fixture uploads two documents built from the *same* default blocks
(`upload(client, "visible.pdf")` / `"hidden.pdf"`, `test_search.py:61`), i.e.
**6 chunks total**, against `settings.search_candidates = 30` and `limit=10`.

**The failure** Mutate `keyword.search` to run the MATCH unfiltered and drop
unauthorised rows in Python after `LIMIT`: both calls still return the same
three visible chunks, and this test stays green. It is a real test of *no leak*
only because the two sibling tests (`:317`, `:335`) assert `got == {visible}`;
the ordering guarantee it is named for is untested. Same family as audit entry
10 — a fixture that cannot produce the condition.

**Smallest fix** Index more than `search_candidates` matching chunks in the
hidden document (e.g. 40 chunks all containing the query terms) and assert the
scoped call returns the *same set*, not the same count.

---

## 8. MEDIUM — `test_identifiers_survive_tokenisation` asserts a substring of the MATCH string over a query that matches nothing

**`backend/tests/test_keyword.py:66-71`**

```python
def test_identifiers_survive_tokenisation():
    q = keyword.build_match_query("what is clause 5.3.2 of API 610")
    assert '"5.3.2"' in q
    assert '"API 610"' in q or '"610"' in q
```

**What is wrong** It asserts the shape of the generated query, never that the
query retrieves the clause.

**The failure** The query it inspects contains
`AND ("clause 5" OR "clause no. 5" OR …)` and returns **0 rows** against a
chunk containing "clause 5.3.2" (measured here, finding 1). The test is green
over the exact defect its name claims to prevent — "the default tokenizer splits
5.3.2 into three tokens, destroying exactly the lookups lexical search exists to
get right". A test of a string, standing in for a test of retrieval.

Named in the same class, and still passing if the feature were deleted:

* **`backend/tests/test_rerank_scale.py:158-166`**
  `test_precedence_does_not_override_a_decisive_field` calls nothing. Its whole
  body is `assert search.INDISTINGUISHABLE < 0.5` — a constant against a
  literal, wearing a behavioural name. Delete `apply_heading_precedence`
  entirely and it stays green (this is audit entry 10's third item exactly).
* **`backend/tests/test_rerank_scale.py:196-206`**
  `test_the_lexical_gate_is_not_relative` asserts only that two keys are present
  in the verdict and that `lexical.MIN_SEPARATION` does not exist. It passes if
  `assess` is changed to return `ok=True` unconditionally.
* No test anywhere reads `heading_precedence` (finding 10), and no test asserts
  that `example_questions`, `term_occurrences` or `indexed_count` respect a
  scope (findings 2, 3) — there is nothing to remove.

**Smallest fix** For the first: index a chunk containing "clause 5.3.2" and
assert `keyword.search("what is clause 5.3.2 of API 610", …)` returns it. That
assertion goes red today.

---

## 9. MEDIUM — `score_analysis_gold.py` still documents itself as measuring the product's path

**`eval/score_analysis_gold.py:1-9`**

```python
"""Score the Analysis pipeline using the PRODUCT'S OWN retrieval code.
...
This version imports app.keyword and calls search() exactly as the API does, so
a failure here is the product's failure.

Run: python score2.py <sqlite> <backend-dir>
"""
```

**What is wrong** It calls `keyword.search` (`:54`, `:81`, `:106`) — the raw FTS
side. The API calls `search.search` (hybrid + RRF + rerank) and the Analysis
route calls `analysis.gather`. `keyword.search` is not "search() exactly as the
API does".

**The failure** This is recorded defect 22, and the sibling file
`eval/verify_analysis_accuracy.py:3-6` states the correction accurately — but
the false docstring was never removed from the file a reader opens first. It is
worse than a stale sentence, because §LAYER 2 prints
`"SCOPE: does a named-document comparison stay on those docs?"` while
named-document scoping lives in `analysis.narrow_to_named`, a layer this harness
never enters. A green Layer 2 says nothing about scope discipline, and the
banner invites the opposite reading. (`Run: python score2.py` also names a file
that does not exist, and `id_to_name` at `:40` is dead.)

**Smallest fix** Rewrite the docstring to say what `verify_analysis_accuracy.py`
already says about it — "measures the RAW keyword layer, before analysis-layer
scoping, the per-document cap and percentage recall; it documents the original
defect and cannot see the fix" — and rename the Layer 2 banner to
"RAW KEYWORD RECALL, not scope enforcement".

---

## 10. MEDIUM — `heading_precedence` is computed for auditability, dropped by the response model, and read by nothing; two documents justify the API's shape by claiming it is read

**`backend/app/search.py:821-822`**, **`backend/app/schemas.py:512-529`**,
**`docs/preflight-inventory.md:82`** and **`:243`**.

```python
        # Stated so a reordering is auditable rather than mysterious.
        "heading_precedence": precedence_note,
```

`schemas.SearchResult` declares `query, mode, reranked, keyword_candidates,
dense_candidates, total, seconds, timings, hits, applied_scope` — no
`heading_precedence`, so FastAPI strips it from `/api/search`. `answer.py`'s
`base` never copies it either, so `/api/answer` and the chat transcript never
carry it. A repo-wide grep for the name finds `search.py`, one comment in
`answer.py`, and the two docs — no frontend, no `eval/`, no test.

**What is wrong** The one reordering in the pipeline that can move a *different
document's* passage to rank 1 produces a human-readable reason that no consumer
can see. And the justification for keeping `search()`'s dict return type is
stated as:

> "That dict carries `hits`, `mode`, `timings`, `keyword_candidates`,
> `dense_candidates` and `heading_precedence` — the explainability payload that
> the dashboard, `eval/run_eval.py` and `eval/reachability.py` all read."

None of the three reads `heading_precedence`.

**The failure** An engineer asks why A.1 was quoted rather than clause 4.5 and
there is no answer available anywhere in the product — the sentence explaining
it was built and discarded per request. And a reader of ADR-adjacent docs
believes a field is load-bearing that is dead.

**Smallest fix** Add `heading_precedence: str | None = None` to
`schemas.SearchResult` and carry it in `answer.base`; or delete the field and
the "auditable" comment. Either way correct the two lines in
`preflight-inventory.md` to name only the fields that are actually read.

---

## 11. MEDIUM — every dense query rebuilds a chunk→document map with a full table scan, reintroducing the corpus growth the vector cache exists to remove

**`backend/app/search.py:211-216`**, called at `search.py:193`.

```python
def _chunk_owner_map() -> dict[str, str]:
    """chunk_id -> document_id, for masking the dense matrix by scope."""
    return {r["id"]: r["document_id"]
            for r in connect().execute("SELECT id, document_id FROM chunks")}
```

**What is wrong** Uncached, unfiltered, per query — including
`document_id`-scoped queries, where the whole corpus is read to mask a single
document's vectors.

**The failure** At the measured 4,780 retrievable chunks this is a ~5k-row scan
and dict build on the critical path of every question, and it is linear in
`chunk_count_total` (not `chunk_count`) — so it also scales with the front
matter and gate-rejected rows search can never return. `vectorcache.py:11-12`
states "It was the ONLY component of retrieval that grew with the corpus"; that
is no longer true of the code beside it, and the comment at `search.py:191-192`
("the document each chunk belongs to is resolved once here rather than per
row") describes the inner loop while the outer cost is the scan.

**Smallest fix** Store `document_id` alongside `ids` in the vector cache
metadata (`vectorcache._build` already writes `ids` to JSON and already selects
from `chunk_vectors`, which carries `document_id`), and mask from that — no
query at all. Failing that, memoise the map on the same `signature()` the cache
already computes.

---

## 12. MEDIUM — an empty or unusable question is a silent zero-result, distinguishable from nothing

**`backend/app/keyword.py:241-243`** with **`search.py:653-662`**

```python
    match = build_match_query(question)
    if not match:
        return []
```

**What is wrong** `build_match_query` returns `""` for any input with no token
of two or more word characters (`"?? !!"`, `"5"`, a single CJK character, an
emoji-only question — all confirmed to produce `""`). `search()` records nothing
for this: `EVICTION_REASONS` covers only losses *inside* the RRF pool, and
`shortlist_excluded` is empty because no candidate ever entered.

**The failure** The response is `keyword_candidates: 0`, `total: 0`,
`shortlist_excluded: []` — identical to "the query ran and the corpus does not
contain this". `answer()` then reports `"no indexed passage matched this
question"`, a claim about the documents, for an input the query builder refused
to turn into a query. Same shape as finding 6 and as audit entry 12: a
candidate lost to a rule, indistinguishable from one that never existed.

**Smallest fix** Return the reason with the result — `("", "no_queryable_token")`
— and carry it as `query_rejected` in the search response so `answer()` can say
"this question carries no term the index can look up" instead of blaming the
corpus.

---

## 13. LOW — the reader is told reranking is happening when no reranker is installed, and the recorded reason is never surfaced

**`backend/app/search.py:719-723`** and **`backend/app/reranker.py:45-50`**

```python
    if rerank and pool:
        progress.stage(progress_id, "reranking",
                       f"{min(len(pool), settings.rerank_candidates)} of "
                       f"{len(pool)} candidates")
```

`reranker.available()` and `reranker.unavailable_reason()` exist; the first is
read only by `test_metrics.py:184` and a skip marker, the second by nothing at
all. **The failure**: with no model staged, the reader watches "reranking 16 of
40 candidates", `rerank_ms` is recorded for a call that scored nothing,
`reranked` comes back `false`, and the reason the ADR's mandatory critical-path
component is absent is held in a module global no response reads. The stage is
derived from the *intent* to rerank, not from the reranker.
**Fix**: gate the stage on `reranker.available()` and put
`unavailable_reason()` on the degraded response beside `reranked: false`.

---

## 14. LOW — the same measurement is quoted as 0.19 ms and 1.2 ms, eleven lines apart in one file

**`backend/app/vectorcache.py:21`** — "Measured: 0.19 ms against an 83 ms load."
**`backend/app/vectorcache.py:62`** — "Measured at 1.2 ms against an 83 ms load."

Both describe `signature()` against the same 83 ms baseline; they differ by 6×.
**The failure**: whichever is stale, a reader deciding whether the validity
check is cheap enough to run per query is reading a number nobody can attribute
— standing rule 9. **Fix**: re-measure once, keep one figure, and say what it
counts (per call, cold or warm, at what corpus size).

---

## 15. LOW — follow-up context can be dropped by the history bound with no record, and `get_messages` is unbounded

**`backend/app/chat.py:381-402`**

```python
           ORDER BY ordinal DESC LIMIT ?""",
        (conversation_id, window * 4),
    ).fetchall()
    questions = [r["text"] for r in rows if intent_mod.is_document_question(r["text"])]
    return list(reversed(questions[:window]))
```

`window * 4 = 12` rows are read so that dropping greetings "does not silently
shorten it". **The failure**: if the last 12 user turns are all greetings,
acknowledgements, single lowercase words or advice requests — an ordinary run of
"ok", "thanks", "nice" — the list comes back empty, `resolve_followup` returns
`(question, [])`, and "and its curing time" is retrieved with no subject. The
reader sees no chips, which reads as "nothing needed carrying" rather than
"context ran out": the UI at `ChatView.tsx:68` renders only when
`carried_terms.length > 0`. Separately, `get_messages` has no `LIMIT` at all, so
a long conversation returns every message with every stored payload.
**Fix**: return `(questions, truncated: bool)` and show the reader when the
window was exhausted; paginate `get_messages`.

*(Related but not a finding: a follow-up whose antecedent named a document by
filename does not carry the filename forward — filenames are not identifiers —
so a follow-up may be answered from a different document. It is not silent: the
answering passage carries its own `filename` and the frontend shows it.)*

---

# Verified clean

Checked, and sound:

* **Scope reaches the SQL `WHERE` of both sides before any LIMIT.**
  `keyword.search:251-272` binds `AND document_id IN (?,?,…)` into the same
  statement as `ORDER BY score LIMIT ?`; `dense_search:191-203` masks the score
  vector with `-inf` before `argsort(...)[:limit]` and keeps index alignment
  with `ids`. An empty scope returns `[]` on both sides rather than everything
  (`keyword.py:247`, `search.py:184`). Routes thread the scope from
  `Depends(access.current_scope)` into the call (`main.py:486-494`, `:525-528`,
  `:1209-1218`) — no resolved-and-discarded scope in the paths I read.
* **No string interpolation of user input into SQL anywhere in these files.**
  Every `f"…IN ({marks})"` interpolates only `?` placeholders
  (`keyword.py:259`, `search.py:437`, `answer.py:235`, `coverage`,
  `classification`). The MATCH expression is a bound parameter.
* **FTS5 escaping.** `_escape` quoting with `"` → `""` survived every hostile
  input I could construct **(measured here)**: `NEAR`, `NEAR/2`, `OR`, `AND`,
  `NOT`, `*`, `-`, `^`, `:`, `(`, `)`, `{}`, `[]`, `$`, `#`, `%`, an
  unterminated quote, `"" ""`, apostrophes, `café`, `naïve`, Arabic `النظام`,
  `...`, `---`, `///`, `___`, a 300-character token, and
  `NDFT "coating system no. 1"`. **No input produced a syntax error**, so no raw
  FTS message can reach a user, and the accent/Arabic cases match correctly
  (`remove_diacritics 2` applies to index and query alike). A query of only
  stopwords becomes a harmless OR of them, not an error.
* **Classification may only narrow.** `classification.narrow_to_scope:475-502` —
  empty filter returns `scope.allowed_document_ids, False` ("do not filter"),
  a filter matching nothing returns an empty set (fail closed), and the return
  is `frozenset(matched & set(scope.allowed_document_ids))`, computed before
  retrieval; `restrict` returns a narrowed `AccessScope` via `replace`, so
  widening is structurally impossible.
* **RRF.** `rrf_fuse:248-259` sums `1/(k+rank)` per list, tolerates one or both
  lists being empty, and leaves `keyword_rank`/`dense_rank` absent rather than
  zero for a hit only one side found (asserted at `test_search.py:82-91`).
  Magnitudes are discarded, which is the point. Ranks come from list order, so
  a bm25 tie is broken arbitrarily by SQLite — harmless at `k=60`.
* **The reranker sees heading + body** (`search.py:739-741`,
  `Candidate.searchable_text`), and `rerank_max_tokens = 480` now covers
  `chunk_max_tokens = 480`, closing the recorded truncation defect.
* **Rerank and RRF scales are not mixed in the ordering**: when the reranker
  produces scores the pool is *replaced* by the shortlist (`pool = shortlist`,
  `search.py:759`) rather than merged with unreranked leftovers, and the
  conflict penalty is rescaled to whichever field is in play
  (`_apply_conflict_penalty`). The one remaining cross-scale addition is
  finding 4.
* **Candidate accounting.** Five eviction reasons under one slug vocabulary,
  asserted against `EVICTION_REASONS`, with a test that a candidate is never
  both returned and reported dropped (`test_search.py:519`) and that the
  shortlist record is discarded when the reranker produces nothing
  (`:538`) — the audit entry 12 fix is real and the tests for it are not
  vacuous.
* **`document_census` / coverage.** `best_rerank_score` stays `None` on the
  unreranked path rather than `0.0`; `coverage.document_incidence` refuses to
  emit any credibility verdict when `reranked` is false, emits no
  `out_of_scope` row, and builds every row from `allowed_document_ids`. A
  document that contributed nothing is absent from the census but is still
  classified (`searched_no_match` vs `expected_not_retrieved`) from the
  incidence table, so the entry-12 question "was doc17 ever in the pool?" is
  answerable.
* **A previous answer is never evidence.** `prior_user_questions` restricts to
  `role='user'` in SQL; `resolve_followup` takes only prior questions;
  greetings and definitional questions short-circuit before any carry
  (`chat.py:187-196`); the designator conflict rule refuses to carry `system 1`
  into a question that says `system 4`, and blocks its tokens from returning as
  loose topic words.
* **What was carried is shown.** `carried_terms` and `resolved_question` are
  persisted per message, returned by `ask`, typed in `contracts/types.ts`, and
  rendered as "Read as a follow-up. Also searched for …" at
  `frontend/src/views/ChatView.tsx:63-79`. The evidence panel scores the span
  against the resolved question and the comparison test against the typed one,
  each with a stated reason.
* **`context_budget.py`** — the estimate is an upper bound by construction
  (one token per byte for digit runs), the safety factor is justified, positional
  citation markers are protected by dropping everything after the first removal,
  a fragment under `MIN_USEFUL_CHARS` is dropped rather than presented as
  evidence, and `evidence_removed` is carried on the answer and persisted in
  `_PAYLOAD_KEYS`. No finding.
* **`eval/run_eval.py`** measures the product: conversational mode drives
  `chat.ask` in one conversation (so `resolve_followup` runs) and prints
  `<- REWRITTEN, carried [...]` with both the asked and the run question;
  `--isolated` is labelled a diagnostic in the docstring, the `--tier`/README
  claims match `evidence_of`, `observed_corpus()`/`machine_state()` are read at
  run time, and `check_ground_truth` distinguishes stale ground truth from a
  refusal regression. `eval/reachability.py` states its layer (real `search()`,
  rerank deliberately off) and its ceiling honestly; `eval/coverage.py` states
  its definitions and queries both exclusion scopes;
  `eval/rerank_distribution.py` and `eval/run_phrasings.py` call
  `search.search` / `answer.answer` and claim no more. Only
  `score_analysis_gold.py` misdescribes its layer (finding 9).
* **`intent.classify`** is conservative in the safe direction — a lookup marker
  vetoes the advice classification before any other rule — and runs before
  retrieval, so a greeting shows no "considered" passages. The leak is in
  `example_questions`, not in the classifier.

# Not reviewed

* Nothing was executed against the real corpus or database: **no pytest, no
  vitest, no eval harness run**. Findings 1 and 8 include a measurement made in
  this container against a reconstruction of the quoted regex and tokenizer;
  every other statement is static reading. Running the suite would settle
  whether findings 7 and 8's mutations behave as I predict — I reasoned them
  from the fixture sizes, not from a red run.
* `analysis.py` (1,071 lines), `synthesis.py`, `claims.py`, `passages.py`,
  `acronyms.py` beyond its call signature, `reports.py`, `metrics.py`,
  `admin.py`, `auth.py`, ingestion, OCR, chunking, and the market path — outside
  the brief. `analysis.narrow_to_named` was read only far enough to confirm the
  classification intersection is written once (`classification.py:456`).
* The frontend, except `ChatView.tsx`'s carried-terms and question-selection
  blocks and the `contracts/types.ts` fields for messages.
* `test_relevance_floor.py`, `test_clause_headings.py`, `test_typo_tolerance.py`,
  `test_correctness_fixes.py`, `test_audit_findings.py` and
  `test_coverage_report.py` were grepped for the guarantees above but not read
  in full.
* Whether the vector cache's `_close`/`memmap` behaviour is correct on Windows
  under concurrent queries — reasoned about, not exercised.

# Candidate-loss map

Every point a candidate can leave the pipeline, and whether a person can later
find out.

| Where | Mechanism | Recorded? |
|---|---|---|
| Not indexed | `index_document` indexes `retrievable = 1` only | Yes — `exclusions` table, `quality_flags`, and `chunk_count` vs `chunk_count_total` |
| Keyword query never built | `build_match_query` returns `""` for input with no 2+ word-char token | **No** — finding 12; indistinguishable from "matched nothing" |
| Keyword required-term exclusion | identifiers ANDed; designators ANDed across four spellings — including the truncated `clause 5` of finding 1 | **No** — the query is not returned; zero hits look like an empty corpus |
| Keyword SQL error | `except sqlite3.OperationalError: return []` | **No** — finding 6; a locked DB reads as "nothing matched" |
| Keyword candidate limit | `LIMIT 30` (`search_candidates`) after scope, before fusion | **No**, by design — the pool boundary; rank 31 is not "dropped", it never entered |
| Dense: no vectors | `_load_vectors` returns `[]` | Yes — `mode: "keyword_only"`, `dense_candidates: 0` |
| Dense: out of scope | `-inf` mask before top-k | Yes, as a scope decision — and correctly *not* itemised (naming it would leak existence) |
| Dense candidate limit | `argsort(-scores)[:30]` | **No**, same boundary as above |
| Row gone / de-retrievable at hydrate | `search.py:671-681` | Yes — `chunk_no_longer_exists`, `not_retrievable` |
| Empty after tokenisation | `deduplicate`, `_tokens()` empty | Yes — `empty_after_tokenisation` |
| Near-duplicate merge | `deduplicate`, ≥0.85 token overlap on the *shorter* text | Yes — `near_duplicate`. Note: the loser's identity is recorded, the **winner's is not**, so "which chunk absorbed doc17's candidate?" is still unanswerable; and the comparison runs on RRF order, before the cross-encoder could have preferred the loser |
| Shortlist cut | `pool[settings.rerank_candidates:]` (16) | Yes — `displaced_before_rerank`, and correctly discarded when the reranker scores nothing |
| Conflict penalty | full field spread subtracted when a heading declares another member | Yes — `conflicts` and `penalty` on each hit |
| Reranker skipped a shortlist member | `by_id.get(chunk_id, -inf)` | **No** — a chunk the reranker failed to score is set to `-inf` and sorts last, reported as an ordinary low score rather than as unscored |
| Below `limit` | response slice `pool[:limit]` | Yes, structurally — `total` minus `len(hits)`, documented at `search.py:823-826` |
| Lexical gate refusal | `lexical.assess` over the top 5 (`GATE_CANDIDATES`) | Yes — `reason`, `terms`, `covered`, `absent_from_corpus`; but computed corpus-wide (finding 2), and candidates 6+ are never examined without a record |
| Credibility floor | `MIN_RERANK_SCORE = -3.0`, or `MIN_RRF_SCORE = 0.012` unreranked | Yes — `reason`, plus `best_rerank_score` per document in the census |
| Second-passage refusal | separation, different clause, distinguishing term, designator ownership | Partly — the passage simply does not appear; no reason is emitted |
| Tier 2 context budget | `fit_passages` trims then drops all later sources | Yes — `evidence_removed`, per passage, with action and character counts, persisted |
| Invented citation | `validate_citations` strips it | Yes — `rejected_citations` |
| Follow-up context window | `prior_user_questions`, 12 rows read, non-questions filtered, 3 kept | **No** — finding 15; an exhausted window looks like a question that needed no context |
