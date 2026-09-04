# Measured benchmarks

> **Rule:** nothing enters this file that was not measured on the target hardware.
> Projections belong in ADRs, labelled as projections. Empty rows stay empty.

## Hardware — this is the production machine

| Field | Value |
|---|---|
| Machine | Lenovo IdeaPad Flex 7i |
| CPU | Intel Core i7-1255U — 10 cores (2 P + 8 E), 12 threads, 15 W mobile |
| RAM | 15.6 GB usable |
| GPU offload | **None.** `ollama ps` reports `100% CPU` |
| iGPU | Intel Iris Xe, 2 GB dedicated allocation (can address shared system memory) |
| OS | Windows 11 Home 26200 |
| Free disk (working volume) | ~45.8 GB |
| Python | 3.12.10 |
| Node | 24.18.0 |
| Ollama | 0.33.2 |

> There is no faster environment later. Every number here is a production number.

---

## Answer model — `qwen3.5:4b` (Q4_K_M, 3.4 GB)

### Prompt-eval throughput vs runtime settings
951-token prompt, `num_predict=1`, warm model.

| Settings | Tokens | Time | Throughput |
|---|---:|---:|---:|
| Ollama defaults | 951 | 45.9 s | 20.7 tok/s |
| `num_thread=4`, `num_batch=512` | 951 | 46.4 s | 20.5 tok/s |
| `num_thread=8`, `num_batch=1024` | 951 | 38.6 s | 24.6 tok/s |
| **`num_thread=12`, `num_batch=2048`** | 951 | **34.0 s** | **27.9 tok/s** |

**Adopted:** `num_thread=12`, `num_batch=2048` — +35% over defaults, free.

### End-to-end, realistic RAG context

| Measurement | Value |
|---|---|
| Prompt tokens | 3,767 |
| Prompt eval | 185.94 s (20.3 tok/s, untuned) |
| Generation | 53 tokens / 8.83 s (6.00 tok/s) |
| **Total wall clock** | **195.2 s** |

Answer was correct and cited a source. **The problem is throughput, not quality.**

### Small-context reference

| Measurement | Value |
|---|---|
| Prompt | 25 tokens / 0.37 s (68.0 tok/s) |
| Generation | 26 tokens / 2.77 s (9.40 tok/s) |
| Total | 3.3 s |

⚠️ 68 tok/s on a 25-token prompt does **not** extrapolate. At 951 tokens it is 27.9 tok/s; at 3,767 tokens, 20.3 tok/s. Always quote prompt-eval throughput with its context size.

### Cold start

| Measurement | Value |
|---|---|
| Model load (cold) | 23.6 s |
| Model load (warm) | 0.01 s |

Implication: `keep_alive` must hold the model resident for the demo.

### Thinking mode

- With thinking enabled and `num_predict=60`, **the visible response was empty** — the entire budget was consumed by the thinking block.
- **`think=false` is mandatory** on the factual path.

---

## Cross-encoder: already batched, and the memory it holds

Two latency levers were investigated and both came back negative. Recorded
because a negative result stops the next person spending the same day on it.

**It already batches.** `rerank_batch = 32` against a 16-passage shortlist, so
16 pairs are one forward pass, not sixteen. Scoring them individually is not
reliably faster — 0.59x to 1.43x across five questions, median 0.85x — and it
perturbs scores by up to 0.49 (see `limitations.md`). There is no loop to
remove; the cross-encoder's ~1.45 s is 89% of retrieval and irreducible
without an accuracy trade.

**ONNX Runtime's CPU arena holds a great deal of memory.** It reserves large
per-thread blocks and never returns them:

| | process RSS | tier-1 query | embed |
|---|---|---|---|
| both arenas on (default) | 3,247 MB | ~1,926 ms | 6.9 chunks/s |
| rerank off, embed on | 2,438 MB | ~2,493 ms | 6.8 chunks/s |
| both off | **503 MB** | ~2,500 ms | 5.7 chunks/s |

Rerank scores are **bit-identical** either way (`np.array_equal`, max
difference exactly 0.0) — arena configuration changes allocation, not
arithmetic. So there is no accuracy trade, but there is a latency one: roughly
2.7 GB against roughly 575 ms.

**Default is ON.** Two hypotheses for turning it off were tested and both
failed:

- that it would recover the latency lost to memory pressure — it does not, it
  costs latency;
- that freeing memory would speed up Explain, which needs ~2.5 GB for
  `qwen3.5:4b` — measured with the model warm, Explain is 7.4-7.9 s with the
  arena on against 8.3-10.5 s with it off. A 63 s Explain measured first was
  Ollama's cold model load, and the arena-on run had *more* free RAM at the
  time, so it cannot be attributed to the arena.

Left configurable as `onnx_cpu_arena_rerank` / `onnx_cpu_arena_embed`, because
503 MB against 3,247 MB is a real option on a machine that demos at 92% RAM —
but it buys headroom, not speed.

## Not yet measured

These rows stay empty until measured. Do not fill them with estimates.

| Metric | Value |
|---|---|
| Tier 1 end-to-end (retrieve → rerank → passage) | — |
| Tier 2 CPU, `qwen3.5:4b`, 2×250-token context | — |
| Tier 2 CPU, `qwen3.5:2b`, identical context | — |
| Tier 2 iGPU (IPEX-LLM), if it works | — |
| Cross-encoder rerank latency | — |
| System prompt token count | — |
| **Embedding throughput (chunks/s), ONNX int8 e5-small** | — |
| Native PDF extraction (pages/s) | — |
| Chunking (pages/s, chunks/page) | — |
| Time to first searchable batch | — |
| Peak RAM during ingestion | — |

> **Priority:** embedding throughput is needed early. 12,000 pages ≈ 36,000 chunks
> on this same CPU. Report measured chunks/s as soon as EMB-001 runs.

---

## Model artefact manifest — SHA-256

`intfloat/multilingual-e5-small`, staged to `backend/models/e5-small/` (git-ignored):

```
DD476DD0C2514E9B9BE83AEB3853FAC0763E0BDF4A71645407587D77C48A2D88  onnx/model_qint8_avx512_vnni.onnx  112.86 MB
4654C156F3E4171ABC9C716CDB771BF9116455D15AC1AAB364AEEEDE0E3205B0  onnx/model_O4.onnx                 224.16 MB
0B44A9D7B51C3C62626640CDA0E2C2F70FDACDC25BBBD68038369D14EBDF4C39  tokenizer.json                      16.29 MB
CFC8146ABE2A0488E9E2A0C56DE7952F7C11AB059ECA145A0A727AFCE0DB2865  sentencepiece.bpe.model              4.83 MB
A1D6BC8734A6F635DC158508BEF000F8E2E5A759C7D92F984B2C86E5FF53425B  tokenizer_config.json
69137736CAB8B8903A07FE8AFAAFDDA25AAC55415A12A55D1BFFA9F581ABF959  config.json
D05497F1DA52C5E09554C0CD874037A083E1DC1B9CFD48034D1C717F1AFC07A7  special_tokens_map.json
```

Ollama: `qwen3.5:4b` — id `2a654d98e6fb`, 3.4 GB, digest `81fb60c7daa8`.

Supply chain: `gitleaks_8.30.1_windows_x64.zip` SHA-256 verified as
`d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.

## Capacity - the 1,400-page document (measured 2026-09-04)

This closes the claim that no document over 613 pages had been processed.
`book4ChemicalProcessDynamicsAndControls.pdf`, 1,400 pages, 2,030,224
characters, ingested cold with no configuration changed.

| stage | measured | rate |
|---|---|---|
| extract | 5.0 s | 277.6 pages/s |
| chunk | 8.1 s | 2,223 chunks, 2,110 retrievable |
| keyword index | 0.2 s | answerable from here |
| **time to answerable** | **~13 s** | inside the 30-second target |
| embedding | 2,113 vectors | at the measured 9.22 chunks/s sustained |

### RETRACTED: "the cost of a larger corpus is latency"

**This section previously claimed retrieval scaled superlinearly with the
corpus. It does not. The claim was wrong and is retracted here rather than
quietly deleted.**

What it said:

| corpus | median answer latency | p95 |
|---|---|---|
| 3 documents (2,966 chunks) | 1,915 ms | 2,345 ms |
| 4 documents (~5,100 chunks) | 4,346 ms | 9,887 ms |

...concluding "2.3x slower for 1.7x the chunks. Ingestion scales; retrieval
does not."

**Why it was wrong.** The two figures came from two different eval runs 40
minutes apart, and no stored result could say which corpus either ran against
— the `corpus` field was a static string copied from the questions file (see
instance nine in `status-honesty-audit.md`). Both runs were attributed by
assumption, not by record.

### What a direct measurement shows

Both corpus sizes measured in one process against the same warmed models, on a
copy of the database with the fourth document deleted from the copy:

| corpus | chunks | total | FTS5 | dense | (load / matmul) | cross-encoder | RRF + assembly |
|---|---|---|---|---|---|---|---|
| 3 documents | 2,670 | 1,573 ms | 14 | 87 | 39 / 48 | **1,450** | 24 |
| 4 documents | 4,780 | 1,637 ms | 23 | 133 | 83 / 51 | **1,463** | 26 |

**Retrieval grew x1.04 for x1.79 the chunks.** End-to-end `answer()` was flat
too — 1,934 ms against 1,851 ms, with an identical tier mix. The larger corpus
measured marginally faster, which is noise, and that is the point.

Work done per question does not grow at all: FTS5 hits 30 -> 30, pool 16 -> 16,
**cross-encoder pairs 16 -> 16**. Both candidate lists are hard-capped at
`search_candidates = 30` and the shortlist at `rerank_candidates = 16`, so the
cross-encoder — 89% of retrieval latency — scores exactly 16 pairs at any
corpus size.

### What the 1,915 -> 4,346 ms actually was

Machine state. Across nine runs of the same question set, on the same code:

| run | cold start | warm median |
|---|---|---|
| 09:35 | 7.5 s | 1,716 ms |
| 09:51 | 5.4 s | 1,434 ms |
| 11:45 | 6.3 s | 1,910 ms |
| 12:04 | 16.5 s | 2,550 ms |
| 12:23 | **38.4 s** | **4,291 ms** |

Cold start and warm median correlate at **r = 0.977** with the corpus
unchanged. RAM was at 91.9% with 1.26 GiB free. Absolute latency on this
machine drifts by more than 2x with free memory, so **any single latency figure
here is only comparable against another measured in the same session** — which
is why `run_eval.py` now stamps free RAM and model residency on every result.

### The one component that does grow with the corpus

Only the dense vector load: x2.11 across the doubling, against x1.05 for the
matmul. It re-read every vector blob from SQLite on every query. Now served
from a memory-mapped cache (`app/vectorcache.py`), revalidated by a 1.2 ms
signature:

| | before | after |
|---|---|---|
| vector load | 27.2 ms | **0.93 ms** |
| dense stage | 133.3 ms | **28.9 ms** |

Mapped rather than heap-resident deliberately: this machine demos at 92% RAM,
so the matrix should be pages the OS can evict and share. Results are
bit-identical to a direct read.

An approximate (ANN) index remains cancelled, and for a better reason than
before: at ~29 ms the whole dense stage is under 2% of query latency, and the
matmul half of it grew x1.05. An ANN index would target the smaller half of an
already negligible cost.

---

## OCR — RapidOCR 3.9.2 / PP-OCRv6 (measured 2026-09-05)

**Machine state stamped:** backend API process **not running**; Ollama server up
but `qwen3.5:4b` **not loaded** (23 MB RSS, not 3.4 GB); three Vite dev servers
running; free RAM 2.31–2.39 GB of 15.57 GB. VS Code, CapCut, WhatsApp and six
Edge WebView processes resident. **This is not the demo-time state**, where the
answer model is loaded and free RAM was 1.15 GiB.

Pages are the **real** flagged pages of the ingested corpus, not synthetic
images. 12 pages per run, identical page set, runs serialised.

### Rate and memory, one worker

| Config | s/page | Peak RSS (sampled 20 Hz) |
|---|---|---|
| tiny, 150 dpi, cls on | **0.90** | 430 MB |
| tiny, 300 dpi, cls on | 1.25 | 616 MB |
| tiny, 150 dpi, cls off | 0.89 | 456 MB |
| small, 150 dpi, cls on | 4.43 | 444 MB |
| tiny, 150 dpi — 8 heaviest pages only | 1.36 | 527 MB |
| tiny, 150 dpi — same 12-page run, later in session | 0.99 | 416 MB |

The last row is the repeatability check: the same benchmark 90 minutes later on
a busier machine moved 0.90 → 0.99 s/page, **+10 %**. Absolute rates carry that
much noise; the relative comparisons above were run back-to-back and do not.

### Two workers

| Metric | Value |
|---|---|
| Effective rate, 2 workers × 8 heaviest pages | **0.97 s/page** (vs 1.36 single) |
| Speed-up | 1.4× — not 2×; 2 P-cores, 2 ONNX threads each |
| Per-worker peak RSS | 549 MB and 524 MB |
| Free RAM before / lowest during | 2.39 GB → **1.48 GB** (0.91 GB consumed) |

**Two workers do not fit at demo time.** 0.91 GB consumed against the 1.15 GiB
free measured with the answer model loaded leaves 0.24 GB. One worker, or OCR
only while the answer model is unloaded. This is the measurement behind the
runbook rule that OCR must not run while questions are being answered.

### Recogniser alphabet: v5 English vs v6 multilingual (same 12 pages, 150 dpi)

| Config | s/page | Peak RSS | Non-ASCII emitted | Weights |
|---|---|---|---|---|
| v6 tiny det + v6 tiny rec (multilingual) | 0.90 | 430 MB | `≦ 凤 日 · Ç` | 6.9 MB |
| v6 small det + rec (multilingual) | 4.43 | 444 MB | — | 31.8 MB |
| v5 mobile det + v5 **en** rec | 4.11 | 421 MB | `√` (a real tick on the page) | 13.3 MB |
| **v6 tiny det + v5 en rec (hybrid)** | **2.16** | 421 MB | **NONE** | **10.3 MB** |

Detection and recognition configure independently, so the hybrid pairs v6's
fast multilingual detector with v5's Latin-only recogniser. Engine choice is
held pending one client question (Arabic in the corpus or not); both are
staged.

### Vendored OCR weights — SHA-256

| File | SHA-256 |
|---|---|
| `ocr/PP-OCRv6_det_tiny.onnx` | `f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5` |
| `ocr/PP-OCRv6_rec_tiny.onnx` | `e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b` |
| `ocr/en_PP-OCRv5_rec_mobile.onnx` | `c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8` |
| `ocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx` | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

Pinned by RapidOCR release tag `v3.9.2` in the URL as well as by hash, and
checked by `fetch_models.py --verify-only`. Guard proven by deliberate
failure: nine bytes appended to the detector produced
`WRONG CONTENT (SHA-256 does not match the pinned value)`, exit 1.

### Projections (labelled as projections, per the rule at the top of this file)

At the measured 0.90–1.36 s/page single-worker range, for a **fully scanned**
document where every page needs recognition:

| Document | 1 worker | 2 workers (model unloaded) |
|---|---|---|
| 74 flagged pages, this corpus | ~1.2 min | ~1 min |
| 500 pages | 8–11 min | ~8 min |
| 1,400 pages | **21–32 min** | ~23 min |

The brief projected 12–23 min for 1,400 pages. Measured is **slower than that
at the top of the range**, because 0.5 s/page is RapidOCR's documented figure
and this 15 W mobile CPU does not reach it.

### Model artefacts on disk

| File | Size |
|---|---|
| `PP-OCRv6_det_tiny.onnx` | 1.83 MB |
| `PP-OCRv6_rec_tiny.onnx` | 4.49 MB |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | 0.59 MB |
| **tiny set total** | **6.91 MB** |
| `PP-OCRv6_det_small.onnx` | 9.93 MB |
| `PP-OCRv6_rec_small.onnx` | 21.23 MB |

### Test-suite wall time is not a usable regression signal on this machine

478 tests passed on every run. Wall time, unchanged tree, four runs:

| Run | Wall |
|---|---|
| Before installing rapidocr | 195 s |
| After | 421 s |
| After | 466 s |
| After (`--durations=12`) | 304 s |

A 2.4× spread with no code change. The new packages are **not reachable from
the test path** — neither `app/` nor `tests/` imports `PIL`, `cv2` or
`rapidocr`, and page rendering goes through PyMuPDF — and the 12 slowest tests
account for only 62 s of 304 s, so the cost is thin per-test overhead sensitive
to machine load. **A quiet-machine baseline is needed before any future number
here is called a regression.**

---

## OCR stage, run for real on the whole corpus (measured 2026-09-05)

Not a harness: `ocr.recognise_document` through the real pipeline, writing to
the real database. Machine state as stamped in the previous section, except the
backend API was stopped so the stage had the machine to itself.

| Document | Pages recognised | With text | s/page | Peak RSS (parent + children) | Alphabet violations |
|---|---|---|---|---|---|
| NORSOK M-501 Rev 5 | 3 | 1 | 0.94 | 563 MB | 0 |
| book1 professional practices | 12 | 7 | 0.85 (2 workers) | **1,399 MB** | 0 |
| book2 differential equations | 8 | 8 | 0.62 | 598 MB | 0 |
| book4 chemical process | 54 | 54 | 1.32 | 652 MB | **84** |

### Two workers do not fit. One does. This corrects the earlier estimate.

Measuring one worker in isolation gave 524–549 MB and suggested two would fit
in the 1.15 GiB free at demo time. **Measuring the real stage — parent and
children at their simultaneous peak — gave 1,399 MB for two against 598 MB for
one.** The isolated figure missed the parent and the overlap. `ocr_processes`
is 1, on this measurement rather than on the estimate.

### The alphabet guard fired on real data, and it matters

| | |
|---|---|
| Pages recognised across the corpus | 77 |
| Pages containing characters the document cannot contain | **18 (23 %)** |
| Such characters in total | 84 |

Observed: `米 。【华博器四性 国昌立 口我日 凤 二十大 一反 区回` — and **`≦` on two
pages**. The CJK ideographs are obvious to any reader. `≦` where a
specification says `≤` is not, and that is the failure this system exists to
prevent. This is the multilingual PP-OCRv6 recogniser on an all-English corpus;
the English recogniser cannot produce any of it.

### Provenance, end to end

| Document | extracted | recognised | worst chunk confidence |
|---|---|---|---|
| NORSOK M-501 | 80 | 1 | 0.997 |
| book1 | 1,100 | 7 | 0.864 |
| book2 | 1,740 | 8 | 0.957 |
| book4 | 2,175 | 93 | 0.501 |

Mixed documents behave as designed: 7 recognised chunks among 1,107 in book1,
so nothing presents as "an OCR'd document". The 0.501 worst case is the first
real data point for a confidence threshold; it is still not enough to set one.

### Re-chunk cost, which sets the re-index cadence

| Document | Chunks | Full re-chunk |
|---|---|---|
| NORSOK M-501 | 81 | 0.7 s |
| book1 | 1,107 | 2.6 s |
| book2 | 1,748 | 4.8 s |
| book4 | 2,268 | 8.6 s |

Re-chunking is whole-document, so re-indexing after every OCR batch would cost
more than the recognition. Rounds double instead — page 40 is answerable within
a couple of rounds while page 900 is still being read, and the total re-index
cost converges to about twice one full pass rather than growing with the page
count. A 1,400-page scanned document reaches full coverage in **at most 10
rounds**, asserted in `test_ocr.py`.

### Exclusion ledger after the rename

| Rule | Rows |
|---|---|
| `content_quality_gate` | 268 |
| `page_classified_toc` | 46 |
| `page_classified_frontmatter` | 13 |
| `page_classified_index` | 9 |
| `ocr_found_no_text` | 5 |
| `page_yielded_no_chunk` | 1 |
| `page_classified_references` | 1 |
| `needs_ocr_not_implemented` | **0** — 15 rows renamed by the migration |

`ocr_found_no_text` is the five genuinely blank pages. They are recorded as
blank rather than as unreadable, which the single old rule could not express.

---

## Coverage per document, before and after OCR (measured 2026-09-05)

**Machine state:** backend API not running; Ollama server up, `qwen3.5:4b` NOT
resident; RAM 89.1% used, 1.7 GiB free. Corpus read at run time by
`observed_corpus()`: 4 ready documents, 5,204 chunks, 4,787 retrievable, 417
excluded, 4,787 vectors, document-set hash `051b4e592931faea`.

Coverage is the ceiling on everything downstream: if a page never reaches the
index, no retrieval improvement can answer from it.

| Document | Pages | Before | After | Gain | Recognised |
|---|---|---|---|---|---|
| NORSOK M-501 Rev 5 | 24 | 87.5% | 91.7% | **+4.2%** | 1 |
| book1 professional practices | 546 | 95.8% | 96.9% | +1.1% | 7 |
| book2 differential equations | 613 | 93.3% | 93.8% | +0.5% | 8 |
| book4 chemical process | 1,400 | 93.6% | 97.2% | **+3.6%** | 54 |
| **ALL** | **2,583** | **94.0%** | **96.3%** | **+2.3%** | **70** |

### The first version of this measurement was wrong, and hand-checking caught it

`before` was first computed by dropping every recognised CHUNK. That also drops
coverage of pages such a chunk merely *spans*. One NORSOK chunk covers pages
21–24: page 21 was already covered, **page 22 has 413 extracted characters of
its own**, page 23 is genuinely blank. Only page 24 was reached by OCR.

That definition reported **+12.5%** for NORSOK. The true figure is **+4.2%** —
it would have overstated the feature's value by three times, in the feature's
own headline number. Coverage is now attributed per PAGE, by that page's own
text source: a page counts as OCR-dependent only if it had no usable
extractable text AND recognition produced characters for it.

NORSOK was chosen as the first proof precisely because 24 pages can be checked
by hand. It was worth it.

### What is still missing, with the rule that accounts for it

| Document | Missing | Rules |
|---|---|---|
| NORSOK M-501 | 2 of 24 (8.3%) | `page_classified_toc` 1, `ocr_found_no_text` 1 (pages 2 and 3) |
| book1 | 17 of 546 (3.1%) | toc 8, frontmatter 4, `ocr_found_no_text` 4, yielded-no-chunk 1 |
| book2 | 38 of 613 (6.2%) | `content_quality_gate` on every chunk 17, index 9, frontmatter 7, toc 5 |
| book4 | 39 of 1,400 (2.8%) | toc 32, `content_quality_gate` on every chunk 4, frontmatter 2, references 1 |

Most of what remains is *deliberately* excluded — contents, index, front matter
and references never compete with body text.

**Every uncovered page has a written reason. The count of silently-dropped
pages is ZERO**, across all 2,583.

An earlier version of this table reported *"21 pages uncovered with no
exclusion recorded"* and that was about to be filed as a defect against the
pipeline. It was a defect in **this script**: `missing_reasons` queried only
`scope='page'`, and a page can also be uncovered because every CHUNK on it was
excluded. All 21 carry a chunk-scope `content_quality_gate` row with a quality
flag giving the reason — `no_clause(longest=2<6)` and similar. The invariant
held; the query asked a narrower question than the one being answered, which is
the same shape as the coverage-definition error above.

What those 21 pages do show is a real question worth investigating: book2 pages
2 and 4 carry **1,266 and 1,217 extracted characters** and are excluded because
no clause on them reaches the minimum length. That is the quality gate working
as designed on prose that may or may not be worth keeping. Filed to the backlog
as a question, not as a defect.

---

## Stale embeddings, repaired and observed (measured 2026-09-05)

Asserted before, observed now. Retrievable chunks with no vector:

| | Count |
|---|---|
| Before a worker cycle | **4,787** |
| After a worker cycle (438 s) | **0** |

The earlier report said re-chunking left "some" stale. It left **all of them** —
re-chunking the whole corpus for OCR provenance invalidated every vector. The
repair works, and now it has been watched working rather than asserted.

---

## The 15-question eval, before and after OCR (measured 2026-09-05)

NORSOK M-501 restored. Compared against `20260904T133641Z-extract.json`, the
last pre-OCR run.

| Metric | Before | After |
|---|---|---|
| Retrieval (correct page) | 10/10 (100%) | **10/10 (100%)** |
| Citation (correct clause) | 9/9 (100%) | **9/9 (100%)** |
| Answer tokens present | 10/10 (100%) | **10/10 (100%)** |
| Refusal accuracy | 4/4 (100%) | **4/4 (100%)** |
| False refusals | 0/10 (0%) | **0/10 (0%)** |
| Median latency | 1,703 ms | 1,804 ms |
| p95 / worst | — | 2,129 / 3,073 ms |

**Accuracy did not move.** The 6% latency difference is a busy shared machine,
not a regression; question 12 is excluded as stale ground truth, not as a
failure.

**And OCR contributed an answer.** Question 3 now cites a **recognised**
passage — NORSOK page 21, confidence 0.9973, zero alphabet violations — and
still scores correct on both page and clause.

### Provenance asserted, not eyeballed

Every cited passage across all 15 questions was compared against the database's
own `text_source` for that chunk: **32 cited passages, provenance matches for
every one.** The check that this is not vacuous: a recognised chunk retrieved
by its own text arrives labelled `recognised`.
