"""Import the OCR boxes of a rule book's scanned pages, so a quote is judged by the boxes it stands in (order 12, N7).

WHY. `rule_label_ocr` already judges a quote on a recognised (scanned) page by the MINIMUM score of the boxes its words
touch, when the database holds the boxes (`ocr_box`, `ocr_box_page`). The app stores only one score per PAGE
(`page_ocr.min_conf`), so one weak box anywhere on a page demotes every quote on it. The label lab kept the boxes of the
pages it judged (a re-run of the app's own recogniser). This module brings those boxes into the app's tables. The 0.70
line (`settings.ocr_low_conf_threshold`) and the quote-level check are NOT changed: a quote that touches a low box stays low.

A PAGE IS STORED ONLY WHEN EVERY CHECK HOLDS (else it is counted under one cause word, never stored):
  * the document exists, is a company standard (a rule book, never a paper) and its sha256 equals the one in the file: boxes
    made from another revision of the book are refused (`revision_mismatch`);
  * the page exists in the app's own page text and that page is a recognised (scanned) one (`no_such_page`,
    `not_recognised_page`); a text-layer page has no use for boxes;
  * every score is a number from 0 to 1 and every box has text (`bad_score`);
  * the page's boxes, joined, agree with the app's stored text of that page (`text_mismatch`). The rule: both texts go
    through the quote finder's own folding (`ai_requirement_tables._squash`: whitespace collapsed, case folded, case-kept
    units marked; then `compiled_rule_pages.join_hyphens`), are cut into words, and the words are matched in order
    (`difflib`); at least `AGREEMENT_MIN` (0.95) of the stored page's words AND of the boxes' words must be matched. Why a
    tolerance: re-running the recogniser does not give the same text twice (measured: 35 of 60 pages differ by 1 to 21 words,
    at most 4.6 %). Why it is safe: the stored-text word-for-word check of the quote still comes first, and `align_quote`
    needs the quote's own words to stand in the boxes exactly, so a quote is word for word in both readings;
  * a page already stored with other boxes is refused (`conflict`): the tables are append-only. Identical again: counted as
    `unchanged`, nothing written.
Per page the table records engine, model, dpi, made-at, the document's sha256, the boxes' sha256, the file's sha256, the
agreement and the import time. The lab recogniser's boxes carry no geometry; none is stored.

BEHIND ONE SWITCH (`agent_review_enabled`). Nothing here is deleted or updated: triggers refuse it. No table of the rule
book, the labels or the documents is written.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import compiled_rule_report, rule_label_import
from .ai_requirements import _squash
from .compiled_rule_pages import join_hyphens
from .rule_label_schema import require_on

EXPORT_FORMAT = "ocr-boxes-v1"
AGREEMENT_MIN = 0.95
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
STANDARD_ROLE = "COMPANY_STANDARD"
CAUSES = (
    "malformed",
    "unknown_document",
    "not_a_rule_book",
    "revision_mismatch",
    "no_such_page",
    "not_recognised_page",
    "bad_score",
    "text_mismatch",
    "conflict",
)

_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS ocr_box (document_id TEXT NOT NULL, page_no INTEGER NOT NULL, seq INTEGER NOT NULL,
        text TEXT NOT NULL, score REAL, PRIMARY KEY (document_id, page_no, seq))""",
    """CREATE TABLE IF NOT EXISTS ocr_box_page (document_id TEXT NOT NULL, page_no INTEGER NOT NULL, engine TEXT,
        extracted_at TEXT, matches_page INTEGER, model TEXT, dpi INTEGER, document_sha256 TEXT, boxes_sha256 TEXT,
        file_sha256 TEXT, text_agreement REAL, imported_at TEXT, PRIMARY KEY (document_id, page_no))""",
    """CREATE TRIGGER IF NOT EXISTS ocr_box_no_update BEFORE UPDATE ON ocr_box
        BEGIN SELECT RAISE(ABORT, 'ocr_box: rows are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS ocr_box_no_delete BEFORE DELETE ON ocr_box
        BEGIN SELECT RAISE(ABORT, 'ocr_box: rows are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS ocr_box_page_no_update BEFORE UPDATE ON ocr_box_page
        BEGIN SELECT RAISE(ABORT, 'ocr_box_page: rows are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS ocr_box_page_no_delete BEFORE DELETE ON ocr_box_page
        BEGIN SELECT RAISE(ABORT, 'ocr_box_page: rows are append-only'); END""",
)
_PAGE_COLUMNS = (
    "model",
    "dpi",
    "document_sha256",
    "boxes_sha256",
    "file_sha256",
    "text_agreement",
    "imported_at",
)


class BoxSchemaError(RuntimeError):
    """An `ocr_box_page` table of an older shape is already there; it is not altered."""


def create_tables(conn: sqlite3.Connection) -> None:
    """Create what is missing (switch off: raises). An existing `ocr_box_page` without the provenance columns is refused."""
    require_on()
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _STATEMENTS:
            conn.execute(statement)
        have = {r[1] for r in conn.execute("PRAGMA table_info(ocr_box_page)")}
        if not set(_PAGE_COLUMNS) <= have:
            raise BoxSchemaError("ocr_box_page exists without the provenance columns")
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def read_file(path: Path) -> tuple[list[Any], str]:
    """(the pages of a box file, the file's sha256), or ImportPathError (not JSON, not this format, no pages list)."""
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        raise rule_label_import.ImportPathError("not_valid_json") from None
    if (
        not isinstance(data, dict)
        or data.get("format") != EXPORT_FORMAT
        or not isinstance(data.get("pages"), list)
    ):
        raise rule_label_import.ImportPathError("not_a_box_file")
    return data["pages"], hashlib.sha256(raw).hexdigest()


def boxes_sha256(boxes: list[tuple[str, float]]) -> str:
    return hashlib.sha256(
        json.dumps([[t, s] for t, s in boxes], ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _words(text: str) -> list[str]:
    """The quote finder's folding, cut into words (the stored page text and the boxes alike)."""
    return _squash(join_hyphens(text or "")).split()


def agreement(boxes: list[str], page_text: str) -> tuple[float, bool]:
    """(the lower of: share of the stored page's words matched, share of the boxes' words matched; whether the two word
    lists are identical). Zero when either side has no words."""
    from .numparse import normalise_text

    a, b = _words(normalise_text("\n".join(boxes))), _words(page_text)
    if not a or not b:
        return 0.0, False
    same = sum(
        m.size
        for m in difflib.SequenceMatcher(
            None, a, b, autojunk=False
        ).get_matching_blocks()
    )
    return min(same / len(a), same / len(b)), a == b


def _shape(raw: Any) -> tuple[list[tuple[str, float]], str | None] | None:
    """(the page's boxes as (text, score) pairs, None), ([], "bad_score"), or None when the boxes are not a list of texts."""
    if not isinstance(raw, dict):
        return None
    boxes = raw.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        return None
    out: list[tuple[str, float]] = []
    for b in boxes:
        if not isinstance(b, dict) or not isinstance(b.get("text"), str):
            return None
        s = b.get("score")
        if (
            isinstance(s, bool)
            or not isinstance(s, (int, float))
            or not math.isfinite(s)
            or not 0.0 <= float(s) <= 1.0
            or not b["text"].strip()
        ):
            return [], "bad_score"
        out.append((b["text"], float(s)))
    return out, None


def _well_formed(raw: Any) -> tuple[list[tuple[str, float]] | None, str | None]:
    """(the page's boxes, None) or (None, the cause word): the shape of one page of the file, before the database is asked."""
    if not isinstance(raw, dict):
        return None, "malformed"
    page, dsha = raw.get("page"), raw.get("document_sha256")
    if (
        not isinstance(raw.get("document_id"), str)
        or not raw["document_id"]
        or isinstance(page, bool)
        or not isinstance(page, int)
        or not _HEX64.match(str(dsha or ""))
        or not isinstance(raw.get("engine"), str)
        or not raw["engine"].strip()
        or not isinstance(raw.get("made_at"), str)
    ):
        return None, "malformed"
    shaped = _shape(raw)
    if shaped is None:
        return None, "malformed"
    boxes, bad = shaped
    if bad:
        return None, bad
    if raw.get("boxes_sha256") not in (None, boxes_sha256(boxes)):
        return None, "malformed"
    return boxes, None


def _document(conn: sqlite3.Connection, did: str) -> tuple | None:
    """(sha256, role, page texts, page origins) of a document as the app holds it, or None when it is not there."""
    row = conn.execute(
        "SELECT d.sha256, c.document_role FROM documents d LEFT JOIN document_classification c"
        " ON c.document_id = d.id WHERE d.id = ?",
        (did,),
    ).fetchone()
    if row is None:
        return None
    return (
        row[0],
        row[1],
        compiled_rule_report.pages_of(conn, did),
        compiled_rule_report.page_origin(conn, did),
    )


def _against_the_app(
    raw: dict, boxes: list, held: tuple | None
) -> tuple[str | None, float, bool]:
    """(the cause word or None, the text agreement, whether the words are identical) of a well-formed page against the
    document the app holds."""
    if held is None:
        return "unknown_document", 0.0, False
    sha, role, texts, origin = held
    page = raw["page"]
    if role != STANDARD_ROLE:
        return "not_a_rule_book", 0.0, False
    if sha != raw["document_sha256"]:
        return "revision_mismatch", 0.0, False
    if not (texts.get(page) or "").strip():
        return "no_such_page", 0.0, False
    if (origin.get(page) or {}).get("page_source") != "recognised":
        return "not_recognised_page", 0.0, False
    score, identical = agreement([t for t, _ in boxes], texts[page])
    return ("text_mismatch" if score < AGREEMENT_MIN else None), score, identical


def _store(
    conn: sqlite3.Connection,
    raw: dict,
    boxes: list,
    score: float,
    identical: bool,
    file_sha256: str,
) -> None:
    did, page = raw["document_id"], raw["page"]
    with conn:
        conn.execute(
            "INSERT INTO ocr_box_page (document_id, page_no, engine, extracted_at, matches_page, model, dpi,"
            " document_sha256, boxes_sha256, file_sha256, text_agreement, imported_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
            (
                did,
                page,
                raw["engine"],
                raw["made_at"],
                1 if identical else 0,
                raw.get("model") if isinstance(raw.get("model"), str) else None,
                raw.get("dpi") if isinstance(raw.get("dpi"), int) else None,
                raw["document_sha256"],
                boxes_sha256(boxes),
                file_sha256,
                round(score, 6),
            ),
        )
        conn.executemany(
            "INSERT INTO ocr_box (document_id, page_no, seq, text, score) VALUES (?,?,?,?,?)",
            [(did, page, i, t, s) for i, (t, s) in enumerate(boxes)],
        )


def import_pages(conn: sqlite3.Connection, pages: list[Any], file_sha256: str) -> dict:
    """Check and store `pages` on `conn` (the server's own connection). Returns counts only:
    {read, stored, unchanged, refused: {cause: n}, refused_total}. Switch off: raises `SwitchedOff`."""
    require_on()
    create_tables(conn)
    refused = dict.fromkeys(CAUSES, 0)
    counts: dict[str, Any] = {
        "read": 0,
        "stored": 0,
        "unchanged": 0,
        "refused": refused,
    }
    docs: dict[str, tuple | None] = {}
    for raw in pages:
        counts["read"] += 1
        boxes, cause = _well_formed(raw)
        if cause is None:
            if raw["document_id"] not in docs:
                docs[raw["document_id"]] = _document(conn, raw["document_id"])
            cause, score, identical = _against_the_app(
                raw, boxes, docs[raw["document_id"]]
            )
        if cause is None:
            have = conn.execute(
                "SELECT boxes_sha256 FROM ocr_box_page WHERE document_id = ? AND page_no = ?",
                (raw["document_id"], raw["page"]),
            ).fetchone()
            if have is None:
                _store(conn, raw, boxes, score, identical, file_sha256)
                counts["stored"] += 1
            elif have[0] == boxes_sha256(boxes):
                counts["unchanged"] += 1
            else:
                cause = "conflict"
        if cause is not None:
            refused[cause] += 1
    counts["refused_total"] = sum(refused.values())
    return counts
