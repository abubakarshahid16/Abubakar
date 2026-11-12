"""Assemble ONE paper's list of points: the rule check's comments and the AI review's lines, their decisions, the counts and the
proposed review code (owner, 12 Nov 2026, the redesigned page). Reads only; the scope question is asked here once (rule 5)."""

from __future__ import annotations

import logging
from pathlib import Path

from . import (
    evidence_boxes,
    review_code_proposal,
)
from . import review as review_mod
from . import (
    review_point_decisions as decisions_mod,
)
from . import (
    review_points as rp,
)
from .db import connect

DONE = ("complete", "completed")


def runs_of_paper(conn, paper_id: str) -> tuple[str | None, str | None]:
    """(the paper's latest finished rule-check run, its latest finished AI review run), None where there is none."""
    marks = ",".join("?" for _ in DONE)
    base = (
        "SELECT r.id FROM review_runs r WHERE r.submittal_document_id = ? AND r.status IN ("
        + marks
        + ") {extra}"
        " ORDER BY r.started_at DESC LIMIT 1"
    )
    ai = None
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'agent_review_run'"
    ).fetchone():
        row = conn.execute(
            base.format(extra="AND r.id IN (SELECT run_id FROM agent_review_run)"),
            (paper_id, *DONE),
        ).fetchone()
        ai = row["id"] if row else None
        rc_row = conn.execute(
            base.format(extra="AND r.id NOT IN (SELECT run_id FROM agent_review_run)"),
            (paper_id, *DONE),
        ).fetchone()
    else:
        rc_row = conn.execute(base.format(extra=""), (paper_id, *DONE)).fetchone()
    return (rc_row["id"] if rc_row else None), ai


SHALL, SHOULD, UNKNOWN = "shall", "should", "unknown"
UNKNOWN_STRENGTH_WORDS = (
    "the rule's strength is not recorded, so it is treated as mandatory"
)


def _checklist_entry(rule_id: str) -> dict | None:
    """The approved checklist entry (`reference/datasheet_checks.json`) with this id, or None."""
    from . import datasheet_checks

    try:
        data = datasheet_checks.load_rules()  # the ONE reader of the approved checklist
    except (OSError, ValueError):
        return None

    def walk(node):
        if isinstance(node, dict):
            if node.get("id") == rule_id:
                return node
            for v in node.values():
                if (got := walk(v)) is not None:
                    return got
        elif isinstance(node, list):
            for v in node:
                if (got := walk(v)) is not None:
                    return got
        return None

    return walk(data)


def _strength(finding: dict | None) -> str:
    """ "shall", "should" or "unknown", read from EVERY home that knows the rule's strength: the stored requirement (its type is a
    recommendation or not), and for a datasheet-check finding the approved checklist entry (mandatory unless the entry says it is a
    recommendation). Nothing known: "unknown", and the proposal treats it as mandatory and says so (the stricter code, never a silent
    softer one)."""
    f = finding or {}
    rid = f.get("requirement_id")
    if rid:
        row = (
            connect()
            .execute(
                "SELECT requirement_type FROM standard_requirements WHERE id = ?",
                (rid,),
            )
            .fetchone()
        )
        if row:
            return SHOULD if row["requirement_type"] == "recommendation" else SHALL
    if f.get("origin") == "datasheet_check":
        import re

        m = re.search(
            r"\b([A-Z][A-Z0-9]*-[A-Z0-9]+):",
            str(f.get("requirement_source_text") or ""),
        )  # "<label> DS-C1: <text>"
        entry = _checklist_entry(m.group(1)) if m else None
        if entry is not None:
            soft = entry.get("recommendation") is True or str(
                entry.get("strength") or ""
            ).lower() in ("should", "recommendation")
            return SHOULD if soft else SHALL
        return SHALL  # an approved checklist check: mandatory unless its entry says otherwise
    return UNKNOWN


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _on_page(document_id: str | None, page, text, scope) -> bool:
    """Code check: the passage stands in the stored text of that page of a document the caller may read. This is what lets a
    rule-check point show a passage ("this passage is on the page"): located by code, never invented."""
    quote = _fold(text)
    if not (
        document_id
        and isinstance(page, int)
        and page >= 1
        and quote
        and scope.may_read(document_id)
    ):
        return False
    row = (
        connect()
        .execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
            (document_id, page),
        )
        .fetchone()
    )
    return bool(row) and quote in _fold(row["text"])


def _sides(finding: dict, scope) -> dict:
    """{"submittal": {"document", "page", "verified"}, "standard": {...}} for a finding: `verified` only when the cited passage is found
    in the stored text of the cited page (`_on_page`)."""
    out = {}
    for side, (doc_f, page_f, text_f) in evidence_boxes.SIDES.items():
        doc, page = finding.get(doc_f), finding.get(page_f)
        readable = bool(doc) and scope.may_read(doc)
        out[side] = {
            "document": doc if readable else None,
            "page": page if readable else None,
            "verified": _on_page(doc, page, finding.get(text_f), scope),
        }
    return out


def _rule_points(run_id: str, paper_id: str, scope) -> list[dict]:
    from . import main as main_mod

    rows = main_mod._crs_content(
        run_id, scope, "internal", apply_point_decisions=False
    )[0]
    ctx = {
        "run_id": run_id,
        "paper_document_id": paper_id,
        "readable": frozenset(scope.allowed_document_ids),
    }
    out = []
    for row in rows:
        fid = row.get("finding_id")
        finding = review_mod.get(fid) if fid else None
        if finding is not None and not scope.may_read(finding["document_id"]):
            finding = None
        sides = _sides(finding, scope) if finding else {}
        p = rp.rule_point(row, ctx, finding, sides, strength=_strength(finding))
        p["_book_docs"] = _book_docs_of_row(row, finding, p)
        p["_confirmed"], p["_rejected"] = (
            bool(row.get("engineer_confirmed")),
            bool(row.get("engineer_rejected")),
        )
        out.append(p)
    shown = {p["id"] for p in out}
    for pid, d in decisions_mod.latest(
        paper_id
    ).items():  # a REMOVED point stays in the record (and the list), though its row left the sheet
        key = pid.removeprefix("rc:")
        if (
            pid.startswith("rc:")
            and d["state"] == decisions_mod.REMOVE
            and pid not in shown
        ):
            finding = review_mod.get(key)
            if (
                finding
                and finding.get("review_run_id") == run_id
                and scope.may_read(finding["document_id"])
            ):
                out.append(rp.removed_stub(finding, ctx, strength=_strength(finding)))
    return out


def _book_docs_of_row(row: dict, finding: dict | None, point: dict) -> list[str]:
    """Every rule book (document id) the row's findings cite, in order, without repeats: a row that cites several clauses, or several
    books, is one point that counts once for each book."""
    docs: list[str] = []
    if finding and finding.get("standard_document_id"):
        docs.append(finding["standard_document_id"])
    for fid in row.get("finding_ids") or []:
        other = review_mod.get(fid) if fid != (finding or {}).get("id") else None
        if other and other.get("standard_document_id"):
            docs.append(other["standard_document_id"])
    return list(dict.fromkeys(docs))


def _stem(filename: str | None) -> str | None:
    """A rule book's name from its file name: the stem (the same rule the AI reviewer uses for its rule book labels)."""
    return Path(filename).stem.strip() or None if filename else None


def resolve_books(points: list[dict], readable: frozenset[str]) -> None:
    """Give each point its rule books by IDENTITY: `books` = [{id, name}] of the books it cites that the caller may read (the name is
    the book's own file name, not a string made of its clause and page), `rule_book` = the first one's name. A book the caller may not
    read is counted by the listing, never named (rule 5). Points that cite no book have an empty `books`."""
    ids = {d for p in points for d in p.get("_book_docs") or [] if d in readable}
    names: dict[str, str] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for r in connect().execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", sorted(ids)
        ):
            if _stem(r["filename"]):
                names[r["id"]] = _stem(r["filename"])
    for p in points:
        books = [
            {"id": d, "name": names[d]}
            for d in p.get("_book_docs") or []
            if d in readable and d in names
        ]
        p["books"] = books
        # a point that cites a book the caller may not read is counted apart for it, even when another of its books is readable
        p["_other_books"] = any(d not in names or d not in readable for d in p.get("_book_docs") or [])
        p["no_book"] = not (p.get("_book_docs") or p.get("_book_doc"))  # cites no rule book at all
        if books:
            p["rule_book"] = books[0]["name"]
        elif p.get("_book_docs") or p.get("_book_doc"):
            p["rule_book"], p["clause"] = None, None  # held but not readable (or not found): not named
        else:
            p["rule_book"] = None  # no identity, no chip: a display string is never parsed into a book


def _names(ids) -> dict[str, str]:
    ids = sorted(i for i in ids if i)
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    return {
        r["id"]: r["display_name"]
        for r in connect().execute(
            f"SELECT id, display_name FROM users WHERE id IN ({marks})", ids
        )
        if r["display_name"]
    }


def assemble(paper_id: str, scope) -> dict:
    conn = connect()
    rc_run, ai_run = runs_of_paper(conn, paper_id)
    readable = frozenset(scope.allowed_document_ids)
    ai_pts, not_held = (
        rp.ai_points_of_run(conn, ai_run, paper_id, readable) if ai_run else ([], [])
    )
    rc_pts = _rule_points(rc_run, paper_id, scope) if rc_run else []
    names = _names(decisions_mod.people(paper_id))
    add_pts = [
        decisions_mod.added_point(r, names.get(r["added_by"]) or r["added_by"])
        for r in decisions_mod.added(paper_id)
    ]
    points = rp.build(ai_pts, rc_pts, add_pts)
    resolve_books(points, readable)
    decided_by_me = decisions_mod.latest(paper_id)
    for p in points:
        d = decisions_mod.decision_of_point(p["id"], decided_by_me)
        if d["state"] is None and p.get("_rejected"):
            d = {
                "state": decisions_mod.REMOVE,
                "words": "Removed",
                "by": None,
                "reason": "removed earlier by an engineer",
            }
        elif d["state"] is None and p.get("_confirmed"):
            d = {"state": decisions_mod.KEEP, "words": "Kept", "by": None}
        if d.get("by"):
            d["by"] = names.get(d["by"]) or d["by"]
        p["decision"] = d
    decided = sum(1 for p in points if p["decision"]["state"])
    counts = rp.counts(
        points, two_reader_possible=bool(ai_run), not_held=not_held, decided=decided
    )
    from .config import settings

    proposal = review_code_proposal.propose(
        points,
        unread_pages=_unread_pages(rc_run or ai_run, scope),
        resubmit_at=int(settings.review_code_resubmit_at_kept_mandatory_not_met or 0),
        reviews_ran=bool(rc_run or ai_run),
    )
    final = (
        conn.execute(
            "SELECT engineer_final_code FROM review_runs WHERE id = ?",
            (rc_run or ai_run,),
        ).fetchone()
        if (rc_run or ai_run)
        else None
    )
    return {
        "paper_document_id": paper_id,
        "runs": {"rule_check": rc_run, "ai_review": ai_run},
        "points": [rp.public(p) for p in points],
        "counts": counts,
        "proposed_code": proposal,
        "final_code": (final["engineer_final_code"] if final else None) or None,
        "code_run_id": rc_run or ai_run,
        "decided": decided,
        "of": len(points),
        "removed": [
            rp.public(p)
            for p in points
            if p["decision"]["state"] == decisions_mod.REMOVE
        ],
        "contractor_copy": _contractor_copy(conn, ai_run),
    }


def _unread_pages(run_id: str | None, scope) -> int | None:
    """How many pages of the paper were not read, from the run's page record; None when it holds none (said, never 0)."""
    if not run_id:
        return None
    from . import comparison, page_ledger

    try:
        outcome = (
            comparison.run_outcome(
                run_id, allowed_document_ids=scope.allowed_document_ids
            )
            or {}
        )
        cov = outcome.get("page_coverage")
        if not cov or cov.get("pages_total") is None:
            return None
        return len(page_ledger.run_unread_pages(cov, page_ledger.run_reader(outcome)))
    except Exception as exc:  # noqa: BLE001 - an unreadable record is "not known", never 0
        logging.getLogger(__name__).warning(
            "review points: the page record is unreadable (%s)", type(exc).__name__
        )
        return None


def undecided(paper_id: str, scope) -> tuple[int, int]:
    """(points not decided, points in all) for the sign gate."""
    got = assemble(paper_id, scope)
    return sum(1 for p in got["points"] if not p["decision"]["state"]), len(
        got["points"]
    )


def decided_ai_sheet(run_id: str, paper_id: str, copy: str, folder) -> Path | None:
    """The AI review's CRS copy drawn again with the engineer's decisions (removed lines out, edited text in, added points in), or None
    when nothing was decided or added for this paper (the stored file stands). The run's own meta is read from the file kept beside the
    sheet; an older run without one gets a minimal meta (the paper and the run id)."""
    import json
    from pathlib import Path

    from . import agent_review_crs, crs_ai_workbook

    if not decisions_mod.latest(paper_id) and not decisions_mod.added(paper_id):
        return None
    conn = connect()
    lines = [
        {**json.loads(r["line_json"] or "{}"), "item_id": r["item_id"]}
        for r in conn.execute(
            "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
    ]
    folder = Path(folder)
    meta_path = folder / "crs-meta.json"
    try:
        meta = (
            json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.is_file()
            else {}
        )
    except (OSError, ValueError):
        meta = {}
    meta.setdefault("paper", paper_id)
    meta.setdefault("run_id", run_id)
    kept = decisions_mod.apply_to_lines(
        paper_id, run_id, lines, _names(decisions_mod.people(paper_id))
    )
    agent_review_crs._refuse_unproven(kept)  # the exit's own refusal still stands
    return crs_ai_workbook.write(kept, folder / f"crs-{copy}-decided.xlsx", meta, copy)


def archive_ai_contractor_copy(rule_check_run_id: str, *, actor: str) -> dict | None:
    """At signing: keep the exact bytes of the AI review's contractor copy (with the engineer's decisions and added points in it), like
    the rule check's own copy (`crs_issue.archive`: a file of its own and a record with its checksum, never rewritten). None when the
    paper has no finished AI review. After this, no later decision changes it: `decided_ai_sheet` writes a separate working file."""
    from . import agent_review_jobs, crs_issue
    from .db import connect as _connect

    conn = _connect()
    row = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?",
        (rule_check_run_id,),
    ).fetchone()
    if row is None:
        return None
    _rc, ai = runs_of_paper(conn, row["submittal_document_id"])
    if not ai:
        return None
    folder = agent_review_jobs.run_dir(ai)
    path = decided_ai_sheet(ai, row["submittal_document_id"], "contractor", folder) or (
        folder / "crs-contractor.xlsx"
    )
    if not path.is_file():
        return None
    return crs_issue.archive(
        ai, path.read_bytes(), "ai-review-contractor.xlsx", actor=actor
    )


def _contractor_copy(conn, ai_run: str | None) -> dict:
    """{kind, words}: what the AI review's contractor copy holds for this paper's kind (the kind of its AI run)."""
    kind = None
    if ai_run:
        row = conn.execute(
            "SELECT paper_kind FROM agent_review_run WHERE run_id = ?", (ai_run,)
        ).fetchone()
        kind = row["paper_kind"] if row else None
    from . import kind_review_table

    return {"kind": kind, "words": kind_review_table.contractor_copy_words(kind)}
