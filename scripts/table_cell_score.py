"""R27 (#504): a CELL-LEVEL score for a layout reader, on the invented datasheets.

`scripts/datasheet_bench.py` scores a reader by FIELD (was the right value
stored under the right name?). Nothing measured the step before that: does
the layout tool find the table's cells at all, with the right text in the
right box? The two-tool reader of R27 hands each cell to a second reader, so
a cell the layout tool loses, merges or swallows as a header is lost to it.

The key is `answer_key.json`'s `cells`: every cell the generator DREW (text
and box, page points), written by `scripts/make_datasheet_bench.py`. A file
whose drawn boxes are not the page's (a rotated page, a scan) has
`cells: null` and a reason; a file with no drawn table has no cells. Neither
is scored, and both are COUNTED - a file left out is never a silent pass.

Per keyed cell, exactly one of:
  right    a read cell sits in the drawn box and its text equals the drawn text
  wrong    a read cell sits in the drawn box with different text
  header   the cell's text was taken as a column header: it is known, but it
           is no longer a cell with a box (so no second reader can be sent to it)
  missed   nothing was read there
plus `extra`: read cells with text that sit in no drawn box.

Usage:  python scripts/table_cell_score.py [--json]
Invented data only; reads no database and opens no socket.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "backend" / "tests" / "fixtures" / "synthetic" / "datasheets"
RIGHT, WRONG, HEADER, MISSED = "right", "wrong", "header", "missed"
OUTCOMES = (RIGHT, WRONG, HEADER, MISSED)


def _fold(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def _centre(box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _inside(point, box, slack: float = 1.0) -> bool:
    return box[0] - slack <= point[0] <= box[2] + slack and box[1] - slack <= point[1] <= box[3] + slack


def score_cells(truth: list[dict], read: list[dict], headers: dict[int, list[str]] | None = None) -> dict:
    """Score one file. `truth`: the key's cells ({page, text, box}). `read`:
    the reader's cells ({page, text, box}; a cell with no box cannot be
    placed and counts for nothing). `headers`: per page, the texts the reader
    took as column headers."""
    headers = {page: [_fold(t) for t in texts] for page, texts in (headers or {}).items()}
    placed = [c for c in read if c.get("box") and _fold(c.get("text"))]
    used: set[int] = set()
    counts = dict.fromkeys(OUTCOMES, 0)
    detail = []
    for cell in truth:
        here = [i for i, c in enumerate(placed)
                if c["page"] == cell["page"] and _inside(_centre(c["box"]), cell["box"])]
        want = _fold(cell["text"])
        if any(_fold(placed[i]["text"]) == want for i in here):
            outcome = RIGHT
        elif here:
            outcome = WRONG
        elif want in headers.get(cell["page"], []):
            outcome = HEADER
        else:
            outcome = MISSED
        used.update(here)
        counts[outcome] += 1
        detail.append({"page": cell["page"], "text": cell["text"], "outcome": outcome})
    extra = sum(1 for i, c in enumerate(placed) if i not in used
                and not any(c["page"] == t["page"] and _inside(_centre(c["box"]), t["box"]) for t in truth))
    return {"cells": len(truth), **counts, "extra": extra, "detail": detail}


def read_layout(path: Path) -> tuple[list[dict], dict[int, list[str]]]:
    """The cells and header labels `geometry_reader.read_tables` returns for a PDF."""
    import pymupdf

    sys.path.insert(0, str(REPO / "backend"))
    from app import geometry_reader

    cells: list[dict] = []
    headers: dict[int, list[str]] = {}
    with pymupdf.open(str(path)) as doc:
        for page in doc:
            found = geometry_reader.read_tables(page)
            for table in found.get("tables") or []:
                headers.setdefault(table["page"], []).extend(str(x) for x in table.get("labels") or [] if x)
                for row in table.get("rows") or []:
                    for cell in row.get("cells") or []:
                        cells.append({"page": cell["page"], "text": cell.get("text"), "box": cell.get("bbox")})
    return cells, headers


def score_all(reader=read_layout, data: Path = DATA) -> dict:
    """Every file of the key: scored, or named with why it is not."""
    key = json.loads((data / "answer_key.json").read_text(encoding="utf-8"))["files"]
    files, not_scored = {}, {}
    for name, entry in key.items():
        cells = entry.get("cells")
        if cells is None:
            not_scored[name] = entry.get("cells_not_keyed") or "no cell key"
        elif not cells:
            not_scored[name] = "no drawn table cells in this file"
        elif not name.lower().endswith(".pdf"):
            not_scored[name] = "not a PDF"
        else:
            read, headers = reader(data / name)
            files[name] = score_cells(cells, read, headers)
    total = {k: sum(f[k] for f in files.values()) for k in ("cells", *OUTCOMES, "extra")}
    return {"files": files, "not_scored": not_scored, "total": total}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    out = score_all()
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"{'file':34} {'cells':>5} {'right':>5} {'wrong':>5} {'header':>6} {'missed':>6} {'extra':>5}")
    for name, f in out["files"].items():
        print(f"{name:34} {f['cells']:>5} {f[RIGHT]:>5} {f[WRONG]:>5} {f[HEADER]:>6} {f[MISSED]:>6} {f['extra']:>5}")
    t = out["total"]
    print(f"{'TOTAL (' + str(len(out['files'])) + ' files)':34} {t['cells']:>5} {t[RIGHT]:>5} {t[WRONG]:>5} "
          f"{t[HEADER]:>6} {t[MISSED]:>6} {t['extra']:>5}")
    if t["cells"]:
        print(f"cells read right: {t[RIGHT]} of {t['cells']} keyed cells in {len(out['files'])} invented files")
    for name, why in out["not_scored"].items():
        print(f"not scored: {name}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
