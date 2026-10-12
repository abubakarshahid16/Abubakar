"""How often is OCR right? Measured against pages whose true text is known.

WHY THIS WAY. A real scan has no answer key: nobody has typed out what the
page really says. But most of the owner's PDFs carry a TEXT LAYER written by
the software that made them, and that text is exactly what the page says. So
this renders such a page to an image, runs the project's own recogniser on
the image (the same engine, models and DPI `ocr.recognise_batch` uses), and
compares what OCR read with the text layer. Two image qualities:

  clean  the page rendered as the system renders it for OCR
  scan   the same image made to look scanned: greyscale, a slight blur, a
         small rotation, and JPEG compression - an ESTIMATE of a real scan,
         labelled as one, not a real scan

WHAT IS MEASURED (per page, then summarised), order-free because OCR reads a
table in a different order from the text layer and order is not what an
engineer cares about:

  word recall      share of the page's words OCR reproduced exactly
  number recall    share of the page's numbers (12, 0.5, 3/4, 150) OCR
                   reproduced exactly - the figures a review compares
  misread numbers  numbers OCR produced that are NOT on the page at all,
                   per 100 true numbers - a wrong figure is worse than a
                   missing one, because it can be compared as if real

PRIVACY (CLAUDE.md rule 1). It reads a diagnostic COPY of the database, prints
counts and percentages only - never text, file names or document numbers -
and writes nothing into the repository.

    python scripts/ocr_accuracy.py --db <copy.sqlite> [--pages 60] [--per-doc 2]
        [--path-map "D:\\project\\Rag_chatbot=/mnt/Rag_chatbot"] [--out result.json]
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import random
import re
import sqlite3
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_WORD = re.compile(r"[A-Za-z0-9]+(?:[./][0-9]+)*")
_NUMBER = re.compile(r"\d+(?:[.,/]\d+)*")


def words(text: str) -> collections.Counter:
    """Lowercase word tokens; a decimal or fraction stays one token."""
    return collections.Counter(w.lower() for w in _WORD.findall(text or ""))


def numbers(text: str) -> collections.Counter:
    """Numeric tokens exactly as printed ("0.5" and "0,5" differ on purpose:
    a comma where the page has a point is a misread a review could act on)."""
    return collections.Counter(_NUMBER.findall(text or ""))


def recall(truth: collections.Counter, read: collections.Counter) -> float | None:
    """Share of `truth` reproduced in `read` (multiset). None when the truth
    has nothing to recall - never 0 or 1 by default (CLAUDE.md rule 4)."""
    total = sum(truth.values())
    if not total:
        return None
    return sum((truth & read).values()) / total


def invented(truth: collections.Counter, read: collections.Counter) -> int:
    """How many tokens OCR produced that the truth does not contain."""
    return sum((read - truth).values())


def score_page(truth_text: str, ocr_text: str) -> dict:
    tw, rw = words(truth_text), words(ocr_text)
    tn, rn = numbers(truth_text), numbers(ocr_text)
    return {
        "true_words": sum(tw.values()),
        "true_numbers": sum(tn.values()),
        "word_recall": recall(tw, rw),
        "number_recall": recall(tn, rn),
        "misread_numbers": invented(tn, rn),
    }


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def summarise(pages: list[dict]) -> dict:
    """Summary over scored pages. Rates carry their denominators."""
    wr = [p["word_recall"] for p in pages if p["word_recall"] is not None]
    nr = [p["number_recall"] for p in pages if p["number_recall"] is not None]
    true_numbers = sum(p["true_numbers"] for p in pages)
    misread = sum(p["misread_numbers"] for p in pages)
    return {
        "pages": len(pages),
        "pages_with_numbers": len(nr),
        "word_recall_median": statistics.median(wr) if wr else None,
        "word_recall_p10": _pct(wr, 0.10),
        "number_recall_median": statistics.median(nr) if nr else None,
        "number_recall_p10": _pct(nr, 0.10),
        "true_numbers": true_numbers,
        "misread_numbers": misread,
        "misread_per_100_true": (100 * misread / true_numbers) if true_numbers else None,
    }


def degrade(png: bytes, seed: int) -> bytes:
    """The 'scan' image: greyscale, slight blur, a small rotation, JPEG 60.
    Deterministic per seed. An estimate of a scanner, not a scanner."""
    from PIL import Image, ImageFilter

    rng = random.Random(seed)
    img = Image.open(io.BytesIO(png)).convert("L")
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))
    img = img.rotate(rng.uniform(-1.0, 1.0), expand=True, fillcolor=255)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=60)
    return buf.getvalue()


def sample_pages(db: sqlite3.Connection, n: int, per_doc: int, seed: int,
                 min_chars: int = 200) -> list[tuple[str, str, int, str]]:
    """(document id, stored path, page, text layer) for native-text pages,
    at most `per_doc` per document, seeded - a SAMPLE, labelled as one."""
    rng = random.Random(seed)
    rows = db.execute(
        """SELECT d.id, d.stored_path, p.page_no, p.text FROM pages p
           JOIN documents d ON d.id = p.document_id
           WHERE d.status = 'ready' AND p.needs_ocr = 0 AND p.char_count >= ?
             AND lower(d.stored_path) LIKE '%.pdf'""", (min_chars,)).fetchall()
    by_doc: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by_doc[r[0]].append(r)
    picked = []
    for doc_id in sorted(by_doc):
        pages = by_doc[doc_id]
        rng.shuffle(pages)
        picked.extend(pages[:per_doc])
    rng.shuffle(picked)
    return [(r[0], r[1], r[2], r[3]) for r in picked[:n]]


def _map_path(stored: str, mapping: list[tuple[str, str]]) -> str:
    for src, dst in mapping:
        if stored.lower().startswith(src.lower()):
            return dst + stored[len(src):].replace("\\", "/")
    return stored


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path, help="a diagnostic COPY")
    ap.add_argument("--pages", type=int, default=60)
    ap.add_argument("--per-doc", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260929)
    ap.add_argument("--path-map", action="append", default=[],
                    help="'<stored prefix>=<local prefix>' when the PDFs moved")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--offset", type=int, default=0,
                    help="skip this many sampled pages (to run the sample in slices)")
    ap.add_argument("--count", type=int, default=None,
                    help="score at most this many sampled pages in this call")
    ap.add_argument("--jsonl", type=Path,
                    help="append one line per scored page (counts only) - for slices")
    ap.add_argument("--summarise", type=Path,
                    help="print the summary of a --jsonl file and exit")
    args = ap.parse_args(argv)
    if args.summarise:
        rows = [json.loads(line) for line in args.summarise.read_text().splitlines() if line]
        report = {"pages_scored": len({r["i"] for r in rows}),
                  "documents_sampled": len({r["doc"] for r in rows}),
                  "clean": summarise([r for r in rows if r["mode"] == "clean"]),
                  "scan_estimate": summarise([r for r in rows if r["mode"] == "scan"])}
        print(json.dumps(report, indent=2))
        return 0

    sys.path.insert(0, str(REPO / "backend"))
    import pymupdf
    from app import ocr
    from app.config import settings

    mapping = [tuple(m.split("=", 1)) for m in args.path_map]
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    sample = sample_pages(db, args.pages, args.per_doc, args.seed)
    engine = ocr._build_engine()
    scored: dict[str, list[dict]] = {"clean": [], "scan": []}
    skipped = collections.Counter()
    end = len(sample) if args.count is None else args.offset + args.count
    for i, (doc_id, stored, page_no, truth) in enumerate(sample):
        if not args.offset <= i < end:
            continue
        path = _map_path(stored, mapping)
        try:
            with pymupdf.open(path) as pdf:
                png = pdf.load_page(page_no - 1).get_pixmap(dpi=settings.ocr_dpi).tobytes("png")
        except Exception as exc:  # noqa: BLE001 - counted, never silent
            skipped[type(exc).__name__] += 1
            continue
        for mode, image in (("clean", png), ("scan", degrade(png, args.seed + i))):
            result = engine(image)
            text = "\n".join(result.txts or [])
            page_score = score_page(truth, text)
            scored[mode].append(page_score)
            if args.jsonl:
                with open(args.jsonl, "a", encoding="utf-8") as fh:
                    # counts only; the document id is an opaque hash, kept so a
                    # slice run can count documents - never a name
                    fh.write(json.dumps({"i": i, "doc": doc_id, "mode": mode,
                                         **page_score}) + "\n")
        print(f"  page {i + 1:>3}/{len(sample)} done", file=sys.stderr)

    report = {
        "sample": "seeded sample of native-text pages, the text layer as ground truth",
        "engine": f"{settings.ocr_det_model} + {settings.ocr_rec_model} @ {settings.ocr_dpi} dpi",
        "documents_sampled": len({s[0] for s in sample}),
        "skipped_unreadable": dict(skipped),
        "clean": summarise(scored["clean"]),
        "scan_estimate": summarise(scored["scan"]),
    }
    print(json.dumps(report, indent=2))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
