"""ONE CRS FILE per paper, built from the page's own list of points (K4, owner 15 Nov 2026: "when I generated the CRS internal copy and
the contractor copy they were not complete").

THE ONE HOME. The review page counts the points of `review_points_service.assemble` (the rule check's comments and the AI review's
lines, the engineer's decisions and added points). This module draws a workbook from the SAME list (`export_listing`), so the page and
the file can never disagree: a test asserts "N points on the page; N rows in this file" for every stored run.

  Team file (`build_team`): sheet "CRS" holds EVERY point the page counts, worst first, one row each (the removed ones are in the sheet
  "Removed (record)", with who and why, and counted in the same line); then "Does not apply", "Rule books not held", "What was not
  checked" and "How it was reviewed".
  Contractor file (`build_contractor`): the rows that may go to a contractor by today's rule: a point proven by code to be Not met and
  KEPT by the engineer, and the engineer's own words (an edited or an added point). Nothing else; and when that is no row, the sheet
  itself says why, in words, with the counts. "Working copy, not issued" until the paper is signed.

NO UNMARKED CUT. A cell of the team file that is shortened ends with "…" and its whole text is in the column "Full text"; a cut never
falls inside a number, a unit or a clause number (`crs_export_quality.split_comment`). The contractor file is never cut.

HONESTY (CLAUDE.md rule 4). A fact that is not recorded is written "not recorded", never invented; nothing unproven is shown as proven;
a quote is shown only when code verified it (the points carry that); every count says what it counts. A draft never says "Date Issued".
No document text is logged. Reads only; no model, no network.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO

from openpyxl import Workbook

from . import crs_ai_words as words
from . import crs_comments as comments
from . import crs_completeness as completeness
from . import crs_export_quality, crs_layout
from . import review_point_decisions as decisions_mod
from . import review_points as rp
from . import review_points_content as content
from .agent_run_crs import _cell
from .crs_ai_actions import reason_for
from .db import connect

log = logging.getLogger(__name__)
NOT_RECORDED = "not recorded"
NOT_DECIDED = "not decided yet"
CUT_MARK = completeness.CUT_MARK
CELL_LIMIT = 500
TEAM_SHEET, CONTRACTOR_SHEET = "CRS", "CRS"
EVIDENCE_SHEET = "Evidence"
REMOVED_SHEET = "Removed (record)"
DNA_SHEET = "Does not apply"
HELD_SHEET = "Rule books not held"
NOT_CHECKED_SHEET = "What was not checked"
HOW_SHEET = "How it was reviewed"
FILE_TEAM = "crs-team.xlsx"
FILE_CONTRACTOR = "crs-contractor.xlsx"
#: the archived copy of the one contractor file (`crs_issue.archive`): the file the engineer signed is this builder's, byte for byte
ISSUED_NAME = "crs-contractor-one.xlsx"
#: The AI reviewer's own reasoning, labelled as its view (never a code-proven line's). The WHOLE reasoning: it is never cut, so no mark and no Full text entry are needed.
REASONING_COLUMN = "The AI reviewer's reasoning"
COMMENT_COLUMNS = (
    "Comment", "Pill", "Class", "Priority", "Field or item", "Points", "Pages", "Rule books and clauses", "What the contractor must do",
    "What the paper shows", REASONING_COLUMN, "What the rule requires", "Reason", "Checked by", "Decisions", "Note", "Full text",
)  # fmt: skip
COMMENT_WIDTHS = (9, 26, 14, 10, 30, 8, 14, 52, 48, 48, 48, 48, 36, 30, 22, 34, 60)
TEAM_COLUMNS = (
    "No", "Comment", "Source", "Pill", "Class", "Priority", "Field or item", "Page", "Rule book", "Clause", "What the contractor must do",
    "What the paper shows", REASONING_COLUMN, "What the rule requires", "Reason", "Checked by", "Decision", "Group", "First reader", "Second reader",
    "Agreed", "Full text",
)  # fmt: skip
TEAM_WIDTHS = (6, 9, 16, 22, 14, 10, 30, 7, 24, 12, 48, 48, 48, 48, 36, 30, 22, 18, 20, 20, 10, 60)
CONTRACTOR_COLUMNS = (
    "Item No",
    "Document Name",
    "Page No./Section",
    "COMPANY Comments",
    "Standard Reference",
    "Priority",
    "Status",
    "Decided by",
)
CONTRACTOR_WIDTHS = (8, 26, 16, 90, 28, 10, 10, 20)
_LONG = ("action", "paper_shows", "requires", "reason")


# ------------------------------------------------------------------------------------------------ plain words of a point


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _cut(text: str) -> tuple[str, bool]:
    """(the cell's text, whether it was shortened): at most `CELL_LIMIT` characters, ending with the cut mark, never inside a number."""
    text = str(text or "")
    if len(text) <= CELL_LIMIT:
        return text, False
    head, _rest = crs_export_quality.split_comment(text, CELL_LIMIT - 1)
    return head.rstrip() + CUT_MARK, True


def reason_of(point: dict) -> str:
    """The point's reason in plain words, from the stored line or finding: what the run itself recorded, never written here."""
    line, row, finding = (
        point.get("_line") or {},
        point.get("_row") or {},
        point.get("_finding") or {},
    )
    if point.get("source") == rp.SOURCE_ADDED:
        return "Added by an engineer."
    if line:
        why = words.why_phrase(line.get("not_proven_reason") or line.get("why") or "")
        code = (
            words.code_phrase(line.get("reason_code"))
            if line.get("reason_code")
            else ""
        )
        if why and why != words.UNKNOWN_WHY:
            return _clean(reason_for(line, why))
        return _clean(reason_for(line, code))
    if point.get("reason_words"):
        return _clean(point["reason_words"])
    code = finding.get("reason_code") or row.get("row_kind") or ""
    return _clean(words.code_phrase(code)) if code else ""


def paper_shows(point: dict) -> str:
    """Only a quote code verified, with its check note, or the page's own words for "no verified quote"."""
    if point.get("paper_quote"):
        return f'"{point["paper_quote"]}" ({point["paper_quote_note"]})'
    if point.get("paper_value"):  # stored, but code did not verify it: shown as stored, never as verified
        page = point.get("paper_value_page")
        return f'"{point["paper_value"]}" (as stored{f", page {page}" if page else ""}; {content.NOT_VERIFIED})'
    return content.NOTHING


def rule_requires(point: dict) -> str:
    if point.get("clause_quote"):
        return f'"{point["clause_quote"]}" ({point["clause_quote_note"]})'
    if point.get("rule_text"):
        return f'"{point["rule_text"]}" (as stored; {content.NOT_VERIFIED})'
    return content.NOTHING


def readers_of(point: dict) -> tuple[str, str, str]:
    """(first reader, second reader, agreed) from the stored line when present; one phrase "one reader" when no second reader looked."""
    if point.get("source") != rp.SOURCE_AI_REVIEW:
        return (
            (
                "the rule check (code)"
                if point.get("source") == rp.SOURCE_RULE_CHECK
                else "an engineer"
            ),
            "—",
            "—",
        )
    from .agent_review_two_reader import independent

    line = point.get("_line") or {}
    first = _clean(line.get("model")) or NOT_RECORDED
    indep = independent(line)
    second = line.get("second_opinion")
    if isinstance(indep, dict):
        return (
            first,
            f"independent reader: {_clean(indep.get('verdict')) or NOT_RECORDED}",
            "yes" if point.get("rank") in (2, 6) else "no",
        )
    if isinstance(second, dict):
        return (
            first,
            "asked (saw the first answer)",
            "yes" if second.get("agree") else "no",
        )
    return first, "one reader", "—"


def decision_words(point: dict) -> str:
    d = point.get("decision") or {}
    state = d.get("state")
    if not state:
        return NOT_DECIDED
    by = f" by {d['by']}" if d.get("by") else ""
    return f"{d.get('words') or state}{by}"


def group_words(point: dict) -> str:
    n = point.get("n_alike") or 1
    return f"{n} alike" if n > 1 else ""


def full_texts(point: dict) -> dict[str, str]:
    """The whole text of each long cell of a point: the ONE source of what a shortened cell must keep in the column Full text."""
    d = point.get("decision") or {}
    action = _clean(
        d.get("text")
        if d.get("state") == decisions_mod.EDIT and d.get("text")
        else point.get("action")
    )
    if action and point.get("action_source") == "ai_suggestion" and not (d.get("state") == decisions_mod.EDIT and d.get("text")):
        action = f"{content.AI_SUGGESTION[0].upper()}{content.AI_SUGGESTION[1:]}: {action}"  # internal copy only (the contractor file never reads this)
    return {
        "action": action,
        "paper_shows": paper_shows(point),
        "requires": rule_requires(point),
        "reason": reason_of(point),
    }


def row_of(n: int, point: dict, comment: int | str | None = None) -> tuple[list, int]:
    """(the cells of one point, how many cells were shortened). The whole text of every shortened cell is in the last column."""
    first, second, agreed = readers_of(point)
    long_cells = full_texts(point)
    shown, cut_any, full = {}, 0, []
    for key in _LONG:
        shown[key], cut = _cut(long_cells[key])
        if cut:
            cut_any += 1
            full.append(f"{key.replace('_', ' ')}: {long_cells[key]}")
    books = ", ".join(b["name"] for b in point.get("books") or []) or (
        point.get("rule_book") or ""
    )
    cells = [
        n, comment, point.get("source_words"), point.get("pill"), rp.TILE_WORDS.get(point.get("tile"), ""), point.get("priority") or None,
        point.get("name"), point.get("page") or NOT_RECORDED, books or None, point.get("clause"), shown["action"] or None,
        shown["paper_shows"], point.get("ai_reasoning") or None, shown["requires"], shown["reason"] or None, point.get("checked_by") or None, decision_words(point), group_words(point) or None,
        first, second, agreed, "\n".join(full) or None,
    ]  # fmt: skip
    return [_cell(c) for c in cells], cut_any


# ------------------------------------------------------------------------------------------------ the facts of the paper and its runs


def _engine_of(conn, run_id: str, model: str, part: str) -> str:
    """The engine of a run: from its stored model name; else from the engine choice stored with the run (Claude or Local, "model name not
    recorded"); else NOT_RECORDED. Never a guess."""
    if model:
        return "Claude" if model.startswith("claude") else "Local"
    try:
        row = conn.execute("SELECT plan_json FROM review_engine_choice WHERE run_id = ?", (run_id,)).fetchone()
        for p in (json.loads(row["plan_json"]).get("parts") or []) if row else []:
            if p.get("name") == part and p.get("engine") in ("claude", "local"):
                return f"{'Claude' if p['engine'] == 'claude' else 'Local'} (model name not recorded)"
    except Exception:  # noqa: BLE001 - no stored choice (an older run, or no table): not recorded
        logging.getLogger(__name__).debug("no engine choice stored for run %s", run_id)
    return NOT_RECORDED


def _run_facts(extra: dict) -> list[dict]:
    """One dict per run behind the list: what ran, on which engine, when. Facts the app does not hold are NOT_RECORDED."""
    conn = connect()
    out = []
    rc, ai = extra.get("rc_run"), extra.get("ai_run")
    if rc:
        r = conn.execute("SELECT * FROM review_runs WHERE id = ?", (rc,)).fetchone()
        model = (r["model_name"] if r else None) or ""
        out.append({
            "what": "Rule check", "run": rc, "engine": _engine_of(conn, rc, model, "rule_check"),
            "models": [model] if model else [], "date": (r["completed_at"] or r["started_at"]) if r else None, "kind": None,
            "equipment": None, "usd": None,
        })  # fmt: skip
    if ai:
        r = conn.execute(
            "SELECT * FROM agent_review_run WHERE run_id = ?", (ai,)
        ).fetchone()
        models = json.loads(r["models_json"] or "[]") if r else []
        out.append({
            "what": "AI review", "run": ai,
            "engine": "Claude" if any(str(m).startswith("claude") for m in models) else ("Local" if models else NOT_RECORDED),
            "models": models, "date": (r["finished_at"] or r["started_at"]) if r else None,
            "kind": r["paper_kind"] if r else None, "equipment": r["equipment_type"] if r else None, "usd": r["usd"] if r else None,
        })  # fmt: skip
    return out


def _paper_facts(paper_id: str, runs: list[dict]) -> dict:
    from . import crs_ai_header, kind_words

    conn = connect()
    doc = conn.execute(
        "SELECT filename FROM documents WHERE id = ?", (paper_id,)
    ).fetchone()
    kind = next(
        (r["kind"] for r in runs if r.get("kind")), None
    ) or kind_words.decided_kind(paper_id)
    equipment = next((r["equipment"] for r in runs if r.get("equipment")), None)
    head = crs_ai_header.document_header(conn, paper_id, equipment)
    return {
        "name": (doc["filename"] if doc else None) or paper_id, "kind": kind_words.noun_of_kind(kind) if kind else NOT_RECORDED,
        "equipment": equipment or NOT_RECORDED, "head": head,
    }  # fmt: skip


def _people(paper_id: str, names: dict) -> str:
    who = sorted({names.get(p) or p for p in decisions_mod.people(paper_id)})
    return ", ".join(who) or NOT_RECORDED


def _header_pairs(
    paper_id: str, listing: dict, extra: dict, *, exported: str, signed: bool
) -> list[tuple[str, str]]:
    runs = _run_facts(extra)
    facts = _paper_facts(paper_id, runs)
    head = facts["head"]
    code = listing.get("proposed_code") or {}
    engines = "; ".join(f"{r['what']}: {r['engine']}" for r in runs) or NOT_RECORDED
    dates = (
        "; ".join(f"{r['what']} {str(r['date'])[:10]}" for r in runs if r.get("date"))
        or NOT_RECORDED
    )
    return [
        ("Paper:", facts["name"]),
        ("Document number:", _clean(head.get("document_number")) or NOT_RECORDED),
        ("Revision:", _clean(head.get("revision")) or NOT_RECORDED),
        ("Kind of paper:", facts["kind"]),
        ("Equipment type:", facts["equipment"]),
        ("Discipline:", _clean(head.get("discipline")) or NOT_RECORDED),
        ("Engine:", engines),
        ("Review date:", dates),
        ("Exported on:", exported),
        ("Decided by:", _people(paper_id, extra.get("names") or {})),
        (
            "Proposed review code:",
            f"{code.get('code') or NOT_RECORDED} ({code.get('line') or 'no line'})",
        ),
        ("Recorded review code:", listing.get("final_code") or NOT_RECORDED),
        ("Status of this file:", "Issued" if signed else "Working copy, not issued"),
    ]


def _books_line(points: list[dict]) -> str:
    c: Counter = Counter()
    for p in points:
        for b in p.get("books") or []:
            c[b["name"]] += 1
    return (
        "; ".join(
            f"{n} ({k})" for n, k in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        or "none"
    )


def _put_block(ws, pairs: list[tuple[str, str]], lines: list[str]) -> int:
    """The header block and the count lines above the table; returns the table's header row."""
    ws.append([_cell("Comment Resolution Sheet")])
    ws.cell(1, 1).font = crs_layout.HEADER_FONT
    row = 2
    for label, value in pairs:
        ws.cell(row, 1, label).font = crs_layout.Font(
            name=crs_layout.ARIAL, bold=True, size=10
        )
        ws.cell(row, 3, _cell(value))
        row += 1
    for line in lines:
        ws.cell(row, 1, _cell(line)).font = crs_layout.Font(
            name=crs_layout.ARIAL, bold=True, size=10
        )
        row += 1
    return row + 1


def _table(ws, header_row: int, columns, rows: list[list], widths) -> None:
    for c, name in enumerate(columns, start=1):
        ws.cell(header_row, c, name)
    for r, cells in enumerate(rows, start=header_row + 1):
        for c, value in enumerate(cells, start=1):
            ws.cell(r, c, value)
    crs_layout.style_table(ws, header_row, len(columns), header_row + len(rows), widths)


def _sheet_table(
    wb: Workbook, title: str, columns, rows: list[list], widths, note: str | None = None
) -> None:
    ws = wb.create_sheet(title)
    top = 1
    if note:
        ws.cell(1, 1, _cell(note)).font = crs_layout.Font(
            name=crs_layout.ARIAL, bold=True, size=10
        )
        top = 3
    _table(ws, top, columns, rows or [["", *[None] * (len(columns) - 1)]][:0], widths)


# ------------------------------------------------------------------------------------------------ the team file


def _outcome(run_id: str, scope) -> dict:
    """The run's stored outcome; {} when it cannot be read (logged by type, never guessed, never document text)."""
    from . import comparison

    try:
        return (
            comparison.run_outcome(
                run_id, allowed_document_ids=scope.allowed_document_ids
            )
            or {}
        )
    except Exception as exc:  # noqa: BLE001 - logged by type; the sheet then says "not recorded"
        log.warning("crs_one: a run's outcome is unreadable (%s)", type(exc).__name__)
        return {}


def _not_checked_rows(points: list[dict], extra: dict, scope) -> list[list]:
    """What the review did NOT check, in counts and plain words: from the stored runs only."""
    from . import local_engine_bar, page_ledger

    conn = connect()
    rows: list[list] = []
    other = Counter(p.get("other_kind") for p in points if p.get("rank") == 8)
    for kind, n in sorted(other.items(), key=lambda kv: str(kv[0])):
        rows.append(
            [
                kind or words.KIND_NOT_APPLICABLE,
                n,
                "points of this list, on the sheet CRS and on the sheet Does not apply",
            ]
        )
    for run_id in (extra.get("rc_run"), extra.get("ai_run")):
        if not run_id:
            continue
        outcome = _outcome(run_id, scope)
        cov = outcome.get("page_coverage")
        if cov and cov.get("pages_total") is not None:
            unread = page_ledger.run_unread_pages(cov, page_ledger.run_reader(outcome))
            line = [
                "Pages not fully read",
                len(unread),
                f"of {cov['pages_total']} pages ({', '.join(str(p) for p in unread) or 'none'})",
            ]
            if line not in rows:  # the rule check and the AI review of one paper share one page record: said once
                rows.append(line)
            if cov.get("ai_skipped_line"):
                rows.append(
                    [
                        "AI page reader not run",
                        len(cov.get("pages_ai_skipped") or []),
                        _clean(cov["ai_skipped_line"]),
                    ]
                )
        elif run_id == extra.get("rc_run"):
            rows.append(
                ["Page record", None, "the reading record is missing for this review"]
            )
        comp = outcome.get("completeness") or {}
        if comp.get("not_checked_plain"):
            rows.append(
                [
                    "Nothing of this kind of paper was checked",
                    None,
                    _clean(comp["not_checked_plain"]),
                ]
            )
        for skipped in outcome.get(local_engine_bar.OUTCOME_KEY) or []:
            rows.append(
                [
                    "AI step skipped",
                    skipped.get("calls_not_made"),
                    f"{local_engine_bar.STEP_WORDS.get(skipped.get('step'), skipped.get('step'))}: {_clean(skipped.get('note'))}",
                ]
            )
        unchecked = outcome.get("unchecked_counts") or {}
        if unchecked.get("not_compared"):
            rows.append(
                [
                    "Requirements that apply but were not compared",
                    unchecked["not_compared"],
                    "the rule check could not compare them with a value",
                ]
            )
    if extra.get("ai_run"):
        r = conn.execute(
            "SELECT stop_reason FROM agent_review_run WHERE run_id = ?",
            (extra["ai_run"],),
        ).fetchone()
        if r and r["stop_reason"]:
            rows.append(["AI review stopped early", None, _clean(r["stop_reason"])])
        left = Counter(
            x["left_out_reason"]
            for x in conn.execute(
                "SELECT left_out_reason FROM agent_review_rule WHERE run_id = ? AND asked = 0",
                (extra["ai_run"],),
            )
        )
        for why, n in sorted(left.items(), key=lambda kv: (-kv[1], str(kv[0]))):
            rows.append(
                ["Rules not asked of this paper", n, _clean(str(why).replace("_", " "))]
            )
    if not rows:
        rows.append(
            [
                "Nothing recorded as not checked",
                None,
                "the stored runs name no unchecked part",
            ]
        )
    return rows


def _how_rows(extra: dict, scope) -> list[list]:
    from . import page_ledger

    conn = connect()
    rows: list[list] = []
    for r in _run_facts(extra):
        rows.append([f"{r['what']}: engine", r["engine"]])
        if r["models"]:
            rows.append(
                [f"{r['what']}: models", ", ".join(str(m) for m in r["models"])]
            )
        rows.append(
            [
                f"{r['what']}: date",
                str(r["date"])[:19] if r.get("date") else NOT_RECORDED,
            ]
        )
        if r.get("usd") is not None:
            rows.append([f"{r['what']}: cost (USD)", r["usd"]])
        outcome = _outcome(r["run"], scope)
        cov = outcome.get("page_coverage")
        if cov and cov.get("pages_total") is not None:
            unread = page_ledger.run_unread_pages(cov, page_ledger.run_reader(outcome))
            rows.append([f"{r['what']}: pages", pages_line(cov, unread)])
        if r["what"] == "AI review":
            asked = conn.execute(
                "SELECT COUNT(*) FROM agent_review_rule WHERE run_id = ? AND asked = 1",
                (r["run"],),
            ).fetchone()[0]
            left = Counter(
                x["left_out_reason"]
                for x in conn.execute(
                    "SELECT left_out_reason FROM agent_review_rule WHERE run_id = ? AND asked = 0",
                    (r["run"],),
                )
            )
            rows.append(["AI review: rules asked", asked])
            for why, n in sorted(left.items(), key=lambda kv: (-kv[1], str(kv[0]))):
                rows.append(
                    [
                        f"AI review: rules left out, {_clean(str(why).replace('_', ' '))}",
                        n,
                    ]
                )
            lines = conn.execute(
                "SELECT COUNT(*) FROM agent_review_line WHERE run_id = ?", (r["run"],)
            ).fetchone()[0]
            rows.append(["AI review: stored lines", lines])
    if len(_run_facts(extra)) == 2:
        rows.append(
            [
                "Readers",
                "the rule check is code; the AI review has a first reader and, where the line says so, a second reader (columns First reader, Second reader, Agreed)",
            ]
        )
    rows.append(
        [
            "Older files of each run (history)",
            "under Older files on the review page (one file per earlier run, kept as it was)",
        ]
    )
    for r in _run_facts(extra):
        rows.append([f"{r['what']}: run id", r["run"]])
    return rows


def pages_line(cov: dict, unread: list) -> str:
    """"N pages: R read, P not fully read (pages ...)" that cannot contradict itself: the read count is said only when the run recorded
    which pages it read; otherwise the line says that is not recorded (never "0 read" for an unknown)."""
    n, read = cov["pages_total"], cov.get("pages_read") or []
    partly = f"{len(unread)} not fully read" + (f" (pages {', '.join(str(p) for p in unread)})" if unread else "")
    if read:
        return f"{n} pages: {len(read)} read, {partly}"
    return f"{n} pages: {partly}; how many were read in full is not recorded"


def count_line(listing: dict, rows_evidence: int, comments: int) -> str:
    n = listing["of"]
    return (
        f"{n} points on the page; {rows_evidence} rows in this file (the sheet {EVIDENCE_SHEET}, one row per point), "
        f"read as {comments} comments on the sheet {TEAM_SHEET}"
    )


def comment_full_texts(c: dict) -> dict[str, str]:
    """The whole text of each long cell of a comment (the strongest point's words and every clause): the source of its Full text."""
    out = full_texts(c["strongest"])
    out["clauses"] = "; ".join(
        " ".join(
            x
            for x in (k["book"], k["clause"], f"(p.{k['page']})" if k["page"] else "")
            if x
        )
        for k in c["clauses"]
    )
    return out


def highest_priority(points: list[dict]) -> str:
    """The highest Priority word of a comment's points (High, then Medium, then Low); "" when none of them has one."""
    words_ = [p.get("priority") for p in points if p.get("priority")]
    return min(words_, key=lambda w: rp.PRIORITY_ORDER.get(w, 3)) if words_ else ""


def comment_cells(c: dict, by_id: dict) -> tuple[list, int]:
    """(the cells of one comment, how many were shortened). The strongest point's words lead; every clause, page and tag is listed;
    a shortened cell keeps its whole text in the column Full text."""
    ms = [by_id[i] for i in c["member_ids"]]
    long_cells = comment_full_texts(c)
    shown, cut_n, full = {}, 0, []
    for key, text in long_cells.items():
        shown[key], cut = _cut(text)
        if cut:
            cut_n += 1
            full.append(f"{key.replace('_', ' ')}: {text}")
    decided = sum(1 for p in ms if (p.get("decision") or {}).get("state"))
    note = (
        comments.DISAGREE
        if c["disagree"]
        else (f"{c['n_points']} points on this field" if c["n_points"] > 1 else "")
    )
    note += (" ; tags: " + ", ".join(c["tags"])) if c["tags"] else ""
    cells = [
        c["number"], c["pill"], rp.TILE_WORDS.get(c["tile"], ""), highest_priority(ms) or None, c["name"], c["n_points"],
        ", ".join(str(x) for x in c["pages"]) or NOT_RECORDED, shown["clauses"] or None, shown["action"] or None,
        shown["paper_shows"], c["strongest"].get("ai_reasoning") or None, shown["requires"], shown["reason"] or None, c["strongest"].get("checked_by") or None, f"{decided} of {len(ms)} decided",
        note.strip(" ;") or None, "\n".join(full) or None,
    ]  # fmt: skip
    return [_cell(x) for x in cells], cut_n


def build_team(
    paper_id: str,
    scope,
    *,
    exported: str | None = None,
    signed: bool = False,
    listing_raw=None,
) -> bytes:
    """The ONE team workbook of a paper (see the module words): sheet CRS = one comment per field, sheet Evidence = every point."""
    from . import review_points_service as svc

    listing, raw, extra = listing_raw or svc.export_listing(paper_id, scope)
    exported = exported or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    removed = [
        p for p in raw if (p.get("decision") or {}).get("state") == decisions_mod.REMOVE
    ]
    numbers = {p["id"]: n for n, p in enumerate(raw, start=1)}
    by_id = {p["id"]: p for p in raw}
    grouped = comments.group(raw)
    comment_of = {i: c["number"] for c in grouped for i in c["member_ids"]}
    evidence, cut = [], 0
    for p in raw:
        row, cc = row_of(numbers[p["id"]], p, comment_of.get(p["id"], "removed"))
        evidence.append(row)
        cut += cc
    comment_rows = []
    for c in grouped:
        row, cc = comment_cells(c, by_id)
        comment_rows.append(row)
        cut += cc
    wb = Workbook()
    ws = wb.active
    ws.title = TEAM_SHEET
    lines = [
        completeness.team_statement(listing["of"], len(grouped)),
        count_line(listing, len(evidence), len(grouped)),
        f"Decisions: {listing['decided']} of {listing['of']} decided"
        + (
            f"; {cut} cell(s) shortened with {CUT_MARK} (the whole text is in the column Full text)"
            if cut
            else "; no cell shortened"
        ),
        "Rule books used (points): " + _books_line(raw),
    ]
    header_row = _put_block(
        ws,
        _header_pairs(paper_id, listing, extra, exported=exported, signed=signed),
        lines,
    )
    _table(ws, header_row, COMMENT_COLUMNS, comment_rows, COMMENT_WIDTHS)
    ws.freeze_panes = ws.cell(header_row + 1, 2)
    _sheet_table(
        wb, EVIDENCE_SHEET, TEAM_COLUMNS, evidence, TEAM_WIDTHS,
        note="Every point the page counts, one row each, linked to its comment by the column Comment (removed points are in no comment).",
    )  # fmt: skip
    _sheet_table(
        wb, REMOVED_SHEET, ("No", "Field or item", "Page", "Removed by", "When", "Why"),
        [[_cell(c) for c in (numbers[p["id"]], p.get("name"), p.get("page"), (p["decision"].get("by") or NOT_RECORDED), p["decision"].get("at") or NOT_RECORDED, p["decision"].get("reason") or NOT_RECORDED)] for p in removed],
        (6, 40, 8, 22, 22, 60), note="Points an engineer removed. They stay in the record and are counted in the line above the sheet CRS.",
    )  # fmt: skip
    dna = [p for p in raw if p.get("rank") == 8]
    _sheet_table(
        wb, DNA_SHEET, ("No on the sheet Evidence", "Field or item", "What it is", "Page"),
        [[_cell(c) for c in (numbers[p["id"]], p.get("name"), p.get("other_kind") or words.KIND_NOT_APPLICABLE, p.get("page"))] for p in dna],
        (12, 48, 30, 8), note="These points are also rows of the sheet Evidence (they are counted on the page); listed here by themselves.",
    )  # fmt: skip
    held = extra.get("not_held") or []
    _sheet_table(
        wb, HELD_SHEET, ("Rule book", "What it means"), [[_cell(n), "Cited by the paper (or asked for), not held in the library: not checked against it"] for n in held],
        (48, 80), note=f"{len(held)} rule book(s) not held. They are not points: nothing was checked against them.",
    )  # fmt: skip
    _sheet_table(
        wb,
        NOT_CHECKED_SHEET,
        ("What", "How many", "Why"),
        [[_cell(c) for c in r] for r in _not_checked_rows(raw, extra, scope)],
        (46, 12, 90),
    )
    _sheet_table(
        wb,
        HOW_SHEET,
        ("What", "Detail"),
        [[_cell(c) for c in r] for r in _how_rows(extra, scope)],
        (46, 110),
    )
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ the contractor file


def issuable_text(p: dict) -> str:
    """The words a contractor may be given for one point, or "": the engineer's own text (an edit, an added point), else, for a point
    PROVEN by code to be Not met, the code's own action line. Never the stored waiting placeholder (`NOTE_PARKED`); the engineer's own sentence is issued whatever words it uses."""
    d = p.get("decision") or {}
    if p.get("source") == rp.SOURCE_ADDED or d.get("state") == decisions_mod.EDIT:
        text = _clean(
            d.get("text")
            if d.get("state") == decisions_mod.EDIT and d.get("text")
            else p.get("action")
        )
    elif p.get("rank") == 1 and d.get("state") == decisions_mod.KEEP:
        # never the AI's suggestion (a stored finding's words that code did not prove); only the check's own comment
        text = "" if p.get("action_source") == "ai_suggestion" else _clean(p.get("action"))
    else:
        return ""
    return (
        "" if comments.is_parked(text) else text
    )  # the stored placeholder is recognised by what it IS, never by words


def contractor_points(raw: list[dict]) -> tuple[list[dict], int]:
    """(the points that go to a contractor, how many kept points were withheld). By the owner's rule a contractor file holds ONLY
    (a) a failure proven by code that the engineer kept, and (b) a point whose comment is the engineer's own words (edited or
    written by him). Each needs issuable text. A kept point with none is withheld and counted, exactly as the old issue copy
    withheld a row with no words; an AI opinion kept with one click is never issued."""
    out, withheld = [], 0
    for p in raw:
        d = p.get("decision") or {}
        state = d.get("state")
        if state == decisions_mod.REMOVE:
            continue
        wanted = (
            p.get("source") == rp.SOURCE_ADDED
            or state == decisions_mod.EDIT
            or (p.get("rank") == 1 and state == decisions_mod.KEEP)
        )
        if not wanted:
            withheld += state == decisions_mod.KEEP
            continue
        if issuable_text(p):
            out.append(p)
        else:
            withheld += 1
    return out, withheld


def status_of(p: dict) -> str:
    """ "Fail" only for a failure proven by code; otherwise the engineer's own decision word, or empty. Never from an AI rank."""
    if p.get("rank") == 1:
        return "Fail"
    if p.get("source") == rp.SOURCE_ADDED:
        return "Added"
    return {decisions_mod.EDIT: "Edited", decisions_mod.KEEP: "Kept"}.get(
        (p.get("decision") or {}).get("state"), ""
    )


def why_none(raw: list[dict], withheld: int = 0) -> str:
    """The sentence a contractor file with no row says in the file itself, with the counts."""
    open_n = sum(
        1 for p in raw if (p.get("decision") or {}).get("state") != decisions_mod.REMOVE
    )
    undecided = sum(1 for p in raw if not (p.get("decision") or {}).get("state"))
    return (
        "This copy holds only failures proven by code that the engineer kept, and the engineer's own words. This review has none: "
        f"{withheld} kept point(s) not issued for lack of engineer wording; "
        f"{open_n} points are open on the internal copy ({undecided} not decided yet; {len(raw)} points in all)."
    )


def build_contractor(
    paper_id: str,
    scope,
    *,
    exported: str | None = None,
    signed: bool = False,
    listing_raw=None,
) -> bytes:
    """The ONE contractor workbook (see the module words). Never a bare header row."""
    from . import review_points_service as svc

    listing, raw, extra = listing_raw or svc.export_listing(paper_id, scope)
    exported = exported or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    mine, reasons = completeness.contractor_split(raw)
    withheld = reasons.get(completeness.REASON_NO_WORDING, 0)
    paper = (_paper_facts(paper_id, _run_facts(extra)))["name"]
    cells = []
    for n, p in enumerate(mine, start=1):
        text = issuable_text(p)
        parts = [text]
        if p.get("paper_quote"):
            parts.append(f'The paper shows: "{p["paper_quote"]}"')
        if p.get("clause_quote") and p.get("books"):
            parts.append(f'The rule requires: "{p["clause_quote"]}"')
        ref = ", ".join(b["name"] for b in p.get("books") or []) + (
            f" {p['clause']}" if p.get("clause") else ""
        )
        status = status_of(p)
        cells.append(
            [
                _cell(c)
                for c in (
                    n,
                    paper,
                    f"p.{p['page']}" if p.get("page") else NOT_RECORDED,
                    "\n".join(x for x in parts if x),
                    ref.strip() or None,
                    "High" if status == "Fail" else None,
                    status or None,
                    decision_words(p),
                )
            ]
        )
    wb = Workbook()
    ws = wb.active
    ws.title = CONTRACTOR_SHEET
    pairs = [
        ("Paper:", paper),
        ("Status of this file:", "Issued" if signed else "Working copy, not issued"),
        ("Exported on:", exported),
        ("Recorded review code:", listing.get("final_code") or NOT_RECORDED),
    ]
    lines = [
        f"{len(mine)} row(s) in this copy; {listing['of']} points in the review; {listing['decided']} of {listing['of']} decided",
        completeness.contractor_statement(listing["of"], len(mine), reasons),
        "This copy is a working copy, not issued: it becomes the contractor's copy when the engineer signs."
        if not signed
        else "Issued to the contractor.",
    ]
    if not mine:
        lines.insert(0, why_none(raw, withheld))
    header_row = _put_block(ws, pairs, lines)
    _table(ws, header_row, CONTRACTOR_COLUMNS, cells, CONTRACTOR_WIDTHS)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ signing: the same builder, kept


def issue(
    rule_check_run_id: str, scope, *, actor: str, **record_facts
) -> tuple[bytes, str, dict]:
    """At signing: the ONE contractor file, built by `build_contractor` with the status "Issued", checked for completeness, and kept
    through the app's one issuing path (`crs_issue.archive`). The bytes are built and checked before anything is written, so a failure
    (or an incomplete file: `completeness.Incomplete`) leaves nothing half issued; the archive writes its record and its file as one
    step and removes the record if the file cannot be written. Returns (bytes, file name, record). The issued bytes are never
    rebuilt: `issued_file` serves them."""
    from . import crs_issue

    row = (
        connect()
        .execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?",
            (rule_check_run_id,),
        )
        .fetchone()
    )
    if row is None:
        raise crs_issue.IssueError("no review run with that id")
    data = completeness.file_or_refuse(
        row["submittal_document_id"], scope, "contractor", signed=True
    )
    record = crs_issue.archive(
        rule_check_run_id, data, ISSUED_NAME, actor=actor, **record_facts
    )
    return data, ISSUED_NAME, record


def issued_file(paper_id: str) -> tuple[dict, bytes] | None:
    """The newest ISSUED one-contractor file of the paper (record, exact bytes), or None while it is not signed."""
    from . import crs_issue
    from . import review_points_service as svc

    rc, _ai = svc.runs_of_paper(connect(), paper_id)
    for rec in crs_issue.issued(rc) if rc else []:
        if rec["filename"] == ISSUED_NAME:
            return crs_issue.issued_bytes(rc, rec["id"])
    return None
