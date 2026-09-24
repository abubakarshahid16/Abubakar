# ADR-0019 — Layout and table recognition: Docling / DocLayNet vs the PyMuPDF table reader

- **Status:** Accepted (research stage 1)
- **Date:** 2026-09-24
- **Decision:** **ADOPT-FOR-EVALUATION-ONLY.** Benchmark Docling offline as a
  *second-tier* reader for table pages the current reader fails on. No
  wholesale parser replacement. No dependency added until the benchmark passes.

## Sources read

- Docling technical report (IBM Research page; full text at arXiv 2408.09869).
  MIT licence. Layout model (RT-DETR trained on DocLayNet) plus TableFormer for
  table structure. OCR optional and off by default.
- DocLayNet (arXiv 2206.01062). 80,863 manually annotated pages, 11 classes,
  deliberately diverse sources, because models trained on scientific-article
  sets (PubLayNet, DocBank) generalise poorly to other layouts.

## The existing weakness

- `backend/app/tables.py` calls PyMuPDF `find_tables()` per page;
  `backend/app/datasheets.py` `pairs_from_table_shape` turns the grid into
  label/value pairs. Measured real parse rate on table pages: **33 of 98
  (~34%)**.
- Each recent fix (#162/#175 multi-column header, #179 row-numbered
  dual-column rows) was a heuristic for one layout seen on the pump datasheet
  regression document. This is the failure mode DocLayNet documents: rules
  that fit one layout family do not transfer.
- `datasheets._pairs_from_vision_fallback` returns `[]`. There is no tier
  after the heuristic reader.

## Evaluation data needed

- The 65 failing table pages plus the 33 passing ones, scored with the existing
  `scripts/eval_extraction.py` (both denominators: filled and all-slots).
- **A held-out layout set** (DocLayNet's lesson): datasheets from vendors and
  templates *not* used to tune #162/#175/#179. Without it, every gain is
  in-sample.
- Per-page wall time and peak RSS on the target laptop, measured the way
  ADR-0005 measured OCR (parent plus children, runs serialised).

## Measured benefit on our data

**Measured 2026-09-25 (owner-approved benchmark). Result: NOT ADOPTED - no
measured gain.**

Setup, exactly as approved: Docling 2.130.0 + torch 2.14.0 in a throwaway
venv OUTSIDE the repo (`C:\project\docling-bench`), not in the project's
dependencies; COPIES of the three regression PDFs split to their table
pages (every page of all three has a table: vessel 11, PSV 5, pump 7);
Ollama stopped for the run and restarted after; no cloud call. Weights were
downloaded ONCE from the official HuggingFace repositories on the first run
and hashed:

| file | size | sha256 |
|---|---|---|
| docling-layout-heron `model.safetensors` (snapshot 8f39ad3c) | 164 MB | `00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c` |
| docling-models `tableformer_accurate.safetensors` (snapshot fc0f2d45) | 203 MB | `2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9` |
| docling-models `tableformer_fast.safetensors` (snapshot fc0f2d45) | 139 MB | `3119563aab5a7c96fda4d621119b63fd8806272b86c30936d15507616422f718` |

Cost on this laptop (i7-1255U, CPU only, Ollama stopped):

| sheet | table pages | tables found | pairs exported | wall time | per page | peak RSS |
|---|---|---|---|---|---|---|
| vessel | 11 | 12 | 529 | 467 s | 42 s | 2.33 GB |
| PSV | 5 | 5 | 830 | 218 s | 44 s | 2.13 GB |
| pump | 7 | 4 | 43 | 155 s | 22 s | 2.43 GB |

Quality on the one sheet with a gold key (pump, `gold/M03-FIELDS.csv`,
scored by `scripts/eval_extraction.py --rows`, same harness as the live
reader):

| reader | filled P | filled R | filled F1 | all-slots F1 |
|---|---|---|---|---|
| current rule reader (live, range-aware, commit 81337df) | 0.698 (30/43) | 0.186 (30/161) | **0.294** | **0.504** |
| Docling (table cells -> label/value, first column = label) | 0.372 (16/43) | 0.099 (16/161) | 0.157 | 0.073 |

Docling found tables on only 3 of the pump's 7 pages and reads no blank
slots, so both headline numbers fall. Caveat, stated not hidden: the
label/value export is a first-column-is-label rule written for the
benchmark; a smarter export over TableFormer's row/column headers could
score higher. That is not a reason to adopt - it is a reason the gain, if
any, is unproven.

The question the benchmark was run for - issue #193's biggest lever, the
vessel's pages 6-11 that the rule reader reads nothing from - answered
page by page:

| vessel page | content | Docling pairs | usable as label/value? |
|---|---|---|---|
| 6 | nozzle schedule | 123 | **no** - header row lost; labels come out as "row number + nozzle mark" ("4 N1 5") with the title-block text as the column header, and a row's cells (size, NPS, rating, facing) split into separate "values" |
| 7 | drawing sheet | 0 | - |
| 8, 9, 10 | notes | 10 each | **no** - only the repeated drawing title block (DWG TYPE, PLANT NO, DRAWING NO); the notes themselves are not tables |
| 11 | standard-drawings applicability checklist | 53 | partly - drawing number + "X" marks, not design data |

**Decision (rule from this ADR: adopt only if it lifts filled-F1 without
dropping all-slots F1): NOT ADOPTED.** Both fall on the pump sheet, and on
the vessel it does not turn the nozzle schedule or notes into usable
label/value pairs. The integration risk above (torch in an ONNX-only stack;
~2.3 GB per run, so it cannot run beside Ollama and the API on 16 GB)
stands unchanged. The throwaway venv and cached weights stay outside the
repo; nothing was added to `requirements.txt`. For #193's table pages the
next candidate is the adopted local text model reading a table page's
native text into verified pairs, which needs its own measured pilot.

## Cost on the stated hardware (estimate)

- The paper reports 0.60–0.92 pages/s on a 16-core Xeon and ~6.2 GB peak
  memory (native backend, 4 threads), and 2–6 s per table on CPU. **Those are
  the paper's machines, not ours.** On an i7-1255U with Ollama (~3.4 GB) and the
  API (up to ~3.2 GB) resident, the same memory would not fit alongside them;
  a benchmark must run with Ollama stopped or in a subprocess that exits.
- Scoped to table pages only it is affordable; applied to all ~2 M planned
  pages at ~0.5 pages/s it would be ~46 days of continuous CPU (estimate,
  extrapolated). That alone rules out wholesale replacement.

## Integration risk

- Brings a torch runtime; the stack is deliberately ONNX-only (ADR-0005:
  "No PaddlePaddle, no torch"). Weights must be vendored and checksum-pinned,
  as the OCR weights are, or the first run downloads them — a privacy-boundary
  breach (ADR-0002).
- TableFormer output is a model's structure guess. Pairs from it must carry
  provenance distinct from native-text pairs (ADR-0006 pattern), never shown as
  verbatim table reads.

## Reason for the decision

The weakness is real and measured (34%); the fix candidate is unmeasured on
our pages and heavy on our hardware. Benchmark first, on held-out layouts,
behind the existing `_pairs_from_vision_fallback` seam. Adopt only if it
lifts filled-F1 on the held-out set without dropping all-slots F1.
