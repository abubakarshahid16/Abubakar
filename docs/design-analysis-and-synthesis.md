# Design — analysis lifecycle and multi-source synthesis

Written against the code and against measured hardware numbers from
`docs/benchmarks.md`. The headline conclusion is arithmetic, not opinion.

> **Note on one finding that did not survive verification.** An earlier reading
> of this design reported that the `coverage` object was computed and then
> silently dropped at three layers. It was fixed while the reading was in
> progress — `coverage` is on `AnswerResult` (`schemas.py:472`) and in
> `_PAYLOAD_KEYS` (`chat.py:420`). Recorded here because a design that reports a
> stale defect as live is the same error class this project keeps finding:
> **a measurement whose subject moved while it was being measured.**

## The number that governs everything

### The token budget, computed

```text
num_ctx                 = 1536
max_output_tokens       = 250
generated_context_chars = 1200   per passage
SYSTEM_PROMPT           = 122 net tokens (measured, answer.py:34-35)

evidence_budget = 1536 - 122 - 250 - 25 (question) - 45 (headers) - 50 (margin)
                = 1044 tokens
```

Three passages at 1,200 characters each, at engineering-prose tokenisation:

| chars/token | 3 x 1200 chars | vs 1044 |
|---|---:|---|
| 4.0 plain prose | 900 | fits, 144 spare |
| 3.7 typical | 973 | fits, 71 spare |
| **3.5 identifier-dense** | **1029** | **fits by 15 tokens** |

**The current configuration is already at its edge and nothing asserts it.**
`test_answer.py:357` checks the budget *parameter*, not the token count.
`answer.py:571-574` says overflow "would silently truncate the evidence the
answer is supposed to be grounded in" — and llama.cpp truncation is silent.

**A fourth passage does not fit at any plausible tokenisation.** Passages per
generation is **3**, and the branching factor of any staged synthesis is
therefore 3, at every level.

### What that means for 15 documents

```text
leaf calls   = ceil(15 docs x 3 passages / 3 per call) = 15
reduce L1    = ceil(15 / 3) = 5      # 3 x 250-token summaries = 750 < 1044
reduce L2    = ceil(5 / 3)  = 2
reduce L3                   = 1
                        total 23 generations
```

### The latency, from measured throughput

`benchmarks.md:32-46` — prompt eval falls with context length: 68.0 tok/s at 25
tokens, 27.9 at 951, 20.3 at 3,767. A full-budget leaf prompt is ~1,190 tokens,
so ~26 tok/s.

```text
prompt eval   1190 / 26  = 46 s
generation    ~110 tok @ 6-9.4 tok/s = 12-18 s
per leaf call            = 58-64 s

23 calls x 58 s = 22 minutes
23 calls x 25 s = 10 minutes   (optimistic: short passages)
```

**A 15-document comprehensive synthesis takes 10-22 minutes of wall clock on the
production machine, during which no other Tier 2 query can run.** Ten documents
is ~15 minutes. **Twenty documents is ~30 minutes**, and
`coverage_max_documents = 20` makes that the configured default.

**Raising `num_ctx` does not help.** Prompt-eval throughput *falls* with context
length, so doubling it to halve the call count is latency-neutral at best, and
costs ~1 GB more RAM on a host with 1.15 GB free.

The plan says it itself: *"Do not assume the current 1,536-token context and
100-token output can produce a detailed 15-document synthesis."* It cannot. It
can produce a 23-call, 20-minute one.

## The lifecycle

**Keep 202 + `analysis_id` + checkpoints. Cut SSE. Cut resume.**

Not because async is over-engineering — because at 10-22 minutes a synchronous
request is not a design choice, it is a broken one. `httpx.Client(timeout=180.0)`
(`answer.py:383`) already caps one generation at 180 s.

**Checkpoints are nearly free and are the audit record §7.2 already demands.**
Six boundaries, one write each: after scope resolution; after the single
retrieval and single rerank batch; after evidence extraction (no model); after
each leaf synthesis; after each reduce level; after validation.

**Cut SSE.** Every route is sync; SSE needs an async generator plus a cross-thread
channel, and events would arrive **once every 30-60 seconds** — the leaf-call
cadence. That is a poll. `GET /api/analyses/{id}` every 2 s is strictly better:
it survives a reload, needs no new concurrency primitive, and reuses the existing
`response_model` discipline.

**Cut resume.** Resuming correctly requires proving the corpus did not change,
and a resumed run that re-reranks produces scores from a **different batch**,
which the coverage design forbids comparing. **Resume is where the score-scale
invariant dies quietly.** A cancelled or crashed run re-runs from scratch, and
its checkpoints stay as a record of what it had done.

**Keep cancellation.** A cooperative flag read at each boundary. Without it a
mistaken 20-minute run cannot be stopped in front of a client. Partial batches
are retained and **rendered as batches, never as a consolidated answer.**

## Evidence ids — the blocking structural problem

Citations are positional: `[S1]` is `passages[0]` **of one request**
(`answer.py:372-378, 422-427`). §7.2 wants `evidence_id`, `citation_ids`,
`also_supported_by`. `chunk_id` is not a substitute — `chunk_signature` changes
on re-chunk and `search.py:668-676` already evicts chunks whose row has gone.

```text
evidence_id = sha256(document_id | page_start | page_end | section | exact_span)[:16]
```

Stable across re-chunking, reproducible for report regeneration, content-addressed.
The `[S{i}] -> evidence_id` map is recorded **per LLM call**, so a citation is
always resolvable to the exact text the model was shown.

**This is the single most likely way this feature invents a citation:** a level-2
reduce that reads a level-1 summary's `[S1]` marker textually, where `[S1]` now
means a different passage. Citations must be carried **structurally** — each
batch stores `cited_evidence_ids` resolved from its own map, and a reduce prompt
is built from those ids re-expanded to evidence text, never from the summary's
markers.

## The claim algorithm — what is mechanical, what costs 60 seconds

### Mechanical. No model. Deterministic. Testable.

**Typed extraction** — numbers with units, `keyword.IDENTIFIER` (already exists
and is already the "named subject" test), `keyword.find_designators` (what
distinguishes coating system no. 1 from no. 9), comparators.

**Do not extract subject / property / action.** There is no reliable mechanical
way, and asking the model costs 60 s per batch. **Carry the exact span instead.**
A claim row whose subject is a quoted sentence is honest; one whose subject is a
model paraphrase is Tier 1 laundering.

**Unit normalisation** — pure table lookup. Store `{raw_value, raw_unit,
normalized_value, normalized_unit, normalizer_version}` and **render the raw**.
An unknown unit is `normalized_value: null` — never a guessed conversion, never
0. The template is `test_rerank_scale.py:342`: **a normalizer that meets an
unknown unit must raise, not coerce.**

**Facet clustering** — the key is *not* semantic similarity. It is
`lexical.distinctive_terms(question)` intersected with the claim's terms, plus
the unit dimension. Two claims cluster iff they share a distinctive term **and**
the same dimension. The plan says "never merge merely because wording is
similar"; this rule cannot, because it never looks at wording.

**Labels, entirely arithmetic** — `agreement` (values compatible),
`addition` (one has a property the others lack), `possible_conflict` (values
incompatible, both applicabilities parse and overlap), `unresolved` (incompatible
but applicability does not parse, or units un-normalisable).

**`possible_conflict`, never `conflict`.** With no revision or approval columns
(`db.py:15-33`) the system cannot tell a superseded requirement from a
contradicting one, and inferring supersession from a filename is forbidden.
`unresolved` will be the commonest label. That is honest.

### Requires the model

**Consolidated prose. That is all.** One generation per batch, ~60 s.

Do **not** call the model to type claims, decide facets, convert units, or judge
conflicts. At 60 s a call, a per-claim pass over 45 evidence items is 45 minutes,
and every one of those judgements is unverifiable.

**The claim table is the product; the prose is the garnish.** That inverts the
plan's emphasis, and the inversion is what makes it shippable.

## Gap analysis — the baseline must come from the user

**There is no other source, and all of them were checked.** No `revision`, no
`approval_status`, no `is_baseline` on `documents`. Nothing parses a revision
block. Inferring "this document is the requirement and that one is the
deliverable" from text alone is not available on a corpus where `contractor`
means a real requirement in one document and "the Federal Government and their
contractors" in another. Filename ordering is explicitly forbidden.

So the user nominates a baseline: a document, a section, or a typed requirement.
The baseline is retrieved by the **same** retrieval and **same single** rerank
batch, must clear the **same** -3.0 floor, gets an `evidence_id`, and its
citation is recorded on every gap item.

**No nomination means `gaps.applicability = "insufficient_baseline"`, `items:
[]`.** Not `not_applicable` — the question may have been comparative; the
*baseline* is what is missing.

A typed requirement is **the requirement, not evidence**. Labelled
`source_kind: "user_stated"`, carries no citation, never enters an evidence
ledger, never becomes a documentary finding.

**Per-item status:** `met` requires *positive matching evidence* — absence never
produces `met`. `possible_gap` requires that term incidence confirms we looked in
the right place. `insufficient_evidence` covers the rest.

**`possible_gap`, not `gap`.** The system can prove *retrieval found nothing*. It
cannot prove *the document says nothing*.

## Confidence — a word, and `high` is never emitted

There is no calibration data. A number — 0.72, 72% — is a claim of calibration,
and it would be the same defect as a value computed on one scale and read on
another: quantitative-looking, not quantitative, and read as protection.

Worse, if the **model** emits the word it is a token sampled at temperature 0.1
conditioned on its own prose, with no relationship to whether the evidence
supports it.

**Compute it from countable facts:**

```text
low     default, and the honest floor. Any of:
          gaps.applicability != "applicable"
          any document failed or not_searchable
          any cluster labelled possible_conflict or unresolved
          any evidence with text_source == "recognised"
          coverage.complete is False
          any generation truncated
medium  every sentence cites >= 1 evidence item, no conflicts,
        no OCR evidence, coverage.complete is not False
high    NEVER EMITTED - same rule that forbids coverage.complete: true
```

`high` being structurally unreachable is the point, and it is documented as such
rather than left as a dead enum. Confidence then means exactly *"how many of the
things that would undermine this were detected"* — a checklist result, defensible
line by line, and displayable as the checklist.

An uncited recommendation is **refused**, not shown — the same rule
`answer.py:622-638` already applies to a generated answer.

## Where the invariants are most at risk

### Tier 1 verbatim becoming generated prose

`answer["answer"]` is verbatim in extract mode (`answer.py:552`) and model prose
in generated mode (`answer.py:648`) — **same key, two meanings**, distinguished
only by `answer_type`. A synthesis stage that gathers `result["answer"]` across
documents converts quotations into prose with no marker anywhere.

> **Rule: the synthesis input type is `EvidenceItem`, never `AnswerResult`.
> Nothing that has an `answer_type` may be an input to a generation.**

> **Rule: a batch of size 1 is not summarised; it is passed through as evidence.**
> The moment a one-item batch is generated, that item's verbatim text has become
> prose.

And the ledger's `exact_span` must render **typographically distinct** from
generated prose. If they look the same, the reader cannot tell them apart — the
failure `answer.py:11-15` says matters more than anything else in the product.

### The lexical gate becoming per-document

`lexical.assess` threads `document_id` into its counts, and the absolute-presence
branch produces the user-visible string *"does not appear **anywhere** in the
indexed documents"*. **One loop makes that sentence false.**

The plan says *"Apply the credibility/evidence gate independently per document"*.
**That instruction is wrong for the lexical half and must not be followed.** The
gate runs once, on the request's own scope, before any per-document reasoning,
and its verdict is final. A refused question produces no analysis, no coverage
table and no claim table.

A third form worth recording: `lexical.assess` counts over **all** of
`chunks_fts`, ignoring `allowed_document_ids`. Under `demo_required` the refusal
message is computed over documents the user may not be allowed to see. A weak
oracle today — presence/absence of a term only — but worth knowing before
analysis multiplies the surface.

### Cross-batch score comparison

`rerank_batch = 32` and `rerank_candidates = 16`, so every call today is one
forward pass. The plan's *"rerank candidates in deterministic per-document
batches"* breaks it: 20 documents x 8 = 160 pairs = **five forward passes, five
int8 activation-scale regimes**, compared against an absolute -3.0 floor with a
3.5-point calibration gap and +/-0.494 measured drift — roughly a seventh of the
gap, injected as noise, on the boundary between answer and refuse.

> **Rule: one rerank batch per analysis, at most `rerank_batch` pairs. If the
> candidate set exceeds it, reduce the per-document quota rather than adding a
> pass.**

At 32 that caps comprehensive retrieval far below the plan's 160 — and **that cap
is a real, stated limitation of this hardware, not something to engineer around.**

### Unmeasured becoming zero

`validated_evidence_count` for a failed or not-searchable document must be
**null**, not 0 — zero means "searched and found nothing"; null means "did not
search". `failed_documents: 0` is a genuine zero only if every document was
attempted; after a cancellation it is null. `normalized_value` for an
un-normalisable unit is null with the raw rendered. `confidence` with no
recommendation is null, not `"low"`. `coverage.complete` is false or null, never
true.

## Tests that fail today

- **Synthesis never invents a citation.** Stub the model to emit `[S1] [S4] [S9]`
  for a 3-evidence batch; assert S4/S9 land in `rejected_citations` and appear
  nowhere in the text. Then the form that matters: stub level 1 to emit `[S1]`,
  feed its summary into a level-2 reduce whose own map has a *different* passage
  at position 1, and assert the output resolves to the **level-1** evidence. A
  naive text-passthrough reduce fails this.
- **Never presents an unsupported claim.** An uncited sentence does not appear in
  `documented_findings`; if no sentence is cited the whole result is
  `insufficient_evidence`. Second form: a claim carrying a number that appears in
  no cited span is rejected.
- **The lexical gate is never called per document.** Monkeypatch `assess` to
  record every `document_id`; assert it is only ever the request's own.
- **One rerank batch per analysis.** Count calls; assert exactly one, and
  `len(passages) <= rerank_batch`.
- **A score from outside the scored batch is None, not zero** — and cannot satisfy
  `_is_semantically_credible`.
- **The evidence budget is computed, not assumed.** Build a Tier 2 prompt from
  three passages padded to `generated_context_chars`, tokenise with the deployed
  tokenizer, assert `system + prompt + max_output <= num_ctx`. **Run this first —
  see the uncertainty below.**
- **A normalizer refuses an unknown unit.**
- **A cancelled analysis is never presented as complete.**

## The smallest honest version — 90 minutes, zero new model calls

**ISSUE-009 as written is not deliverable in 90 minutes, and the 3-hour block is
not deliverable in three hours.** One comprehensive run is 10-22 minutes of wall
clock; you cannot iterate on a feature whose test cycle is 20 minutes, inside a
90-minute budget, on the machine also running the demo. The plan's own hour-7
no-go — *"if cited synthesis is not stable, retain existing Tier 1 evidence and
make generated analysis a disabled preview"* — should be **pulled forward and
treated as the plan, not the fallback.**

| Step | Work | Min |
|---|---|---|
| 1 | `claims.py` — mechanical extraction over evidence already in `answer_passages`: number+unit, identifiers, designators, comparators. Raw and normalized, unknown unit -> null. No model | 30 |
| 2 | Facet clustering + the four labels. Facet key = question distinctive terms ∩ claim terms + unit dimension. Deterministic | 25 |
| 3 | Render the claim table beside the existing passages, quoted spans typographically distinct, every row carrying document + page + section | 20 |
| 4 | The tests above; run the gold questions and record what the table produces | 15 |

### What it demonstrably produces

For a question whose evidence spans two documents, the reader currently sees three
passages and compares them by eye. After:

> *NORSOK M-501 A.1 p22 says MDFT 280 um; doc17 §3.8 p179 says minimum 250 um;
> same facet, incompatible values, applicability unresolved — engineer review
> required*

with both spans quoted verbatim and both citations live. **Zero seconds added to
a 2.1 s Tier 1 answer.**

### What it does not claim

**It is not synthesis.** No consolidated prose, no hierarchical reduce, no
15-document analysis. Anyone describing this as multi-document synthesis is
overstating it — it is **mechanical cross-document claim comparison over the
passages one query already retrieved.**

Not a gap analysis (no baseline nominated). No recommendation. No analysis
lifecycle. **No conflict is asserted** — `possible_conflict` only. **Coverage of
the comparison is not claimed** — it compares what was retrieved, at most three
passages.

### Cut, and say so out loud

SSE. Resume. Per-document reranking. Per-document evidence gating. Hierarchical
reduce. Market comparison (the machine is offline). The advisory recommendation.
`num_ctx` at 4,096.

**Worth doing next, in order:** the lifecycle skeleton (202 + polling + six
checkpoints, ~45 min, mostly INSERTs), then a **single-batch** synthesis over one
batch of 3 — one generation, ~60 s, honestly labelled as covering three passages.
Fifteen-document synthesis is a post-Sunday item with a measured 10-22-minute
cost attached to its name.


## MEASURED: the token budget is already exceeded, and the estimate was wrong twice

The 3.5-4.0 chars/token figure above was an estimate. It has now been measured
against real chunk text from this corpus, using the Qwen BPE tokenizer.

**It is wrong in both directions, and one of them is a live defect.**

| Content | chars/token | 1,200-char passage |
|---|---:|---:|
| Engineering prose (doc17, doc18, book1) | **5.0 - 6.0** | ~200-240 tokens |
| **Numeric tables (book2, book4)** | **1.01 - 1.02** | **~1,190 tokens** |

Prose is far cheaper than estimated. A numeric table is **five times more
expensive**, because Qwen's BPE tokenises digits individually: `30.0000` is seven
tokens, and a table row of ten such values is seventy.

Measured sample, `15.3 WAVE EQUATION`, 1,200 characters, zero non-ASCII:

```text
0.00 30.0000 30.0000 30.0000 30.0000 30.0000 30.0000 ...
-> tokens: '0' '.' '0' '0' ' ' '3' '0' '.' '0' '0' '0' '0' ' ' '3' '0' ...
```

**One such passage is 1,189 tokens against an evidence budget of 1,044.** Three
of them is **3,567 tokens against a `num_ctx` of 1,536** - more than double the
whole context window, before the system prompt or the question.

### What this means, concretely

For any Tier 2 question whose evidence is a numeric table, the context overflows
and llama.cpp truncates **silently**. `answer.py:571-574` names the consequence:
overflow "would silently truncate the evidence the answer is supposed to be
grounded in". Sources are dropped or cut mid-table, and the answer is generated
from whatever survived - with citations that still name all three.

This is reachable today. book2 and book4 are full of numeric tables, both are in
the corpus, and nothing warns.

### What it does NOT mean

**Prose is fine.** Three prose passages are ~700 tokens against 1,044 - a
comfortable margin, better than the estimate. The five gold questions all landed
on prose, which is why none of them exposed this.

### The fix is not a smaller constant

`generated_context_chars` is a **character** budget standing in for a **token**
budget, and the substitution is only valid when the ratio is stable. It is not:
it varies 6x across this corpus. A character cap tuned for tables would waste
80% of the window on prose; one tuned for prose overflows on tables.

**Measure the tokens.** Build the prompt, tokenise it with the deployed
tokenizer, and drop or trim sources until it fits - reporting what was dropped
rather than letting the runtime discard it. The system already has the machinery
to report a truncation honestly: `done_reason == "length"` surfaces output
truncation to the reader, and input truncation deserves the same treatment.

Until then, the honest limitation is: **a Tier 2 answer over numeric-table
evidence may be generated from truncated sources, and the system does not
currently detect or report this.**

## The uncertainty to resolve first, in five minutes

**The 3.5-4.0 chars/token figure is an estimate.** Run the deployed tokenizer over
ten real chunks before trusting the 15-token margin. **If it is 3.2, the current
three-passage Tier 2 prompt is already overflowing `num_ctx` silently — a live
defect rather than a design constraint.**

The 58-64 s per-call figure is interpolated from `benchmarks.md`, not measured at
1,190 tokens. The direction is certain; the number is not.

Whether facet clustering on question-derived terms produces useful clusters on
this corpus is unknown at n=0. Ship with no tuned constant and a note saying the
basis is presence-based, rather than fitting a constant to one observation.
