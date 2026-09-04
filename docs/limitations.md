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

## Scope not implemented

- **OCR reads scanned pages, and its output is never presented as a quotation.** Recognised text is a guess about pixels, so it is stored separately (`page_ocr`), labelled *"Read by OCR from a scanned page — not the document's own text"*, and shown with the page image expanded rather than collapsed. See ADR-0005 and ADR-0006.
  - **No accuracy claim is made, because this corpus cannot support one.** Of 74 flagged pages, those carrying text are book covers and Excel/Mathematica UI screenshots — not scanned specification prose. Measured errors on that material include `Pyblish` for "Publish" and `Ja66nqaa` for "Debugger". **Neither model has been tested on the content this system is for**, and no number will be quoted until the Aramco documents arrive. Saying so is worth more than a figure nobody can defend.
  - **The tiny-vs-small choice is a judgement call on unrepresentative evidence, recorded as one.** `small` is visibly more accurate (4.9x slower); the pages that expose the difference are UI screenshots we will never answer from. Revisit on real documents; it is a config value, not a code path.
  - **PP-OCRv6 has no English model** — every artefact is multilingual, so recognising English pages emitted `凤`, `日`, `区` and `≦` for "Save". An alphabet guard counts characters outside the document's expected script and flags the page. The engine choice is open pending one client question: whether the Aramco documents contain Arabic.
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
