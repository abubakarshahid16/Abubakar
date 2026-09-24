# ADR-0020 — Visually-rich page retrieval: ColPali vs the text-only index

- **Status:** Accepted (research stage 1)
- **Date:** 2026-09-24
- **Decision:** **DEFER.** Re-open only when (a) image pages exist in the corpus
  in measured numbers and (b) a query set shows text + OCR retrieval failing
  on them.

## Source read

ColPali (arXiv 2407.01449). Embeds page *images* with a vision-language model
(PaliGemma-3B), producing ~1,024 patch vectors of 128 dims per page, matched by
late interaction. Reports beating text pipelines on its ViDoRe benchmark.
Paper-stated cost: ~257.5 KB per page (float16), 0.39 s/page indexing **on an
NVIDIA L4 GPU**.

## The existing weakness

- Every retrievable unit is text. Chunks come from PyMuPDF text
  (`backend/app/extract.py`) or RapidOCR text (`backend/app/ocr.py`, only on
  pages flagged `needs_ocr`). Dense vectors are 384-dim e5-small rows stored as
  SQLite BLOBs and searched brute force through a numpy memmap
  (`backend/app/vectorcache.py`); lexical is SQLite FTS5; fused by
  `search.rrf_fuse`.
- A drawing, P&ID or figure whose meaning is in its geometry, not its words, is
  retrievable only through whatever words OCR reads off it.
- **But on this machine the weakness has no measured instance:** 7,937 pages,
  all native text, zero scanned. The ~30% image-page share of the planned
  ~2 M pages is an owner planning assumption, not a measurement.

## Evaluation data needed

- A measured image-page share from a real sample of incoming submittals.
- A labelled query set whose answers live on image pages, scored with
  recall@k/MRR against the current text + OCR pipeline first. Only a measured
  failure there justifies a second index.

## Measured benefit on our data

**Not measured.** ViDoRe results are the paper's, on its data.

## Cost on the stated hardware (estimate)

- Storage: 600 k image pages x ~257.5 KB ≈ **~155 GB**; all 2 M pages ≈
  ~515 GB (paper's per-page figure, before compression).
- Indexing: a 3 B-parameter VLM forward pass per page on an i7-1255U with no
  discrete GPU. Not measured; our one VLM trial (qwen3.5:9b generating, a
  heavier task) ran ~2 tok/s. Assume tens of seconds per page at best:
  600 k pages at ~20 s ≈ **~140 days** of CPU (estimate).
- Query: late interaction over ~600 M patch vectors does not fit the existing
  single-matrix memmap design; it needs a multi-vector store (new
  infrastructure).

## Integration risk

- A page-image hit has no quotable text span. The honesty invariant "no claim
  without a resolving citation" and the product promise (answers *quoted* with
  document and page) cannot be met from a patch-similarity score alone.
- New model runtime (torch) and weights to vendor.

## Reason for the decision

No measured problem, a large and GPU-shaped cost, new infrastructure, and a
conflict with the quote-with-citation contract. The cheaper path for image
pages already exists: OCR text into the same index (ADR-0005/0006).
