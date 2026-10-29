"""The review X-ray (a tool, not part of the app): everything the system stored about one review, in pipeline order (order 219).

WHY. Pieces of this existed in six places (`scripts/fact_report.py`, the page
ledger, `review_trace`, the scope ledger, the traceability route, the CRS
preview). The owner wants ONE page that shows, for one review, what each stage
did, so a wrong answer can be traced to the stage that made it.

WHAT. `build(conn, run_id)` reads what the run STORED, with a READ-ONLY sqlite
connection, and returns nine sections in pipeline order, each
`{"id", "title", "note", "columns", "rows"}`. Where the system stored nothing
(an AI call has no run id; a stage that did not record) the section SAYS so
instead of guessing. `render_html(report)` turns the sections into one local
HTML page; every stored string is HTML-escaped, so a document's own words can
never run in the page. No network, no AI call, no write. The page lives under
`backend/data/debug/` (git-ignored) and holds document values: it stays on this
machine.
"""

from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path

#: Longest cell shown; the full text stays in the database.
CELL = 220
NOT_RECORDED = "not recorded"
#: the start of a held requirement's finding text (`held_findings.HELD_REASON`)
HELD_PREFIX = "Held, not compared with the datasheet"


def _short(value: object, limit: int = CELL) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _json(raw: object) -> dict:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.Error:  # a table this database never created
        return []


def _section(
    sid: str,
    title: str,
    note: str,
    columns: list[str],
    rows: list[list],
    *,
    counts: dict | None = None,
    fold: tuple[int, str] | None = None,
) -> dict:
    """`counts`: label -> rows, shown above the table. `fold`: (column, value) -
    rows with that value are shown in a closed <details> below the table."""
    return {
        "id": sid,
        "title": title,
        "note": note,
        "columns": columns,
        "rows": rows,
        "counts": counts or {},
        "fold": fold,
    }


def _run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    rows = _rows(
        conn,
        "SELECT r.*, d.filename FROM review_runs r"
        " LEFT JOIN documents d ON d.id = r.submittal_document_id WHERE r.id = ?",
        (run_id,),
    )
    return rows[0] if rows else None


def header(
    run: sqlite3.Row, outcome: dict, conn: sqlite3.Connection | None = None
) -> dict:
    split = outcome.get("requirement_split") or {}
    rows = [
        ["review run", run["id"]],
        ["datasheet", run["filename"]],
        ["status", run["status"]],
        ["model", run["model_name"] or NOT_RECORDED],
        ["started", run["started_at"] or NOT_RECORDED],
        ["completed", run["completed_at"] or NOT_RECORDED],
        ["config version", run["config_version"] or NOT_RECORDED],
    ]
    if conn is not None:
        # Order 309.2: the settings this run was queued with (the hash above says only that they differ).
        settings_rows = _rows(
            conn,
            "SELECT name, value FROM review_run_settings WHERE review_run_id = ? ORDER BY name",
            (run["id"],),
        )
        rows += [[f"setting: {r['name']}", r["value"]] for r in settings_rows]
        if not settings_rows:
            rows.append(
                ["settings", NOT_RECORDED + " (run queued before settings were kept)"]
            )
    if isinstance(split, dict):
        rows += [
            [f"requirements: {k}", _short(v, 80)]
            for k, v in split.items()
            if not isinstance(v, (dict, list))
        ]
    return _section(
        "run", "The review", "The run's own record.", ["item", "value"], rows
    )


def documents(conn: sqlite3.Connection, doc: str) -> dict:
    """1. Pages: text layer, OCR, index, facts, with the reason the ledger gives."""
    rows = []
    for p in _rows(
        conn,
        "SELECT p.page_no, p.char_count, p.needs_ocr, l.native_status, l.ocr_status, l.ocr_reason,"
        " l.ocr_engine, l.ocr_mean_conf, l.index_status, l.index_reason, l.facts_status,"
        " l.facts_count, l.facts_reason, l.vision_status, l.vision_reason,"
        " (l.document_id IS NOT NULL) AS in_ledger"
        " FROM pages p LEFT JOIN page_ledger l ON l.document_id = p.document_id"
        " AND l.page_no = p.page_no WHERE p.document_id = ? ORDER BY p.page_no",
        (doc,),
    ):
        if not p["in_ledger"]:
            rows.append([p["page_no"], p["char_count"], NOT_RECORDED, "", "", "", ""])
            continue
        ocr = " ".join(
            x
            for x in (
                p["ocr_status"],
                _short(p["ocr_reason"], 60),
                p["ocr_engine"] or "",
            )
            if x
        )
        conf = (
            f" (mean conf {p['ocr_mean_conf']:.2f})"
            if p["ocr_mean_conf"] is not None
            else ""
        )
        rows.append(
            [
                p["page_no"],
                p["char_count"],
                p["native_status"],
                ocr + conf,
                " ".join(
                    x for x in (p["index_status"], _short(p["index_reason"], 60)) if x
                ),
                f"{p['facts_status']} ({p['facts_count']})"
                + (f": {_short(p['facts_reason'], 80)}" if p["facts_reason"] else ""),
                " ".join(
                    x for x in (p["vision_status"], _short(p["vision_reason"], 60)) if x
                ),
            ]
        )
    return _section(
        "pages",
        "1. The document: pages",
        "Per page: text layer, OCR, the index, whether fields were read, and why not.",
        [
            "page",
            "chars",
            "text layer",
            "OCR",
            "index",
            "fields read",
            "picture reader",
        ],
        rows,
    )


def reader(conn: sqlite3.Connection, doc: str) -> list[dict]:
    """2. The datasheet reader: its run summary, then every current value."""
    out = []
    summary_rows = _rows(
        conn,
        "SELECT summary, read_at, extractor_version FROM datasheet_reader_runs WHERE document_id = ?",
        (doc,),
    )
    summary = _json(summary_rows[0]["summary"]) if summary_rows else {}
    rows = [
        [k, _short(json.dumps(v) if isinstance(v, (dict, list)) else v, 160)]
        for k, v in summary.items()
    ]
    if summary_rows:
        rows[:0] = [
            ["read at", summary_rows[0]["read_at"]],
            ["extractor version", summary_rows[0]["extractor_version"]],
        ]
    out.append(
        _section(
            "reader_run",
            "2a. The datasheet reader's run",
            "Which engine and model read the sheet, which pages it read, which fields it was asked for."
            if rows
            else "No reader summary is stored for this document.",
            ["item", "value"],
            rows,
        )
    )
    facts = []
    methods: dict[str, int] = {}
    for f in _rows(
        conn,
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL"
        " ORDER BY page, id",
        (doc,),
    ):
        methods[f["extraction_method"] or "?"] = (
            methods.get(f["extraction_method"] or "?", 0) + 1
        )
        facts.append(
            [
                f["page"],
                _short(f["field_label"] or f["field_name"], 60),
                "(blank)"
                if f["is_blank"]
                else _short(
                    f["raw_value"] if f["raw_value"] is not None else f["field_value"],
                    60,
                ),
                f["raw_unit"] or f["unit"] or "",
                _short(f["source_text"], 120),
                f["extraction_method"] or "",
                f["confidence"] if f["confidence"] is not None else "",
                f["validation_state"] or "",
                f["confirmed_by"] or "",
            ]
        )
    out.append(
        _section(
            "facts",
            "2b. Every value read (current)",
            "By method: "
            + (", ".join(f"{k} {v}" for k, v in sorted(methods.items())) or "none")
            + ". The quote is the sheet's own text the value was read from.",
            [
                "page",
                "field",
                "value",
                "unit",
                "quote",
                "reader",
                "confidence",
                "check",
                "confirmed by",
            ],
            facts,
        )
    )
    return out


def classification(conn: sqlite3.Connection, doc: str) -> dict:
    """3. Equipment type, title, discipline and the quotes behind them."""
    rows = []
    c = _rows(
        conn, "SELECT * FROM document_classification WHERE document_id = ?", (doc,)
    )
    if c:
        c = dict(c[0])
        ev = _json(c["equipment_type_evidence"])
        fields = _json(c["field_evidence"])
        rows.append(
            [
                "equipment type",
                c["equipment_type"] or "(none)",
                ev.get("quote", ""),
                ev.get("page", ""),
                ev.get("method", ""),
                ev.get("confidence", ""),
            ]
        )
        for name in (
            "title",
            "discipline",
            "document_number",
            "revision",
            "project",
            "service",
        ):
            e = fields.get(name) or {}
            rows.append(
                [
                    name,
                    c.get(name) or "(none)",
                    e.get("quote", ""),
                    e.get("page", ""),
                    e.get("method", ""),
                    e.get("confidence", ""),
                ]
            )
        rows.append(
            [
                "document role",
                c["document_role"] or "(none)",
                "",
                "",
                c["suggested_by"] or "",
                "confirmed by " + c["confirmed_by"]
                if c["confirmed_by"]
                else "not confirmed",
            ]
        )
    return _section(
        "classification",
        "3. Equipment type, title and discipline",
        "A guess is shown as a guess: 'not confirmed' means no engineer has confirmed it."
        if rows
        else "No classification is stored.",
        ["what", "value", "quote", "page", "how", "confidence"],
        [[_short(x, 120) for x in r] for r in rows],
    )


def standards(conn: sqlite3.Connection, run_id: str, outcome: dict) -> dict:
    """4. Every standard the review considered: chosen or dropped, and why."""
    rows = []
    for s in _rows(
        conn,
        "SELECT a.*, d.filename FROM review_applicable_standards a"
        " LEFT JOIN documents d ON d.id = a.standard_document_id WHERE a.review_run_id = ?"
        " ORDER BY a.included DESC, d.filename",
        (run_id,),
    ):
        rows.append(
            [
                s["filename"] or s["standard_document_id"],
                "chosen" if s["included"] else "dropped",
                s["selection_method"] or "",
                _short(s["selection_reason"], 100),
                _short(s["exclusion_reason"], 80) if not s["included"] else "",
                s["confidence"] if s["confidence"] is not None else "",
                f"p{s['evidence_page']}: {_short(s['evidence_quote'], 100)}"
                if s["evidence_quote"]
                else "",
                _short(
                    " ".join(x for x in (s["scope_decision"], s["held_reason"]) if x),
                    100,
                ),
            ]
        )
    missing = [
        m.get("identifier") if isinstance(m, dict) else m
        for m in (outcome.get("missing_references") or [])
    ]
    for m in missing:
        rows.append(
            [
                m,
                "NOT HELD",
                "cited by the datasheet",
                "no copy of this standard is in the library",
                "",
                "",
                "",
                "",
            ]
        )
    return _section(
        "standards",
        "4. Standards: chosen, dropped, and cited but not held",
        f"{len(missing)} standard(s) the datasheet cites are not in the library (listed last).",
        [
            "standard",
            "state",
            "route",
            "reason",
            "why dropped",
            "confidence",
            "evidence",
            "part-scope reading",
        ],
        rows,
    )


def coverage(conn: sqlite3.Connection, run_id: str, outcome: dict) -> dict:
    """5. Per chosen standard: how many requirements exist and where each went."""
    rows = []
    totals = {
        r["standard_document_id"]: r["n"]
        for r in _rows(
            conn,
            "SELECT standard_document_id, count(*) AS n FROM standard_requirements"
            " WHERE superseded_at IS NULL GROUP BY standard_document_id",
        )
    }
    for r in _rows(
        conn,
        "SELECT d.filename, q.standard_document_id AS sid, s.state, s.reason_code, count(*) AS n,"
        " min(s.reason) AS example FROM review_scope_decisions s"
        " JOIN standard_requirements q ON q.id = s.requirement_id"
        " LEFT JOIN documents d ON d.id = q.standard_document_id"
        " WHERE s.review_run_id = ? GROUP BY q.standard_document_id, s.state, s.reason_code"
        " ORDER BY d.filename, s.state, n DESC",
        (run_id,),
    ):
        rows.append(
            [
                r["filename"] or r["sid"],
                totals.get(r["sid"], ""),
                r["state"],
                r["reason_code"],
                r["n"],
                _short(r["example"], 120),
            ]
        )
    line = (
        (outcome.get("clause_coverage") or {}).get("line")
        if isinstance(outcome.get("clause_coverage"), dict)
        else None
    )
    return _section(
        "coverage",
        "5. Requirements per standard and how each was handled",
        (line + ". " if line else "")
        + "State: checked / applies, not checked / does not apply. "
        "The reason code says which gate (scope, citation, service, table, ...) decided.",
        [
            "standard",
            "requirements stored",
            "state",
            "gate / reason",
            "count",
            "an example reason",
        ],
        rows,
    )


def pairing(conn: sqlite3.Connection, run_id: str) -> dict:
    """6. Which sheet value each requirement was paired with, by what method."""
    rows = []
    for f in _rows(
        conn,
        "SELECT f.standard_clause, f.standard_page, f.requirement, f.matched_phrase, f.match_method, sd.filename AS sfile,"
        " sf.field_label, sf.field_name, sf.raw_value, sf.raw_unit, sf.page AS fpage FROM review_findings f"
        " LEFT JOIN submittal_facts sf ON sf.id = f.fact_id"
        " LEFT JOIN documents sd ON sd.id = f.standard_document_id WHERE f.review_run_id = ?"
        " ORDER BY f.standard_document_id, f.standard_clause",
        (run_id,),
    ):
        rows.append(
            [
                f["standard_clause"] or "",
                _short(f["requirement"], 100),
                _short(f["field_label"] or f["field_name"] or "(no field paired)", 50),
                _short(f"{f['raw_value'] or ''} {f['raw_unit'] or ''}".strip(), 40),
                f["fpage"] if f["fpage"] is not None else "",
                f["match_method"] or "",
                _short(f["matched_phrase"], 50),
            ]
        )
    rejected = _rows(
        conn,
        "SELECT requirement_id, fact_id, rejected_by, rejected_at, reason FROM review_pair_rejections"
        " WHERE requirement_id IN (SELECT requirement_id FROM review_findings WHERE review_run_id = ?)",
        (run_id,),
    )
    for r in rejected:
        rows.append(
            [
                "",
                "(pairing rejected by an engineer)",
                r["fact_id"] or "",
                "",
                "",
                "rejected",
                _short(r["reason"], 60),
            ]
        )
    return _section(
        "pairing",
        "6. Pairing: requirement to sheet field",
        "Method says how the pair was made (name, containment, field name by a model, a question to the model). "
        f"{len(rejected)} pairing(s) rejected by an engineer.",
        [
            "clause",
            "requirement",
            "sheet field",
            "value",
            "page",
            "method",
            "matched phrase",
        ],
        rows,
    )


def comparison(conn: sqlite3.Connection, run_id: str) -> dict:
    """7. Required against offered, and the rule that decided."""
    rows = []
    held: dict[tuple[str, str], list[str]] = {}
    counts: dict[str, int] = {}
    for f in _rows(
        conn,
        "SELECT f.standard_clause, sd.filename AS sfile, f.compliance_status, f.reason_code, f.ai_rationale, f.contractor_evidence_text,"
        " f.requirement, q.operator, q.value, q.unit, q.raw_value, q.raw_unit, q.condition,"
        " sf.normalized_value, sf.normalized_unit FROM review_findings f"
        " LEFT JOIN standard_requirements q ON q.id = f.requirement_id"
        " LEFT JOIN submittal_facts sf ON sf.id = f.fact_id"
        " LEFT JOIN documents sd ON sd.id = f.standard_document_id WHERE f.review_run_id = ?"
        " ORDER BY f.compliance_status, f.standard_clause",
        (run_id,),
    ):
        counts[f["compliance_status"]] = counts.get(f["compliance_status"], 0) + 1
        why = f["ai_rationale"] or ""
        if why.startswith(HELD_PREFIX):
            reason = why[len(HELD_PREFIX) :].split(". An engineer")[0].lstrip(": ")
            held.setdefault((f["sfile"] or "", reason), []).append(
                f["standard_clause"] or ""
            )
            continue
        required = " ".join(
            str(x)
            for x in (
                f["operator"],
                f["raw_value"] if f["raw_value"] is not None else f["value"],
                f["raw_unit"] or f["unit"],
            )
            if x not in (None, "")
        )
        offered = _short(f["contractor_evidence_text"], 40)
        conv = ""
        if f["normalized_value"] is not None:
            conv = f"{f['normalized_value']:g} {f['normalized_unit'] or ''}".strip()
        rows.append(
            [
                f["standard_clause"] or "",
                f["compliance_status"],
                required or "(no number)",
                offered,
                conv,
                _short(f["condition"], 40),
                f["reason_code"] or "",
                _short(f["ai_rationale"], 200),
            ]
        )
    held_rows = [
        [
            sfile,
            reason,
            len(cl),
            ", ".join(c for c in cl[:8] if c) + (" ..." if len(cl) > 8 else ""),
        ]
        for (sfile, reason), cl in sorted(held.items(), key=lambda kv: -len(kv[1]))
    ]
    return [_comparison_section(rows, counts), _held_section(held_rows)]


def _held_section(rows: list[list]) -> dict:
    return _section(
        "held",
        "7b. Held requirements, by standard and reason",
        "Requirements that apply but were NOT compared with the datasheet (an engineer decides). Grouped; the full list is in the run's scope ledger.",
        ["standard", "reason held", "requirements", "first clauses"],
        rows,
    )


def _comparison_section(rows: list[list], counts: dict) -> dict:
    return _section(
        "comparison",
        "7. Comparison: required, offered, verdict and the rule",
        "Counts per verdict first (held requirements are in 7b, but counted here). 'Offered, converted' shows the unit conversion the arithmetic used. "
        "Rows 'not in document scope' are folded below the table.",
        [
            "clause",
            "verdict",
            "required",
            "offered",
            "offered, converted",
            "condition",
            "reason code",
            "why",
        ],
        rows,
        counts=dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        fold=(1, "NOT_IN_DOCUMENT_SCOPE"),
    )


def crs(db_path: Path, run_id: str) -> dict:
    """8. The comment sheet rows as the contractor copy builds them, from a COPY
    of the database (the builders open the app's own connection and may write
    schema); if that cannot be done the section says so."""
    import shutil
    import tempfile

    note = "As the review screen builds them (the same code). Built from a temporary copy; the original is untouched."
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "xray.sqlite"
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(db_path) + suffix)
                if src.exists():
                    shutil.copy2(src, str(target) + suffix)
            from app import access, db, main
            from app.config import settings

            old = (settings.db_path, settings.data_dir)
            settings.db_path, settings.data_dir = target, Path(tmp)
            db.reset_connection()
            try:
                ids = frozenset(
                    r["id"] for r in db.connect().execute("SELECT id FROM documents")
                )
                scope = access.AccessScope(user_id="xray", allowed_document_ids=ids)
                rows, *_ = main._crs_content(run_id, scope)
            finally:
                db.reset_connection()
                settings.db_path, settings.data_dir = old
    except Exception as exc:  # noqa: BLE001 - the page still shows the other eight sections
        return _section(
            "crs",
            "8. The comment sheet",
            f"Not built here ({type(exc).__name__}).",
            ["row"],
            [],
        )
    return _section(
        "crs",
        "8. The comment sheet (contractor rows)",
        note,
        [
            "no.",
            "kind",
            "priority",
            "page / section",
            "comment",
            "standard",
            "confirmed",
        ],
        [
            [
                r.get("crs_ref") or i,
                r.get("row_kind") or "",
                r.get("priority_label") or r.get("priority") or "",
                _short(r.get("page_section"), 60),
                _short(r.get("comment"), 300),
                _short(r.get("standard_reference"), 60),
                "yes" if r.get("engineer_confirmed") else "no",
            ]
            for i, r in enumerate(rows, 1)
        ],
    )


def ai_calls(conn: sqlite3.Connection, run_id: str) -> dict:
    """9. The run's step timings and the cached AI answers in this database."""
    rows = []
    trace = _rows(
        conn, "SELECT trace FROM review_run_traces WHERE review_run_id = ?", (run_id,)
    )
    for step in (_json(trace[0]["trace"]).get("steps") or []) if trace else []:
        rows.append(
            [
                "step",
                step.get("step", ""),
                step.get("status", ""),
                _short(step.get("summary") or step.get("line") or "", 140),
                step.get("seconds", ""),
            ]
        )
    cached = _rows(
        conn,
        "SELECT task, model, count(*) AS n FROM ai_task_cache GROUP BY task, model ORDER BY n DESC",
    )
    for c in cached:
        rows.append(
            [
                "cached answers (whole database)",
                c["task"],
                c["model"],
                f"{c['n']} answer(s)",
                "",
            ]
        )
    uses = _rows(
        conn,
        "SELECT task, model, SUM(reused) AS reused, SUM(fresh) AS fresh FROM review_run_cache_uses"
        " WHERE review_run_id = ? GROUP BY task, model ORDER BY task, model",
        (run_id,),
    )
    for u in uses:
        rows.append(
            [
                "cached answers (this run)",
                u["task"],
                u["model"],
                f"{u['reused']} reused, {u['fresh']} asked fresh and kept",
                "",
            ]
        )
    if not uses:
        rows.append(["cached answers (this run)", NOT_RECORDED, "", "", ""])
    return _section(
        "ai",
        "9. Steps and AI answers",
        "'whole database' rows count every stored answer, not only this review's. 'this run' rows count the stored "
        "answers this run reused and the ones it asked fresh and kept (order 309.2); a call that was not cacheable is "
        "not recorded there. Steps are from the run's stored trace.",
        ["kind", "name", "status / model", "what", "seconds"],
        rows,
    )


def build(db_path: Path | str, run_id: str) -> dict:
    """The nine sections for `run_id`, read from `db_path` read-only."""
    path = Path(db_path)
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        run = _run(conn, run_id)
        if run is None:
            raise LookupError(f"no review run {run_id!r} in this database")
        outcome = _json(run["outcome_json"])
        doc = run["submittal_document_id"]
        sections = [
            header(run, outcome, conn),
            documents(conn, doc),
            *reader(conn, doc),
            classification(conn, doc),
            standards(conn, run_id, outcome),
            coverage(conn, run_id, outcome),
            pairing(conn, run_id),
            *comparison(conn, run_id),
        ]
        sections.append(crs(path, run_id))
        sections.append(ai_calls(conn, run_id))
    finally:
        conn.close()
    return {"run_id": run_id, "sections": sections}


_CSS = (
    "body{font:14px/1.4 system-ui,sans-serif;margin:24px;max-width:1500px}h1{font-size:20px}"
    "h2{font-size:16px;margin:28px 0 4px}p.note{color:#555;margin:2px 0 8px}"
    "table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #ccc;padding:3px 6px;"
    "text-align:left;vertical-align:top}th{background:#f2f2f2}tr:nth-child(even){background:#fafafa}"
    "nav a{margin-right:10px}.empty{color:#888}.counts{margin:4px 0}input.filter{margin:4px 0;width:260px}"
)


_JS = (
    "document.querySelectorAll('input.filter').forEach(function(box){"
    "box.addEventListener('input',function(){var q=box.value.toLowerCase();"
    "var n=box.nextElementSibling;var t=n&&n.tagName=='TABLE'?n:null;if(!t)return;"
    "t.querySelectorAll('tr').forEach(function(r,i){if(i==0)return;"
    "r.style.display=r.textContent.toLowerCase().indexOf(q)<0?'none':'';});});});"
)


def _table(columns: list[str], rows: list[list]) -> str:
    esc = html.escape
    return (
        "<table><tr>"
        + "".join(f"<th>{esc(c)}</th>" for c in columns)
        + "</tr>"
        + "".join(
            "<tr>" + "".join(f"<td>{esc(str(v))}</td>" for v in row) + "</tr>"
            for row in rows
        )
        + "</table>"
    )


def render_html(report: dict) -> str:
    """One HTML page; every stored string is escaped."""
    esc = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>Review X-ray {esc(report['run_id'])}</title><style>{_CSS}</style></head><body>",
        f"<h1>Review X-ray: {esc(report['run_id'])}</h1>",
        "<p class='note'>Read-only view of what this review stored. Contains document values: keep it on this machine.</p>",
        "<nav>"
        + "".join(
            f"<a href='#{esc(s['id'])}'>{esc(s['title'])}</a>"
            for s in report["sections"]
        )
        + "</nav>",
    ]
    for s in report["sections"]:
        parts.append(
            f"<h2 id='{esc(s['id'])}'>{esc(s['title'])} <small>({len(s['rows'])})</small></h2>"
        )
        parts.append(f"<p class='note'>{esc(s['note'])}</p>")
        if s.get("counts"):
            parts.append(
                "<p class='counts'>"
                + " &middot; ".join(
                    f"<b>{esc(str(k))}</b> {esc(str(n))}"
                    for k, n in s["counts"].items()
                )
                + "</p>"
            )
        if not s["rows"]:
            parts.append("<p class='empty'>nothing stored</p>")
            continue
        fold = s.get("fold")
        shown = [r for r in s["rows"] if not fold or r[fold[0]] != fold[1]]
        folded = [r for r in s["rows"] if fold and r[fold[0]] == fold[1]]
        parts.append(
            "<input class='filter' placeholder='filter rows' aria-label='filter rows'>"
        )
        parts.append(_table(s["columns"], shown))
        if folded:
            parts.append(
                f"<details><summary>{len(folded)} row(s) {esc(str(fold[1]))}</summary>"
                + _table(s["columns"], folded)
                + "</details>"
            )
    parts.append(f"<script>{_JS}</script></body></html>")
    return "".join(parts)
