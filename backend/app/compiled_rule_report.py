"""#1584: what a standard's pages hold, and version 1 beside version 2. Reads only; counts only, never document text.

`side_by_side` puts both versions through the SAME quote check, and says for version 2 how its run ended and what the
proof dropped, so a partial version 2 cannot read as a weaker one beside a full version 1. Version 1 has no model
column: "not recorded", never a guess. Version 2 rows are held, not in use.
"""

from __future__ import annotations

import json
from collections import Counter

from .compiled_rule_proof import quote_verified
from .converter_gates import fold as _fold

NOT_RECORDED = "not recorded"
NOT_COMPILED = "not compiled"
BOUNDARY = "active rows of the standards named in this report, this database copy only"


def rule_documents(conn, documents: list[str]) -> dict[str, str]:
    """{compiled rule id: its standard document} for `documents`, for `run_record`'s tick counts. Reads only."""
    if not documents:
        return {}
    marks = ",".join("?" for _ in documents)
    rows = conn.execute(
        f"SELECT id, standard_document_id FROM compiled_rules WHERE standard_document_id IN ({marks})",
        documents,
    )
    return {r[0]: r[1] for r in rows}


def run_book(conn, review_run_id: str) -> tuple[int, str | None] | None:
    """The rulebook's own record of a run (`rulebook_v2.run_used`)."""
    from . import rulebook_v2

    return rulebook_v2.run_used(conn, review_run_id)


def decisions_on(conn, documents: list[str]) -> list[tuple[str, str, str]]:
    """The rulebook's decisions on rules read in `documents` (`rulebook_v2.decisions_on`)."""
    from . import rulebook_v2

    return rulebook_v2.decisions_on(conn, documents)


def _page_rows(conn, document_id: str) -> list:
    """The app's one way to read a document's pages, the text it chunks and cites: recognised text over the text
    layer (`chunker._load_pages`). So a scanned standard is read here, and quotes are verified, as it is cited."""
    from .chunker import _load_pages

    return _load_pages(conn, document_id)[2]


def pages_of(conn, document_id: str) -> dict[int, str]:
    """The standard's page text as the app cites it."""
    return {r["page_no"]: r["text"] or "" for r in _page_rows(conn, document_id)}


def page_origin(conn, document_id: str) -> dict[int, dict]:
    """{page with text: where its text came from}. The confidence is OCR's own, on a recognised page only."""
    return {
        r["page_no"]: {
            "page_source": "recognised" if r["recognised"] else "native",
            "page_min_conf": r["min_conf"] if r["recognised"] else None,
        }
        for r in _page_rows(conn, document_id)
        if (r["text"] or "").strip()
    }


def page_coverage(conn, document_id: str) -> dict:
    """Pages read natively, from OCR and not at all, with their numbers. A confidence only when one is stored."""
    pages, origin = pages_of(conn, document_id), page_origin(conn, document_id)
    from_ocr = [o for o in origin.values() if o["page_source"] == "recognised"]
    known = [o["page_min_conf"] for o in from_ocr if o["page_min_conf"] is not None]
    out = {
        "pages_total": len(pages),
        "pages_native": len(origin) - len(from_ocr),
        "pages_from_ocr": len(from_ocr),
        "pages_no_text": sorted(set(pages) - set(origin)),
    }
    if known:
        out |= {
            "ocr_lowest_confidence": min(known),
            "ocr_pages_with_confidence": len(known),
        }
    return out


def page_table_texts(conn, document_id: str) -> dict[int, set[str]]:
    """{page: the folded words of each row the table reader recorded}. Native pages only: a recognised page has no
    table record, so a row on one cannot be told from a sentence."""
    from .chunker import _load_pages

    _pages, raw, rows = _load_pages(conn, document_id)
    text_of = {r["page_no"]: (r["text"] or "").split("\n") for r in rows}
    out: dict[int, set[str]] = {}
    for page, record in raw.items():
        try:
            tables = json.loads(record).get("tables") or []
        except (ValueError, AttributeError):
            continue  # an unreadable record is no tables
        found = out.setdefault(page, set())
        for table in tables:
            lines = text_of.get(page, [])
            found |= {
                _fold(lines[i]) for i in table.get("lines", []) if 0 <= i < len(lines)
            }
            found |= {
                _fold(" ".join(c or "" for c in row)) for row in table.get("rows", [])
            }
    return out


def _has_table(conn, name: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return found is not None


def _v1_row(conn, document_id: str, pages: dict[int, str]) -> dict:
    rows = conn.execute(
        "SELECT field, operator, value, unit, source_text, page, extractor_version FROM standard_requirements"
        " WHERE standard_document_id = ? AND superseded_at IS NULL",
        (document_id,),
    ).fetchall()
    return {
        "rules": len(rows),
        "usable_numeric_limits": sum(
            1
            for r in rows
            if r["field"] and r["operator"] and r["value"] is not None and r["unit"]
        ),
        "verified_quotes": sum(
            1 for r in rows if quote_verified(r["source_text"], pages.get(r["page"]))
        ),
        "extractor_versions": dict(
            sorted(
                Counter(r["extractor_version"] or NOT_RECORDED for r in rows).items()
            )
        ),
        "models": {NOT_RECORDED: len(rows)},
    }


def _latest_run(conn, document_id: str) -> tuple[str, dict, str | None]:
    if not _has_table(conn, "compile_runs"):
        return NOT_COMPILED, {}, None
    found = conn.execute(
        "SELECT id, status, counts_json FROM compile_runs WHERE standard_document_id = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    if found is None:
        return NOT_COMPILED, {}, None
    return (
        found["status"] or NOT_RECORDED,
        json.loads(found["counts_json"] or "{}"),
        found["id"],
    )


def latest_compile(conn, document_id: str) -> dict | None:
    """The newest compile of this standard: its id, name, prompt version, how it ended and its counts. None if none."""
    status, counts, run_id = _latest_run(conn, document_id)
    if run_id is None:
        return None
    row = conn.execute(
        "SELECT standard, prompt_version FROM compile_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return {
        "id": run_id,
        "status": status,
        "counts": counts,
        "standard": row["standard"],
        "prompt_version": row["prompt_version"],
    }


def compiled_rows(conn, run_id: str) -> list:
    """One compile's rows, in reading order. Rulebook version 2 reads them through here (`rulebook_v2_ingest`)."""
    return conn.execute(
        "SELECT * FROM compiled_rules WHERE run_id = ? ORDER BY page, quote_start, id",
        (run_id,),
    ).fetchall()


def _v2_row(conn, document_id: str, pages: dict[int, str]) -> dict:
    """The latest compile only: an older prompt version's rules stay stored and are not added to it."""
    status, counts, run_id = _latest_run(conn, document_id)
    rows = []
    if run_id is not None:
        rows = conn.execute(
            "SELECT field, comparator, limit_value, unit, quote, page, model, prompt_version, batch_id, status"
            " FROM compiled_rules WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    return {
        "run_status": status,
        "run_statuses": {status: 1},
        "proposed": int(counts.get("proposed") or 0),
        "dropped": counts.get("dropped") or {},
        "dropped_table_rows": counts.get("dropped_table_rows") or {},
        "kept_with_context_flag": counts.get("kept_with_context_flag") or {},
        "pages_not_read": len(counts.get("pages_not_read") or []),
        "rules": len(rows),
        "usable_numeric_limits": sum(
            1
            for r in rows
            if r["field"]
            and r["comparator"]
            and r["limit_value"] is not None
            and r["unit"]
        ),
        "verified_quotes": sum(
            1 for r in rows if quote_verified(r["quote"], pages.get(r["page"]))
        ),
        "models": dict(sorted(Counter(r["model"] for r in rows).items())),
        "prompt_versions": dict(
            sorted(Counter(r["prompt_version"] for r in rows).items())
        ),
        "batch_ids": sorted({r["batch_id"] for r in rows if r["batch_id"]}),
        "by_status": dict(sorted(Counter(r["status"] for r in rows).items())),
    }


def _add(total: dict, part: dict) -> None:
    for key, value in part.items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value
        elif isinstance(value, dict):
            into = total.setdefault(key, {})
            for name, count in value.items():
                into[name] = into.get(name, 0) + count
        elif isinstance(value, list):
            total[key] = sorted({*total.get(key, []), *value})


def side_by_side(conn, documents: dict[str, str]) -> dict:
    """Version 1 beside version 2, per standard and in total, counts only. Both versions go through the SAME quote
    check. Version 1 has no model column: "not recorded", never a guess. Version 2 rows are held, not in use."""
    from . import rulebook_v2_ingest

    out = {"boundary": BOUNDARY, "per_standard": [], "total": {"v1": {}, "v2": {}}}
    for document_id, label in sorted(documents.items(), key=lambda kv: kv[1]):
        pages = pages_of(conn, document_id)
        row = {
            "standard": label,
            "document_id": document_id,
            **page_coverage(conn, document_id),
            "v1": _v1_row(conn, document_id, pages),
            "v2": _v2_row(conn, document_id, pages),
        }
        rulebook = rulebook_v2_ingest.report_row(conn, document_id)
        if rulebook:  # switch off: this table is what it was
            row["rulebook_v2"] = rulebook
        out["per_standard"].append(row)
        _add(out["total"]["v1"], row["v1"])
        _add(out["total"]["v2"], row["v2"])
    return out
