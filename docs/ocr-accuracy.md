# OCR accuracy, measured on the owner's own documents

`scripts/ocr_accuracy.py`. Measured 2026-09-29 on a diagnostic copy of the owner's
database, in the owner's VM, counts only.

## How (and why this way)

A real scan has no answer key. Most of the owner's PDFs carry a **text layer** written
by the software that produced them, and that text is exactly what the page says. So the
script renders such a page to an image, runs the project's own recogniser on it (same
engine, models and DPI as `ocr.recognise_batch`: PP-OCRv6 det/rec tiny at 150 dpi), and
compares the result with the text layer. Two image qualities: **clean** (as the system
renders it) and **scan estimate** (greyscale, slight blur, up to 1 degree rotation, JPEG
60) - an estimate of a scanner, not a real scan.

Order-free measures, because OCR reads tables in a different order from the text layer:
word recall, number recall (numbers kept whole: `12.5`, `3/4`; `12,5` is a different
number on purpose), and misread numbers (numbers OCR produced that are not in the text
layer, per 100 true numbers).

## Result - a SAMPLE: 40 pages, 1 each from 40 documents, 1,570 true numbers

| | Clean | Scan estimate |
|---|---|---|
| Word recall, median page | 98.4% | 98.6% |
| Word recall, worst 10% of pages | below 88.0% | below 87.0% |
| Pages under 90% word recall | 8 of 40 | 7 of 40 |
| Number recall, median page | 100% | 100% |
| Number recall, worst 10% of pages | below 81.3% | below 81.3% |
| Misread numbers per 100 true numbers | 4.7 (74 of 1,570) | 2.9 (45 of 1,570) |

## What this does and does not show

- **Typical pages read very well**: half the pages had every number right.
- **The weak pages are dense tables**: the worst page had 250 numbers and OCR reproduced
  69% of them. A reviewer should not trust OCR text on a dense numeric table without
  looking at the page image - which is why OCR'd pages already carry a confidence and
  low-confidence-box count (`page_ocr.low_conf_boxes`) and go to engineer review.
- **"Misread" is an upper bound**: a number OCR reads from a drawing or an embedded image
  that the text layer does not contain is counted as misread although it may be right.
- **The scan estimate is mild**: it came out about the same as clean, so this simulation
  does not stress the recogniser the way a poor photocopy would. It is not evidence about
  bad scans. A real answer needs a few truly scanned pages with a typed answer key.
- One run, one seed, 40 pages. A sample, labelled as one.

Re-run: `python scripts/ocr_accuracy.py --db <diagnostic copy> --pages 40 --per-doc 1`
(add `--offset/--count --jsonl` to run in slices and `--summarise` to combine).
