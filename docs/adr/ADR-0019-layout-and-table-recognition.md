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

**Not measured.** No Docling run has been made on this corpus.

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
