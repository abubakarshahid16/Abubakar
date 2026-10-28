"""The board's data for the STANDARDS library (order 274.6, Tab 3 Standards).

    python scripts/board_standards_export.py --db <copy of the database> --out <folder> \\
        [--converter-dir <folder of the converter's drafts>]

READ-ONLY on a COPY (a live-shaped path is refused), no AI call, no network call. It writes four kinds of data
file into `--out` (the mirror's folder), each a script the board loads by relative path (a page opened from
disk cannot fetch JSON):

  * `library.js`  - one row per company standard: how many rules it holds by type, how many pages and how many
                    were read by OCR, and what the converter's drafts say about it;
  * `rules-<document id>.js` - every rule of ONE standard (clause, page, type, text) beside what the converter
                    made of it: a verified check, a "no check", unproven with the reason, or not asked;
  * `converter.js` - one row per converter draft file (lane, model, prompt version, how the run ended);
  * `missing.js`  - standards a sheet cites that the library does not hold, by sheet.

EVERY NUMBER carries `source_file` and `source_path`: a number with no file behind it is not written. A draft is
shown as a draft: "unproven" stays "engineer, please look" and never shows a limit; a rule the converter did not
reach is "not asked: <why>", not a failure. Every count states whose rows it counts (the copy named in `--db`,
rules not superseded).

The files hold clause text and stay on this machine: `--out` must be outside the repository. A file that already
exists is never overwritten. Output of the command itself: counts only.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

#: The converter's own words for a row (`standards_converter`), and the colour the board gives each.
COLOUR = {
    "verified": "green",
    "unproven": "amber",
    "no_check": "grey",
    "not_applicable": "grey",  # a v1 file's "no": shown, never counted as a check
    "not_asked": "grey",
}
RECOMMENDATION = "recommendation"


def _number(label: str, value: object, source_file: str, source_path: str) -> dict:
    """A number never travels alone: the file and the place in it that it came from."""
    return {
        "label": label,
        "value": value,
        "source_file": source_file,
        "source_path": source_path,
    }


def _script(path: str, payload: object) -> str:
    data = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    return (
        "// Saved once by scripts/board_standards_export.py. Holds clause text: this machine only.\n"
        "window.BOARD = window.BOARD || {};\n"
        f"{path} = {data};\n"
    )


def refuse_out(out_dir: Path) -> Path:
    resolved = Path(out_dir).expanduser().resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise ValueError(
            f"refusing: {resolved} is inside the repository; the board's files belong in the mirror"
        )
    return resolved


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "standard"


# ------------------------------------------------------------------------------------ the converter's drafts


def read_drafts(folder: Path | None) -> list[dict]:
    """The converter's draft files in `folder` (JSON only), each as {file, header, entries}. A file that is not
    a converter draft is left out; one that cannot be read is listed as unreadable (never silently dropped)."""
    if folder is None:
        return []
    out = []
    for path in sorted(Path(folder).expanduser().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append({"file": path.name, "unreadable": True})
            continue
        if not isinstance(data, dict) or data.get("converter") is not True:
            continue
        header = {
            k: data.get(k)
            for k in (
                "equipment_type",
                "standard",
                "lane",
                "model",
                "prompt_version",
                "run",
                "usd_spent",
                "calls",
                "counts",
                "status",
            )
        }
        header["form_sha"] = (data.get("form_source") or {}).get("sha")
        out.append(
            {
                "file": path.name,
                "header": header,
                "entries": [e for e in data.get("entries", []) if isinstance(e, dict)],
            }
        )
    return out


def _draft_for(label: str, drafts: list[dict]) -> list[dict]:
    from app import standard_ids

    return [
        d
        for d in drafts
        if not d.get("unreadable")
        and standard_ids.same_standard(d["header"].get("standard") or "", label)
    ]


def _converter_view(entry: dict, header: dict, file: str) -> dict:
    status = entry.get("status")
    view = {
        "status": status,
        "colour": COLOUR.get(status, "grey"),
        "reason": entry.get("reason"),
        "lane": header.get("lane"),
        "model": header.get("model"),
        "prompt_version": header.get("prompt_version"),
        "source_file": file,
    }
    if status == "verified":  # only a verified row shows a check
        for k in ("field", "comparator", "limit", "unit", "condition", "quote"):
            view[k] = entry.get(k)
    elif status == "unproven":
        view["note"] = "engineer, please look"  # never a limit, never a verdict
    return view


# ------------------------------------------------------------------------------------------- the library


def _have(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _standards(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    extra = [
        f"c.{col} AS {col}"
        for col in ("standard_family", "licence_status", "superseded_by")
        if _have(conn, "document_classification", col)
    ]
    cols = ", ".join(
        ["d.id", "d.filename", "d.page_count", "c.document_number", *extra]
    )
    return conn.execute(
        f"SELECT {cols} FROM documents d JOIN document_classification c ON c.document_id = d.id"
        " WHERE c.document_role = 'COMPANY_STANDARD' ORDER BY d.id"
    ).fetchall()


def _rules(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, clause, page, requirement_type, requirement_text FROM standard_requirements"
        " WHERE standard_document_id = ? AND superseded_at IS NULL ORDER BY page IS NULL, page, rowid",
        (document_id,),
    ).fetchall()


def _ocr_pages(conn: sqlite3.Connection, document_id: str) -> int | None:
    """Pages marked for recognition, or None when the table has no such column (nothing is guessed)."""
    if not _have(conn, "pages", "needs_ocr"):
        return None
    return conn.execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ? AND needs_ocr = 1",
        (document_id,),
    ).fetchone()[0]


def _optional(row: sqlite3.Row, key: str):
    return row[key] if key in set(row.keys()) else None


def build(
    conn: sqlite3.Connection, db_name: str, drafts: list[dict]
) -> tuple[dict, dict]:
    """(library payload, {document id: rules payload}). Pure on its inputs."""
    from app import rule_roles

    library_rows: list[dict] = []
    rules_by_doc: dict[str, dict] = {}
    boundary = (
        f"the library copy named {db_name}: company standards, rules not superseded; "
        "converter rows from the draft files in the folder given, matched by the sentence's text hash"
    )
    for std in _standards(conn):
        label = std["document_number"] or std["filename"]
        matched = _draft_for(label, drafts)
        by_hash: dict[str, tuple[dict, dict, str]] = {}
        for d in matched:
            for e in d["entries"]:
                if e.get("text_sha256"):
                    by_hash.setdefault(e["text_sha256"], (e, d["header"], d["file"]))
        rules, by_type, by_status = [], {}, {}
        recommendations_answered = 0
        for r in _rules(conn, std["id"]):
            kind = r["requirement_type"] or "untyped"
            by_type[kind] = by_type.get(kind, 0) + 1
            hit = by_hash.get(rule_roles.text_hash(r["requirement_text"]))
            if kind == RECOMMENDATION:
                # Advice is not a requirement: an answer the converter once gave to a "should" sentence is
                # never shown as a check and never counted as proved (order 294, #1429).
                recommendations_answered += 1 if hit else 0
                hit = None
            view = _converter_view(*hit) if hit else None
            if view:
                by_status[view["status"]] = by_status.get(view["status"], 0) + 1
            rules.append(
                {
                    "id": r["id"],
                    "clause": r["clause"],
                    "page": r["page"],
                    "type": kind,
                    "text": r["requirement_text"],
                    "converter": view,
                }
            )
        rules_file = f"rules-{_slug(std['id'])}.js"
        recommendations = by_type.get(RECOMMENDATION, 0)
        held = sum(by_type.values()) - recommendations
        library_rows.append(
            {
                "id": std["id"],
                "label": label,
                "family": _optional(std, "standard_family"),
                "licence_status": _optional(std, "licence_status"),
                "superseded": bool(_optional(std, "superseded_by")),
                "pages": std["page_count"],
                "pages_ocr": _ocr_pages(conn, std["id"]),
                "rules_by_type": by_type,
                "recommendations": recommendations,
                "recommendations_answered_by_converter_not_counted": recommendations_answered,
                "converter_draft_files": [d["file"] for d in matched],
                "converter_by_status": by_status,
                "rules_file": rules_file,
                "numbers": [
                    _number(
                        "rules held (without recommendations)",
                        held,
                        rules_file,
                        "count of rules where type is not recommendation",
                    ),
                    _number(
                        "recommendations held",
                        recommendations,
                        rules_file,
                        "count of rules where type is recommendation",
                    ),
                    *[
                        _number(
                            f"converter: {status}",
                            n,
                            rules_file,
                            f"count of rules where converter.status = {status}",
                        )
                        for status, n in sorted(by_status.items())
                    ],
                ],
            }
        )
        rules_by_doc[std["id"]] = {
            "standard": {"id": std["id"], "label": label},
            "boundary": boundary,
            "rules": rules,
        }
    library = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "boundary": boundary,
        "numbers": [
            _number(
                "standards held", len(library_rows), "library.js", "count of standards"
            ),
            _number(
                "rules held (without recommendations)",
                sum(
                    sum(n for k, n in r["rules_by_type"].items() if k != RECOMMENDATION)
                    for r in library_rows
                ),
                "library.js",
                "sum over standards of rules where type is not recommendation",
            ),
            _number(
                "rules the converter proved",
                sum(r["converter_by_status"].get("verified", 0) for r in library_rows),
                "library.js",
                "sum over standards of converter_by_status.verified",
            ),
        ],
        "standards": library_rows,
    }
    return library, rules_by_doc


def converter_rows(drafts: list[dict]) -> dict:
    rows = []
    for d in drafts:
        if d.get("unreadable"):
            rows.append({"file": d["file"], "readable": False})
            continue
        h = d["header"]
        rows.append(
            {
                "file": d["file"],
                "readable": True,
                "standard": h.get("standard"),
                "equipment_type": h.get("equipment_type"),
                "lane": h.get("lane"),
                "model": h.get("model"),
                "prompt_version": h.get("prompt_version"),
                "run": h.get("run"),
                "counts": h.get("counts"),
                "usd_spent": h.get("usd_spent"),
                "calls": h.get("calls"),
                "form_sha": h.get("form_sha"),
                "source_file": d["file"],
            }
        )
    return {"files": rows, "boundary": "the converter draft files in the folder given"}


def missing_by_sheet(cited: list[dict]) -> dict:
    """Group `standards_inventory.cited_but_not_held` rows by the SHEET (a contractor submittal) that cited
    them. A standard cited by a clause of another standard is listed apart, never as a sheet's gap."""
    sheets: dict[str, dict] = {}
    from_standards: list[dict] = []
    for row in cited:
        for where in row.get("cited_by", []):
            item = {
                "identifier": row["identifier"],
                "family": row.get("standard_family"),
                "licence_status": row.get("licence_status"),
            }
            if where.get("source_type") == "submittal":
                sheet = sheets.setdefault(
                    where["document_id"],
                    {
                        "document_id": where["document_id"],
                        "filename": where.get("filename"),
                        "missing": [],
                    },
                )
                if item not in sheet["missing"]:
                    sheet["missing"].append(item)
            else:
                from_standards.append({**item, "cited_in": where.get("document_id")})
    return {
        "boundary": "standards cited by a sheet or by a clause that the library copy does not hold",
        "by_sheet": sorted(sheets.values(), key=lambda s: s["document_id"]),
        "cited_by_other_standards": from_standards,
        "numbers": [
            _number(
                "sheets with a missing standard",
                len(sheets),
                "missing.js",
                "count of by_sheet",
            ),
            _number(
                "standards cited but not held",
                len({r["identifier"] for r in cited}),
                "missing.js",
                "count of distinct identifiers",
            ),
        ],
    }


def _cited(db_path: Path, ids: frozenset[str]) -> list[dict]:
    """`standards_inventory.cited_but_not_held` on the copy (the application's own matching rule)."""
    from app import standards_inventory
    from app.config import settings
    from app.db import connect

    settings.db_path = db_path
    connect()
    return standards_inventory.cited_but_not_held(allowed_document_ids=ids)


def export(
    db_path: Path, out_dir: Path, converter_dir: Path | None = None
) -> dict[str, int]:
    """Write the files; return counts only. Refuses a live path, a folder inside the repository and any
    existing file. The folder is made only when everything else is fine."""
    from rehearse_requirement_reextraction import refuse_live

    path = refuse_live(db_path)
    folder = refuse_out(out_dir)
    drafts = read_drafts(converter_dir)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        library, rules_by_doc = build(conn, Path(path).name, drafts)
        ids = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    finally:
        conn.close()
    missing = missing_by_sheet(_cited(path, ids))
    files = {
        "library.js": _script("window.BOARD.library", library),
        "converter.js": _script("window.BOARD.converter", converter_rows(drafts)),
        "missing.js": _script("window.BOARD.missing", missing),
    }
    for doc_id, payload in rules_by_doc.items():
        files[f"rules-{_slug(doc_id)}.js"] = _script(
            f"window.BOARD.rules = window.BOARD.rules || {{}};\nwindow.BOARD.rules[{json.dumps(doc_id)}]",
            payload,
        )
    existing = sorted(name for name in files if (folder / name).exists())
    if existing:
        raise ValueError(
            f"refusing to overwrite {len(existing)} saved file(s): {', '.join(existing[:5])}"
        )
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return {
        "standards": len(library["standards"]),
        "rules": sum(len(p["rules"]) for p in rules_by_doc.values()),
        "converter_files": len(drafts),
        "sheets_with_missing": len(missing["by_sheet"]),
        "files": len(files),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--converter-dir", type=Path)
    args = ap.parse_args(argv)
    try:
        counts = export(args.db, args.out, args.converter_dir)
    except ValueError as exc:
        print(json.dumps({"refused": str(exc)}, indent=1))
        return 2
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
