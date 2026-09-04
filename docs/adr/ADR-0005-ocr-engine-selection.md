# ADR-0005 — OCR engine selection

- **Status:** Accepted for RapidOCR / 150 dpi / tiny / classifier-on / subprocess.
  **The recogniser is OPEN**, pending one client question — see "The alphabet
  question" below.
- **Date:** 2026-09-05
- **Decision:** RapidOCR 3.9.2 on ONNX Runtime, 150 dpi, in a **subprocess**,
  weights vendored under `backend/models/ocr/`. Recognised text lives in a
  **separate table** and is **labelled**, never presented as a verbatim
  quotation.

## What the data showed first

Measured on this machine (i7-1255U, 10 physical / 12 logical cores), on the
**real** flagged pages of the ingested corpus, not synthetic images.

| Configuration | s/page | Peak RSS | Notes |
|---|---|---|---|
| PP-OCRv6 tiny, 150 dpi, cls on | **0.90** | 430 MB | baseline |
| PP-OCRv6 tiny, 300 dpi, cls on | 1.25 | 616 MB | +39 % time, +186 MB, **not more accurate** |
| PP-OCRv6 tiny, 150 dpi, cls off | 0.89 | 456 MB | −1 % time. Not worth it |
| PP-OCRv6 small, 150 dpi, cls on | 4.43 | 444 MB | 4.9× slower, visibly more accurate |

12 pages per run, identical page set, runs serialised so no run competed with
another for CPU.

## Engine verification (Phase 2)

| Check | Result |
|---|---|
| 2A — `pip install` reachable | **Yes.** `rapidocr==3.9.2` installed from PyPI |
| 2B — PP-OCRv6 exposed | **Yes**, and it is the package default (`config.yaml` `ocr_version: "PP-OCRv6"`). Verified in the installed package, not the docs |
| 2C — no network at inference | **Verified, but only once the weights are on disk.** See below — the first version of this claim was true and incomplete |
| 2E — licences | rapidocr Apache-2.0, onnxruntime MIT, opencv-python Apache-2.0, Shapely BSD-3, pyclipper MIT, omegaconf BSD. Commercial offline use permitted |

**Reuses infrastructure we already ship.** RapidOCR did not pull its own
runtime — it bound to the existing `onnxruntime` 1.24.1 already present for
e5-small and the reranker. No PaddlePaddle, no torch.

### The offline claim, stated properly

The first version of the 2C result — *"sockets patched, attempts NONE"* — was
true and **incomplete**, in a way worth recording because it is the same shape
as the `Server:` header defect in `status-honesty-audit.md`: a test that passes
because it never traverses the layer where the thing happens.

RapidOCR resolves an unset `model_path` by **downloading from modelscope.cn on
first construction**, into `site-packages`. The offline test passed because a
previous run had already cached the weights there. On a fresh or air-gapped
machine the same code fails — at the first recognition, which is the worst
moment to discover it.

**Fixed, not documented around.** The weights are vendored into
`backend/models/ocr/` by `scripts/fetch_models.py`, pinned by SHA-256 and by
RapidOCR release tag, and `--verify-only` now fails on a machine that has not
staged them. Re-verified properly:

> `site-packages/rapidocr/models` **moved away**, sockets patched to raise,
> engine constructed from `backend/models/ocr/` by explicit path →
> **engine constructed, inference OK (97 boxes), socket attempts: NONE**, and
> the site-packages directory was **not** recreated.

The checksum guard is proven by deliberate failure, the way the pre-commit hook
was: nine bytes appended to the detector →
`WRONG CONTENT (SHA-256 does not match the pinned value)`, exit 1.

Sizes on disk, measured:

```
  1.83 MB  PP-OCRv6_det_tiny.onnx
  4.49 MB  PP-OCRv6_rec_tiny.onnx
  0.59 MB  ch_ppocr_mobile_v2.0_cls_mobile.onnx
  ───────
  6.91 MB  tiny set, total

  9.93 MB  PP-OCRv6_det_small.onnx
 21.23 MB  PP-OCRv6_rec_small.onnx
 31.16 MB  small set (det+rec)
```

## Two findings that change the shape of the work

### 0. Higher dpi produced WORSE text. The measurement contradicted instinct.

This deserves its own heading because everybody's first instinct — the brief's
included — is that raising resolution raises accuracy. On these pages it did
the opposite.

The cover of book2, at 150 dpi and at 300 dpi, same model, same settings:

```
150 dpi:  Differential / Equations / With Boundary-Value Problems / SEVENTH / Dennis G. Zill
300 dpi:  Different / tial / EquationsS / With Boundary-Value Problems / Denis G. Zill / SEVENTH
```

At 300 dpi the title splits mid-word, gains a spurious `S`, and **loses an `n`
from a proper name**. For that, 300 dpi charges **39 % more time and 186 MB
more RSS**.

The mechanism is not mysterious: detection resizes to `max_side_len` regardless
of input resolution, so the extra pixels never reach the detector as detail —
they only change the resampling that feeds it. Recognition then works from
crops of a differently-resampled image. More pixels in is not more signal out.

**150 dpi is chosen on this evidence, not on cost.** The cost saving is a
by-product. It also means the OCR render and the display render are the same
150 dpi image, so lever 7's cache separation, while confirmed to work, turns
out not to be needed.

### 1. PP-OCRv6 is multi-language only. There is no English model.

Every v6 artefact is named `multi_PP-OCRv6_*`. `lang_type` cannot narrow the
character set. The consequence is measurable: recognising **English** pages
produced CJK characters — `凤`, `日`, `区`, `园` — and `≦` for "Save". A
Latin-only recogniser cannot make that class of error; this one can, because
its output alphabet includes CJK.

This is not a reason to reject v6, but it is a real defect mode that the
labelling must cover, and it argues against ever treating recognised text as
verbatim. PP-OCRv5 does ship English-specific models and is the fallback if
this proves worse than the CJK leak suggests.

### 2. The corpus cannot answer the accuracy question.

Of 74 flagged pages, the ones carrying text are **book covers and Excel/
Mathematica UI screenshots**, not scanned specification prose. Sample, tiny at
150 dpi against the page image:

```
tiny   : Pyblish      el Optjons    Example_1_Excel_File,xls    Ja66nqaa
small  : Publish      el Options    Example_1_Excel_File.xls    Dəbbəgr
truth  : Publish      el Options    Example_1_Excel_File.xls    Debugger
```

`small` is clearly better on words, and still cannot read "Debugger" out of an
anti-aliased menu bar. **Neither model has been tested on the content this
system is for.** Any accuracy claim before the Aramco documents arrive would
be a guess. Stated as a guess, not smuggled in as a measurement.

## The alphabet question — v5 English against v6 multilingual

The brief's research covered accuracy and size and never checked the output
alphabet. That is the more consequential gap, because **a wrong alphabet is a
category error, not a quality gap**: a Latin-only recogniser cannot emit `凤`
at all, so the entire class disappears by construction rather than by being
outscored on a benchmark.

The stakes are asymmetric in exactly the way that matters here. `凤` in a
temperature value is obvious and harmless — a reader sees it instantly. `≦`
where the document says `≤`, or a digit substituted from a CJK numeral, is
**invisible and wrong**, and that is precisely the failure this system exists
to prevent.

Same 12 real pages, same 150 dpi, same classifier setting, runs serialised.

| Config | s/page | Peak RSS | Non-ASCII emitted | Weights |
|---|---|---|---|---|
| v6 tiny det + v6 tiny rec (multilingual) | **0.90** | 430 MB | `≦ 凤 日 · Ç` | 6.9 MB |
| v6 small det + rec (multilingual) | 4.43 | 444 MB | — | 31.8 MB |
| v5 mobile det + v5 **en** rec | 4.11 | 421 MB | `√` (a real tick on the page) | 13.3 MB |
| **v6 tiny det + v5 en rec (hybrid)** | **2.16** | 421 MB | **NONE** | **10.3 MB** |

The last row was not in the brief and is the most useful result here.
Detection and recognition are configured independently in RapidOCR, so the
fast multilingual **detector** can be paired with the Latin-only **recogniser**.
It costs 2.4× the all-v6 rate instead of v5's 4.6×, and the non-ASCII class is
gone entirely.

On the diagnostic strings, against the page image:

| Probe | v6 tiny | v6 small | v5 en full | **hybrid** |
|---|---|---|---|---|
| `Publish` | *absent* | ✅ | ✅ | ✅ |
| `Example_1_Excel_File.xls` | `,xls` ❌ | ✅ | ✅ | ✅ |
| `Dennis G. Zill` | ✅ | ✅ | `G. Zill` ❌ | ✅ |
| `Debugger` | `Ja66nqaa` ❌ | `Dəbbəgr` ❌ | ✅ | `Ja66nqaa` ❌ |

The hybrid is better than either parent on three of four probes and no worse on
the fourth. It does not fix `Debugger`, which only the full v5 detector reads —
that is a *detection* difference, not a recognition one, and it is a menu bar
we will never answer from.

### This is held, not decided

**One question settles it, and it is the client's: do the Aramco documents
contain any Arabic?**

- **If yes** — multilingual is mandatory and the all-v6 configuration stands.
  Note that v5 also ships `arabic_PP-OCRv5_rec_mobile`, so a per-script v5
  pairing is a third option rather than v6 by default.
- **If no** — the hybrid wins: no CJK by construction, better words, 10.3 MB,
  at 2.16 s/page against 0.90.

Both configurations are staged by `scripts/fetch_models.py`, so switching is a
config change with no download. The Phase 3 stage reads the model paths from
config for this reason.

## Levers, and what the measurement supported

| Lever | Decision | Basis |
|---|---|---|
| 4 — direction classifier | **Keep it on** | Turning it off saved 1 % (0.90 → 0.89 s/page) and *changed* the output on 2 of 12 pages. A 1 % saving is not worth a behaviour change. Measured, not assumed |
| 5 — dpi | **150 dpi** | 300 dpi costs 39 % more time and 186 MB more RSS and is **not more accurate**. On the book2 cover, 150 read `Differential Equations … Dennis G. Zill`; 300 read `Different / tial / EquationsS … Denis G. Zill` — a split word, a spurious `S`, and a dropped `n` from a proper name |
| 6 — parallelism | **2 workers, from memory** | 430–530 MB per worker against ~1.2 GB headroom. Two fit; three do not. Matches `extract_processes` |
| 7 — separate render cache | **Confirmed** | `cache_path` already keys on dpi. Both `…_p00169_150.png` and `…_p00169_300.png` exist side by side; the OCR render cannot evict the display render |

**`intra_op_num_threads` is set to 2, never −1**, and `enable_cpu_mem_arena`
is already `false` in the RapidOCR default config — the arena behaviour that
cost 829 MB on the reranker is off here by default. `Rec.rec_batch_num` is
pinned at 4 and `Global.max_side_len` at 2000.

## Model choice: tiny, and why not small

`tiny` at 0.90 s/page. `small` at 4.43 s/page for visibly better words.

The gate in the brief was "move to small only if tiny's text is visibly wrong
against the page image". It is (`Pyblish`, `Ja66nqaa`). But the pages that
expose the difference are **UI screenshots we will never need to answer
from**, and the 4.9× cost is charged against every page of a scanned
document — 21 minutes becomes 103 minutes on 1,400 pages.

**Decision: tiny now, revisit when real scanned specifications exist.** This
is a judgement call on unrepresentative evidence, and it is recorded as one.
The model is a config value, not a code path, so the revisit is cheap.

## Memory: OCR runs in a subprocess

Not a tuning detail. The API process peaks at 3,247 MB with both ONNX arenas
on, and Ollama holds ~3,400 MB alongside it; measured free RAM at demo time
was 1.15 GiB. An OCR session inside the API process would not fit.

`extract.py` already dispatches to worker processes because PyMuPDF is not
thread-safe. OCR takes the same treatment, and the memory problem dissolves as
a side effect: the ONNX session, the image buffers and the arena live in a
child whose entire footprint returns to the OS on exit.

## Consequences

- A new install-time network dependency for model weights. Must be vendored.
- Six new transitive packages, of which `opencv-python` is the large one.
- Recognised text is a *guess about pixels*. Everything downstream of this ADR
  exists to make sure a reader is never told otherwise. See the provenance
  design in ADR-0006, which is the other half of this decision.

## Rejected

- **Surya** — RAIL-M licence restricts commercial use above a $5M threshold. A
  legal blocker, not a technical one.
- **Tesseract** — needs `tesseract.exe` installed separately on the demo
  machine, and a published comparison had it produce `Qty` → `ay`. Retained as
  the fallback comparator only if RapidOCR proves unusable on real documents.
- **A VLM** — can invent a value that was never on the page. Wrong failure mode
  for a specification.
