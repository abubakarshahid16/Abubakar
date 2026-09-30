# Known limitations register

> Client-facing. Every entry here must be stated plainly at handoff.
> Nothing in this project may be presented as better than what this file says.

## Performance — measured on the production machine

- Answer generation runs on a 15 W mobile CPU with **no GPU acceleration**. This laptop is the production machine; there is no faster environment later.
- A single LLM answer over a full RAG context measured **195 seconds**. This is why the system defaults to a **no-LLM Tier 1 path** that returns the quoted source passage in 1–2 seconds.
- LLM synthesis (Tier 2) remains materially slower than Tier 1 and is an explicit, opt-in action.
- Ingestion is paused during demonstrations; running it concurrently invalidates latency figures.
- **Tier 1 median is ~2.1 s, not the 1-2 s originally targeted, and that is a deliberate trade.** The cross-encoder's rerank window was 256 tokens against a 480-token chunk ceiling, so any long passage was scored on its first half. NORSOK's clause 11 holds Table 3 flattened to 486 tokens with the answer at token 350: the reranker never saw it and returned -10.95, which was correct about what it had been shown and wrong about the passage.
  - Widening the window to cover the whole chunk cost **+650 ms median (1.45 s -> ~2.1 s)** and bought **retrieval 9/10 -> 10/10, citation 8/9 -> 9/9, answer tokens 9/10 -> 10/10** on the independent 15-question set.
  - **Do not re-tune `rerank_max_tokens` downward without re-running `eval/run_eval.py`.** The setting must remain >= `chunk_max_tokens`; a test asserts that relationship rather than the literal number, because the alternative to a slower answer here is a wrong safety-relevant figure delivered confidently.
  - `rerank_candidates` was reduced 20 -> 16 to recover part of the cost. 10 candidates also scored perfectly and was faster, but 12 degraded, and a non-monotonic curve means the shortlist composition is shifting rather than the depth being unnecessary - so the safer point was taken.

## Reranker score depends on which passages it was batched with

The cross-encoder scores the 16-passage shortlist in one forward pass, padding
every passage to the longest in the batch. Measured on one real shortlist, the
same question and passage scores differently depending on its company:

| effect | isolated by | largest difference |
|---|---|---|
| padding width | pair alone vs padded to the batch's longest | **0.494** |
| batch composition | padded alone vs inside the real batch | **0.435** |

Both are int8 quantisation artefacts: activation scales are computed per
tensor over the whole batch, so a passage's rounding depends on its
batchmates. Ordering was preserved in the case measured.

**Why it matters.** `MIN_RERANK_SCORE = -3.0` is an absolute threshold that
decides answer against refuse. In the shortlist measured, a passage at -3.281
scored -3.039 in the batch — it stayed on the refuse side, but within 0.04 of
crossing. So the answer/refuse boundary carries roughly ±0.5 of noise that has
nothing to do with the passage.

**Not fixed, and deliberately.** Scoring each pair alone removes the padding
component and is sometimes faster, but it shifts every score, which would
invalidate the measured calibration of the -3.0 floor — the number that stands
between the system and a confident wrong answer. Changing it requires
re-running `eval/run_eval.py` and `eval/run_phrasings.py` and re-deriving the
floor, not a code edit. Recorded here so the -3.0 floor is read as a threshold
with a noise band, not a sharp line.

## Extraction fidelity - substituted ligatures

- **Some PDFs encode `ti` and `fi` as glyphs whose embedded font mapping is wrong**, so extraction yields the wrong character entirely: `Introduc,on` for Introduction, `Sec3on` for Section, `DeEinitions` for Definitions. No retrieval change can match a word that is not in the text, so this is a **coverage** limit rather than a ranking one.
  - **Measured on book4 (1,400 pages, 2,030,224 characters):** 292 pages affected (20.9%), 535 corrupted tokens = 0.68% of words on affected pages, **0.18% of the document**. Sparse, but concentrated where it hurts: the commonest were `Sec3on` (91), `Introduc,on` (83) and `Ques,on` (51) - the structural words a "what is section 3.4 about" question matches on.
  - **Repaired at extraction, and validated.** Corrupt and clean forms coexist in the same document (177 pages corrupt against 1,196 clean), which made a targeted repair verifiable rather than a guess. Applied to 2,281 clean pages across the whole corpus it produces **zero changes**, and that safety property is a permanent test. book4 now carries 0 corrupted tokens, down from 537.
  - **NOT repaired:** an `ff -> ?` substitution on 37 pages (50 hits) has no clean reference in that document, so there is nothing to validate a rule against. Left alone rather than guessed at.
  - The other three documents carry no ligature corruption.

## Document reading - what the 2026-09-30 reading audit fixed, and what it did not

Fixed (CHUNKER_VERSION 9, TABLE_READER_VERSION 2; tests `backend/tests/test_audit_reading.py`, mutations M1540-M1553). Documents chunked before this read the old way until re-processed (`scripts/reindex_chunking.py`).

- **Rotated pages keep their ruled tables.** A table on a page rotated 90/180/270 is read in the unrotated space the text is read in. Only rotation by page `/Rotate` is handled; text drawn sideways on an unrotated page is not.
- **Unruled data sheets are read as rows.** Label and value on alternate lines, at least 4 pairs, most values carrying a digit. Not handled: a sheet with a blank value (the alternation breaks, and the rows around the gap are read separately - a run shorter than 4 pairs can still be misread as a clause heading); a label that starts with a digit; three or more columns without ruling.
- **A contents page needs contents evidence.** Dot leaders on half its lines, or page numbers that fit the document (ascending, unless at the back as an index). Not handled: a contents page of an EXCERPT without dot leaders, whose page numbers exceed the PDF's page count, is now read as prose.
- **2-4 page documents strip their page header** when a line at the top or bottom of every page has the same shape and one of its numbers moves with the page number. A header without a page number on a short document is still read as text.
- **Quality gate:** rpm, kW, kV, m3/h, Hz, psig, barg are measured values. A line of three or more equipment tags (P-101A) is KEPT as searchable, by decision: a tag is what an engineer searches for.
- **OCR merge reads two columns one after the other**, when both sides of the widest x gap hold at least 3 lines of 4+ words. Not handled: three or more columns; a two-column page of short lines (read row by row, as a data sheet is). A misread duplicate is only recognised within two line spacings of the line it misreads.

## Known false refusals - phrasing sensitivity

- **6 of 10 facts cite the same page across all three phrasings; 4 do not.** Measured by `eval/run_phrasings.py` and recorded fact by fact in `docs/demo-readiness-table.md`, which asks each fact as originally written, as the document words it, and as a user loosely types it.
- **The pattern, in plain terms: retrieval is solid when a question borrows the document's vocabulary and brittle when it does not.** Ask about *relative humidity* and the right page comes back; ask *how humid* and it does not. The system is matching words, and a question that shares none of the document's words has little to match on.
- **The two questions that matter most, because they are how a person actually talks:**

| question, as a user types it | what should be cited | what happens | why |
|---|---|---|---|
| "how humid is too humid to paint" | 4.4 Ambient conditions, p7 | **wrong page** | the document says *relative humidity*, never *humid* |
| "how much salt is allowed on the surface" | 6.3 Soluble impurities, p10 | **wrong page** — cites 2.1, p5-6 | the document says *chlorides* and *NaCl*, never *salt* |

- **Recorded, not moved.** The number is a measurement of the system as it stands. Retrieval heuristics are frozen for this sprint (`RAG-INTELLIGENCE-POC-EXECUTION.md`, change budget), and tuning them would invalidate every figure in `docs/benchmarks.md` — so this entry exists to state the limit, not to justify closing it.
- **One caveat, stated so the pattern is not read as a law.** Three of the four failures are the loosely-typed phrasing, but the fourth is not: `In clause 3.2 Abbreviations, what does the abbreviation NDFT mean?` is worded straight out of the document and still cites the wrong page, while both the original and the casual `ndft means what` are correct. Document vocabulary raises the odds; it does not guarantee the page.
- **The 6/10 held through a corpus doubling** — the same 6 of 10, unchanged, after a 1,400-page document was added. A result that survives the corpus changing underneath it is evidence of a real fix rather than one fitted to the measurement, so it is recorded as such.
- Two are **false refusals** where the correct passage was retrieved at rank 1 and then rejected:

| question | correct passage | rerank | outcome |
|---|---|---|---|
| "how humid is too humid to paint" | 4.4 Ambient conditions, p7 | -5.09 | refused |
| "how often do i check humidity and what's the max" | 4.4 Ambient conditions, p7 | -8.01 | refused |

- **Why this is not tuned away.** The cross-encoder's score for the same passage swings 16 points across two phrasings of one fact. Over 35 queries with known ground truth the answer-present and answer-absent populations do not separate on any shape statistic: a floor low enough to admit every correct-at-rank-1 query is -8.01 or lower, and the highest-scoring genuinely absent question the lexical gate permits scores -3.85. Such a floor admits **3 of 3** unanswerable questions. Lowering `MIN_RERANK_SCORE` trades three correct refusals for three confident wrong answers, so it stays absolute.
- **Mitigation, and it is how engineers work anyway: use the document's own words and write designators in full.** "relative humidity" not "humid"; "coating system no. 1" not "system 1" - though both designator forms now work.
- **A related vocabulary limit, now addressed by a curated glossary (2026-09-29, `app/glossary.py`):** "how much salt is allowed on the surface before painting" cited the wrong clause because the document says *chlorides* and *NaCl*, never *salt*. Lay words with an entry (humid, salt, rust, paint, ...) are now OR-ed with the document's phrasing on the keyword side, count as covered by the lexical gate, and the reranker also scores the question in the document's words, keeping the higher score. Proven on synthetic pages rebuilt from both measured misses (both now answer from the right clause; three unanswerable questions still refuse; "salt spray" is never widened). It only helps words the list covers; an engineer extends it.
- **Measured on the owner's real corpus (2026-09-29, self-supervised calibration, `eval/refusal_calibration.py`).** 55 present items, 4 wordings each, plus their wrong-value siblings and 45 absent-topic questions (377 questions total). The premise above does not hold on this corpus the way the reference-corpus measurement suggested: false refusals at the current floor were rare (2 of 166 present-question instances, 1.2%). The real failure mode is different - a different chunk stating a *different* value was returned as if it answered the question 66 of 166 times (40%), because the right chunk and a topically similar wrong one score almost identically (right-top median rerank 6.59, wrong-top median 5.09 - heavy overlap, no floor separates them cleanly). Four candidate fixes were measured (best score across the 4 wordings; a relative-separation gate; the floor swept from -8 to +2; the floor unchanged): **none of them fixed the dominant failure**, because it is a same-topic-different-value retrieval problem, not a threshold-placement problem. Owner decision (2026-09-29): `MIN_RERANK_SCORE` stays at -3.0.
- **A shared-terms fix the same self-supervised calibration found (2026-09-29, M1390):** four absent-topic questions were answered confidently, each sharing exactly one distinctive term with an unrelated passage - a single coincidental match was enough for a question of any length. The lexical gate now requires two shared distinctive terms, not one, when the question names three or more (a shorter question still needs only one - it has less to share in the first place). Measured cost: 6 of 166 new refusals for 4 of 4 fewer confident-wrong absent answers on the calibration set. `MIN_RERANK_SCORE` itself is unchanged - that decision and the fuller calibration results are tracked separately (`feat/refusal-calibration`).

## The output-token cap, and what raising it cost

Recorded the way the reranker-window trade is recorded: what it cost in
seconds, what it bought.

**The defect.** `max_output_tokens` was 100, chosen for generation speed on a
15 W CPU and tuned against short factual answers. Two of two Tier 2 answers in
a live demo stopped mid-sentence, one of them *inside a citation marker* —
`…to run a trust algorithm [S2` — which reads as a malformed citation system
rather than a length limit.

**Measured**, four gold questions, model warm, caps interleaved, three repeats:

| Question | cap 100 median | cap 250 median | tokens used | truncated at 100 |
|---|---|---|---|---|
| Q1 zero trust | 19.9 s | 24.3 s | 101 | **2 of 3** |
| Q2 carbon capture | 21.9 s | 16.1 s | 89 | 0 of 3 |
| Q3 stripe coat | 14.7 s | 15.3 s | 56 | 0 of 3 |
| Q4 incident response | 30.5 s | 25.6 s | 108 | **3 of 3** |

**At 100, 5 of 12 generations were cut off. At 250, none were.** The largest
answer used 108 tokens, so 250 is about twice the observed worst case rather
than a round number.

**What it cost: nothing measurable.** `num_predict` is a CEILING, not a target
— a generation that finishes early stops early. The medians moved in *both*
directions (Q1 slower, Q2 and Q4 faster), which is machine noise on a shared
laptop, not a latency cost. The extra tokens are paid only by the answers that
were previously being truncated, which is exactly the population that needed
them.

**What it bought:** the demo-visible defect, on the two questions that showed
it.

### Two invariants that hold at any cap

- **An answer never ends inside a citation marker.** A trailing `[`, `[S` or
  `[S1` with no closing bracket is stripped, using the same machinery that
  already removes invented citations. A broken citation is worse than a missing
  one.
- **A truncated answer says so.** The response carries `truncated`, set from
  Ollama's `done_reason == "length"`, and the UI renders a line saying the
  answer reached its length limit. Without it a reader cannot tell "the model
  finished" from "it ran out of budget" from "it crashed" — three situations,
  one appearance, and only one of them a defect.

**One consequence worth knowing.** If the budget runs out inside the *only*
citation, stripping it leaves an answer with no support, and an uncited
generated answer is refused — by the same rule that rejects invented citations.
The refusal then says it hit a length limit rather than that the documents lack
the answer, because those are different facts and only one is about the corpus.
The alternative would be guessing which source the model meant, and a guessed
citation is the thing this system exists not to do.

## Numeric tables do not fit the context window, and are reported when trimmed

**A numeric table costs about one token per character.** The tokenizer splits
digits individually - `30.0000` is eight tokens for seven characters - so a
1,200-character table passage is around 1,175 tokens where the same length of
prose is about 250.

The context window is 1,536 tokens with 250 reserved for the answer. **One
table passage therefore fills most of the evidence budget, and three do not fit
at all** - measured at 3,645 tokens, 2.4 times the whole window.

Until 2026-09-05 the overflow was discarded silently inside the runtime, and
**there was no way to detect it from outside**: the same prompt sent at the
deployed window reported 1,026 tokens evaluated, five hundred BELOW the
ceiling, indistinguishable from a small prompt. Roughly 72% of the evidence
disappeared and the answer was generated from what survived, citing sources it
had never been shown.

The evidence is now costed before the prompt is sent, and anything trimmed or
dropped is **named on the answer** (`evidence_removed`), the same way an answer
cut off by the output cap is named. Measured:

| Evidence | Sources kept | Reported |
|---|---|---|
| Three prose passages | **3 of 3, untouched** | nothing removed |
| Three numeric-table passages | 1 whole, 1 trimmed to 949 characters | 1 trimmed, 1 dropped |

**What this costs the reader.** A question answered from a numeric table gets
roughly one source instead of three. That is a real limit on table-heavy
documents, and it is the honest version of a limit that was previously hidden.

**As of this commit `evidence_removed` is in the API and not on screen** - the
same gap as the coverage report below it.

**The token cost is estimated, not measured per question, and the margin is the
only guard.** The deployed tokenizer is only reachable through Ollama, and both
routes were measured and rejected: probing at a larger window forces a model
reload (16.0 s up, 16.3 s back), and probing at the deployed window returns the
truncated count above. Nor is there a post-hoc check - a truncated prompt and a
cached prompt both report a low count, so the two cannot be told apart. The
local estimate is therefore built to over-count: 1.03-1.05x on tables, where
the decision is made, and 1.25-1.73x on prose, where there is room to spare.
Worst observed margin **1.035x over twelve measured chunks**. Ground truth in
`docs/benchmarks.md`, re-checked by `test_context_budget.py`.

## A summary sees about two passages, however many were retrieved

Measured on 2026-09-05: one retrieved passage costs roughly **849 tokens**, so
two already exceed the 1,286-token evidence budget. The context guard therefore
lands on **two sources - one whole, one trimmed - whatever `limit` is set to**,
and a real call evaluated 776 tokens and generated 122 in 75.5 s wall clock.

Raising the retrieval limit does not give the summary more to work with. It
gives the **gap analysis** more, which needs no model, and it adds rows to
`evidence_removed`.

Nothing here is silent: each removal is reported with its source and the
characters dropped. But a reader looking at eight passages in the evidence
ledger and a summary built from two needs that list to understand why.

## Two comparators in NORSOK M-501 are lost, and are not guessed

`NORSOKM501Rev5.pdf` renders some glyphs in a symbol font that extracts as the
wrong character. Measured span by span through all twelve source PDFs:

| What | Count | Where |
|---|---:|---|
| Symbol glyph extracted as a Latin letter | 48 | all NORSOK |
| — of which the micro sign as `P` | 4 | `"1000 Pm NDFT"` |
| — of which a bullet as `x` | 44 | list items |
| Comparator extracted as a C1 control | 2 | p20, p21 |

**The micro sign is repaired** (`backend/app/symbols.py`), so `1000 µm NDFT`
now yields a measurement where it previously yielded none. The rule fires
**3 times across 3,717 pages** and is anchored on both sides, because
`book2-Differential-Equations.pdf` contains `Pm(x)Pn(x)` — Legendre
polynomials, where P is genuinely P and is even preceded by a digit.

**The fourth `P` is not repaired.** Its digit is on the previous line, so the
rule declines it rather than guess.

**The two comparators are not repaired, deliberately.** On p20 the coating
thickness reads `<?> 1000 µm NDFT` and on p21 `operating temperature <?> 80`.
The byte does not say whether the character was `>` or `≥` — and those mean
different things to a claim comparison, so inventing one would be the
invented-measurement defect one level up. The number is extracted; the
comparator is absent, which means the value is compared as a point value
rather than as a bound.

**The bullets are not repaired either.** A rule matching `x` at the start of a
line hit **1,051 places, of which only 44 were NORSOK's bullets** — the other
992 were the variable `x` in the differential-equations textbook. It cannot be
gated without the span's font, and `get_text("text")` does not carry fonts. A
bullet drawn as `x` is cosmetic; a missing `µm` loses the answer.

## A generated sentence carrying an unsupported number is deleted, not flagged

If a sentence cites a source but contains a number that appears in no span it
cites, the sentence is **removed from the prose entirely**. It is reported in
`dropped_sentences` with the reason and the offending number, so the loss is
visible and auditable — never silent.

**This deletes some legitimate sentences.** A model that rounds "279.6 µm" to
"280 µm", or restates a figure in different units, loses the sentence even
though it said something true.

That trade is deliberate. The alternative — keeping the sentence with a
`number_unsupported` flag — still puts the number on the screen, and a reader
takes the number. This build has already recorded twice that a warning shown
beside the thing it warns about gets ignored. The asymmetry decides it:
dropping a good sentence costs a **paraphrase**, and the passage it paraphrased
is still cited and quoted verbatim below it; keeping a bad one puts a converted
or invented figure in front of an engineer as though the document had stated
it.

The case that motivates it is a silent unit conversion — "0.28 mm [S1]" over a
source that says "280 um" cites a real page for a number that page does not
contain.

**Where this check runs, and exactly what it accepts (2026-09-30).**

- It runs on every lane: the cross-document summary (`synthesis._cite`), the
  local chat lane (`answer.ground_numbers`) and the Claude chat lanes
  (`answer.verify_claims`, used by the one-shot answer, the streamed answer and
  Claude-first chat). On the Claude lanes a quote found on the page is NOT
  enough: every figure in the sentence must also be in a passage the sentence
  cites. Until 2026-09-30 "6 mm [S1 "minimum wall thickness"]" over a page
  saying 3 mm was shown as verified.
- Clause, table, page, revision and standard numbers are removed from the
  sentence AND from the cited passage before comparing, so a page's "clause 6"
  never supports an answer's "6 mm".
- The summary lane accepts exact figures only, so "279.6 µm" restated as
  "280 µm" is still lost there. The chat lanes also accept a genuine rounding:
  fewer decimals than the page, and equal to the page's value rounded to that
  precision ("17.2" or "17" for 17.24). "17.4" for 17.24 is removed. A figure
  written in words ("six millimetres") is not checked at all.
- A Claude quote must be at least three words, found on word boundaries
  (`model_evidence.claim_quote_verified`). One- and two-word quotes ("the",
  "10 barg") are on nearly every page and prove nothing. A word the PDF
  hyphenated across a line break matches the unbroken word; this layout rule
  goes beyond the owner's closed normalisation list for B5 values and applies
  to chat claim quotes only.
- A point read from a page image with no text layer cannot be checked. It is
  kept, labelled "read from image - check the page", and never counted as
  verified. The label is the same while the answer streams (it used to show
  as a bare `[S1]` until the answer finished; M1610).
- A chat turn whose first Claude call fails after it was sent (so it is
  charged) and falls back to the local pipeline shows that charge in the
  answer's cost, with a notice saying so - the ledger and the answer agree
  (M1611, M1614).

## Public market information is a fixture and can never become one by accident

**There is no provider and this machine makes no network call.** Every row on
the market panel is loaded from `backend/app/samples/market_sample.json`, is
marked `is_sample: true`, and carries a `sample://` URL - a scheme that
resolves nowhere, chosen so a row cannot become a real citation by being
clicked.

The rule that a sample is never presented as a source is enforced at LOAD time
rather than at render, three ways: a row without `is_sample: true` is refused,
a row whose URL is fetchable is refused, and a row claiming `source_read` or
`snippet_only` is refused. The failure this guards against is not somebody
writing `is_sample: false` on purpose - it is a real row being pasted into the
fixture during a demo, which is why the `https://` case has its own test.

`MarketVerification` keeps all three values because that is what the word
means and a UI has to render each; `MarketFinding.verification` is pinned to
`source_not_verified`, so the API cannot emit the other two.

**No query has ever left this machine.** `POST /api/market/preview-query`
builds the object that *would* be sent and returns it with `sent: false`. It is
assembled from the caller's own words and two public fields, never from
retrieved document text - a query built from a client's specification would
exfiltrate that specification to a search engine one phrase at a time.

**The phrase is built by whitelist, word by word.** Besides public standard
designators, a word reaches the phrase only if the bundled English vocabulary
vouches for it: `backend/app/reference/english_words.txt.gz` (lower-case words
from SCOWL's en_US dictionary - so no proper noun, place or company name - built
by `scripts/build_english_words.py`; British spellings accepted by ending) plus
a short reviewed list of public engineering abbreviations
(`reference/market_extra_words.txt`). An unknown word ("zqx", a project code, a
facility's name) is dropped (M1608-M1609, M1613). Limit, stated: a genuine
technical word missing from both lists is dropped too - the phrase gets
blunter, never wider.

**What this does not claim:** nothing here is market research, and no figure in
it is real. The panel exists so the shape of the feature - where verification
sits, what a reader is told about provenance - can be reviewed before egress is
ever considered, rather than on the day the network is opened.

## Evidence reports are single-answer, and three things about them are not proven

**Not the analysis report.** A report is one question, its quoted evidence and
the documents cited, frozen when generated. It says so in a bordered box on
page 1 and names what it does not contain: coverage ledger, gap analysis,
recommendation, public-market findings. No revision or approval status either -
those columns do not exist on `documents`, and the report prints "not recorded"
rather than inventing one.

**`report_sha256` is not a reproducibility hash.** It is the SHA-256 of the
stored PDF bytes and proves the file on disk is the one issued. PyMuPDF embeds a
producer string and an ID array, so re-rendering the same snapshot on a
different build gives a **different file hash and identical content**. Compare
`snapshot_sha256` for content. Someone who re-renders and treats the differing
file hash as corruption has misread which hash is which.

**Arabic is shaped and not proven correct.** The spike (CHANGELOG, 2026-09-05)
rendered a mixed Arabic/English paragraph through `Story` in the embedded Noto
Naskh Arabic with no missing glyphs and with contextual (joined) forms present.
What nobody has done is have a reader of Arabic look at the page: **glyphs
appearing is not evidence of correct joining or correct bidi order.** The test
that covers this says in its docstring what it does not prove. Arabic body text
is confined to `Story`; the simple text APIs perform no shaping and would print
unjoined Arabic that still looks like Arabic to a non-reader.

**Tables that span a page break lose their header.** Measured in the spike:
`<thead>` does not repeat in PyMuPDF `Story`. A single-answer report cites at
most three documents, so its table does not span. Any future report with a
long table needs its header re-drawn per page.

**Not cleared for client distribution.** PyMuPDF now generates a deliverable
rather than only parsing an input. That is a different licence question
(AGPL-3.0 / commercial dual) from the one already answered for ingestion, and
it is open.

**Download needs `auth_mode=disabled` today.** The PDF is fetched by a plain
browser navigation, which cannot carry the bearer token. Under `demo_required`
the download returns 404 until the client fetches it as a blob.

## An answer includes at most three passages

**When more than three credible passages exist, the ones beyond the cut are not
shown.** The answer takes its highest-ranked passages only; a passage that
cleared the credibility floor in another document can be left out of the answer
entirely, and nothing on screen says it existed.

This is a client-facing limit and it was invisible until 2026-09-05.

Measured on gold question Q4 (*"what should an organisation do to contain and
eradicate a security incident?"*): the correct *3.8 INCIDENT RESPONSE* section
of a second document was retrieved, shortlisted, scored **+2.104 against a
-3.0 credibility floor**, and placed **fifth of sixteen** - above four passages
from the document that was cited. It was not missed and it was not judged
irrelevant. It was fifth, and the answer takes three.

**As of this commit the coverage report exists in the API and not on screen.**
`AnswerResult.coverage` names every such document with the status
`credible_not_cited`. Until the UI renders it, those passages are not shown to
the reader *and not reported to them either* - the API knows, and the screen
does not. Raising the passage count is deliberately not the fix: three expanded
sources already have to fit inside the model's context window, and overflowing
it silently truncates the evidence the answer is grounded in.

## Scope not implemented

- **OCR reads scanned pages, and its output is never presented as a quotation.** Recognised text is a guess about pixels, so it is stored separately (`page_ocr`), labelled *"Read by OCR from a scanned page — not the document's own text"*, and shown with the page image expanded rather than collapsed. See ADR-0005 and ADR-0006.
  - **No accuracy claim is made, because this corpus cannot support one.** Of 74 flagged pages, those carrying text are book covers and Excel/Mathematica UI screenshots — not scanned specification prose. Measured errors on that material include `Pyblish` for "Publish" and `Ja66nqaa` for "Debugger". **Neither model has been tested on the content this system is for**, and no number will be quoted until the client documents arrive. Saying so is worth more than a figure nobody can defend.
  - **The tiny-vs-small choice is a judgement call on unrepresentative evidence, recorded as one.** `small` is visibly more accurate (4.9x slower); the pages that expose the difference are UI screenshots we will never answer from. Revisit on real documents; it is a config value, not a code path.
  - **PP-OCRv6 has no English model** — every artefact is multilingual, so recognising English pages emits CJK. **Measured across the whole corpus: 18 of 77 recognised pages (23%) contain characters the document cannot contain**, 84 characters in total, including `≦` on two pages where a specification would say `≤`. The CJK ideographs are obvious; `≦` is not, and that is the dangerous one. An alphabet guard counts these per page and flags them; under an English recogniser it cannot fire at all, which makes it a guard on the guard. The engine choice is open pending one client question: whether the client documents contain Arabic.
  - **No confidence threshold is set.** Confidence is stored per page and per chunk, and a sub-threshold page would go to the exclusion ledger under its own rule — but the threshold itself is not set, because there is no labelled ground truth to set it from. The lowest chunk confidence observed so far is 0.501. Until it is measured the gate stays open: recognised text is indexed and labelled, never silently dropped.
- **Chunking assumes a clause is a paragraph. On a catalogue whose atomic unit is a TABLE ROW, citations point at the wrong granularity.**
  - **Which documents this applies to.** Any reference catalogue built as a long series of short, uniformly structured entries — a controls catalogue, a requirements register, a parameter table, a glossary of numbered items — where the thing a reader asks about is one row rather than one paragraph. It does **not** apply to prose specifications like NORSOK M-501, which is what the chunker was tuned on and where a clause genuinely is a paragraph. A reader can tell which kind they have without re-running anything: if the answer to a typical question is one row of a table, this limit applies.
  - **Measured on NIST SP 800-53r5** (492 pages, 963 retrievable chunks), against the four documents the chunker was developed against:

    | | SP 800-53r5 | Rest of corpus |
    |---|---|---|
    | Median chunk | **432 tokens** | 255–289 |
    | Chunks at the 480-token ceiling | **47%** | — |
    | Chunks classified `table` | **0** | 95 / 21 / 9 |
    | Chunks holding more than one control ID | **61%** (median 3, max 67) | — |

  - **What the reader actually sees.** Ask about `AC-2` and you get the right document and the right region of it, quoted accurately — under a section heading of `1.1 PURPOSE AND APPLICABILITY`. The citation names the chapter that contains the control, not the control. Nothing is wrong in the quoted text; the label above it does not name what was asked for, and a reader checking the citation has to find the control themselves.
  - **Deliberately not fixed.** Chunk sizing, quality thresholds and retrieval heuristics are frozen for the current sprint: changing them would invalidate every measurement in `docs/benchmarks.md`, which is the whole evidence base. Recorded as a limit and a demo boundary instead — **ask a controls catalogue about concepts, not about control IDs.**
- **No ANN index** — brute-force vector search. Correct and fast at prototype scale; requires an index before full-corpus use.
- **Perfect table and diagram extraction is not claimed** for every PDF type.
- **Table column pairing is not preserved.** A table chunk keeps its caption, headers and every value in reading order, one cell per line, but the row/column pairing is positional rather than explicit. A reader can see the table; a search engine cannot reliably answer "what is the value at row X, column Y".
  - **Plan, deferred deliberately:** when the real client documents arrive, run PyMuPDF `page.find_tables()` on *only* the pages already flagged `kind=table`, to recover real rows and cells. Building this before we know what the client's tables look like would be guesswork.
- **Mathematical notation degrades.** PyMuPDF text extraction loses `=` and `+` operators and flattens sub/superscripts, so an equation-dense page becomes prose *about* mathematics with the mathematics missing. Not fixable in text mode, and re-implementing a PDF layout engine is out of scope.
  - **The flag is conservative and NOT exhaustive.** On a 613-page differential-equations textbook only 11 pages were flagged. The signal is weak precisely *because* the equations were already stripped by extraction — a page whose mathematics vanished cleanly leaves little evidence that it ever contained any. Treat `equation_pages` as "the worst offenders", never as "every page whose mathematics degraded". This is deliberately not being tuned further: page images are the mitigation, and client specifications are prose and tables rather than dense mathematics.
  - **Made visible, not hidden.** Pages are scored for equation density at extraction and flagged `equation_heavy`, the same way `needs_ocr` works. `GET /api/documents/{id}/pages` reports the flag per page and the document record carries an `equation_pages` count, so a degraded page is visible rather than quietly useless.
  - **Mitigated by page images.** `GET /api/documents/{id}/pages/{page}/image` renders the real page to PNG on demand (150 DPI default, cached by content hash). The citation panel shows the actual page beside the quoted text, so whatever the extracted text lost — equations, table column pairing, figures — the reader still sees the truth. This is the durable answer to both degraded equations and flattened tables.
  - A side effect: equation debris is sometimes segmented as `kind="table"`. The quality gate correctly rejects it (fractions extract as `1 / 210 / 250 X dX`), so it is recorded in the exclusion ledger rather than retrieved as a table.
  - **An OCR engine failure fails pages, not the document** (audit 2026-09-30). A missing or corrupt OCR model, or a recognition worker process that dies, records every page it held as `ocr_failed` with the reason (`page_ocr.error`, the exclusion ledger, the page ledger) and the document finishes on its extracted text. It used to mark a readable document `failed` and retry it until poisoned. After the cause is fixed, `ocr.retry_failed` makes those pages pending again.
  - **Search never answers from a document that stopped without being answerable** (`failed`, `no_searchable_content`, `stored_not_indexed` - `states.NOT_SEARCHABLE_STATES`, applied inside `keyword.search` and `vector_store.search`). A `failed` document used to keep answering from chunks an earlier pass indexed while the Documents page called it failed. A document being re-processed (queued, extracting, chunking, indexing) keeps answering from its last complete build, which `chunk_document` replaces in one transaction. Readers of `chunks_fts` outside `keyword.search` (for example the vocabulary the answerability check reads) are not narrowed and may still see a failed document's words.
  - **A re-chunk keeps the vectors of chunks that did not change** (audit 2026-09-30). Only a vector whose chunk id is gone, whose chunk is no longer retrievable, or whose section or heading chain changed is deleted and re-embedded. Until then every re-chunk (every OCR round that found text, every re-process) deleted all of the document's vectors and dense search was dark for it until embedding caught up.
  - **A document can finish with nothing searchable.** A fully scanned PDF, or one whose every chunk fails the content-quality gate, reaches the terminal state `no_searchable_content` — never `ready`. The reason is carried on the record (for example, that all pages were scanned and recognition produced no usable text) and the UI renders it as a warning, not a success. Calling such a document ready would tell an operator it is usable when it can answer nothing.
- **Front matter, contents, index and references pages are excluded from search.** They are classified and stored, with `retrievable=0`, so they can be inspected, but they never compete with body text. A contents line such as "5.3.1 Identity Theft 257" would otherwise outrank the page where the answer actually is.
- **The contents/index detector is positional and will not generalise to the real corpus.** It looks for contents pages in the front 6% of a document and index pages in the back 15%, which is right for books. Client specifications are often multi-part compilations with contents pages part-way through, which this rule would miss.
  - **Durable answer:** the generic content-quality gate, not more positional detectors. The gate rejects a chunk whose text does not read like natural language (alphabetic ratio, symbol ratio, proportion of real words, average word length, longest unbroken run, control characters), and it catches failure modes no structural detector anticipated. Tuned against known-good prose and known-bad symbol-font tables: 0 of 1033 good chunks rejected, 157 of 159 known-bad rejected.
- **Section headings are null when uncertain.** A heading is only accepted from an unambiguous numbered pattern. Roughly 12% of retrievable chunks carry no section. That is deliberate: a wrong heading in a citation is worse than a missing one.
- **Context notes (CHUNKER_VERSION 8) help search find a clause by the heading ABOVE it - only after re-processing.** A chunk's section is its nearest heading, and for a numbered requirement only its number, so "4.2.2" under "4.2 Pipes larger than 2 inch" never said "larger than 2 inch". Each chunk now records its heading chain in `chunks.context`, read by the keyword index, the embedder and the reranker; the quoted text is unchanged. Limits, stated:
  - **Existing documents gain nothing until they are re-chunked** (`scripts/reindex_chunking.py`, an owner decision). Their `context` is NULL and they search exactly as before.
  - **The chain is only as good as heading detection.** Where no heading was accepted (the ~12% above) there is no chain; a clause is filed only under headings whose number is a prefix of its own ("4.4" never under "8"); an unnumbered heading starts a new chain and a numbered one drops it; a clause number reused under two different chains gets no context rather than a guessed one.
  - **Deterministic, not generated.** The chain is the document's own headings. A model-written note per chunk (the published "contextual retrieval" method) is not built: on this hardware it would cost hours per full re-process and is measured first if ever proposed.
  - **Deployment is safe without a re-process.** Vectors written before this change (input format `heading-v1`) stay searchable (`embedder.LEGACY_PASSAGE_INPUT_VERSIONS`) and are upgraded when their document is processed (any worker pass through embedding re-embeds a legacy vector - until 2026-09-30 only a pass where some chunk had no vector at all did; a READY document is not processed again on its own, so it is upgraded when it is re-processed); the keyword index rebuilds itself once at server start (INDEX_VERSION 3), writing identical rows for chunks with no context.
  - **Not yet measured on the owner's corpus.** Whether it fixes the "right clause never found" cases (43 of 66 in the 2026-09-29 calibration) is measured by re-running `eval/refusal_calibration.py` on a re-chunked diagnostic copy, with the SAME questions as before.
- **Which clause applies (plan step 4) reads conditions with fixed patterns.** When near-equal clauses set different values for different conditions, a question naming a condition is answered from the one clause that holds under it, and a question naming none gets every clause with its condition and a question back (`answer._condition_choice`, `condition_choice.py`). Since 2026-09-30 the same holds inside ONE passage, in the generated tier, and in the answer-level verdict (below). Limits, stated:
  - **Only what the patterns read.** Size (inch incl. fractions like 1-1/2, mm, NPS, DN via the ASME B36.10 pairing; "larger than", "and smaller", ranges), temperature (°C, °F, negative values), pressure (psi, bar, kPa, MPa), ASME class and PN, and closed lists of services, materials and locations (a bare "wet", "dry", "steam" or "atmospheric" is not one: "dry film thickness"). A condition written any other way is not seen, and the answer is the top passage exactly as before.
  - **A bare number in a clause is a value, not a condition.** "shall be 5 mm" is what the clause sets; only a comparison, a range or a nominal pipe size ("6 inch pipe", not "thickness of 1/4 inch") is read as the case a clause applies to. So a table row "| 6 inch | 5 mm |" (a bare size, no "pipe" beside it) is not read as a case; "| 2 inch and smaller | 3 mm |" is.
  - **A question's range must lie wholly inside a clause's.** "larger than 2 inch" is not answered by "2 inch and smaller" (they share only the excluded endpoint). Found by the 2026-09-30 audit before merge; pinned by tests.
  - **One passage that lists several cases is read line by line, and quoted whole.** "pipes 2 inch and smaller: 3 mm; pipes larger than 2 inch: 6 mm", or a table whose rows are size ranges (`condition_choice.cases`, `answer._passage_cases`): a question naming a size gets the line that holds HIGHLIGHTED and a note saying so; a question naming none gets every line listed with its condition (options pointing at the same passage) and the highlight spanning all of them. The quoted text is never changed. Limits: only in the quoted-answer tier and only when no rival clause competed (a clause chosen from rivals is not also split into lines); one kind of condition per passage (the one with most distinct cases); a line is bounded by `;`, a row break or a sentence end, so cases separated only by commas inside one sentence are cut at the next case; and it applies only when the sentence the question matched is part of, or leads straight into, the lines - a list of cases elsewhere in the passage is left alone.
  - **An options answer is `depends_on_condition`, not `supported`.** `answerability` returns this verdict (schema, `contracts/types.ts`, the chat headline "The value depends on a condition the question does not state") whenever `condition_choice` is in options mode, clause-level or within one passage, in either tier.
  - **Same-document conflicts are flagged, with a narrow definition of "different clause".** Two passages of ONE document stating different values in the same unit for what was asked are `conflicting_evidence` - unless the condition reader sees them written for different cases (then `condition_choice` is what shows them), or they are listed as condition options. "Different clause" means both passages carry a section and the sections differ: a passage with no section (about 12% of chunks) is never compared with others of its own document. The conflict check itself is the same coarse one as across documents (the best-matching sentence of each, number plus unit).
  - **Never a guess.** A question naming a condition that no single clause (or line) meets, or that several meet, keeps today's answer. Values are never merged into one.
  - **The generated (Tier 2) answer is warned, not rewritten.** The model's prose and its citation and figure checks are unchanged. A question naming a condition sends the clause that holds first and does NOT send a clause written for another case of that kind (a clause stating no such condition is still sent); a question naming none gets the options notice, narrowed to the passages the model was actually given (two needed), saying the answer may mix them. The model itself is not told about the conditions, and the lines of one passage are not read in this tier.
  - **Not yet measured on the owner's corpus.** The 2026-09-29 calibration scored 66 of 166 answers as "a different clause with a different value"; a 20-case check (automatic, counts only, not an engineer's verdict) suggested about two in three were unsized questions. The calibration's scoring must count an options answer that includes the right clause separately before this can be measured.
- **Tables were already kept as tables.** Checked 2026-09-30 before building anything for it: a ruled table is split on row boundaries with its caption and header row repeated at the top of every piece (`chunker._split_structured`), so a value is never separated from its column header. Nothing changed there.
- **RBAC and password authentication exist and are OFF BY DEFAULT.** `auth.py` (389 lines, 23 tests) implements login, a signed bearer token and role-scoped document access, and there is a login screen — that shipped in commit `e1d7ea7`. But `AUTH_MODE` defaults to **`disabled`** (`backend/app/config.py`), and in that mode every request is unauthenticated and every document is visible to whoever opens the app. **A deployment that does not set `AUTH_MODE=demo_required` has no access control at all.** The shell header now says so — `RoleBadge` renders "Authentication disabled — no user identity" (`LoginView.tsx:187`) — which corrects the previous sentence here, "and nothing in the UI says so". That was true when written and stopped being true with the redesign. The header states the condition; it does not prevent it.

  The role model gained a `kind` column in the same period: `admin` is a capability held alongside a discipline, not a fifth discipline (`db.py`). The four seeded disciplines are Civil Engineering, Mechanical, Chemical/Process and IT. **No admin screen is reachable in this build** — users, disciplines and grants are still managed by `scripts/seed_access.py` from a terminal.
  - **Turning it on activates five documented holes, none of which is fixed** (`docs/design-access-holes.md`). All five are pre-existing and all five are invisible while `AUTH_MODE=disabled`:
    1. **Page images bypass the bearer token** — `GET /api/documents/{id}/pages/{n}/image` takes no scope, so a guessed document id returns a rendered page of a document the caller may not see.
    2. **Conversations are unscoped** — history is not filtered by owner, and a conversation written before there were users has `owner_user_id` NULL.
    3. **Upload is unscoped, and its deduplication is an oracle** — anyone may upload, and the "already indexed" response tells an unauthorised caller that a document with that hash exists.
    4. **`/api/metrics` declares a scope and discards it** — it returns filenames across the whole corpus.
    5. **`DELETE /api/conversations/{id}` takes no scope at all** — any caller may delete any conversation by id.
  - Also absent: **SSO, high availability, disaster recovery, and enterprise key management**. Password setup/reset is available through administrator-issued, 24-hour, one-time tokens; there is no email delivery service.
  - Fine for a demo on a machine you control. **Not fine on a client's machine.**
- **No domain fine-tuning**, and no production accuracy claim.
- **Full corpus not ingested.** ~45 GB free disk does not accommodate ~1.2 M pages.

## Submittal review and the CRS - what the engine decides, and what it leaves to the engineer

Corrected 2026-09-30 after an audit of the CRS path (`backend/tests/test_audit_crs_fixes.py`, mutations M1430-M1449).

- **Equipment exceptions depend on the sheet's classification.** "90 dB(A), except pressure relief valves 115 dB(A)" applies the 115 only when the submittal's stored `equipment_type` (confirmed by an engineer, or read by the classifier from the sheet's own title) names that equipment. An unclassified sheet gets the general limit. Matching is one-directional: every word of the exception's equipment must be in the equipment type ("Pressure Safety Valve" is a pressure relief valve; a sheet classified only as "valve" does not borrow the exception). Before this fix no production path passed the equipment at all, so every exception was ignored.
- **Closed categorical clauses (flange class, radiography extent, PWHT)** are read as: minimum ("minimum Class 300"), ceiling ("shall not exceed Class 600"), exact, prohibited ("Class 150 flanges shall not be used"), or alternatives ("Class 150 or Class 300"). A clause saying something is *not required* or *optional*, a clause with any other negation, two radiography extents, or a class list in any other shape gives **no categorical verdict** - it becomes a question for the engineer. A size scope ("nozzles 2 inch and larger") makes the clause conditional, so it is reported, never decided.
- **Conditional requirements are decided from the datasheet's own facts, only where the condition is fully read** (review conditions, 2026-09-30; `conditions.read_condition`, `backend/tests/test_review_conditions.py`, mutations M1560-M1579). A `numeric_limit` requirement whose condition reads "for pipes larger than 2 inch", "Class 600 and above", "in sour service", "for carbon steel" or "above 60 °C" is compared only when the datasheet puts it inside the condition; clearly outside gives NOT_APPLICABLE with the condition and the datasheet value and page quoted, and the CRS lists it on the engineer's Review notes ("Not applicable - datasheet is outside the requirement's condition"), never as a contractor comment or a breach. What is read, and what is not:
  - **Parsed by `condition_choice`**: size (inch, NPS, DN; "larger than", "and smaller", ranges), temperature (°C, °F), pressure (psi, bar, kPa, MPa), ASME class and PN with "and above" / "and below", and the closed service and material lists. Anything else in the condition text beyond connectives and generic nouns ("hydrocarbon", "unless ...", "critical", a location such as "buried") makes the condition **unknown -> engineer review**, even when the part that was read is clearly outside. Same-kind alternatives that are not parsed ("... and alloy steel systems") may still let a matching material apply the clause, but never excuse it. "Or" between different kinds, or two bounds of the same kind ("larger than 2 inch and smaller than 24 inch"), is not decided. A condition in which nothing is parsed ("Type K thermocouples", "titanium") goes through the older B24 term gate exactly as before.
  - **Datasheet fields by role only**: nominal size from NPS / DN / nominal size / line, nozzle, pipe or valve size (never a wall thickness or other length); temperature and pressure from the DESIGN field, or the OPERATING field only when the condition says "operating"; class from a flange / pressure rating that reads as an ASME class or PN; service from service / fluid fields, and "outside sour" only from an explicit "No" in a sour/H2S field or "non-sour" / "sweet" - a service such as "crude oil" is unknown, not "not sour"; material from material fields, and "outside" only when every stated material is a known base metal of a different family (a grade like "A106 Gr B" is unknown - there is no grade-to-material table). A value must be one reading that accounts for every number it states ("6 x 4 inch", "-29 / 95 °C" and a temperature with no unit are unknown); a range straddling the bound is unknown.
  - **Per item**: a value about one equipment tag or nozzle mark is judged on that item's facts and on untagged ones, never on another item's.
  - **Low-trust values** (the same test as the breach guard: `needs_engineer_review` / `conflict` validation state or model-read, unconfirmed) never establish a condition on their own, and a trusted answer that an untrusted reading would change is held for the engineer. This now applies to the older term gate too.
  - **Not done**: no synonym or grade tables, no location conditions, no "operating" vs "design" choice when a condition names neither beyond defaulting to design, and the model tier is not told about conditions.
- **Datasheet self-checks treat untagged fields as the sheet's common section.** A value stated once for P-101A and P-101B counts for both tags. A value stated under one tag is never used for another.
- **"Label : value" one-per-line sheets are read line by line.** Inside a text block of several lines, a line of that shape with no drawn answer slot is a pair by itself; other lines are paired left to right as before. A one-line block is still left to the geometry reader, and a line with a drawn slot is still cut by the slot rule.
- **No verdict rests on an untrusted value.** A datasheet value with `validation_state` `needs_engineer_review` (below the confidence threshold, including the OCR fallback) or `conflict`, or read by the model reader, and not confirmed by an engineer, produces neither NON_COMPLIANT nor COMPLIANT: the finding is NEEDS_ENGINEER_REVIEW with reason `LOW_TRUST_VALUE`, the arithmetic kept in its words, and the CRS question row says why ("Engineer to check: the value was read with validation state ... so no verdict (neither compliant nor a breach) is stated ..."). Corrected 2026-09-30 (leftovers, `test_audit_leftovers.py`, M1600-M1601): a COMPLIANT on such a value used to be accepted.
- **A re-run keeps every engineer decision.** Confirmed, accepted, rejected, dispositioned or re-worded findings survive any re-run (`review.UNDECIDED_SQL`, used by the comparison, the job cancel path, the AI engineering check and the web standards check). A pair the engineer rejected is not proposed again in that run; identical AI/web items and datasheet checks the engineer rejected are not re-proposed either. A NEW run of the same submittal can still raise the same comment as an unconfirmed draft - kept, never silently dropped, but its "Comment By" ends "previously rejected by <display name> on <date>" (from the rejection on record, on any run of that submittal the caller may read), so the engineer is not asked twice blind (M1606-M1607). A confirmed row is never marked.
- **A rejected comment is never issued.** A numbered comment rejected before the contractor replied is *Withdrawn*: not carried forward, not issued, and a later draft of the same comment is not treated as confirmed. Confirming or accepting it again re-opens the same number. A comment the contractor has already answered was issued, so a rejection does not withdraw it; the reviewer closes it.
- **CRS workbook cells are written as text.** A value beginning with `=`, `+`, `-` or `@` (a contractor reply included) is stored as a text cell, never a formula; control characters that Excel cannot store are replaced by a space rather than failing the export. The bylines print the engineer's display name. A carried-forward comment snapshotted before that change is resolved to the display name when it is printed (M1605); an id with no display name on record is printed as the id - a name is never invented.
- **"Could not be read as a number" is said as that.** A value like "see note" is reported as unreadable, not as a unit mismatch between two identical units. Two values with no unit at all are reported as that ("neither the submitted value nor the requirement states a unit ..."), and one missing unit names only the unit that exists (M1602-M1603); the Claude recheck still reads these as "not compared" (M1604).

## Security and governance

- ⚠️ **This is a locally-inferencing system on a networked machine. It is NOT air-gapped.** Client document content never leaves the machine, but the machine has internet access.
- The repository is private but on GitHub **free tier**, where four controls are **unenforceable** and must not be described as enforced:
  - No direct pushes to `main`
  - No force pushes to `main`
  - Required status checks before merge
  - GitHub Advanced Security secret scanning
- Compensating controls are in place: gitleaks in CI **and** as a pre-commit hook, plus a CI guard rejecting client documents. These are verified by deliberate failure tests.
  - **Corrected 2026-09-30.** The CI guard checked file EXTENSIONS only, and its synthetic-fixture exception (`^tests/fixtures/synthetic/`) matched nothing because the tests live under `backend/`. It now also fails a pull request or push that ADDS a client-identifier-shaped token (`scripts/check_client_identifiers.py`, patterns in `.github/client-identifier-patterns.txt`). **Limits, stated:** it scans the diff only, so identifiers ALREADY tracked (screenshots, CSV, JSON - pending the owner's history clean-up) are not reported; the tracked patterns are generic SHAPES (equipment tags, document and datasheet numbers), because a tracked list of the client's names would publish them - the names are checked only on a machine holding `.githooks/client-identifiers.local`, never in CI; binary files (images, PDFs) are not read at all.
  - gitleaks allowlisted the WHOLE of `.env.example`, so a real key pasted into it was invisible (verified with gitleaks 8.30.1 and a planted key). Only its empty `KEY=` placeholder lines are allowlisted now.
- **Access-control hardening, 2026-09-30** (tests in `backend/tests/test_access_audit_security.py`):
  - The API refuses any `Host` header other than localhost, 127.0.0.1, ::1, a named `HOST`, or a name listed in `ALLOWED_HOSTS` (DNS rebinding). The server refuses to START with a non-loopback `HOST` under `AUTH_MODE=disabled` unless `ALLOW_UNAUTHENTICATED_NETWORK_BIND=true`.
  - `/docs`, `/redoc` and `/openapi.json` answer 404 unless `AUTH_MODE=disabled` or `API_DOCS_ENABLED=true`.
  - The summary schedule, escalation rules, baseline rules and review templates are global settings and need the admin capability (their only UI is the admin screen, `AdminView.tsx`; the server now agrees with it). A non-admin calling the API directly gets the admin surface's silent 404.
  - A password reset (issued by an admin, and again when redeemed) ends every session the user had.
  - `POST /api/risks` checks `source_finding_id`: a finding on a document the caller may not read answers 404, the same as one that does not exist (leftover fixed 2026-09-30, M1612).
  - Still open, not addressed here: rate limits exist only for login.
- "No document content leaves the machine" reduces exfiltration exposure. It does **not** remove malicious-PDF, local-account, disk-theft, dependency, or privilege-escalation risk.
- **The client's security architecture and data-classification review remains a production gate.**

## Measurement honesty

- No accuracy or throughput figure is claimed without a recorded benchmark in `docs/benchmarks.md`, stating hardware, corpus, version, and sample size.
- Domain accuracy cannot be claimed until the client supplies answerable and unanswerable questions with expected page evidence.
- **Every result file records the corpus it actually ran against**, read from
  the database — document count, chunk count, retrievable count, excluded
  count, vector count, and a hash of the document ids — plus free RAM and
  whether the answer model was resident. Previously the stored corpus was a
  static string from the questions file, which made all nine stored results
  unattributable and cost a retracted finding (see
  `status-honesty-audit.md`, instance nine).
- **A latency figure is only comparable against one measured in the same
  session.** Absolute latency on this machine moved 1,434-4,291 ms on an
  unchanged corpus, correlating with free memory at r = 0.977.
