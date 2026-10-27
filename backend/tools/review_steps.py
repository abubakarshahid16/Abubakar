"""Per-step scores of a review run against a key (#832, R28). Counts only, never document text.

`review_score.score` judges the DECISION step (is a defect flagged, is a met item left alone).
A review has more steps, and a wrong answer at an early one (the sheet was read badly, the wrong
standards were chosen) shows up late as a wrong verdict. This scores each step on its own, so a
change is blamed on the step it changed:

| step | what is compared | needs |
|---|---|---|
| reading | the fields the key says the sheet holds / the fields the run read | key `fields_read`, findings file `fields_read` |
| standards chosen | the standards the key says apply / the standards the run selected | key `standards_chosen`, findings file `standards_selected` |
| pairing | for each key item that names a field: did the finding that answers it name that field | key items with `field` |
| decision | defects found, and findings right (from `review_score.score`) | the usual key |
| CRS wording | NOT SCORED: a person reads wording; no automatic key exists | - |

Precision of the reading and standards steps is given only when the key says its list is
complete (`fields_complete`, `standards_complete`); otherwise the extra things the run named are
counted and not judged. A step the key or the file gives nothing for is "not scored", with the
reason; it is never 0 and never 100 %. A table across keys SUMS counts per document type
(`document_type` in the key) and then divides: percentages are never averaged.
"""

from __future__ import annotations

import datetime
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

STEPS = ("reading", "standards", "pairing", "decision", "crs_wording")
NOT_SCORED_WORDING = "not scored: a person reads the wording; no automatic key exists"
UNSTATED_TYPE = "document type not stated"


def _fold(text: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9.]+", " ", str(text or "").lower()).split())


def _words(text: object) -> set[str]:
    return {
        w for w in _fold(text).replace(".", " ").split() if len(w) >= 2 or w.isdigit()
    }


def _ratio(n: int, d: int) -> float | None:
    return (n / d) if d else None


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def check_key_fields(key: dict) -> None:
    """The optional per-step sections must have the right shape; a bad one is refused, not skipped."""
    for name in ("fields_read", "standards_chosen"):
        value = key.get(name)
        if value is not None and (
            not isinstance(value, list)
            or not all(isinstance(x, str) and x.strip() for x in value)
        ):
            raise ValueError(f"{name} must be a list of non-empty strings")
    for name in ("fields_complete", "standards_complete"):
        if name in key and not isinstance(key[name], bool):
            raise ValueError(f"{name} must be true or false")
    if "document_type" in key and not isinstance(key["document_type"], str):
        raise ValueError("document_type must be a string")


def _same_standard(wanted: str, other: str) -> bool:
    a, b = _fold(wanted), _fold(other)
    if a and (a in b or b in a):
        return True
    from app import standard_ids

    return standard_ids.same_standard(wanted, other)


def _same_field(wanted: str, other: str) -> bool:
    """Every word of the key's field is among the words of the field the run read."""
    want = _words(wanted)
    return bool(want) and want <= _words(other)


def _list_step(wanted: object, have: object, same, complete: bool, what: str) -> dict:
    """recall and (when the key's list is complete) precision of one list-vs-list step."""
    if not isinstance(wanted, list) or not wanted:
        return {"scored": False, "why": f"not scored: the key lists no {what}"}
    if not isinstance(have, list):
        return {
            "scored": False,
            "why": f"not scored: the findings file lists no {what}",
        }
    wanted_s = [str(x) for x in wanted]
    have_s = [str(x) for x in have]
    found = [w for w in wanted_s if any(same(w, h) for h in have_s)]
    extra = [h for h in have_s if not any(same(w, h) for w in wanted_s)]
    out = {
        "scored": True,
        "recall": [len(found), len(wanted_s)],
        "missed": len(wanted_s) - len(found),
        "extra": len(extra),
        "precision": None,
        "precision_note": None,
    }
    if complete:
        out["precision"] = [len(have_s) - len(extra), len(have_s)] if have_s else None
    else:
        out["precision_note"] = (
            f"{len(extra)} extra not judged: the key does not say its list is complete"
        )
    return out


def _pairing(key: dict, findings: list[dict], match_item) -> dict:
    """Of the key items that name a field and have an answering finding: how many were answered
    by a finding that itself names that field."""
    right = wrong = unanswered = 0
    items = [
        it for it in key["items"] if it.get("field") and it["kind"] != "not_applicable"
    ]
    if not items:
        return {
            "scored": False,
            "why": "not scored: the key names no field on any item",
        }
    answering: dict[str, list[dict]] = defaultdict(list)
    for finding in findings:
        item = match_item(finding, key["items"])
        if item is not None:
            answering[item["id"]].append(finding)
    for item in items:
        fs = answering.get(item["id"])
        if not fs:
            unanswered += 1
        elif any(_same_field(item["field"], str(f.get("field") or "")) for f in fs):
            right += 1
        else:
            wrong += 1
    return {
        "scored": True,
        "recall": [right, len(items)],
        "precision": [right, right + wrong] if right + wrong else None,
        "paired_wrong": wrong,
        "no_answering_finding": unanswered,
    }


def step_scores(key: dict, findings_doc: dict, decision: dict, match_item) -> dict:
    """The five steps for one key and one run. `decision` is `review_score.score`'s result."""
    findings = findings_doc.get("findings") or []
    decision_step = {
        "scored": bool(decision.get("defects")),
        "recall": [decision["defects_found"], decision["defects"]],
        "precision": [decision["correct_findings"], decision["judged_findings"]]
        if decision.get("judged_findings")
        else None,
    }
    if not decision.get("defects"):
        decision_step["why"] = "not scored: the key lists no defect"
    return {
        "key": key.get("name"),
        "document_type": str(key.get("document_type") or "").strip() or UNSTATED_TYPE,
        "model": findings_doc.get("model"),
        "steps": {
            "reading": _list_step(
                key.get("fields_read"),
                findings_doc.get("fields_read"),
                _same_field,
                bool(key.get("fields_complete")),
                "fields read",
            ),
            "standards": _list_step(
                key.get("standards_chosen"),
                findings_doc.get("standards_selected"),
                _same_standard,
                bool(key.get("standards_complete")),
                "standards chosen",
            ),
            "pairing": _pairing(key, findings, match_item),
            "decision": decision_step,
            "crs_wording": {"scored": False, "why": NOT_SCORED_WORDING},
        },
    }


def _pct(pair) -> str:
    if not pair or not pair[1]:
        return "-"
    return f"{pair[0]} of {pair[1]} ({round(100 * pair[0] / pair[1])}%)"


def _sum(pairs: list) -> list[int] | None:
    pairs = [p for p in pairs if p and p[1]]
    return [sum(p[0] for p in pairs), sum(p[1] for p in pairs)] if pairs else None


def table(results: list[dict]) -> str:
    """Markdown: per document type and step, recall, precision and F1 from SUMMED counts."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        groups[r["document_type"]].append(r)
    lines = [
        "| document type | step | recall | precision | F1 | keys |",
        "|---|---|---|---|---|---|",
    ]
    for dtype in sorted(groups):
        rs_ = groups[dtype]
        for step in STEPS:
            scored = [r["steps"][step] for r in rs_ if r["steps"][step]["scored"]]
            if not scored:
                why = next(
                    (
                        r["steps"][step].get("why")
                        for r in rs_
                        if r["steps"][step].get("why")
                    ),
                    "",
                )
                lines.append(
                    f"| {dtype} | {step} | {why or 'not scored'} | | | 0 of {len(rs_)} |"
                )
                continue
            rec = _sum([s.get("recall") for s in scored])
            pre = _sum([s.get("precision") for s in scored])
            score = f1(_ratio(*pre) if pre else None, _ratio(*rec) if rec else None)
            lines.append(
                f"| {dtype} | {step} | {_pct(rec)} | {_pct(pre) if pre else 'not judged'} | "
                f"{'-' if score is None else f'{score:.2f}'} | {len(scored)} of {len(rs_)} |"
            )
    return "\n".join(lines) + "\n"


def per_step_lists(conn: sqlite3.Connection, run_id: str) -> dict:
    """The standards the run selected and the fields read from the sheet, as names only, for the
    reading and standards steps. A database that lacks a table gives NO list (the step then reads
    "not scored"), never an empty one that reads as "none"."""
    try:
        return _per_step_lists(conn, run_id)
    except sqlite3.OperationalError:
        return {}


def _per_step_lists(conn: sqlite3.Connection, run_id: str) -> dict:
    run = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    chosen = [
        r[0]
        for r in conn.execute(
            "SELECT COALESCE(d.filename, a.standard_document_id)"
            " FROM review_applicable_standards a"
            " LEFT JOIN documents d ON d.id = a.standard_document_id"
            " WHERE a.review_run_id = ? AND COALESCE(a.included, 1) = 1 ORDER BY 1",
            (run_id,),
        )
    ]
    read = (
        [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT field_name FROM submittal_facts"
                " WHERE submittal_document_id = ? ORDER BY 1",
                (run[0],),
            )
        ]
        if run
        else []
    )
    return {"standards_selected": chosen, "fields_read": read}


def report(keys_dir: Path, runs_dir: Path, week: str) -> str:
    """The per-step table per document type, counts only. Hidden-exam keys are never read (#650)."""
    from . import review_score as rs

    results, no_run, unusable = [], [], []
    for path in sorted(keys_dir.glob("*.json")):
        try:
            key = rs.load_key(path)
        except rs.KeyError_ as exc:
            unusable.append(f"{path.name}: {exc}")
            continue
        if key["source"] == "hidden_exam":
            continue
        run_file = runs_dir / f"{key.get('name') or path.stem}.findings.json"
        if not run_file.exists():
            no_run.append(key.get("name") or path.stem)
            continue
        found = rs.load_findings(run_file)
        results.append(step_scores(key, found, rs.score(key, found), rs.match_item))
    out = [f"## Review score by step, {week}", ""]
    out.append(table(results) if results else "No key was scored.")
    if no_run:
        out.append(
            f"Keys with no run (not scored, no number given): {', '.join(no_run)}."
        )
    out += [f"Key not usable: {note}" for note in unusable]
    out.append(
        "Recall and precision are SUMMED counts per document type, never averaged percentages. "
        "Gold-lite and invented keys show change between runs; they do not prove a verdict is right."
    )
    return "\n".join(out) + "\n"


def run_steps(keys_dir: str, runs_dir: str, week: str | None, out: str | None) -> int:
    """The `steps` command. Refuses a hidden-exam folder: that is scored only by the merger session."""
    if "hidden-exam" in str(keys_dir).replace("\\", "/").lower():
        print("REFUSED: the hidden exam is scored only by the merger session (#650).")
        return 2
    week = week or "{}-W{:02d}".format(*datetime.date.today().isocalendar()[:2])
    text = report(Path(keys_dir), Path(runs_dir), week)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    print(text)
    return 0
