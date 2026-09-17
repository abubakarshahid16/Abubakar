# Changelog

Notable changes, newest first. Dates are the date the work landed on `main`.
Figures here are measured; where a number is not measured this file says so
rather than rounding a guess into a fact.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project has not yet cut a versioned release, so changes are grouped by
the day they merged.

## [Unreleased]

### 2026-09-17 — configurable engineering-review baselines

Engineering gap reviews can now use administrator-configured mappings from a
submittal's classified type/discipline to a searchable baseline. The selected
baseline is access-scoped and a manual document choice always takes priority.
The rule and selection endpoints are available under `/api/reviews`, with
regression tests covering automatic selection and manual override.

### 2026-09-07 — the false compliance gap, and a folder that ingests itself

User-facing, newest first. Every figure below was measured on this laptop.

**A compliance gap that did not exist is no longer reported.** Asked to
compare design submittal percentages across two specifications, the product
reported that only one document set a percentage - a gap. Both documents set
one: doc13 page 125 requires a 35% preliminary submittal, and doc16 page 18
asks for "at least a 50% design submission". Only the first was ever retrieved,
because one document had taken 18 of the 24 available evidence slots and, in
doing so, buried its own answer. A comparison is now capped so no single
document can supply more than a third of the evidence, questions that name
documents no longer pull in unrelated textbooks, and a question about
percentages gets a second pass for clauses that write the number as digits.
**This was the most serious defect this system has had**: it did not fail, it
answered confidently and wrongly, about compliance.

**Drop a PDF in a folder and it ingests itself.** No upload screen, no
clicking. The folder is watched; new files are picked up, and duplicates are
recognised by content rather than by filename, so re-dropping the same file
does not ingest it twice.

**Comprehensive analysis now reads every document separately before
consolidating.** It used to put everything into one request, which on this
hardware could quietly exceed what the local model would accept - and the model
declines rather than erroring, so the reader was told "the sources do not
support a summary" when the truth was that the request was too big. Each
document is now summarised on its own and the summaries consolidated.
**Expect Comprehensive to be slower**: measured at 118s before and 204s after
on one question, because it makes six model calls where it made one. On that
particular question the model still declined; the change removes one cause of
the failure, not all of them.

**Advice no longer disappears when the summary does.** The recommendation was
gated on the written summary, so if the model declined to summarise, the
advice vanished too - even where the mechanical document comparison had found
real conflicts and cited them. Advice can now rest on that comparison instead,
and says so in its first sentence, so a reader can tell what it was built
from. With nothing cited from either, it still refuses and names the reason.

**Uploading requires signing in.** Anyone who could reach the port could
previously add a document, and that document then belonged to nobody - it
could not be seen by the uploader, by an administrator, or on any screen.
Uploads now require an identity, and a new document is immediately visible to
its uploader's discipline and to administrators. Re-uploading a copy of a
document you cannot see tells you nothing about it.

**The product is now called the RAG Intelligence System.** The former codename
is gone from the interface and from downloaded report filenames.

**Gap rows no longer contradict the evidence printed beside them**, and the
Dashboard's machine specifications are visible only to administrators.

#### Known, and not fixed

- Three page-level retrieval misses remain: doc16 pages 23, 24 and 25 are not
  retrieved for the questions that target them. Right document, wrong page.
- Search is still literal about spelling: a misspelled query can return
  nothing rather than correcting itself. The work exists but is not merged,
  because it touches the retrieval Chat depends on.
- Comprehensive analysis can still decline on a large corpus, as above.


### Spike — PyMuPDF `Story` as the report renderer (2026-09-05, 10 minutes)

The design made three claims it had not verified. Each was rendered and read
back through `fitz` on PyMuPDF 1.26.6. Recorded verbatim, including the one
that failed.

**1. `<thead>` does NOT repeat across page breaks.** A 40-row table split over
two pages: page 1 carried the header and 31 rows, page 2 carried 9 rows and no
header. The design called this "the single highest-value item in the spike —
verify it, do not assume it". Verified: false. Consequence: a table that may
span pages needs its header re-drawn per page in Python, or must be kept short
enough not to span. A single-answer report cites at most three documents, so
the evidence table does not span; the limitation is stated for anything that
would.

**2. Arabic is shaped by `Story`, and joining is still not proven.** A mixed
Arabic/English paragraph rendered in `NotoNaskhArabic-Regular` (embedded in the
MuPDF DLL, SIL OFL 1.1) with **0 `.notdef` glyphs**. 43 of the 44 Arabic
characters read back were Unicode **presentation forms** (U+FB50–U+FEFF) — the
contextual glyph forms a shaper emits — so shaping ran. What this does NOT
prove: that the joins are the *right* ones, or that bidi order is correct. That
needs a reader of Arabic looking at the page. Two consequences for tests: assert
on the font name and on presentation forms being present, never on the logical
string — it does not come back from the text layer — and do not let a green
tick imply the Arabic is correct.

**3. `write_stabilized_with_links` produces a TOC only if you build one.** It
runs the layout twice and hands `contentfn` the element positions from the
previous pass (`id`, `text`, `page_num`, `heading`), so the HTML can include a
contents list whose page numbers are final. `<a href="#id">` links resolve to
internal page links (5 on page 1 of the spike). `doc.get_toc()` — the PDF
outline — stays **empty**; nothing is added to it automatically.

**A fourth thing nobody claimed:** `fitz` text extraction returns typographic
ligatures — "prefix" came back as "preﬁx". The first version of the
`<thead>` check found no header on any page for exactly this reason. Every
text assertion against a rendered report must NFKC-normalise first.

Timing on this machine: 2 pages in 8–24 ms; the stabilized double pass in about
the same. Not a benchmark — one fixture, warm process.

### The 75-second wait, made legible (2026-09-06)

`GET /api/progress/{id}`, and a `LocalWork` panel in Chat that replaces the
single "Searching the documents" spinner.

**Every stage shown was reported by the work when it happened.** Nothing is
inferred from the clock: retrieval usually finishes in ~2.5 s and generation
takes the rest, so a timer could guess the stage and be right most of the
time — and on the run where retrieval is slow it would tell the reader the
model was writing while the search was still going. Measured live against the
running server:

    retrieving@0.0s -> reranking@1.87s (16 of 53 candidates)
      -> reading@4.675s (3 passages) -> generating@5.197s (2 sources)   78s total

**There is no percentage bar.** The length of a generation is unknown until it
ends, so a bar would be an invention. The reader gets a stage, a count and an
elapsed counter — the counter is the client's own, so it keeps counting through
a missed poll. The panel also says why it is slow: a 15 W laptop CPU, no GPU,
and nothing leaving the machine.

The record is in memory, capped, TTL'd, and carries no document content: a
stage name, a count and a clock. `progress_id` is optional — without one the
work reports nothing and behaves exactly as before.

### CI was red and the local suite was wrong (2026-09-06)

Twenty backend tests failed in CI with `no such table: chunks` while passing
here. Reproduced exactly by pointing `DB_PATH` at an empty directory: **20
failed**, the same twenty.

`test_claims.py` and `test_market.py` had no storage fixture, so locally they
opened the developer's real 62 MB corpus and passed, and in CI they opened an
empty file. The local "756 passing" was the wrong number; CI was right.

Both files now create their own tables. And `conftest.py` gains a session
fixture that points the DEFAULT database at a temp file, so a forgotten
fixture fails HERE exactly as it fails in CI — the same shape as the three
guards already in that file, and the reason it is now four.

### Stages 3, 4 and 6 — the three engines wired to routes (2026-09-05)

`POST /api/analysis/summary`, `/recommendations` and `/gaps`.
`backend/app/analysis.py` is the only impure file: `synthesis.py` and
`claims.py` stay pure — evidence in, result out, no SQLite, no HTTP, no
Ollama — which is what let them be developed and tested without any of it.

**`evidence_id` is not a chunk id.** It is sha256 over document, page span,
section and the quoted text, so it survives a re-chunk. A citation that moves
when the chunker is retuned is not a citation.

**`gaps` makes no model call**, so an unreachable Ollama takes out the summary
and the recommendation and leaves the mechanical comparison working. The
frontend calls the three separately for the same reason; one combined endpoint
would have made a down model look like a broken comparison.

**The system never chooses a baseline.** With none named, applicability is
`not_applicable` and no facet may come back `met`. Picking the oldest document,
or the one with "standard" in its name, would be an engineering judgement it
has no basis for. A baseline the caller may not read is 404.

Four deliberate breaks, all red: an unscoped search, a system-chosen baseline,
a flag instead of a drop for an unsupported number, and a model call inside
`gaps`.

### Stage 5 — public market information, as a labelled fixture (2026-09-05)

`GET /api/market/findings` and `POST /api/market/preview-query`. No provider,
no HTTP client, no URL that resolves: five illustrative rows from
`samples/market_sample.json`, every one `is_sample: true` with a `sample://`
URL.

The one rule — a sample is never presented as a source — is enforced at load
time, and each way has a test that was watched failing against a loader that
trusts the file: a row missing `is_sample`, a row setting it false, a row with
a fetchable `https://` URL, a row claiming `source_read`, and an empty fixture
(which would otherwise render as "no market findings", reading as a
measurement rather than an absence).

`preview-query` builds the object that would leave the machine and returns it
with `sent: false` and `would_be_sent_to: null`. It takes the caller's own
words only. A query assembled from retrieved document text would exfiltrate the
client's specification to a search engine one phrase at a time.

`MarketVerification` keeps its three values — a UI must render each — while
`MarketFinding.verification` is pinned to `source_not_verified`, so the API
cannot emit a state this build has not earned.

### Stage 2 — single-answer evidence reports as PDF (2026-09-05)

`POST /api/reports {message_id}` freezes one answered message - question,
resolved question, every passage with its provenance, and each cited document's
filename, SHA-256, page count, chunk signature and indexed_at - and renders a
PDF from that snapshot **and nothing else**. Rename or re-index the document
afterwards and the body does not change; `GET /api/reports/{id}/verify` reports
the divergence as `evidence_drift` instead of using the new state.

On page 1, in a bordered box: what the report is, and the four things it is not
- coverage ledger, gap analysis, recommendation, public-market findings. Quoted
text is serif on a quote rule; generated text is sans on amber; every
recognised passage carries its OCR line; the engineer-approval sentence appears
where a reader starts and where they stop; `PROTOTYPE - NOT FOR CONSTRUCTION`
and `Page N of M` are drawn as an overlay on every page. Revision and approval
status print as "not recorded" - the columns do not exist.

Content-addressed storage (`reports/<sha[:2]>/<sha>.pdf`), server-assigned
download name, `Cache-Control: private, no-store`. Access is owner AND still
authorised for every cited document; a report whose document has left the
reader's scope is **404** - not 403, not redacted - and the listing carries a
`suppressed_count`. Deleting a document unlinks the files and keeps the rows.

22 tests, all on semantics read back through `fitz` and none on bytes; the
watermark, approval, and revocation tests were each broken on purpose and
watched fail. The Arabic test **skipped**: the fixture's Arabic did not survive
ingestion's own text extraction, so the renderer was never exercised on it, and
a skip says so where a pass would have lied.


### Added
- The evaluation harness drives `chat.ask` inside one conversation, so it
  measures the path a person actually uses rather than answering each question
  in isolation. Isolated mode remains available as a diagnostic.
- A measured upload ceiling (512 MB), enforced during the stream and aborting
  before the file is fully read, with tests for both rejection and acceptance.
- The reachability sweep, run for the first time: **98.5%** of retrievable
  chunks can be reached by some query. The 33 that cannot are numerical tables
  whose rarest token is a word like "time".
- `docs/backlog-issues.md` — twelve entries, each with its evidence: ten open
  gaps, one correction, and one closed as a measurement error.

### Fixed
- Follow-up resolution borrowed terms based on word count rather than
  dependence, so a short but self-contained question asked after an unrelated
  one was rewritten before retrieval saw it. Measured over 200 shuffled
  orderings of the eval set: **72 of 200 (36%)** returned a confident answer
  where a refusal was correct, and it was the only failure in any of them. The
  gate is now grammatical completeness — a question carries terms only if it
  contains an anaphor, opens as a continuation, or is a bare noun phrase with
  no finite verb. Verified by replaying the 72 known-bad orderings (72/72 pass)
  plus 50 fresh ones (50/50) — 122 orderings, which is not the same
  measurement as the original 200.
- A settle guard that failed documents which were progressing. One OCR round
  costs three passes of the status loop and rounds double, so a scanned
  document legitimately needed more than the ten passes allowed. It now counts
  churn rather than iterations, and the recorded reason names the stage that
  stopped rather than the loop that noticed.
- "Quoted verbatim from the document" shown when provenance was unknown. The
  predicate is now positive: verbatim only when the text is known to be
  extracted, never as the fallback for everything not recognised.
- Unguarded response shapes that white-screened three views. Fixed once at the
  API client boundary rather than at each call site.

### Known
- `"what about system 2"` does not return an answer about system 2, with or
  without term-carrying. The canonical example for the feature is one of the
  cases it does not rescue. See `docs/backlog-issues.md` entry 11.
## 2026-09-05

### Added
- **OCR for scanned pages** (RapidOCR / PP-OCRv6, in a subprocess, offline).
  Page coverage across a 2,583-page corpus rose **94.0% → 96.3%**. Recognised
  text is labelled as recognised rather than presented as a quotation.
- `eval/coverage.py`, and the three measurements OCR was built to justify.
- An alphabet guard that rejects scripts the corpus cannot contain, after the
  first recogniser emitted CJK characters for English pages.
- A PR template requiring an explicit `Closes` line; the branch convention
  written down, including that it lapsed.

### Changed
- Coverage is attributed per page by that page's own text source. The previous
  definition dropped every recognised chunk, which also dropped pages a chunk
  merely spanned — reporting **+12.5%** against a true **+4.2%**.
- Setup documentation corrected after a clean-clone run: Ollama install and
  pull commands added, and the disk figure replaced with a measured breakdown
  (768 MB in the clone, plus ~3.4 GB for the answer model).

### Fixed
- OCR failed on every scanned document; found by a clean clone, not by a test.
- OCR text was labelled "quoted verbatim from the document".
- Stale vectors: 4,787 → 0 in one worker cycle after re-chunking.

## 2026-09-04

### Added
- Ingestion view, dashboard rebuild, and CPU/RAM readings that state what they
  measured rather than implying a window they never had.
- A vector-matrix cache; every search result records what corpus it ran
  against.
- Chat memory: conversations and messages, with prior **answers** excluded
  from evidence by construction.
- Two-tier answering — Tier 1 quotes the source with no model involved; Tier 2
  is an explicit, opt-in local generation.
- Hybrid retrieval: SQLite FTS5 and dense vectors fused by Reciprocal Rank
  Fusion, then reranked by a local cross-encoder.
- Structure-aware chunking, streamed PDF upload, resumable page-batch
  extraction.

### Changed
- The reranker's window was widened to cover a whole chunk. It had been
  scoring 480-token chunks on their first 256 tokens, so a table with its
  answer at token 350 was judged on text that did not contain it. Cost
  **+650 ms** median; bought retrieval 9/10 → 10/10 and citation 8/9 → 9/9.

### Fixed
- Substituted ligatures in extracted text; stale ground truth now fails loudly
  rather than passing quietly.
- Eight UI defects from an audit, most of them one bug wearing three faces.

## 2026-09-04 — initial

- Repository initialised with governance templates, secret scanning, a
  client-data guard in CI, and the privacy boundary recorded as ADR-0002.
