"""The board's page viewer data for ONE review run (order 274.6): every value read, drawn on its page.

    python scripts/board_page_boxes.py --db <copy of the database> --run <review_run_id> --out <folder> [--pdf <file>]

READ-ONLY on a COPY (a live-shaped path is refused), no AI call, no network call. For each page that has a
current value it writes `page-<n>.png` (the page, turned upright the way the readers saw it, with a box
round every value whose reader recorded one: geometry in blue, picture reader in green, AI reader in
orange; the label's own box in grey) and one data file, `boxes.js`, listing EVERY current value of the sheet:
drawn ones with their box, and the ones that could not be drawn with the reason ("no box recorded" for a
rule-reader value, "page not in the file", "box off the page"). A value is never drawn where it was not read.

The PDF is the one stored for the datasheet (`documents.stored_path`), or `--pdf`. The pictures and the data
hold document text: `--out` must be outside the repository or under `backend/data/` (git-ignored). Output of
the command itself: counts only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

FINISHED = ("completed", "failed", "cancelled")
DPI = 110
#: Box colours (r, g, b) by who read the value.
COLOURS = {
    "geometry_reader": (0.1, 0.3, 0.9),
    "vision_reader": (0.1, 0.65, 0.2),
    "ai": (0.95, 0.5, 0.05),
}
LABEL_COLOUR = (0.55, 0.55, 0.55)
#: What the board prints beside a picture, so the colours and the boxes are never read as more than they are.
LEGEND = {
    "geometry_reader": "blue: read by the geometry reader",
    "vision_reader": "green: read by the picture reader",
    "ai": "orange: read by the AI reader",
    "label": "grey: the label's own box",
    "red": "red: a reader the board does not name",
}
NOTE = "A box is where a reader says it found the value; it is not a check that the value is right."


def _provenance(raw: object) -> dict:
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _box(value: object) -> tuple[float, float, float, float] | None:
    """Four numbers, left < right and top < bottom, or None."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def reader_of(fact: sqlite3.Row, prov: dict) -> str:
    """Who read the value: the provenance's own `reader`, else the AI reader by its method, else the method."""
    if prov.get("reader") in COLOURS:
        return prov["reader"]
    if prov.get("ai_reader") or "datasheet_ai" in str(fact["extraction_method"] or ""):
        return "ai"
    return str(fact["extraction_method"] or "unknown")


def _fact_row(fact: sqlite3.Row) -> dict:
    prov = _provenance(fact["bbox"])
    label = fact["field_label"] or fact["field_name"]
    value = (
        fact["raw_value"]
        if fact["raw_value"] not in (None, "")
        else fact["field_value"]
    )
    return {
        "fact_id": fact["id"],
        "label": label,
        "value": value,
        "unit": fact["unit"],
        "page": fact["page"],
        "reader": reader_of(fact, prov),
        "box": _box(prov.get("value_bbox")),
        "label_box": _box(prov.get("label_bbox")),
        "drawn": False,
        "reason": None,
    }


def export(
    db_path: Path, run_id: str, out_dir: Path, pdf: Path | None = None
) -> dict[str, int]:
    """Write the page pictures and `boxes.js`; return counts only."""
    import pymupdf

    from app import geometry_reader

    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        run = conn.execute(
            "SELECT submittal_document_id, status FROM review_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise LookupError(f"no review run {run_id!r} in this database")
        if run["status"] not in FINISHED:
            raise ValueError(
                f"the run is {run['status']!r}: a run is saved once, when it has finished"
            )
        doc_id = run["submittal_document_id"]
        stored = conn.execute(
            "SELECT stored_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        facts = [
            _fact_row(f)
            for f in conn.execute(
                "SELECT * FROM submittal_facts WHERE submittal_document_id = ?"
                " AND superseded_at IS NULL ORDER BY page, id",
                (doc_id,),
            )
        ]
    finally:
        conn.close()
    path = Path(pdf) if pdf else Path(stored["stored_path"] if stored else "")
    if not path.is_file():
        raise FileNotFoundError(
            "the datasheet's PDF is not at the stored path: name it with --pdf"
        )
    out_dir = Path(out_dir).expanduser().resolve()
    if (out_dir == REPO or REPO in out_dir.parents) and not out_dir.is_relative_to(
        REPO / "backend" / "data"
    ):
        raise ValueError(
            "the pictures hold document text: write them outside the repository or under backend/data/ (git-ignored)"
        )
    if (out_dir / "boxes.js").exists():
        raise FileExistsError(
            "boxes.js is already saved: a finished run is never overwritten"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_drawn: dict[int, int] = {}
    with pymupdf.open(path) as pdf_doc:
        by_page: dict[int, list[dict]] = {}
        for f in facts:
            by_page.setdefault(f["page"] or 0, []).append(f)
        for number, rows in sorted(by_page.items()):
            if not 1 <= number <= pdf_doc.page_count:
                for f in rows:
                    f["reason"] = "page not in the file"
                continue
            page = pdf_doc[number - 1]
            geometry_reader.upright(page)  # the space the readers' boxes are in
            bounds = page.rect
            for f in rows:
                if f["box"] is None:
                    f["reason"] = "no box recorded"
                    continue
                if not pymupdf.Rect(f["box"]).intersects(bounds):
                    f["reason"] = "box off the page"
                    continue
                if f["label_box"] and pymupdf.Rect(f["label_box"]).intersects(bounds):
                    page.draw_rect(
                        pymupdf.Rect(f["label_box"]), color=LABEL_COLOUR, width=0.6
                    )
                page.draw_rect(
                    pymupdf.Rect(f["box"]),
                    color=COLOURS.get(f["reader"], (0.8, 0.1, 0.1)),
                    width=1.4,
                )
                f["drawn"] = True
            drawn = sum(1 for f in rows if f["drawn"])
            if drawn:
                page.get_pixmap(dpi=DPI).save(str(out_dir / f"page-{number}.png"))
                pages_drawn[number] = drawn
    payload = {
        "dpi": DPI,
        "pdf_scale": DPI / 72,
        "legend": LEGEND,
        "note": NOTE,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pages": {
            str(n): [f for f in facts if (f["page"] or 0) == n]
            for n in sorted({f["page"] or 0 for f in facts})
        },
        "pages_with_picture": sorted(pages_drawn),
        "counts": {
            "values": len(facts),
            "drawn": sum(1 for f in facts if f["drawn"]),
            "not_drawn": sum(1 for f in facts if not f["drawn"]),
        },
    }
    text = (
        "// Saved by scripts/board_page_boxes.py. Holds document text: this machine only.\n"
        "window.BOARD = window.BOARD || { runs: {} };\n"
        f"window.BOARD.runs[{json.dumps(run_id)}] = window.BOARD.runs[{json.dumps(run_id)}] || {{}};\n"
        f"window.BOARD.runs[{json.dumps(run_id)}].boxes = {json.dumps(payload, ensure_ascii=False, indent=1, default=str)};\n"
    )
    (out_dir / "boxes.js").write_text(text, encoding="utf-8")
    return {**payload["counts"], "pages_with_picture": len(pages_drawn)}


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", required=True, type=Path, help="a COPY of the database")
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--pdf", type=Path, help="the datasheet's PDF, if not at its stored path"
    )
    args = ap.parse_args(argv)
    db = args.db.resolve()
    if live_guard.is_live_shaped(db) or not db.exists():
        print(f"refused: {db} is a live database or does not exist. Use a copy.")
        return 2
    try:
        counts = export(db, args.run, args.out, args.pdf)
    except (LookupError, ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"refused: {exc}")
        return 1
    print(json.dumps({"run": args.run, **counts}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
