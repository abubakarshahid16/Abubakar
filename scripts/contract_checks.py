"""CONTRACT CHECKS CT-01 to CT-03 (order 14 lane E, 16 Nov 2026): what code can decide on a contract's own text. READ ONLY.

    python scripts/contract_checks.py --db <COPY or live db, opened ?mode=ro> --document <doc id> [--package <doc id> ...]
                                      [--lines <run id> --mapping <item-to-CT JSON>] [--json <report file>] [--show-text] [--complete]

The checks themselves live in the app (`app.contract_checks`, `run_all(pages, package)`; checklist
`backend/app/reference/contract_checks.json`, CT-01 to CT-08, AI DRAFT, ENGINEER TO CONFIRM). This command runs them on stored pages
read from a database opened read only, judges the CRS candidates with the shared gates G3, G4 and G5 (`gate_rows`), and compares
them with a stored run's lines (`against_stored`: no line is dropped, a contradiction is named). No model, no network, no write.
It prints ids, pages, labels and counts; paper text only with --show-text.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

from app.contract_checks import (  # noqa: E402  (the checks live in the app; this file is the command and the gate rows)
    CHECKLIST,
    CODES,
    CONSISTENT,
    ENGINEER,
    INCONSISTENT,
    RULE_STATE,
    Pages,
    Quote,
    Result,
    _finish,
    check_attachments,
    check_guarantees,
    check_stages,
    checklist,
    labels,
    package_part,
    parties,
    run_all,
)

BOOK = "contract checklist (AI draft)"
FIRM_RANK, QUESTION_RANK = (
    1,
    4,
)  # the app's rank scale (`review_points.RANKS`): 1 Not met proven by code, 4 Question

__all__ = [
    "CHECKLIST", "CODES", "CONSISTENT", "ENGINEER", "INCONSISTENT", "RULE_STATE", "Pages", "Quote", "Result", "_finish",
    "check_attachments", "check_guarantees", "check_stages", "checklist", "labels", "package_part", "parties", "run_all",
]  # fmt: skip


def _read_only(db: str) -> sqlite3.Connection:
    """The database opened read only; a copy whose journal files cannot be opened read only (no writer) is opened immutable."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return conn
    except sqlite3.OperationalError:
        conn.close()
        return sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)


def load_pages(db: str, document_id: str) -> Pages:
    """The stored page texts of one document, read only."""
    conn = _read_only(db)
    try:
        rows = conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        ).fetchall()
    finally:
        conn.close()
    return [(int(p), t or "") for p, t in rows]


# ------------------------------------------------------------------------------------------------ gate rows, stored lines


def gate_rows(results: list[Result]) -> list:
    """The CRS candidates as the shared gates read rows (`scripts/crs_gates.Row`), so G3, G4 and G5 judge them as they judge a CRS."""
    gates = _gates()
    rows = []
    for i, r in enumerate([r for r in results if r.is_row], 1):
        firm = r.outcome == INCONSISTENT
        rows.append(
            gates.Row(
                id=f"{r.ct}#{i}",
                cells=(r.ct, r.topic, r.value, r.message),
                field=f"{r.ct} {r.topic}",
                rank=FIRM_RANK if firm else QUESTION_RANK,
                paper_value=r.value,
                value_verified=bool(r.quotes) and all(q.verified for q in r.quotes),
                absence_proven=r.absence_proven,
                # a finding that something is missing is an absence (G5): it stands only on the proof that every page was read
                reason="absent"
                if r.value.startswith(("not present", "not held"))
                or " 0 found" in r.value
                else "",
                book=BOOK,
                clause=r.ct,
            )
        )
    return rows


def _gates():
    import importlib.util

    if "crs_gates" in sys.modules:
        return sys.modules["crs_gates"]
    spec = importlib.util.spec_from_file_location(
        "crs_gates", REPO / "scripts" / "crs_gates.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["crs_gates"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def judge_rows(results: list[Result]) -> dict:
    gates, rows = _gates(), gate_rows(results)
    return {
        r.gate: r.to_json()
        for r in (
            gates.g3_noise(rows),
            gates.g4_one_per_field(rows),
            gates.g5_firm(rows),
        )
    }


def stored_lines(db: str, run_id: str) -> list[dict]:
    """The decided lines of a stored run (id, part, page, class): read only, no text."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT item_id, part, page, verdict_class FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"item_id": i, "part": part, "page": page, "class": cls}
        for i, part, page, cls in rows
    ]


UNCHECKABLE = "unlabelled"


def against_stored(
    results: list[Result], lines: list[dict], mapping: dict[str, str]
) -> list[dict]:
    """Each stored line, its CT item and what code says of it. `mapping` = {item id: "CT-0n"} or "CT-0n|topic" (the code result's
    topic, for example "Appendix F"; "CT-02|unlabelled" for a reference code cannot read). A stored line reports a problem; code
    CONTRADICTS it only when its CT item is one code decides and every code result of that item (that topic, else on the line's
    page) says consistent. Code never removes a line."""
    decided = {"CT-01", "CT-02", "CT-03"}
    out = []
    for ln in lines:
        ct, _bar, topic = mapping.get(ln["item_id"], "").partition("|")
        if not ct or ln["class"] == "Not reviewed":
            out.append(
                {**ln, "ct": ct or "AI note, no rule book", "code": "kept, not mapped"}
            )
            continue
        if ct not in decided:
            out.append({**ln, "ct": ct, "code": "kept, code does not decide this item"})
            continue
        if topic == UNCHECKABLE:
            out.append(
                {
                    **ln,
                    "ct": ct,
                    "code": "kept, code cannot check this one (the reference has no label)",
                }
            )
            continue
        same = [
            r
            for r in results
            if r.ct == ct
            and (
                r.topic == topic
                if topic
                else ln["page"] is None or ln["page"] in {q.page for q in r.quotes}
            )
        ]
        if any(r.outcome != CONSISTENT for r in same):
            word = "agrees: code finds it too"
        elif same:
            word = "CONTRADICTED: code says consistent on this page"
        else:
            word = "kept, code finds nothing on this page (a reading finding)"
        out.append({**ln, "ct": ct, "code": word})
    return out


# ------------------------------------------------------------------------------------------------ command


def guarded_lines(
    db: str, run_id: str, pages: Pages, package: dict[str, Pages]
) -> list[dict]:
    """Each stored AI line of the run with what the guards say of its comment (`guard_comment`): ids and code words only,
    never the comment's text."""
    from app.contract_checks import guard_comment

    conn = _read_only(db)
    try:
        rows = conn.execute(
            "SELECT item_id, verdict_class, line_json FROM agent_review_line WHERE run_id = ? ORDER BY item_id",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for item, cls, raw in rows:
        text = (json.loads(raw or "{}").get("text") or "").strip()
        g = guard_comment(text, pages, package) if text else None
        out.append({"item_id": item, "class": cls, "guard": g})
    return out


def report(
    db: str,
    document: str,
    package_ids: list[str],
    show_text: bool = False,
    run_id: str | None = None,
    mapping: dict | None = None,
    complete: bool = False,
    guard_run: str | None = None,
) -> dict:
    pages = load_pages(db, document)
    package = {d: load_pages(db, d) for d in package_ids}
    results = run_all(pages, package, complete)
    out = {
        "document": document,
        "pages": len(pages),
        "package": package_ids,
        "complete": complete,
        "checklist": {
            "status": checklist()["status"],
            "approver": checklist()["approver"],
        },
        "counts": {
            f"{ct} {o}": sum(1 for r in results if r.ct == ct and r.outcome == o)
            for ct in ("CT-01", "CT-02", "CT-03")
            for o in (CONSISTENT, INCONSISTENT, ENGINEER)
        },
        "results": [r.to_json(show_text) for r in results],
        "gates": judge_rows(results),
    }
    if guard_run:
        out["guarded_lines"] = guarded_lines(db, guard_run, pages, package)
    if run_id:
        out["stored_lines"] = against_stored(
            results, stored_lines(db, run_id), mapping or {}
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--document", required=True)
    ap.add_argument("--package", nargs="*", default=[])
    ap.add_argument(
        "--lines",
        help="a stored run id: compare its decided lines with the code results",
    )
    ap.add_argument("--mapping", help="JSON {item id: CT id} for --lines")
    ap.add_argument("--json")
    ap.add_argument("--show-text", action="store_true")
    ap.add_argument(
        "--complete",
        action="store_true",
        help="the paper and the package are the WHOLE contract (only then is a missing part a finding)",
    )
    ap.add_argument(
        "--guard-run",
        help="a stored AI run on this paper: what the guards on AI comments say of each of its lines",
    )
    a = ap.parse_args(argv)
    mapping = (
        json.loads(Path(a.mapping).read_text(encoding="utf-8")) if a.mapping else {}
    )
    rep = report(
        a.db,
        a.document,
        a.package,
        a.show_text,
        a.lines,
        mapping,
        a.complete,
        a.guard_run,
    )
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for k, v in rep["counts"].items():
        if v:
            print(f"{k}: {v}")
    for r in rep["results"]:
        print(
            f"{r['ct']} [{r['outcome']}] {r['topic']}: {r['value']} (pages {r['pages']}, quotes verified {r['quotes_verified']})"
        )
    for g, res in rep["gates"].items():
        print(f"{g} {res['status']}: {res['note']}; failed {res['failed']}")
    for ln in rep.get("guarded_lines", []):
        g = ln["guard"]
        print(
            f"{ln['item_id']} [{ln['class']}] -> "
            + (f"{g['rule']}: {g['reason']}" if g else "untouched")
        )
    for ln in rep.get("stored_lines", []):
        print(f"{ln['item_id']} p{ln['page']} {ln['part']} -> {ln['ct']}: {ln['code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
