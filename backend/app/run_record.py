"""Plan change 6 G (#1608): what a review run stands on, recorded on the run and printed on its internal CRS.

Parts of this existed apart: `review_runs.model_name` (Claude models only), `absence.unchecked_parts` (the list, printed
among the review notes and nothing when empty), `standards_compiler.record_rule_version` (a version number, nothing that
says which rules), and the checklist importer's `checklist_ticks` table, which no run mentioned. With
`run_record_enabled`:

  * at the end of each comparison, `record_on_run` stores the rulebook (the version used, how many rules of the standards
    applied, a fingerprint of them, the snapshot of a version 2 run, the review code stamp) and the ticks imported;
  * `crs_rows` makes the "Run record" sheet: those, the models the run's own rows name, and the could-not-check list,
    which says so when it is empty. Internal copy only: the issue copy keeps the count and the share (#633).

What is stored is what is printed, so a past run's sheet does not change when the rules do. A run with no record says
"not recorded" and nothing is guessed. A model only configured is never named. Reads only; it creates no table. Ticks and
signed decisions are kept per standard applied and counted only for the standards the reader may read, never named. Nothing here reaches a verdict.
Switch off: nothing is written or printed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3

from openpyxl.styles import Alignment, Font

from .config import settings
from .db import connect

log = logging.getLogger(__name__)

RUN_KEY = "run_record"
BOUNDARY = "the standards applied to this run"
TICKS_WHEN = (
    "of the standards applied to this run that you may read, when the comparison ended"
)
#: The standards a run applied. Ticks, decisions and rules are counted over these and no others.
_APPLIED = (
    "(SELECT standard_document_id FROM review_applicable_standards"
    " WHERE review_run_id = ? AND COALESCE(included, 1) = 1)"
)
NOT_RECORDED = (
    "Not recorded for this run: the comparison did not finish with the run record on."
)
NO_MODEL = "No model is recorded for this run."
NO_TICKS = (
    "No tick has been imported for the standards applied to this run that you may read."
)
#: A rule count over standards this reader may not all read is a count from them: rule 5.
RULES_WITHHELD = "The rule count and fingerprint are shown only to a reader of every standard applied."
TICKS_UNREADABLE = (
    "The checklist tick table could not be read, so the ticks imported are not known."
)
SHEET = "Run record"
COLUMNS = ("Section", "Item", "Detail")
NOTHING_LISTED = "Nothing is known to be unchecked on this run. That does not mean the review is correct."

#: What a rule says and where it was read: not its row id or times, so a re-read with the same words is the same rulebook.
_RULE_COLUMNS = (
    "standard_document_id",
    "clause",
    "page",
    "requirement_text",
    "source_text",
    "equipment_type",
    "service",
    "requirement_type",
    "field",
    "operator",
    "value",
    "unit",
    "raw_value",
    "raw_unit",
    "condition",
)


def enabled() -> bool:
    return bool(settings.run_record_enabled)


def _has_table(conn, name: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return found is not None


def _rules_of(conn, review_run_id: str) -> tuple[int, str | None]:
    """(rules of the standards applied to this run, a hash of their words). No rule: (0, None)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(standard_requirements)")}
    columns = ", ".join(c for c in _RULE_COLUMNS if c in have)
    rows = conn.execute(
        f"SELECT {columns} FROM standard_requirements WHERE standard_document_id IN {_APPLIED}",
        (review_run_id,),
    ).fetchall()
    if not rows:
        return 0, None
    lines = sorted(json.dumps(list(r), default=str) for r in rows)
    return len(lines), hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _applied_ids(conn, review_run_id: str) -> list[str]:
    rows = conn.execute(f"SELECT * FROM {_APPLIED}", (review_run_id,))
    return sorted(r[0] for r in rows)


def _version_used(conn, review_run_id: str, outcome: dict) -> tuple[int, str | None]:
    """(version, snapshot hash). The rulebook's own record first, then the compiler's note, then 1: verdict code reads
    only `standard_requirements` unless a run recorded otherwise."""
    from .compiled_rule_report import run_book
    from .standards_compiler import V1

    recorded = run_book(conn, review_run_id)
    return recorded or ((outcome.get("rule_version") or {}).get("used") or V1, None)


def _review_code(conn, review_run_id: str) -> str | None:
    row = conn.execute(
        "SELECT code_version FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
        (review_run_id,),
    ).fetchone()
    return row[0] if row else None


def _ticks(conn, review_run_id: str) -> dict:
    """The ticks and signed decisions on the standards this run applied, kept per standard so an export can count only
    what its reader may read. A tick reaches its standard through the compiled rule it names; one that names no rule
    of an applied standard is not counted. A table this cannot read says so, never 0."""
    from .compiled_rule_report import decisions_on, rule_documents

    applied = _applied_ids(conn, review_run_id)
    by_standard: dict = {}
    signed: dict = {}
    try:
        if _has_table(conn, "checklist_ticks"):
            document_of = rule_documents(conn, applied)
            for rule, tick, sha, stamp in conn.execute(
                "SELECT rule_id, tick, source_sha256, version_stamp FROM checklist_ticks"
                " WHERE tick IS NOT NULL"
            ):
                if rule not in document_of:
                    continue
                one = by_standard.setdefault(
                    document_of[rule], {"by_tick": {}, "files": [], "stamps": []}
                )
                one["by_tick"][tick] = one["by_tick"].get(tick, 0) + 1
                one["files"] = sorted({*one["files"], sha})
                one["stamps"] = sorted({*one["stamps"], stamp})
        decisions: dict = {}
        for decision_id, decision, doc in decisions_on(conn, applied):
            decisions.setdefault((decision_id, decision), set()).add(doc)
        for (_decision_id, decision), docs in decisions.items():
            key = (decision, tuple(sorted(docs)))
            signed[key] = signed.get(key, 0) + 1
    except sqlite3.OperationalError:
        return {"unreadable": True}
    return {
        "by_standard": by_standard,
        "signed": [
            {"decision": k[0], "standards": list(k[1]), "n": n}
            for k, n in sorted(signed.items())
        ],
    }


def record_on_run(review_run_id: str) -> None:
    """Store the record on the run's outcome. Switch off: nothing. Never raises: a note must not fail a finished review."""
    if not enabled():
        return
    try:
        conn = connect()
        row = conn.execute(
            "SELECT outcome_json FROM review_runs WHERE id = ?", (review_run_id,)
        ).fetchone()
        if row is None:
            return
        outcome = json.loads(row["outcome_json"] or "{}")
        rules, digest = _rules_of(conn, review_run_id)
        version, snapshot = _version_used(conn, review_run_id, outcome)
        outcome[RUN_KEY] = {
            "rulebook": {
                "used_version": version,
                "rules": rules,
                "rules_sha256": digest,
                "snapshot_sha256": snapshot,
                "review_code": _review_code(conn, review_run_id),
                "boundary": BOUNDARY,
                "standards": _applied_ids(conn, review_run_id),
            },
            "ticks": _ticks(conn, review_run_id),
        }
        with conn:
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                (json.dumps(outcome), review_run_id),
            )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.warning("run record %s: %s", review_run_id, type(exc).__name__)


def _loads(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _models(conn, review_run_id: str, run: dict, outcome: dict) -> list[str]:
    """Names the run's own stored rows give for a model that was used. A matcher that asked nothing used nothing."""
    names = {n for n in (run.get("model_name") or "").split(", ") if n}
    ai_check = _loads(run.get("ai_check_status"))
    if ai_check.get("calls_made"):
        names.add(ai_check.get("model"))
    matcher = outcome.get("ai_matcher") or {}
    if matcher.get("asked"):
        names.add(matcher.get("model"))
    if _has_table(conn, "model_call_metrics"):
        names.update(
            r[0]
            for r in conn.execute(
                "SELECT model FROM model_call_metrics WHERE review_run_id = ? AND calls > errors",
                (review_run_id,),
            )
        )
    if _has_table(conn, "crs_ai_wording_runs"):
        row = conn.execute(
            "SELECT summary FROM crs_ai_wording_runs WHERE review_run_id = ?",
            (review_run_id,),
        ).fetchone()
        wording = _loads(row[0]) if row else {}
        if wording.get("tried"):
            names.add(wording.get("model"))
    return sorted(n for n in names if n)


def _rulebook_line(book: dict, allowed: frozenset[str]) -> str:
    if not set(book.get("standards") or ()) <= allowed:
        return f"Version {book['used_version']}. {RULES_WITHHELD}"
    line = (
        f"Version {book['used_version']}: {book['rules']} rule(s) of {book['boundary']}"
    )
    if book.get("rules_sha256"):
        line += f", fingerprint {book['rules_sha256'][:16]}"
    if book.get("snapshot_sha256"):
        line += f", snapshot {book['snapshot_sha256'][:16]}"
    if book.get("review_code"):
        line += f", code {book['review_code']}"
    return line + "."


def _counts(by: dict) -> str:
    return "; ".join(f"{k}: {v}" for k, v in sorted(by.items()))


def _tick_lines(ticks: dict, allowed: frozenset[str]) -> list[str]:
    """Only the standards this reader may read are counted (rule 5: intersection, never union)."""
    if ticks.get("unreadable"):
        return [TICKS_UNREADABLE]
    by_tick: dict = {}
    files: set = set()
    stamps: set = set()
    for doc, one in (ticks.get("by_standard") or {}).items():
        if doc in allowed:
            for tick, n in one["by_tick"].items():
                by_tick[tick] = by_tick.get(tick, 0) + n
            files.update(one["files"])
            stamps.update(one["stamps"])
    lines = [NO_TICKS]
    if by_tick:
        lines = [
            f"{sum(by_tick.values())} tick(s) imported from {len(files)} file(s), {len(stamps)} version"
            f" stamp(s), {TICKS_WHEN}: {_counts(by_tick)}. Stored only: no verdict reads them."
        ]
    signed: dict = {}
    for row in ticks.get("signed") or ():
        if allowed.intersection(row["standards"]):
            signed[row["decision"]] = signed.get(row["decision"], 0) + row["n"]
    if signed:
        lines.append(
            f"Decisions signed into the rulebook, {TICKS_WHEN}: {_counts(signed)}."
        )
    return lines


def crs_meta(
    run: dict,
    outcome: dict,
    unchecked: list[dict],
    missing: list[str],
    copy: str,
    allowed: frozenset[str],
) -> dict:
    """What `main._crs_content` adds to the CRS meta: nothing with the switch off or on the issue copy."""
    if not enabled() or copy != "internal":
        return {}
    return {
        "run_record": crs_rows(run["id"], run, outcome, unchecked, missing, allowed)
    }


def write_sheet(wb, rows: list[tuple[str, str, str]], write) -> None:
    """Draw the sheet. `write` is `crs_export._write`, which stores every string as text."""
    sheet = wb.create_sheet(SHEET)
    for col, header in enumerate(COLUMNS, start=1):
        write(sheet, 1, col, header).font = Font(bold=True)
    for r, row in enumerate(rows, start=2):
        for col, value in enumerate(row, start=1):
            write(sheet, r, col, value).alignment = Alignment(
                wrap_text=True, vertical="top"
            )
    for col, width in (("A", 18), ("B", 22), ("C", 110)):
        sheet.column_dimensions[col].width = width


def crs_rows(
    review_run_id: str,
    run: dict,
    outcome: dict,
    unchecked: list[dict],
    missing: list[str],
    allowed: frozenset[str],
) -> list[tuple[str, str, str]]:
    """The Run record sheet as (section, item, detail) rows. `unchecked` is `absence.unchecked_parts`, `missing` the
    standards cited and not held, both already under the caller's grants."""
    conn = connect()
    stored = outcome.get(RUN_KEY) or {}
    models = _models(conn, review_run_id, run, outcome)
    rows = [("Model", "Stored on this run", ", ".join(models) or NO_MODEL)]
    book = stored.get("rulebook")
    rows.append(
        ("Rulebook", "Used", _rulebook_line(book, allowed) if book else NOT_RECORDED)
    )
    ticks = stored.get("ticks")
    lines = _tick_lines(ticks, allowed) if ticks else [NOT_RECORDED]
    rows += [("Checklist ticks", "Imported", line) for line in lines]
    return rows + _could_not_check(unchecked, missing, models, ticks)


def _could_not_check(unchecked, missing, models, ticks) -> list[tuple[str, str, str]]:
    from .claude_models import LEDGER_UNREADABLE

    section = "Could not check"
    rows = []
    counted = sum(1 for p in unchecked if not p.get("detail"))
    if counted:
        rows.append(
            (
                section,
                "Count",
                f"{counted} part(s) of this review run could not be checked, the count the CRS notice gives.",
            )
        )
    rows += [
        (section, str(p.get("note") or ""), str(p.get("line") or "")) for p in unchecked
    ]
    rows += [
        (
            section,
            "Cited, not held",
            f"{name}: cited by this submittal, not in the library you may read, so not checked.",
        )
        for name in missing
    ]
    if LEDGER_UNREADABLE in models:
        rows.append((section, "Model", LEDGER_UNREADABLE))
    if (ticks or {}).get("unreadable"):
        rows.append((section, "Checklist ticks", TICKS_UNREADABLE))
    return rows or [(section, "None listed", NOTHING_LISTED)]
