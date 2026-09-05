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

## Known false refusals - phrasing sensitivity

- **6 of 10 facts answer identically across three phrasings; 4 do not.** Measured by `eval/run_phrasings.py`, which asks each fact as originally written, as the document words it, and as a user loosely types it.
- **The 6/10 held through a corpus doubling** — the same 6 of 10, unchanged, after a 1,400-page document was added. A result that survives the corpus changing underneath it is evidence of a real fix rather than one fitted to the measurement, so it is recorded as such.
- Two are **false refusals** where the correct passage was retrieved at rank 1 and then rejected:

| question | correct passage | rerank | outcome |
|---|---|---|---|
| "how humid is too humid to paint" | 4.4 Ambient conditions, p7 | -5.09 | refused |
| "how often do i check humidity and what's the max" | 4.4 Ambient conditions, p7 | -8.01 | refused |

- **Why this is not tuned away.** The cross-encoder's score for the same passage swings 16 points across two phrasings of one fact. Over 35 queries with known ground truth the answer-present and answer-absent populations do not separate on any shape statistic: a floor low enough to admit every correct-at-rank-1 query is -8.01 or lower, and the highest-scoring genuinely absent question the lexical gate permits scores -3.85. Such a floor admits **3 of 3** unanswerable questions. Lowering `MIN_RERANK_SCORE` trades three correct refusals for three confident wrong answers, so it stays absolute.
- **Mitigation, and it is how engineers work anyway: use the document's own words and write designators in full.** "relative humidity" not "humid"; "coating system no. 1" not "system 1" - though both designator forms now work.
- **A related vocabulary limit, not fixed:** "how much salt is allowed on the surface before painting" cites the wrong clause because the document says *chlorides* and *NaCl*, never *salt*. A domain-synonym problem; a curated glossary would fix it and is a decision for later, not a change made on one observation.

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
  - **No accuracy claim is made, because this corpus cannot support one.** Of 74 flagged pages, those carrying text are book covers and Excel/Mathematica UI screenshots — not scanned specification prose. Measured errors on that material include `Pyblish` for "Publish" and `Ja66nqaa` for "Debugger". **Neither model has been tested on the content this system is for**, and no number will be quoted until the Aramco documents arrive. Saying so is worth more than a figure nobody can defend.
  - **The tiny-vs-small choice is a judgement call on unrepresentative evidence, recorded as one.** `small` is visibly more accurate (4.9x slower); the pages that expose the difference are UI screenshots we will never answer from. Revisit on real documents; it is a config value, not a code path.
  - **PP-OCRv6 has no English model** — every artefact is multilingual, so recognising English pages emits CJK. **Measured across the whole corpus: 18 of 77 recognised pages (23%) contain characters the document cannot contain**, 84 characters in total, including `≦` on two pages where a specification would say `≤`. The CJK ideographs are obvious; `≦` is not, and that is the dangerous one. An alphabet guard counts these per page and flags them; under an English recogniser it cannot fire at all, which makes it a guard on the guard. The engine choice is open pending one client question: whether the Aramco documents contain Arabic.
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
  - **Plan, deferred deliberately:** when the real Saudi Aramco documents arrive, run PyMuPDF `page.find_tables()` on *only* the pages already flagged `kind=table`, to recover real rows and cells. Building this before we know what the client's tables look like would be guesswork.
- **Mathematical notation degrades.** PyMuPDF text extraction loses `=` and `+` operators and flattens sub/superscripts, so an equation-dense page becomes prose *about* mathematics with the mathematics missing. Not fixable in text mode, and re-implementing a PDF layout engine is out of scope.
  - **The flag is conservative and NOT exhaustive.** On a 613-page differential-equations textbook only 11 pages were flagged. The signal is weak precisely *because* the equations were already stripped by extraction — a page whose mathematics vanished cleanly leaves little evidence that it ever contained any. Treat `equation_pages` as "the worst offenders", never as "every page whose mathematics degraded". This is deliberately not being tuned further: page images are the mitigation, and Saudi Aramco specifications are prose and tables rather than dense mathematics.
  - **Made visible, not hidden.** Pages are scored for equation density at extraction and flagged `equation_heavy`, the same way `needs_ocr` works. `GET /api/documents/{id}/pages` reports the flag per page and the document record carries an `equation_pages` count, so a degraded page is visible rather than quietly useless.
  - **Mitigated by page images.** `GET /api/documents/{id}/pages/{page}/image` renders the real page to PNG on demand (150 DPI default, cached by content hash). The citation panel shows the actual page beside the quoted text, so whatever the extracted text lost — equations, table column pairing, figures — the reader still sees the truth. This is the durable answer to both degraded equations and flattened tables.
  - A side effect: equation debris is sometimes segmented as `kind="table"`. The quality gate correctly rejects it (fractions extract as `1 / 210 / 250 X dX`), so it is recorded in the exclusion ledger rather than retrieved as a table.
- **A document can finish with nothing searchable.** A fully scanned PDF, or one whose every chunk fails the content-quality gate, reaches the terminal state `no_searchable_content` — never `ready`. The reason is carried on the record (e.g. *"all 3 pages are scanned images with no extractable text; OCR is not implemented"*) and the UI must render it as a warning, not a success. Calling such a document ready would tell an operator it is usable when it can answer nothing.
- **Front matter, contents, index and references pages are excluded from search.** They are classified and stored, with `retrievable=0`, so they can be inspected, but they never compete with body text. A contents line such as "5.3.1 Identity Theft 257" would otherwise outrank the page where the answer actually is.
- **The contents/index detector is positional and will not generalise to the real corpus.** It looks for contents pages in the front 6% of a document and index pages in the back 15%, which is right for books. Saudi Aramco specifications are often multi-part compilations with contents pages part-way through, which this rule would miss.
  - **Durable answer:** the generic content-quality gate, not more positional detectors. The gate rejects a chunk whose text does not read like natural language (alphabetic ratio, symbol ratio, proportion of real words, average word length, longest unbroken run, control characters), and it catches failure modes no structural detector anticipated. Tuned against known-good prose and known-bad symbol-font tables: 0 of 1033 good chunks rejected, 157 of 159 known-bad rejected.
- **Section headings are null when uncertain.** A heading is only accepted from an unambiguous numbered pattern. Roughly 12% of retrievable chunks carry no section. That is deliberate: a wrong heading in a citation is worse than a missing one.
- **No authentication, RBAC, SSO, high availability, disaster recovery, or enterprise key management.**
- **No domain fine-tuning**, and no production accuracy claim.
- **Full corpus not ingested.** ~45 GB free disk does not accommodate ~1.2 M pages.

## Security and governance

- ⚠️ **This is a locally-inferencing system on a networked machine. It is NOT air-gapped.** Client document content never leaves the machine, but the machine has internet access.
- The repository is private but on GitHub **free tier**, where four controls are **unenforceable** and must not be described as enforced:
  - No direct pushes to `main`
  - No force pushes to `main`
  - Required status checks before merge
  - GitHub Advanced Security secret scanning
- Compensating controls are in place: gitleaks in CI **and** as a pre-commit hook, plus a CI guard rejecting client documents. These are verified by deliberate failure tests.
- "No document content leaves the machine" reduces exfiltration exposure. It does **not** remove malicious-PDF, local-account, disk-theft, dependency, or privilege-escalation risk.
- **Saudi Aramco security architecture and data-classification review remains a production gate.**

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
