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
import re
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from . import agent_review_ai_answer as ai_answer
from . import agent_review_not_applicable as not_applicable
from . import (
    crs_ai_header,
    crs_editions,
    crs_export_quality,
    crs_layout,
    standards_web_search,
    standards_web_search_money,
)
from . import crs_ai_words as words
from . import crs_comments as comments
from . import crs_completeness as completeness
from . import review_point_decisions as decisions_mod
from . import review_points as rp
from . import review_points_content as content
from .agent_run_crs import _cell
from .crs_ai_actions import reason_for
from .crs_comments import comment_page_words, point_page_words
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
#: owner on PR #1872: the lines the AI thinks do not apply, to confirm: their own sheet, never comment rows, never the contractor's
NA_SHEET = not_applicable.SHEET
HELD_SHEET = "Rule books not held"
NOT_CHECKED_SHEET = "What was not checked"
HOW_SHEET = "How it was reviewed"
#: Order 14 lane B: the fields that carry no finding (met, does not apply, a coverage line), listed apart and counted, never dropped
NOT_A_COMMENT_SHEET = "Not a comment"
#: Order 14 lane E's contract checks (CT-01..), an AI-draft checklist: internal only, never on the contractor file
CONTRACT_SHEET = "Contract checks"
CONTRACT_CLASS = "AI draft rule, internal only"
CONTRACT_SHOWN = ("inconsistent", "engineer to check")
FILE_TEAM = "crs-team.xlsx"
FILE_CONTRACTOR = "crs-contractor.xlsx"
#: FTU-1: the download is named after the paper (its own document number, else its file stem), built from the database at run time
FILE_STEM_LIMIT = 60
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
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
    if line and (draft := words.ai_draft_words(line)):  # lane A: a check against an AI-draft limit: said first, in code's own words
        return _clean(draft)
    if line:
        why = words.why_phrase(line.get("not_proven_reason") or line.get("why") or "")
        code = (
            ai_answer.marked(words.code_phrase(line.get("reason_code")), ai_answer.is_ai_row(line))
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
    """Only a quote code verified, with its check note, or the page's own words for "no verified quote". A found quote on a point that
    says the paper does not state the value is said as where the reader looked, never as evidence (FTU-1: the page's own note)."""
    # a code-proved absence: its proof, as on the page
    if point.get("paper_looked") or point.get("paper_proof"):
        return point["paper_quote_note"]
    if point.get("paper_quote"):
        return f'"{point["paper_quote"]}" ({point["paper_quote_note"]})'
    if point.get("paper_value"):  # stored, but code did not verify it: shown as stored, never as verified
        page = point.get("paper_value_page")
        return f'"{point["paper_value"]}" (as stored{f", page {page}" if page else ""}; {content.NOT_VERIFIED})'
    return content.NOTHING


def rule_requires(point: dict) -> str:
    if point.get("clause_quote"):
        return f'"{point["clause_quote"]}" ({point["clause_quote_note"]})'
    if point.get("rule_hidden"):
        return content.UNREADABLE_BOOK
    if point.get("rule_text"):
        return f'"{point["rule_text"]}" (as stored; {content.NOT_VERIFIED})'
    if point.get("check_text"):  # order 14 lane B: our checklist's words, said to be ours
        return f'Our checklist asks (our words, not the book\'s): "{point["check_text"]}"'
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
            f"independent reader: {ai_answer.marked(_clean(indep.get('verdict')), ai_answer.is_ai_row(line)) or NOT_RECORDED}",
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


def row_of(
    n: int, point: dict, comment: int | str | None = None, editions: dict | None = None
) -> tuple[list, int]:
    """(the cells of one point, how many cells were shortened). The whole text of every shortened cell is in the last column. With
    `editions` (lane G, `crs_editions.verdicts`) each book carries its edition status in brackets."""
    first, second, agreed = readers_of(point)
    long_cells = full_texts(point)
    shown, cut_any, full = {}, 0, []
    for key in _LONG:
        shown[key], cut = _cut(long_cells[key])
        if cut:
            cut_any += 1
            full.append(f"{key.replace('_', ' ')}: {long_cells[key]}")
    books = ", ".join(
        crs_editions.mark(b["name"], editions, b["id"])
        for b in point.get("books") or []
    ) or (point.get("rule_book") or "")
    cells = [
        n, comment, point.get("source_words"), point.get("pill"), ai_answer.class_words(rp.TILE_WORDS.get(point.get("tile"), ""), point), point.get("priority") or None,
        point.get("name"), point_page_words(point) or NOT_RECORDED, books or no_rule_words([point]), point.get("clause"), shown["action"] or None,
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
            # FTU-17: the run's stored models, read by the one home the page's points read too (`crs_ai_header`)
            "engine": crs_ai_header.engine_short(crs_ai_header.engine_of_models(models)),
            "models": models, "date": (r["finished_at"] or r["started_at"]) if r else None,
            "kind": r["paper_kind"] if r else None, "equipment": r["equipment_type"] if r else None, "usd": r["usd"] if r else None,
            "search_in_cost": standards_web_search_money.added(r["counts_json"]) if r else None,
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
        # the proposal's own line (`review_code_proposal`, the one home): no approving code while a point is still to decide
        ("Proposed review code:", code.get("line") or NOT_RECORDED),
        ("Recorded review code:", (listing.get("final_code_words") or {}).get("team") or NOT_RECORDED),
        ("Status of this file:", "Issued" if signed else "Working copy, not issued"),
    ]


def _books_line(points: list[dict], editions: dict | None = None) -> str:
    """Each cited book with its count of points; with `editions` (lane G: book name -> `standard_editions.against_cutoff` result) also
    what the contract's edition cutoff says of the held edition."""
    c: Counter = Counter()
    for p in points:
        for b in p.get("books") or []:
            c[b["name"]] += 1

    def one(n: str, k: int) -> str:
        return f"{n} ({k}; {words.edition_words(editions.get(n))})" if editions is not None else f"{n} ({k})"

    return "; ".join(one(n, k) for n, k in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"


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
    for kind, n in set_apart(points).items():  # FTU-17: the one count every sheet reads
        rows.append([kind, n["all"], "points of this list, on the sheet CRS and on the sheet Does not apply"])
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
                    f"{local_engine_bar.step_words(str(skipped.get('step') or ''))}: {_clean(skipped.get('note'))}",
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
    if (online := standards_web_search.cost_of(extra.get("found_online"))) is not None:
        # a run whose usd includes the search shows the figure ADDED to it (review R-1866, finding 3)
        added = next((r["search_in_cost"] for r in _run_facts(extra) if r.get("search_in_cost") is not None), None)
        rows.append([standards_web_search_money.COST_ROW_INCLUDED, added] if added is not None
                    else [standards_web_search.COST_ROW, online])  # fmt: skip
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


APART_PLACES = (
    ("aside", f"not a comment (the sheet {NOT_A_COMMENT_SHEET})"),
    ("comment", f"inside a comment on the sheet {TEAM_SHEET}, on a field that also has a finding"),
    ("removed", "removed by an engineer"),
)


def set_apart(points: list[dict]) -> dict[str, dict[str, int]]:
    """FTU-17: THE ONE COUNT of the points that do not apply or were not checked (rank 8; the page's tile "Does not apply" counts the same
    points), by what each is: {kind: {"all", "aside", "comment", "removed"}}. Every sheet reads it: the first sheet, "Not a comment",
    "Does not apply" and "What was not checked", so no sheet counts only the part it lists without saying so."""
    where = {i: "comment" for c in comments.group(points) for i in c["member_ids"]}
    where.update({i: "aside" for c, _kind in comments.set_aside(points) for i in c["member_ids"]})
    out: dict[str, dict[str, int]] = {}
    for p in points:
        if p.get("rank") != 8:
            continue
        got = out.setdefault(p.get("other_kind") or words.KIND_NOT_APPLICABLE, dict.fromkeys(("all", "aside", "comment", "removed"), 0))
        got["all"] += 1
        got[where.get(p["id"], "removed")] += 1
    return dict(sorted(out.items()))


def set_apart_line(apart: dict[str, dict[str, int]]) -> str:
    """The one sentence of `set_apart` ("" when no point is set apart)."""
    each = [
        f"{kind}: {n['all']} ("
        + "; ".join(f"{n[key]} {words_}" for key, words_ in APART_PLACES if n[key])
        + ")"
        for kind, n in apart.items()
    ]
    return (f"Set apart (each one a row of the sheet {DNA_SHEET}): " + "; ".join(each) + ".") if each else ""


def apart_proof(p: dict) -> str | None:
    """FTU-17: why a point does not apply, with its proof, each part found by code (`agent_review_not_applicable.proof`); None
    for any other point. A rule book the reader may not read gives no words of its condition (rule 5)."""
    from .agent_review_not_applicable import proof as not_applicable_proof

    proof = not_applicable_proof(p.get("_line") or {})
    if not proof or p.get("other_kind") != words.KIND_NOT_APPLICABLE:
        return None
    cond = (
        f'the rule\'s condition "{proof["condition"]}" (found in the rule book by code)'
        if p.get("rule_book")
        else "the rule's condition (in a rule book that is not available to you)"
    )
    return f"{proof['reason']}: {cond}; the paper: \"{proof['paper_fact']}\" (found on the page by code)."


def to_confirm(points: list[dict]) -> list[dict]:
    """Owner on PR #1872: the lines the AI thinks do not apply (rank 9), not removed: their own sheet, one row each."""
    return [p for p in points if p.get("rank") == 9 and (p.get("decision") or {}).get("state") != decisions_mod.REMOVE]


def to_confirm_line(points: list[dict]) -> str:
    """The group's ONE count sentence (`agent_review_not_applicable.count_line`), with the sheet it is on."""
    done = sum(1 for p in points if (p.get("decision") or {}).get("state") == decisions_mod.KEEP)
    return f"{not_applicable.count_line(len(points), done)[:-1]} (the sheet {NA_SHEET})."


def confirmed_words(p: dict) -> str:
    d = p.get("decision") or {}
    if d.get("state") != decisions_mod.KEEP:
        return not_applicable.OPEN
    return f"{not_applicable.CONFIRMED}: {d.get('by') or NOT_RECORDED}, {d.get('at') or NOT_RECORDED}"


def aside_line(aside: list[tuple[dict, str]]) -> str:
    """ONE sentence counting the points that are not comments, by what they are (order 14 lane B)."""
    by: Counter = Counter()
    for c, kind in aside:
        by[kind] += c["n_points"]
    n = sum(by.values())
    if not n:
        return "Not a comment: none (every point that is not removed is in a comment)."
    each = "; ".join(f"{kind}: {k}" for kind, k in sorted(by.items(), key=lambda kv: (kv[0] != words.KIND_NOTHING_TO_CHANGE, kv[0])))
    return f"Not a comment: {n} points are not comments ({each}); listed on the sheet {NOT_A_COMMENT_SHEET} with each point's class."


def no_rule_words(points: list[dict]) -> str:
    """What the rule-books cell says when no held book is named: a book the library does not hold is said as missing, with its clause
    or "clause not named" (`review_points.book_missing_words`; order 14 lane C, C1); a rule book the reader may not read is counted and
    not named; otherwise the comment rests on NO rule book and says so (a field check never looks like a rule-backed comment)."""
    missing = list(dict.fromkeys(p["_book_missing_words"] for p in points if p.get("_book_missing_words")))
    if missing:
        return "; ".join(missing)
    held = any(p.get("_book_docs") or p.get("_book_doc") for p in points)
    return content.UNREADABLE_BOOK if held else content.NO_RULE_CITED


def comment_note(c: dict, ms: list[dict]) -> str:
    """The Note of a comment, WHOLE: the readers' disagreement or the count of its points, its tags, and each other point (R91)."""
    many = f"{c['n_points']} points on this field" if c["n_points"] > 1 else ""
    note = comments.DISAGREE if c["disagree"] else many
    note += (" ; tags: " + ", ".join(c["tags"])) if c["tags"] else ""
    # R91: each other point, its class and ask
    note += "".join(f"\n{member_words(p)}" for p in ms if p is not c["strongest"])
    return _clean(note.strip(" ;"))


def comment_full_texts(
    c: dict, by_id: dict | None = None, editions: dict | None = None
) -> dict[str, str]:
    """The whole text of each long cell of a comment (the strongest point's words, every clause and, with `by_id`, its Note): the source
    of its Full text. FTU-1: the Note is a long cell like the others, so a shortened Note carries the mark and its whole text. With no
    clause, the rule-books cell says what `no_rule_words` says of the comment's own points."""
    out = full_texts(c["strongest"])
    if by_id is not None:
        out["note"] = comment_note(c, [by_id[i] for i in c["member_ids"]])
    out["clauses"] = "; ".join(
        " ".join(
            x
            for x in (
                crs_editions.mark(k["book"], editions),
                k["clause"],
                f"(p.{point_page_words(k)})" if k["page"] else "",
            )
            if x
        )
        for k in c["clauses"]
    ) or (
        no_rule_words(c["_members"])
        if c.get("_members")
        else (content.UNREADABLE_BOOK if c.get("book_held") else content.NO_RULE_CITED)
    )
    return out


def highest_priority(points: list[dict]) -> str:
    """The highest Priority word of a comment's points (High, then Medium, then Low); "" when none of them has one."""
    words_ = [p.get("priority") for p in points if p.get("priority")]
    return min(words_, key=lambda w: rp.PRIORITY_ORDER.get(w, 3)) if words_ else ""


def member_words(p: dict) -> str:
    """One other point of a comment (R91): its class, field, rule book and clause, and what it asks, so no finding is folded away."""
    where = " ".join(x for x in (p.get("rule_book") or "", p.get("clause") or "") if x)
    action = _clean(p.get("action"))
    return f"Also: {p.get('pill') or rp.RANKS.get(p.get('rank'), ('point',))[0]}, {p.get('name')}" + (f" ({where})" if where else "") + (
        f": {action}" if action else "")  # fmt: skip


def comment_cells(
    c: dict, by_id: dict, editions: dict | None = None
) -> tuple[list, int]:
    """(the cells of one comment, how many were shortened). The strongest point's words lead; every clause, page and tag is listed;
    a shortened cell keeps its whole text in the column Full text."""
    ms = [by_id[i] for i in c["member_ids"]]
    long_cells = comment_full_texts(c, by_id, editions)
    shown, cut_n, full = {}, 0, []
    for key, text in long_cells.items():
        shown[key], cut = _cut(text)
        if cut:
            cut_n += 1
            full.append(f"{key.replace('_', ' ')}: {text}")
    decided = sum(1 for p in ms if (p.get("decision") or {}).get("state"))
    cells = [
        c["number"], c["pill"], ai_answer.class_words(rp.TILE_WORDS.get(c["tile"], ""), {**c["strongest"], "tile": c["tile"], "rank": c["rank"]}), highest_priority(ms) or None, c["name"], c["n_points"],
        comment_page_words(c) or NOT_RECORDED, shown["clauses"] or None, shown["action"] or None,
        shown["paper_shows"], c["strongest"].get("ai_reasoning") or None, shown["requires"], shown["reason"] or None, c["strongest"].get("checked_by") or None, f"{decided} of {len(ms)} decided",
        shown["note"] or None, "\n".join(full) or None,
    ]  # fmt: skip
    return [_cell(x) for x in cells], cut_n


def contract_rows(results) -> tuple[list[list], int]:
    """(the rows of the sheet Contract checks, how many results were consistent). One row per result whose outcome is "inconsistent" or
    "engineer to check" (lane E's `Result`: ct, topic, outcome, value, message, quotes of page, text, verified); a consistent result is
    counted, not listed. A quote is shown only when code verified it on its page."""
    rows, consistent = [], 0
    for r in results or []:
        outcome = _clean(getattr(r, "outcome", "")).lower()
        if outcome not in CONTRACT_SHOWN:
            consistent += outcome == "consistent"
            continue
        quotes = "; ".join(f'"{_clean(q.text)}" (page {q.page})' for q in getattr(r, "quotes", []) or [] if getattr(q, "verified", False))
        rows.append([_cell(c) for c in (len(rows) + 1, r.ct, r.topic, outcome, r.value, r.message, quotes or content.NOTHING, CONTRACT_CLASS)])
    return rows, consistent


HELD_MEANS = (
    "Cited by the paper (or asked for), not held in the library: not checked against it"
)


#: FTU-16: the two sources of a book not held, kept apart on the sheet (both are honest; they say different things)
HELD_ON_ROWS = "{n} point(s) of this review mark it not held"
HELD_SCOPE_ONLY = "found not held by the review's scope (the books that apply to this paper); no point of this review marks it not held"
HELD_SOURCE_COLUMN = "Where it comes from"


def held_table(held: list[str], found: list[dict] | None, rows_of: dict[str, int] | None = None) -> tuple:
    """The sheet "Rule books not held": (columns, rows, widths). FTU-16: each book says where it comes from (`rows_of`, the points that
    mark it, `review_points.not_held_rows`): the books points mark first, then the books only the review's scope found not held. With the
    online search on (`found` a list), one more column says what it found, "not verified"; never a rule quote, a clause or a point."""
    rows_of = rows_of if rows_of is not None else dict.fromkeys(held, 0)
    order = [n for n in held if rows_of.get(n)] + [n for n in held if not rows_of.get(n)]
    where = {n: HELD_ON_ROWS.format(n=rows_of[n]) if rows_of.get(n) else HELD_SCOPE_ONLY for n in order}
    columns, widths = ("Rule book", "What it means", HELD_SOURCE_COLUMN), (48, 80, 56)
    rows = [[_cell(n), HELD_MEANS, where[n]] for n in order]
    if found is None:
        return columns, rows, widths
    said = {f["name"]: f["words"] for f in found}
    return (
        (*columns, standards_web_search.COLUMN),
        [[*r, _cell(said.get(n) or "not searched")] for r, n in zip(rows, order, strict=True)],
        (*widths, 90),
    )


def held_note(held: list[str], rows_of: dict[str, int], marking: int) -> str:
    """FTU-16: the count line of the sheet "Rule books not held": both sources, apart, adding up to the page's count of books not held."""
    on = sum(1 for n in held if rows_of.get(n))
    return (
        f"{len(held)} rule book(s) not held: {on} marked not held by {marking} point(s) of this review; {len(held) - on} found not held "
        "by the review's scope only, marked by no point. They are not points: nothing was checked against them."
    )


def build_team(
    paper_id: str,
    scope,
    *,
    exported: str | None = None,
    signed: bool = False,
    listing_raw=None,
    contract_results=None,
    editions: dict | None = None,
) -> bytes:
    """The ONE team workbook of a paper (see the module words): sheet CRS = one comment per field, sheet Evidence = every point."""
    from . import review_points_service as svc

    listing, raw, extra = listing_raw or svc.export_listing(paper_id, scope)
    # lane G: None while off, so the file is byte-same
    editions = editions if editions is not None else crs_editions.verdicts(raw)
    exported = exported or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    removed = [
        p for p in raw if (p.get("decision") or {}).get("state") == decisions_mod.REMOVE
    ]
    numbers = {p["id"]: n for n, p in enumerate(raw, start=1)}
    by_id = {p["id"]: p for p in raw}
    grouped = comments.group(raw)
    comment_of = {i: c["number"] for c in grouped for i in c["member_ids"]}
    aside = comments.set_aside(raw)  # order 14 lane B: no finding, so not a comment; named on Evidence, counted, listed on its sheet
    comment_of.update({i: kind for c, kind in aside for i in c["member_ids"]})
    confirm = to_confirm(raw)
    comment_of.update({p["id"]: NA_SHEET for p in confirm})
    evidence, cut = [], 0
    for p in raw:
        row, cc = row_of(
            numbers[p["id"]], p, comment_of.get(p["id"], "removed"), editions
        )
        evidence.append(row)
        cut += cc
    comment_rows = []
    for c in grouped:
        row, cc = comment_cells(c, by_id, editions)
        comment_rows.append(row)
        cut += cc
    wb = Workbook()
    ws = wb.active
    ws.title = TEAM_SHEET
    lines = [
        *completeness.cancelled_line(paper_id, extra),  # FTU-17: a later review was cancelled: said first
        completeness.team_statement(listing["of"], len(grouped)),
        count_line(listing, len(evidence), len(grouped)),
        aside_line(aside),
        *([to_confirm_line(confirm)] if confirm else []),
        *([apart_words] if (apart_words := set_apart_line(set_apart(raw))) else []),
        *([f"Coverage note: {note}"] if (note := comments.coverage_note(raw)) else []),
        f"Decisions: {listing['decided']} of {listing['of']} decided"
        + (
            f"; {cut} cell(s) shortened with {CUT_MARK} (the whole text is in the column Full text)"
            if cut
            else "; no cell shortened"
        ),
        "Rule books used (points): " + _books_line(raw, crs_editions.by_name(editions)),
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
        [[_cell(c) for c in (numbers[p["id"]], p.get("name"), point_page_words(p), (p["decision"].get("by") or NOT_RECORDED), p["decision"].get("at") or NOT_RECORDED, p["decision"].get("reason") or NOT_RECORDED)] for p in removed],
        (6, 40, 8, 22, 22, 60), note="Points an engineer removed. They stay in the record and are counted in the line above the sheet CRS.",
    )  # fmt: skip
    _sheet_table(
        wb, NOT_A_COMMENT_SHEET, ("Field or item", "What it is", "Points", "No on the sheet Evidence", "Pages", "Rule books and clauses", "Class of each point"),
        [[_cell(c) for c in (x["name"], kind, x["n_points"], ", ".join(str(numbers[i]) for i in x["member_ids"]), comment_page_words(x),
                             comment_full_texts(x, editions=editions)["clauses"], "; ".join(f"{numbers[i]}: {by_id[i].get('pill') or ''}" for i in x["member_ids"]))] for x, kind in aside],
        (40, 28, 8, 20, 12, 60, 50),
        note=f"{aside_line(aside)} {apart_words + ' ' if apart_words else ''}Each point is also a row of the sheet {EVIDENCE_SHEET}, where its column Comment says what it is.",
    )  # fmt: skip
    if contract_results is not None:  # order 14 lane E: the contract checks, an AI-draft checklist (internal only; not points of the page)
        c_rows, consistent = contract_rows(contract_results)
        _sheet_table(
            wb, CONTRACT_SHEET, ("No", "Check", "Topic", "Outcome", "Value", "What to do", "Quote (verified by code)", "Class"), c_rows,
            (6, 10, 30, 18, 30, 60, 60, 26),
            note=f"{len(c_rows)} contract check result(s) to look at; {consistent} consistent (not listed). {CONTRACT_CLASS}: never on the contractor file.",
        )  # fmt: skip
    _sheet_table(
        wb, NA_SHEET, ("No on the sheet Evidence", "Field or item", "Rule books and clauses", "Page", "Why the AI thinks so", "Confirmed"),
        [[_cell(c) for c in (numbers[p["id"]], p.get("name"), " ".join(x for x in (crs_editions.mark(p.get("rule_book"), editions), p.get("clause")) if x) or None,
                             point_page_words(p), p.get("ai_reasoning") or p.get("action"), confirmed_words(p))] for p in confirm],
        (12, 40, 30, 8, 70, 40), note=f"{not_applicable.TITLE}. {to_confirm_line(confirm)} These lines are not comments and never go to the contractor.",
    )  # fmt: skip
    dna = [p for p in raw if p.get("rank") == 8]
    _sheet_table(
        wb, DNA_SHEET, ("No on the sheet Evidence", "Field or item", "What it is", "Page", "Why, with its proof (found by code)"),
        [[_cell(c) for c in (numbers[p["id"]], p.get("name"), p.get("other_kind") or words.KIND_NOT_APPLICABLE, point_page_words(p), apart_proof(p))] for p in dna],
        (12, 48, 30, 8, 70), note=f"{apart_words or 'None.'} These points are also rows of the sheet Evidence (they are counted on the page); listed here by themselves.",
    )  # fmt: skip
    held = extra.get("not_held") or []
    rows_of = rp.not_held_rows(held, raw)
    columns, rows, widths = held_table(held, extra.get("found_online"), rows_of)
    _sheet_table(
        wb, HELD_SHEET, columns, rows, widths, note=held_note(held, rows_of, rp.points_marking(held, raw)),
    )  # fmt: skip
    # lane G: one row per cited held book, an engineer note (never a verdict)
    if editions is not None:
        e_columns, e_rows, e_widths, e_note = crs_editions.sheet(editions, raw, held)
        _sheet_table(wb, crs_editions.SHEET, e_columns, e_rows, e_widths, note=e_note)
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
    PROVEN by code to be Not met, the code's own action line. Never the stored waiting placeholder (`NOTE_PARKED`); the engineer's own sentence is issued whatever words it uses.
    Rule 5: an edit on a point whose words are hidden from this viewer (`_words_hidden`) is never issued in his copy, and no sentence
    about it either: the point is counted apart (`crs_completeness.REASON_NOT_SHOWN`)."""
    d = p.get("decision") or {}
    if p.get("_words_hidden") and d.get("state") == decisions_mod.EDIT:
        return ""
    if p.get("source") == rp.SOURCE_ADDED or d.get("state") == decisions_mod.EDIT:
        text = _clean(
            d.get("text")
            if d.get("state") == decisions_mod.EDIT and d.get("text")
            else p.get("action")
        )
    elif p.get("rank") == 1 and d.get("state") == decisions_mod.KEEP:
        # never the AI's suggestion (a stored finding's words that code did not prove); only the check's own comment
        text = "" if p.get("action_source") in ("ai_suggestion", "hidden") else _clean(p.get("action"))
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


#: FTU-16: what a contractor file with no row says on its first sheet: contractor words only (no internal words), and no count of its
#: own: the one count line (`crs_completeness.contractor_statement`) says how many points there are and why none is issued.
NONE_ISSUED = "No comment is issued in this copy."


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
                    f"p.{point_page_words(p)}" if p.get("page") else NOT_RECORDED,
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
        ("Recorded review code:", (listing.get("final_code_words") or {}).get("contractor") or NOT_RECORDED),
    ]
    # FTU-16: the contractor's first sheet in contractor words, with ONE count line whose numbers add up (N reviewed = M in this file
    # + K not issued, K split by reason, each point under one reason); the decided / open counts are the team copy's
    lines = [
        completeness.contractor_statement(listing["of"], len(mine), reasons),
        "This copy is a working copy, not issued: it becomes the contractor's copy when it is signed."
        if not signed
        else "Issued to the contractor.",
    ]
    if not mine:
        lines.insert(0, NONE_ISSUED)
    lines[:0] = completeness.cancelled_line(paper_id, extra)  # FTU-17: a later review was cancelled: said first
    header_row = _put_block(ws, pairs, lines)
    _table(ws, header_row, CONTRACTOR_COLUMNS, cells, CONTRACTOR_WIDTHS)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ the file's name


def paper_file_stem(text: str) -> str:
    """A name part safe in any file system: runs of characters outside [A-Za-z0-9._-] become one "-", at most `FILE_STEM_LIMIT`."""
    safe = _UNSAFE_NAME.sub("-", str(text or "")).strip("-._")
    return safe[:FILE_STEM_LIMIT].rstrip("-._")


def file_name(copy: str, stem: str) -> str:
    base = (FILE_CONTRACTOR if copy == "contractor" else FILE_TEAM).removesuffix(".xlsx")
    return f"{base}-{stem}.xlsx" if stem else f"{base}.xlsx"


def _number_is_a_suggestion(conn, paper_id: str) -> bool:
    """The document number was written by the classifier (it is in the row's `field_evidence`) and no one has confirmed the row: a
    suggestion, so the file is named after its file stem instead (FTU-1 review)."""
    from . import classification

    row = conn.execute(
        "SELECT confirmed_at, field_evidence FROM document_classification WHERE document_id = ?", (paper_id,)
    ).fetchone()
    if row is None or row["confirmed_at"]:
        return False
    return "document_number" in classification._load_evidence(row["field_evidence"])


def download_name(paper_id: str, copy: str) -> str:
    """The one-CRS download's name: "crs-team-<the paper's document number>.xlsx" (or crs-contractor-...), else its file stem; the bare
    name when neither gives a safe character. Read from the database; nothing of a paper is written in code."""
    from . import crs_ai_header

    conn = connect()
    number = crs_ai_header.document_header(conn, paper_id).get("document_number") or ""
    if not paper_file_stem(number) or _number_is_a_suggestion(conn, paper_id):
        row = conn.execute("SELECT filename FROM documents WHERE id = ?", (paper_id,)).fetchone()
        number = Path(str(row["filename"] or "")).stem if row else ""
    return file_name(copy, paper_file_stem(number))


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
