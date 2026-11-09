"""The scorer bridge and the local result files of the agent proof test runner (#1690, part of #805).

Split out of `agent_run` (file size ratchet). See the `agent_run` module note for the scorer contract: sheet "CRS" holds
the problems (RED, YELLOW), "Contractor" the contractor copy, "Checked OK" the GREEN rows (internal only). RESULTS.md holds
counts, spend, minutes and model names only: no document or standard text. EXAMPLES.md and crs.xlsx are LOCAL files.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import agent_loop, agent_run_stats, agent_trace

CRS_SHEET = "CRS"
CONTRACTOR_SHEET = "Contractor"
CHECKED_SHEET = "Checked OK"
CRS_HEADERS = (
    "Sr. No.",
    "Item",
    "Topic",
    "Page No./Section",
    "Standard Reference",
    "Comments",
    "Colour",
    "Priority",
    "Required action",
)
CONTRACTOR_HEADERS = (
    "Sr. No.",
    "Page No./Section",
    "Standard Reference",
    "Comments",
    "Priority",
)
MIN_FILLED_CELLS = 5  # the scorer's definition of a comment row
EXAMPLES = 5
FILES = {
    "finals": "finals.json",
    "second": "second_opinion.json",
    "meta": "run_meta.json",
    "results": "RESULTS.md",
    "examples": "EXAMPLES.md",
    "crs": "crs.xlsx",
    "editions": "editions.json",
}
_ENGINEER_WORDS = re.compile(
    r"\b(engineer|agent|model|second opinion|yellow|green|red flag|ai|llm|claude)\b",
    re.I,
)


# ---- the bridge to the scorer -----------------------------------------------------------------------------------


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _cell(value: Any) -> Any:
    """A cell value that can never be read as a formula."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = _clean(value)
    return " " + text if text[:1] in ("=", "+", "-", "@") else text


def _comment(finding: dict, topic: str) -> str:
    """What is wrong / where / against what / what to do. A missing piece is left out, never zero-filled."""
    colour = finding.get("color")
    what = _clean(finding.get("reason"))
    if not what:
        what = {
            "RED": "Does not comply.",
            "GREEN": "Complies.",
            "YELLOW": "Needs a decision.",
        }.get(colour, "")
    parts = [f"{topic}: {what}" if topic else what]
    if colour != "GREEN":
        quote_ = _clean(finding.get("doc_quote"))
        if quote_:
            parts.append(f"The document states: {quote_[:160]}")
    std = _clean(finding.get("standard"))
    clause = _clean(finding.get("clause"))
    against = " ".join(x for x in (std, f"clause {clause}" if clause else "") if x)
    if against:  # the page is written once per row, in the Page cell (_page_cell)
        parts.append(f"Against {against}")
    action = _clean(finding.get("action"))
    if action:
        parts.append(f"Required action: {action}")
    return ". ".join(p.rstrip(".") for p in parts if p) + "."


def contractor_actionable(finding: dict, comment: str) -> bool:
    """RED or YELLOW, a page, a stated action, and no engineer / model / colour words anywhere in the comment."""
    action = _clean(finding.get("action"))
    return bool(
        finding.get("color") in ("RED", "YELLOW")
        and finding.get("page") not in (None, "")
        and action
        and not _ENGINEER_WORDS.search(comment)
    )


def crs_rows_from_findings(
    findings: Iterable[dict], topics: dict[str, str] | None = None
) -> list[dict]:
    """One row per finding. `topics` maps item id -> the skill item's topic (never the answer key)."""
    topics = topics or {}
    rows = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        item = str(f.get("item"))
        topic = _clean(f.get("topic") or topics.get(item, ""))
        comment = _comment(f, topic)
        colour = f.get("color") if f.get("color") in agent_loop.COLOURS else "YELLOW"
        rows.append(
            {
                "item": item,
                "topic": topic,
                "page": f.get("page"),
                "standard": _clean(f.get("standard")),
                "clause": _clean(f.get("clause")),
                "comment": comment,
                "color": colour,
                "priority": f.get("priority"),
                "action": _clean(f.get("action")),
                "internal_only": colour == "GREEN",
                "contractor": contractor_actionable({**f, "color": colour}, comment),
            }
        )
    return rows


def _page_cell(page: Any) -> str | None:
    """'p.<n>' once per row, or nothing (the scorer matches page digits as a substring of the whole row)."""
    return None if page in (None, "") else f"p.{page}"


def _std_ref(row: dict) -> str | None:
    return " ".join(x for x in (row["standard"], row["clause"]) if x) or None


def write_crs_xlsx(rows: list[dict], path: str | os.PathLike) -> Path:
    """The local workbook: sheets "CRS" (problems), "Contractor" (contractor copy), "Checked OK" (GREEN, internal)."""
    import openpyxl

    wb = openpyxl.Workbook()
    crs = wb.active
    crs.title = CRS_SHEET
    crs.append(list(CRS_HEADERS))
    contractor = wb.create_sheet(CONTRACTOR_SHEET)
    contractor.append(list(CONTRACTOR_HEADERS))
    ok = wb.create_sheet(CHECKED_SHEET)
    ok.append(list(CRS_HEADERS))
    for row in rows:
        values = [
            row["item"],
            row["topic"],
            _page_cell(row["page"]),
            _std_ref(row),
            row["comment"],
            row["color"],
            row["priority"],
            row["action"],
        ]
        if row["internal_only"]:
            ok.append([ok.max_row, *map(_cell, values)])
            continue
        crs.append([crs.max_row, *map(_cell, values)])
        if row["contractor"]:
            contractor.append(
                [
                    contractor.max_row,
                    _cell(_page_cell(row["page"])),
                    _cell(_std_ref(row)),
                    _cell(row["comment"]),
                    _cell(row["priority"]),
                ]
            )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


# ---- local files ------------------------------------------------------------------------------------------------


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    agent_trace._atomic_write(path, json.dumps(data, sort_keys=True))


def quote_verified(findings: list[dict], sink: Any) -> int:
    """Findings whose document quote code accepted (they sit in the run's finding sink) and that carry one."""
    n = 0
    for f in findings:
        stored = sink.get(f.get("item"))
        if stored is not None and _clean(stored.get("doc_quote")):
            n += 1
    return n


def _headline(count: dict, findings: list[dict], second_ran: bool) -> str:
    not_sure = sum(1 for f in findings if f.get("color") not in count)
    if second_ran:
        return (
            f"- GREEN {count['GREEN']}, YELLOW {count['YELLOW']}, RED {count['RED']}, "
            f"not sure {not_sure}"
        )
    return (
        f"- GREEN {count['GREEN']} and RED {count['RED']} (second opinion not run: not decided), "
        f"YELLOW {count['YELLOW']}, not sure {not_sure}"
    )


def _edition_lines(editions: dict | None) -> list[str]:
    """Per standard: its edition and the printed line that confirms it, or 'edition not confirmed'."""
    lines = []
    for std, ev in sorted((editions or {}).items()):
        if ev.get("status") != "confirmed":
            lines.append(f"- Edition: {std} {ev.get('edition')}: edition not confirmed")
        elif ev.get("page") is not None:
            lines.append(
                f"- Edition: {std} {ev.get('edition')} p.{ev['page']} verified: {ev.get('quote')}"
            )
        else:
            lines.append(
                f"- Edition: {std} {ev.get('edition')} verified from the file name"
            )
    return lines


def _sweep_lines(findings: list[dict], sweep_items: int) -> list[str]:
    """Items and findings are different counts for a sweep item; say both (they are all YELLOW at most)."""
    if not sweep_items:
        return []
    n = sum(1 for f in findings if f.get("sweep"))
    return [
        f"- Sweep: {n} sweep findings from {sweep_items} sweep items (sweep findings are never GREEN or RED)"
    ]


def write_results(
    run_dir: Path,
    *,
    findings: list[dict],
    verified: int,
    spend: float,
    seconds: float,
    lead_models: list[str],
    opinion_models: list[str],
    skill: dict,
    document_id: str,
    problems: list[str],
    stopped: str,
    second_ran: bool,
    editions: dict | None = None,
    stats: Any = None,
    items_done: int | None = None,
    sweep_items: int = 0,
) -> Path:
    """RESULTS.md: counts, spend, minutes, model names. No document or standard text."""
    shown = agent_run_stats.view(
        stats, problems
    )  # the same source as LIVE.md and the STATUS box
    extra = shown[0][len(problems) :] or (
        agent_run_stats.stat_lines(stats) if stats else []
    )
    count = dict.fromkeys(("GREEN", "YELLOW", "RED"), 0)
    for f in findings:
        count[f["color"] if f.get("color") in count else "YELLOW"] += 1
    sec = [f.get("second_opinion") for f in findings]
    models = ", ".join(lead_models) or "not reported by the provider"
    other = ", ".join(opinion_models) or (
        "not reported by the provider" if second_ran else "no second opinion run"
    )
    lines = [
        "# RESULTS (local file, never committed)",
        "",
        f"- Skill: {skill.get('kind')} version {skill.get('version')}",
        f"- Document id: {document_id}",
        f"- Items finished: {len(findings) if items_done is None else items_done}"
        + (f" (run paused: {agent_trace.words(stopped)})" if stopped else ""),
        _headline(count, findings, second_ran) + shown[1],
        f"- Quote verified by code: {verified} of {len(findings)} findings",
        *_sweep_lines(findings, sweep_items),
        f"- Second opinion: agreed {sec.count('agreed')}, disagreed {sec.count('disagreed')}, "
        f"no answer {sec.count('no answer')}, not run {sec.count('not run')}",
        f"- Spend: USD {spend:.2f}",
        f"- Minutes: {seconds / 60:.1f}",
        f"- Lead model (reported by the provider's response): {models}",
        f"- Second-opinion model (reported by the provider's response): {other}",
        *_edition_lines(editions),
        "- Scoring note: the scorer matches page digits as a substring; YELLOW rows count as raised",
        "- Wrong verdicts: not measured (needs the key score)",
        f"- Problems: {agent_run_stats.count_for_results(stats, problems)}"
        + ("; " + "; ".join(problems[-5:]) if problems else ""),
        *[f"- {w}" for w in extra],
    ]
    path = run_dir / FILES["results"]
    agent_trace._atomic_write(path, "\n".join(lines) + "\n")
    return path


def pick_examples(rows: list[dict], n: int = EXAMPLES) -> list[dict]:
    """Up to n rows, spread over RED, YELLOW, GREEN in turn."""
    by = {c: [r for r in rows if r["color"] == c] for c in ("RED", "YELLOW", "GREEN")}
    out: list[dict] = []
    while len(out) < n and any(by.values()):
        for colour in ("RED", "YELLOW", "GREEN"):
            if by[colour] and len(out) < n:
                out.append(by[colour].pop(0))
    return out


def write_examples(run_dir: Path, rows: list[dict]) -> Path:
    """EXAMPLES.md: 5 comments. LOCAL ONLY: it holds comment text."""
    lines = ["# Example comments (local file, never committed)", ""]
    for i, r in enumerate(pick_examples(rows), 1):
        lines += [f"{i}. [{r['color']}] {r['comment']}", ""]
    path = run_dir / FILES["examples"]
    agent_trace._atomic_write(path, "\n".join(lines))
    return path
