"""The completeness check of a TRANSMITTAL: documents listed against documents held (K1b, order 13). Code only: no model, no network.

A transmittal is a cover sheet that lists documents. Reviewing it means: is every listed document in the library, and is the
revision the sheet states the revision the library holds? The numbers come from two readings of the sheet's own pages, both by
pattern, never by one layout (rule 13): (1) every held document number (stored classification, readable by the caller) that stands
in the sheet's text; (2) every token shaped like a document number (three or more segments joined by - _ / . with a digit). A
revision is read only when the word Revision or Rev stands after the number on the same line. Per listed document, by code:

  held, revision stated and equal            -> Pass     (a code comparison)
  held, revision stated and different        -> Fail     (a code comparison)
  held, no revision stated or none held      -> Query    (said, never guessed)
  not in the library (for this caller)       -> Query    (not "missing": the caller may simply not read it)

Whose documents it counts (rule 4): only documents the caller may read (a filter narrows, rule 5). No paper text is stored or
logged; the rows hold document numbers and revision words only. The CRS-style list is drawn through the one layout (`crs_layout`).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping

from . import crs_ai_words as words
from . import crs_export, crs_layout
from .agent_run_crs import _cell

PASS, FAIL, QUERY = words.STATUS_PASS, words.STATUS_FAIL, words.STATUS_QUERY
#: A token shaped like a document number: three or more segments, at least one digit.
_NUMBER = re.compile(r"\b[A-Z0-9]{2,}(?:[-_/.][A-Z0-9]{1,}){2,}\b", re.I)
_REV = re.compile(r"\brev(?:ision)?\b\.?\s*[:#-]?\s*([A-Z0-9]{1,3})\b", re.I)
BY = "Code check (no AI)"
CODE_COLUMNS_NOTE = "Documents listed on the transmittal against documents held in the library; revisions compared by code."


def norm(number: str | None) -> str:
    """A document number as compared: upper case, no spaces, one separator."""
    return re.sub(r"[\s_/.]+", "-", str(number or "").strip().upper())


def norm_rev(rev: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(rev or "").upper())


def _held(
    conn: sqlite3.Connection, allowed: frozenset[str], own: str
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT d.id AS id, c.document_number AS number, c.revision AS revision FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id WHERE c.document_number IS NOT NULL"
        " AND TRIM(c.document_number) <> '' ORDER BY d.id"
    ):
        if r["id"] in allowed and r["id"] != own:
            out.setdefault(
                norm(r["number"]),
                {"document_id": r["id"], "revision": norm_rev(r["revision"])},
            )
    return out


def _lines(conn: sqlite3.Connection, document_id: str) -> list[tuple[int, str]]:
    out = []
    for r in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,),
    ):
        for ln in str(r[1] or "").splitlines():
            if ln.strip():
                out.append((int(r[0]), ln))
    return out


def _spans(line: str, numbers: set[str]) -> list[tuple[int, int, str]]:
    """(start, end, normalised number) of every listed number in a line, in order, each place once."""
    spans = []
    for n in sorted(numbers, key=len, reverse=True):
        pattern = r"[\s_/.\-]*".join(re.escape(part) for part in n.split("-"))
        for m in re.finditer(pattern, line, re.I):
            if not any(m.start() < e and s < m.end() for s, e, _n in spans):
                spans.append((m.start(), m.end(), n))
    return sorted(spans)


def listed(
    lines: list[tuple[int, str]], held: Mapping[str, dict], own_number: str
) -> list[dict]:
    """One entry per listed number, in the order first seen: {number, page, revision (stated or '')}. The transmittal's own number
    is not a listed document. A revision is read from the same line, after the number and before the next number."""
    seen: dict[str, dict] = {}
    for page, line in lines:
        shaped = {
            norm(m.group(0))
            for m in _NUMBER.finditer(line)
            if any(ch.isdigit() for ch in m.group(0))
        }
        in_text = {
            n
            for n in held
            if n and re.search(re.escape(n).replace("-", r"[\s_/.\-]*"), line, re.I)
        }
        spans = _spans(line, shaped | in_text)
        for i, (_s, end, number) in enumerate(spans):
            if number == own_number or number in seen:
                continue
            stop = spans[i + 1][0] if i + 1 < len(spans) else len(line)
            rev = _REV.search(line[end:stop])
            seen[number] = {
                "number": number,
                "page": page,
                "revision": norm_rev(rev.group(1)) if rev else "",
            }
    return list(seen.values())


def _status(entry: Mapping, held: Mapping | None) -> tuple[str, str]:
    """(Status, plain reason) by code."""
    if held is None:
        return QUERY, "not in the library for this reader"
    stated, have = entry["revision"], held["revision"]
    if not stated:
        return QUERY, "the transmittal states no revision"
    if not have:
        return QUERY, "the library holds no revision for it"
    return (PASS, "revision equal") if stated == have else (FAIL, "revision differs")


def check(conn: sqlite3.Connection, document_id: str, allowed: frozenset[str]) -> dict:
    """{'rows': [...], 'counts': {...}, 'boundary': words}: the listed documents against the documents `allowed` holds."""
    held = _held(conn, allowed, document_id)
    own = conn.execute(
        "SELECT document_number FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    entries = listed(_lines(conn, document_id), held, norm(own[0] if own else ""))
    rows = []
    for e in entries:
        h = held.get(e["number"])
        status, why = _status(e, h)
        rows.append(
            {
                "number": e["number"], "page": e["page"], "revision_stated": e["revision"] or None,
                "revision_held": (h or {}).get("revision") or None, "held_document_id": (h or {}).get("document_id"),
                "status": status, "reason": why,
            }
        )  # fmt: skip
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (PASS, FAIL, QUERY)}
    return {
        "document_id": document_id,
        "rows": rows,
        "counts": {**counts, "listed": len(rows)},
        "boundary": f"counted against the {len(held)} documents with a stored number that this reader may read",
    }


def _comment(r: Mapping) -> str:
    """Three parts: what is required, what the transmittal shows (numbers and revisions, as stored), what the contractor must do."""
    req = "A transmittal must list only documents that are held, at the revision it states."
    stated = (
        f"revision {r['revision_stated']}" if r["revision_stated"] else "no revision"
    )
    shows = f"The transmittal lists {r['number']} with {stated}, page {r['page']}. "
    if r["status"] == QUERY and r["held_document_id"] is None:
        shows += "No document with that number is held for this reader."
        todo = f"Contractor to confirm {r['number']} was submitted, or send it."
    else:
        have = f"revision {r['revision_held']}" if r["revision_held"] else "no revision"
        shows += f"The library holds it at {have}."
        todo = {
            PASS: "No action.",
            FAIL: f"Contractor to correct the revision of {r['number']} on the transmittal, or send the revision it states.",
        }.get(r["status"], f"Contractor to confirm the revision of {r['number']}.")
    return "\n".join((req, shows, todo))


def build_xlsx(result: Mapping, paper: str) -> bytes:
    """The list as a CRS-style workbook through the one layout (`crs_layout`): nine company columns and Status."""
    rows = []
    for n, r in enumerate(result["rows"], start=1):
        rows.append([_cell(v) for v in (n, paper, f"p.{r['page']}", _comment(r), BY, None, None, r["number"],
                                        words.priority(r["status"], {}) or None, r["status"])])  # fmt: skip
    view = {
        "title": crs_export.default_company(),
        "header": [
            ("Review:", "Transmittal completeness"),
            ("Counted:", result["boundary"]),
        ],
        "sentence": CODE_COLUMNS_NOTE,
        "rows": rows,
        "statuses": [r["status"] for r in result["rows"]],
    }
    return crs_layout.build_layout_crs(view)
