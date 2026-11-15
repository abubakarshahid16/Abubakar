"""COMPLETENESS IS A HARD RULE (owner, 15 Nov 2026, like "0 wrong"): ONE home that compares THREE counts for a paper's review:

  the points on the page      what `review_points_service.assemble` serves,
  the lines in the database   the AI review's stored lines, the rule check's sheet rows (and the removed ones a decision keeps), the
                              engineer's added points,
  the rows in each CRS file   read back from the workbook as BUILT (never from the builder's own number).

Team file: N = N, or the file is refused. Contractor file: it holds fewer rows by design (code-proven Fails and the engineer's own
words), so code checks M in the file + K not issued = N, with K split by reason. When anything differs the download is refused (409)
and the sentence says what is missing (which points by name and page, how many): never a silent short file.

The numbers on the first sheet of each file ("N points reviewed, N in this file") come from this module, never typed twice. The check
runs after every review ends (the result is stored with the run: `record_after_run`) and again at every download.

No model, no network; reads only (the stored result is the one write). No document text is logged: counts and ids only.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO

from openpyxl import load_workbook

from . import nine_sheet
from . import review_point_decisions as decisions_mod
from .db import connect

log = logging.getLogger(__name__)
LIST_AT_MOST = 10
CUT_MARK = "…"  # the visible mark of a shortened cell: one literal, checked here whatever a builder writes
REASON_REMOVED = "removed by an engineer"
REASON_NO_WORDING = "no engineer wording"
REASON_NOT_PROVEN = "not code-proven and not the engineer's own words"
REASON_ORDER = (REASON_NOT_PROVEN, REASON_NO_WORDING, REASON_REMOVED)


class Incomplete(Exception):
    """The three counts differ: the file is not given out. `.report` holds the numbers; `str()` is the plain sentence."""

    def __init__(self, report: dict):
        super().__init__(report["sentence"])
        self.report = report


# ------------------------------------------------------------------------------------------------ the one statement


def team_statement(
    n: int, comments: int | None = None, findings: int | None = None
) -> str:
    as_comments = f", as {comments} comments" if comments is not None else ""
    from_findings = (
        f", from {findings} findings of the reviewer" if findings is not None else ""
    )
    return f"{n} points reviewed, {n} in this file{as_comments}{from_findings}"


def findings_of(raw: list[dict]) -> int:
    """How many findings of the reviewer the lines stand for: the sum of `underlying` (a joined line counts every finding it joined)."""
    return sum(int(p.get("underlying") or 0) for p in raw)


def findings_check(raw: list[dict], ai_run: str | None) -> list[str]:
    """The FOURTH check of a nine-role run: the findings the lines stand for equal the findings the reviewer's join kept (stored in the
    role record by the job). A difference refuses the file like the other three. A run with no such record is not checked here."""
    if not ai_run:
        return []
    from . import nine_record

    record = nine_record.load_record(ai_run)
    if record is None:
        return []
    kept = record.roles[3].produced.get("findings_kept")
    if kept is None:
        return []
    got = findings_of(raw)
    if int(kept) != got:
        return [
            f"the lines stand for {got} findings of the reviewer, the reviewer's join kept {kept}: a finding is missing from the lines"
        ]
    return []


def contractor_statement(n: int, m: int, reasons: dict[str, int]) -> str:
    why = (
        "; ".join(f"{reasons[r]} {r}" for r in REASON_ORDER if reasons.get(r)) or "none"
    )
    return f"{n} points reviewed, {m} in this file, {n - m} not issued: {why}"


def contractor_split(raw: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """(the points in the contractor file, K split by reason). M + sum(reasons) is always the number of points."""
    from . import crs_one

    mine, _withheld = crs_one.contractor_points(raw)
    ids = {id(p) for p in mine}
    reasons: Counter = Counter()
    for p in raw:
        if id(p) in ids:
            continue
        d = p.get("decision") or {}
        state = d.get("state")
        wanted = (
            p.get("source") == "added"
            or state == decisions_mod.EDIT
            or (p.get("rank") == 1 and state == decisions_mod.KEEP)
        )
        if state == decisions_mod.REMOVE:
            reasons[REASON_REMOVED] += 1
        elif (
            wanted or state == decisions_mod.KEEP
        ):  # kept, but no words of the engineer's own to issue
            reasons[REASON_NO_WORDING] += 1
        else:
            reasons[REASON_NOT_PROVEN] += 1
    return mine, dict(reasons)


# ------------------------------------------------------------------------------------------------ the database count


def rule_row_ids(run_id: str, paper_id: str, scope) -> dict[str, str]:
    """{point id: a plain label} of the rule check's rows for the paper as its own sheet builder returns them, plus the removed points
    whose row left the sheet but whose decision keeps them in the record: the ids a point of the page must carry, made without a point."""
    from . import main as main_mod
    from . import review as review_mod

    rows = main_mod._crs_content(
        run_id, scope, "internal", apply_point_decisions=False
    )[0]
    out: dict[str, str] = {}
    shown = set()
    for row in rows:
        shown.add(row.get("finding_id"))
        shown.update(row.get("finding_ids") or [])
        key = str(row.get("finding_id") or row.get("crs_row_key") or "")
        page = f", page {row['page_section']}" if row.get("page_section") else ""
        out[f"rc:{key}"] = f"a rule-check row{page}"
    for pid, d in decisions_mod.latest(paper_id).items():
        key = pid.removeprefix("rc:")
        if (
            pid.startswith("rc:")
            and d["state"] == decisions_mod.REMOVE
            and key not in shown
        ):
            finding = review_mod.get(key)
            if (
                finding
                and finding.get("review_run_id") == run_id
                and scope.may_read(finding["document_id"])
            ):
                out[pid] = "a removed rule-check point"
    return out


def database_lines(paper_id: str, scope, facts: dict) -> dict:
    """{"ai": lines of the AI run, "rule_check": rule rows, "added": the engineer's added points, "total": their sum, "ids": every
    point id the database says the page must carry, with a plain label}."""
    conn = connect()
    ids: dict[str, str] = {}
    ai = 0
    if facts.get("ai_run"):
        for r in conn.execute(
            "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ?",
            (facts["ai_run"],),
        ):
            try:
                line = json.loads(r["line_json"] or "{}")
            except ValueError:
                line = {}
            page = f", page {line['paper_page']}" if line.get("paper_page") else ""
            ids[f"ai:{facts['ai_run']}:{r['item_id']}"] = (
                f"an AI line ({_clean(line.get('field')) or r['item_id']}{page})"
            )
            ai += 1
    rc_ids = (
        rule_row_ids(facts["rc_run"], paper_id, scope) if facts.get("rc_run") else {}
    )
    ids.update(rc_ids)
    added_rows = decisions_mod.added(paper_id)
    for r in added_rows:
        ids[f"add:{r['id']}"] = "a point the engineer added"
    return {
        "ai": ai,
        "rule_check": len(rc_ids),
        "added": len(added_rows),
        "total": ai + len(rc_ids) + len(added_rows),
        "ids": ids,
    }


def _clean(text) -> str:
    return " ".join(str(text or "").split())


# ------------------------------------------------------------------------------------------------ rows as built


def _table_rows(ws, first_header: str) -> list[list]:
    values = [list(r) for r in ws.iter_rows(values_only=True)]
    start = next((i for i, r in enumerate(values) if r and r[0] == first_header), None)
    if start is None:
        return []
    return [r for r in values[start + 1 :] if any(c is not None for c in r)]


def rows_in_file(data: bytes, copy: str) -> tuple[int, list[int]]:
    """(rows in the workbook as built, the point numbers found). Team: the sheet CRS and the sheet Removed (record); contractor:
    its one sheet."""
    from . import crs_one

    wb = load_workbook(BytesIO(data), read_only=False)
    if copy == "team":
        rows = _table_rows(wb[crs_one.EVIDENCE_SHEET], "No")
        return len(rows), [r[0] for r in rows if isinstance(r[0], int)]
    rows = _table_rows(wb[crs_one.CONTRACTOR_SHEET], "Item No")
    return len(rows), []


# ------------------------------------------------------------------------------------------------ no cut without a mark


def cut_report(data: bytes, raw: list[dict], wordings: dict | None = None) -> dict:
    """Every long cell of the team file against the point's own full text: {"marked": shortened cells with the mark AND their full text
    beside them, "problems": cells that differ from the full text without the mark, or marked without the full text beside them}."""
    from . import crs_one

    wb = load_workbook(BytesIO(data))
    ws = wb[crs_one.EVIDENCE_SHEET]
    values = [list(r) for r in ws.iter_rows(values_only=True)]
    start = next(i for i, r in enumerate(values) if r and r[0] == "No")
    head = values[start]
    col = {name: head.index(name) for name in crs_one.TEAM_COLUMNS}
    long_col = {
        "action": col["What the contractor must do"],
        "paper_shows": col["What the paper shows"],
        "requires": col["What the rule requires"],
        "reason": col["Reason"],
    }
    by_no = dict(enumerate(raw, start=1))
    marked, problems = 0, []
    for r in values[start + 1 :]:
        if not isinstance(r[0], int) or r[0] not in by_no:
            continue
        for key, full in crs_one.full_texts(by_no[r[0]]).items():
            cell = r[long_col[key]]
            shown = "" if cell is None else str(cell)
            want = crs_one._cell(full) if full else ""
            if (shown or "") == (want or ""):
                continue
            beside = str(r[col["Full text"]] or "")
            body = shown[:-1].rstrip() if shown.endswith(CUT_MARK) else None
            if body is None:
                problems.append(f"row {r[0]}: {key} is cut without the mark")
            elif (
                not str(want).startswith(body)
                or f"{key.replace('_', ' ')}: {full}" not in beside
            ):
                problems.append(
                    f"row {r[0]}: {key} has the mark but not its full text beside it"
                )
            else:
                marked += 1
    marked, problems = _comment_cuts(
        wb[crs_one.TEAM_SHEET], raw, marked, problems, wordings
    )
    return {"marked": marked, "problems": problems}


def _comment_cuts(
    ws, raw: list[dict], marked: int, problems: list[str], wordings: dict | None = None
) -> tuple[int, list[str]]:
    """The same rule for the sheet CRS: each comment's long cells against the full text of its strongest point and its clauses."""
    from . import crs_comments, crs_one

    values = [list(r) for r in ws.iter_rows(values_only=True)]
    start = next(i for i, r in enumerate(values) if r and r[0] == "Comment")
    head = values[start]
    col = {name: head.index(name) for name in crs_one.COMMENT_COLUMNS}
    spots = {
        "action": col["What the contractor must do"],
        "paper_shows": col["What the paper shows"],
        "requires": col["What the rule requires"],
        "reason": col["Reason"],
        "clauses": col["Rule books and clauses"],
    }
    by_no = {c["number"]: c for c in crs_comments.group(raw)}
    for r in values[start + 1 :]:
        if not isinstance(r[0], int) or r[0] not in by_no:
            continue
        for key, full in crs_one.comment_full_texts(by_no[r[0]], wordings).items():
            if key == "code_words":
                if f"code words: {full}" not in str(r[col["Full text"]] or ""):
                    problems.append(
                        f"comment {r[0]}: worded without the code's words beside it"
                    )
                continue
            shown = "" if r[spots[key]] is None else str(r[spots[key]])
            want = crs_one._cell(full) if full else ""
            if shown == (want or ""):
                continue
            body = shown[:-1].rstrip() if shown.endswith(CUT_MARK) else None
            beside = str(r[col["Full text"]] or "")
            if body is None:
                problems.append(f"comment {r[0]}: {key} is cut without the mark")
            elif (
                not str(want).startswith(body)
                or f"{key.replace('_', ' ')}: {full}" not in beside
            ):
                problems.append(
                    f"comment {r[0]}: {key} has the mark but not its full text beside it"
                )
            else:
                marked += 1
    return marked, problems


# ------------------------------------------------------------------------------------------------ the check


def _named(p: dict) -> str:
    page = f", page {p['page']}" if p.get("page") else ""
    return f"{p.get('name') or 'a point'}{page}"


def sentence_of(report: dict) -> str:
    if report["ok"]:
        return "Complete: the page, the database and the file agree."
    parts = [
        f"This CRS file is not complete and was not given out: the page has {report['page']} points, "
        f"the database holds {report['database']['total']} lines, the file accounts for {report['accounted']}."
    ]
    miss = report["missing"]
    if miss:
        shown = "; ".join(miss[:LIST_AT_MOST])
        more = (
            f" and {len(miss) - LIST_AT_MOST} more" if len(miss) > LIST_AT_MOST else ""
        )
        parts.append(f"Missing: {shown}{more}.")
    return " ".join(parts)


def _comment_accounting(data: bytes, raw: list[dict]) -> list[str]:
    """The sheet CRS must hold every comment of the one grouping function, and its Points column must add up to the points that are in
    a comment (every point of the page except the removed ones)."""
    from . import crs_comments, crs_one

    ws = load_workbook(BytesIO(data))[crs_one.TEAM_SHEET]
    rows = _table_rows(ws, "Comment")
    groups = crs_comments.group(raw)
    head = next(
        list(r) for r in ws.iter_rows(values_only=True) if r and r[0] == "Comment"
    )
    at = head.index("Points")
    out = []
    if len(rows) != len(groups):
        out.append(
            f"the sheet CRS has {len(rows)} comments, the grouping has {len(groups)}"
        )
    if sum(int(r[at] or 0) for r in rows) != sum(g["n_points"] for g in groups):
        out.append(
            "the comments on the sheet CRS do not add up to the points they cover"
        )
    return out


def verify(
    paper_id: str,
    scope,
    copy: str,
    data: bytes,
    listing: dict,
    raw: list[dict],
    facts: dict,
) -> dict:
    """The report for one built file. `ok` only when page == database == the file's own count (team), or M + K == page == database
    (contractor)."""
    db = database_lines(paper_id, scope, facts)
    page = listing["of"]
    in_file, numbers = rows_in_file(data, copy)
    missing: list[str] = []
    if copy == "team":
        accounted = in_file
        present = set(numbers)
        missing = [_named(p) for n, p in enumerate(raw, start=1) if n not in present]
    else:
        mine, reasons = contractor_split(raw)
        accounted = in_file + sum(reasons.values())
        if in_file != len(mine):
            missing = [f"{len(mine) - in_file} row(s) of the contractor file"]
    on_page = {p["id"]: p for p in raw}
    missing += [
        f"{label} is stored but not on the page"
        for pid, label in db["ids"].items()
        if pid not in on_page
    ]
    missing += [
        f"{_named(p)} is on the page but not in the database"
        for pid, p in on_page.items()
        if pid not in db["ids"]
    ]
    missing += findings_check(raw, facts.get("ai_run"))
    if copy == "team":
        missing += _comment_accounting(data, raw)
    cuts = (
        cut_report(data, raw, nine_sheet.load_wordings(connect(), facts.get("ai_run")))
        if copy == "team"
        else {"marked": 0, "problems": []}
    )
    missing += cuts["problems"]
    ok = page == db["total"] == accounted and not missing
    report = {
        "ok": ok,
        "copy": copy,
        "page": page,
        "database": {k: v for k, v in db.items() if k != "ids"},
        "rows_in_file": in_file,
        "accounted": accounted,
        "missing": missing,
        "cut_cells_marked": cuts["marked"],
        "cut_problems": len(cuts["problems"]),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    report["sentence"] = sentence_of(report)
    return report


def checked_files(paper_id: str, scope) -> dict:
    """Both files built ONCE, each checked: {"team": (bytes, report), "contractor": (bytes, report)}. Reads only."""
    from . import crs_one
    from . import review_points_service as svc

    listing, raw, facts = svc.export_listing(paper_id, scope)
    out = {}
    for copy, build in (
        ("team", crs_one.build_team),
        ("contractor", crs_one.build_contractor),
    ):
        data = build(paper_id, scope, listing_raw=(listing, raw, facts))
        out[copy] = (data, verify(paper_id, scope, copy, data, listing, raw, facts))
    return out


def file_or_refuse(paper_id: str, scope, copy: str, **build_kw) -> bytes:
    """The file for a download, or `Incomplete` (the caller answers 409 with the sentence)."""
    from . import crs_one
    from . import review_points_service as svc

    listing, raw, facts = svc.export_listing(paper_id, scope)
    build = crs_one.build_team if copy == "team" else crs_one.build_contractor
    data = build(paper_id, scope, listing_raw=(listing, raw, facts), **build_kw)
    report = verify(paper_id, scope, copy, data, listing, raw, facts)
    if not report["ok"]:
        raise Incomplete(report)
    return data


# ------------------------------------------------------------------------------------------------ stored with the run


def ensure_schema(conn=None) -> None:
    conn = conn or connect()
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS crs_completeness (run_id TEXT PRIMARY KEY, paper_id TEXT, checked_at TEXT, ok INTEGER,"
            " page INTEGER, database_lines INTEGER, team_rows INTEGER, contractor_rows INTEGER, detail_json TEXT)"
        )


def record_after_run(run_id: str) -> dict | None:
    """After a review ends: check both files and store the result with the run. Never fails the run (a failure is logged by type and
    the stored result says "not checked"); None when the run has no paper."""
    from . import access

    try:
        row = (
            connect()
            .execute(
                "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
            )
            .fetchone()
        )
        if row is None:
            return None
        paper = row["submittal_document_id"]
        got = checked_files(paper, access.unrestricted_scope())
        team, contractor = got["team"][1], got["contractor"][1]
        ensure_schema()
        with connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO crs_completeness VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id, paper, team["checked_at"], int(team["ok"] and contractor["ok"]), team["page"],
                    team["database"]["total"], team["rows_in_file"], contractor["rows_in_file"],
                    json.dumps({"team": team, "contractor": contractor}),
                ),
            )  # fmt: skip
        if not (team["ok"] and contractor["ok"]):
            log.error(
                "crs completeness: run %s differs (page %s, database %s)",
                run_id,
                team["page"],
                team["database"]["total"],
            )
        return {"team": team, "contractor": contractor}
    except Exception as exc:  # noqa: BLE001 - logged by type; a failed check never fails the review
        log.warning(
            "crs completeness: the check could not run (%s)", type(exc).__name__
        )
        return None


def stored(run_id: str | None) -> dict | None:
    """The result stored with a run, for the page: {"ok", "page", "database", "team_rows", "contractor_rows", "missing", "sentence",
    "checked_at"}; None when the run has none (a run from before the check, or a check that could not run): the page then says nothing."""
    if not run_id:
        return None
    try:
        row = (
            connect()
            .execute(
                "SELECT ok, page, database_lines, team_rows, contractor_rows, detail_json, checked_at FROM crs_completeness WHERE run_id = ?",
                (run_id,),
            )
            .fetchone()
        )
    except Exception as exc:  # noqa: BLE001 - logged by type; no table yet means no stored result
        log.debug("crs completeness: no stored result (%s)", type(exc).__name__)
        return None
    if row is None:
        return None
    detail = json.loads(row["detail_json"] or "{}")
    missing = list(
        dict.fromkeys(
            [
                *(detail.get("team") or {}).get("missing", []),
                *(detail.get("contractor") or {}).get("missing", []),
            ]
        )
    )
    bad = [
        (detail.get(c) or {}).get("sentence")
        for c in ("team", "contractor")
        if not (detail.get(c) or {}).get("ok", True)
    ]
    return {
        "ok": bool(row["ok"]), "page": row["page"], "database": row["database_lines"], "team_rows": row["team_rows"],
        "contractor_rows": row["contractor_rows"], "missing": missing, "sentence": (bad or [None])[0], "checked_at": row["checked_at"],
    }  # fmt: skip


def stored_latest(*run_ids: str | None) -> dict | None:
    """The newest stored result among a paper's runs (each check covers the whole paper at the time it ran)."""
    got = [r for r in (stored(i) for i in run_ids) if r]
    return max(got, key=lambda r: r["checked_at"]) if got else None
