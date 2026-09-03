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
