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
