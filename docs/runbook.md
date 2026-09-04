# Runbook

Operational rules for running this system on the demo machine. Everything here
is a consequence of a measurement in `docs/benchmarks.md`, not a preference.

## The machine has no spare memory. This governs everything below.

| Component | Resident |
|---|---|
| Backend API, both ONNX arenas ON | 3,247 MB |
| Backend API, both arenas OFF | 503 MB |
| `qwen3.5:4b` in Ollama, when loaded | ~3,400 MB |
| Measured free RAM at demo time | **1.15 GiB** |

## OCR must not run while questions are being answered

**This is the rule, and it is not a preference.** The real stage measured
**598 MB for one worker and 1,399 MB for two**, parent and children at their
simultaneous peak. Against the 1.15 GiB free at demo time, one fits and two do
not.

- **Before a demo or a Q&A session:** let ingestion finish, or stop the worker.
  Check `GET /api/documents` for any document not yet `ready`.
- **While OCR is running:** query latency is not protected. The machine is
  shared and OCR is CPU-bound on the same two performance cores retrieval uses.
- **Run ONE worker. `ocr_processes` is 1.** An earlier estimate from measuring
  a worker in isolation (524-549 MB) suggested two would fit. Measuring the
  real stage - parent and children at their simultaneous peak - gave
  **1,399 MB for two against 598 MB for one**. Two do not fit in 1.15 GiB.
  Raise it to 2 only when the answer model is unloaded AND you have checked
  free RAM first.

To check what is actually resident before deciding:

```powershell
Get-Process | Where-Object {$_.Name -match 'ollama|python'} |
  Select-Object Name, Id, @{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB)}}
```

An `ollama` process at ~23 MB is the server with no model loaded. At ~3,400 MB
the answer model is resident.

## Ordering: OCR never sits in front of the first answer

The pipeline is extract → chunk → **keyword index** → *(OCR rounds)* → embed.
Keyword search needs no vectors, so a text document is answerable seconds after
upload. OCR runs after that point, in rounds that double in size, re-indexing
between rounds — so a scanned document becomes progressively searchable rather
than being unavailable until recognition finishes.

Never move the OCR stage earlier. Time-to-first-answerable on a 1,400-page text
document is ~13 s and recognition would put minutes in front of it.

## Staging models on a fresh machine

```
python scripts/fetch_models.py              # stages all three families
python scripts/fetch_models.py --verify-only  # checks presence AND SHA-256
```

This is the one script that reaches the network. **Run it before the machine is
air-gapped.** Without the OCR weights staged, RapidOCR would try to download
from modelscope.cn at the first recognition — which fails offline, at the worst
possible moment. `--verify-only` exits non-zero if anything is missing or if a
staged file's SHA-256 does not match the pinned value.

## Recognised text is labelled, never quoted

An answer drawn from a recognised page must never carry the verbatim label.
If you see *"Quoted verbatim from the document"* above text that came from a
scanned page, that is a defect — report it. The correct label is *"Read by OCR
from a scanned page"* with the page image expanded.
