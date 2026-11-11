"""Write the OCR box file from the label lab's database copy (order 12, N7). Local file only: it holds the words of rule-book
pages, so it never goes into git, a report or a log.

Reads the lab copy (read only). For every page of `ocr_box_page` whose document is a company standard (a rule book, never a
paper) it writes the page's boxes in reading order with their scores, the document's sha256 from `documents`, and the
recogniser the lab's own `page_ocr` row names for that page (engine, model, dpi) and the time the boxes were made. Nothing is
trusted by the import: it checks the sha256 against the app's document, the page against the app's stored text, and the scores.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from .claude_approved import STANDARD_ROLE
from .ocr_box_import import EXPORT_FORMAT, boxes_sha256


def convert(conn: sqlite3.Connection) -> tuple[list[dict], dict]:
    """(pages in the box file's shape, counts)."""
    conn.row_factory = sqlite3.Row
    counts: Counter = Counter()
    pages: list[dict] = []
    for p in conn.execute(
        "SELECT b.document_id, b.page_no, b.engine, b.extracted_at, d.sha256, c.document_role,"
        " o.engine AS o_engine, o.model AS o_model, o.dpi AS o_dpi"
        " FROM ocr_box_page b LEFT JOIN documents d ON d.id = b.document_id"
        " LEFT JOIN document_classification c ON c.document_id = b.document_id"
        " LEFT JOIN page_ocr o ON o.document_id = b.document_id AND o.page_no = b.page_no"
        " ORDER BY b.document_id, b.page_no"
    ).fetchall():
        counts["lab_pages"] += 1
        if p["document_role"] != STANDARD_ROLE:
            counts["not_a_rule_book"] += 1
            continue
        if not p["sha256"] or not p["o_engine"]:
            counts["no_sha_or_engine"] += 1
            continue
        boxes = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT text, score FROM ocr_box WHERE document_id = ? AND page_no = ? ORDER BY seq",
                (p["document_id"], p["page_no"]),
            )
        ]
        if not boxes:
            counts["no_boxes"] += 1
            continue
        pages.append(
            {
                "document_id": p["document_id"],
                "document_sha256": p["sha256"],
                "page": p["page_no"],
                "engine": p["o_engine"],
                "model": p["o_model"],
                "dpi": p["o_dpi"],
                "made_at": p["extracted_at"] or "",
                "boxes_sha256": boxes_sha256(boxes),
                "boxes": [{"text": t, "score": s} for t, s in boxes],
            }
        )
        counts["written"] += 1
    return pages, dict(counts)


def check_out(out: str | Path, data_dir: str | Path | None) -> Path:
    """`out` resolved, only when it is a .json path INSIDE the data directory given (like the import insists), so the box
    file cannot land in a git checkout by accident. Anything else raises ValueError (a cause word, never a path)."""
    if not data_dir:
        raise ValueError(
            "--data-dir is needed: the box file is written inside a data directory"
        )
    root = Path(data_dir).resolve()
    target = Path(out).resolve()
    if root not in target.parents:
        raise ValueError("--out is outside the data directory")
    if target.suffix.lower() != ".json":
        raise ValueError("--out is not a .json file")
    return target


def write(pages: list[dict], out: str | Path) -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"format": EXPORT_FORMAT, "pages": pages}, ensure_ascii=False),
        encoding="utf-8",
    )
