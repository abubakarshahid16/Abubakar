"""PF1 (#881): the per-type report of one run of the unfamiliar-datasheet set.

COUNTS ONLY. The report holds numbers, a type name, a layout name and item ids
of a sheet that is NOT held out; never a value, a clause, a standard's text, a
finding's text. Held-out types appear in the totals and nowhere else (not as a
row, not by id): their per-item results stay with the scorer.

What it reads, all local, none in git:
  * `index.json` of the set (`pf1_set.build`): per document the type, the
    layout, `held_out`, the `group` ("library" or "invented") and the key file.
  * `<id>.key.json` (`review-answer-key/1`) beside it.
  * `<runs>/<id>.findings.json` (`review-findings/1`, `review_score export`).
  * `<runs>/<id>.run.json` (`pf1-run/1`): `mode` ("main" or "checklists_off"),
    `status`, `minutes`, `pages_read`, `pages_total`. Written by `pf1_run`.

What it reports per sheet (the #881 table):
  * defects caught / planted, and caught as a plain Does-not-meet;
  * FALSE MEETS on planted defects (a finding called one COMPLIANT): the hard
    rule is 0 from day one, and `blocked()` says when it is not;
  * correct items (met + trap) confirmed Meets, wrongly flagged, undecided;
  * keyed items decided (a verdict: Meets, Does-not-meet or Not applicable);
  * citations valid / checked; pages read; minutes; whether the run finished.

A sheet with no findings file is "no run" - listed and never scored as zeros. A
run that did not finish (`status` not "completed", or fewer pages read than
the sheet has) is marked incomplete beside its numbers, never hidden in them.
Two modes in one report are refused: the MAIN score (the normal client
workflow) and the diagnostic (checklists off) are never added together.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import review_score as rs

REPORT_FORMAT = "pf1-report/1"
RUN_FORMAT = "pf1-run/1"
MODES = ("main", "checklists_off")
MODE_WORDS = {
    "main": "MAIN score (the normal client workflow)",
    "checklists_off": "DIAGNOSTIC (checklists off) - not the main score",
}
#: A finding with one of these statuses carries a verdict on the item.
DECIDED = frozenset({rs.OK_STATUS, "NON_COMPLIANT", rs.NA_STATUS})


class ReportError(ValueError):
    """The set, a key, a findings file or a run record cannot be reported on."""


def _read(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"{what} could not be read: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise ReportError(f"{what} is not a JSON object")
    return data


def load_run_record(path: Path) -> dict:
    data = _read(path, "a run record")
    if data.get("format") != RUN_FORMAT:
        raise ReportError(f"a run record must have format {RUN_FORMAT!r}")
    if data.get("mode") not in MODES:
        raise ReportError(f"a run record's mode must be one of {', '.join(MODES)}")
    return data


def item_statuses(key: dict, findings_doc: dict) -> dict[str, set[str]]:
    """{key item id: the statuses of the findings that answer it}. A finding
    answers at most one item, the most specific (`review_score.match_item`)."""
    items = key["items"]
    out: dict[str, set[str]] = {it["id"]: set() for it in items}
    for finding in findings_doc.get("findings") or []:
        hit = rs.match_item(finding, items)
        if hit is not None:
            out[hit["id"]].add(str(finding.get("compliance_status") or ""))
    return out


def sheet_report(
    entry: dict, key: dict, findings_doc: dict | None, run: dict | None
) -> dict:
    """One sheet's numbers. `findings_doc` None = the sheet was not run."""
    head = {
        "id": entry["id"],
        "equipment_type": entry["equipment_type"],
        "layout": entry["layout"],
        "group": entry.get("group") or "invented",
        "held_out": bool(entry["held_out"]),
        "pages": entry.get("pages"),
    }
    if findings_doc is None:
        return {**head, "run": False}
    key = rs.validate_key(key)
    scored = rs.score(key, findings_doc)
    statuses = item_statuses(key, findings_doc)
    kinds = defaultdict(list)
    for item in key["items"]:
        kinds[item["kind"]].append(item["id"])
    defects = kinds[rs.DEFECT]
    correct = kinds[rs.MET] + kinds[rs.TRAP]
    ok = rs.OK_STATUS

    def has(item_id: str, wanted) -> bool:
        return bool(statuses[item_id] & set(wanted))

    keyed = [it["id"] for it in key["items"]]
    pages_total = (run or {}).get("pages_total") or entry.get("pages")
    pages_read = (run or {}).get("pages_read")
    finished = (
        bool(run)
        and run.get("status") == "completed"
        and (pages_read is None or pages_total is None or pages_read >= pages_total)
    )
    return {
        **head,
        "run": True,
        "mode": (run or {}).get("mode"),
        "defects": len(defects),
        "defects_caught": scored["defects_found"],
        "defects_caught_plain_fail": sum(
            1 for i in defects if "NON_COMPLIANT" in statuses[i]
        ),
        "false_meets": scored["false_compliant"],
        "false_meets_ids": [] if head["held_out"] else scored["false_compliant_ids"],
        "correct_items": len(correct),
        "correct_confirmed_meets": sum(1 for i in correct if has(i, [ok])),
        "correct_wrongly_flagged": sum(1 for i in correct if has(i, rs.FLAG_STATUSES)),
        "correct_undecided": sum(1 for i in correct if not statuses[i]),
        "keyed_items": len(keyed),
        "keyed_decided": sum(1 for i in keyed if has(i, DECIDED)),
        "judged_findings": scored["judged_findings"],
        "correct_findings": scored["correct_findings"],
        "citations_checked": scored["citations_checked"],
        "citations_valid": scored["citations_valid"],
        "ai_use": (run or {}).get("ai"),
        "pages_read": pages_read,
        "pages_total": pages_total,
        "minutes": (run or {}).get("minutes"),
        "status": (run or {}).get("status"),
        "finished": finished,
        "model": findings_doc.get("model"),
    }


SUM_FIELDS = (
    "defects",
    "defects_caught",
    "defects_caught_plain_fail",
    "false_meets",
    "correct_items",
    "correct_confirmed_meets",
    "correct_wrongly_flagged",
    "correct_undecided",
    "keyed_items",
    "keyed_decided",
    "judged_findings",
    "correct_findings",
    "citations_checked",
    "citations_valid",
)


def _ratio(n: int, d: int) -> float | None:
    return (n / d) if d else None


def _totals(rows: list[dict]) -> dict:
    ran = [r for r in rows if r.get("run")]
    out = {
        "sheets": len(rows),
        "sheets_run": len(ran),
        "sheets_not_run": len(rows) - len(ran),
    }
    for name in SUM_FIELDS:
        out[name] = sum(r[name] for r in ran)
    out["incomplete_runs"] = sum(1 for r in ran if not r["finished"])
    out["recall"] = _ratio(out["defects_caught"], out["defects"])
    out["precision"] = _ratio(out["correct_findings"], out["judged_findings"])
    out["citation_validity"] = _ratio(out["citations_valid"], out["citations_checked"])
    out["ai_use"] = sorted(
        {json.dumps(r["ai_use"], sort_keys=True) for r in ran if r.get("ai_use")}
    )
    out["ai_use_not_recorded"] = sum(1 for r in ran if not r.get("ai_use"))
    minutes = [r["minutes"] for r in ran if r.get("minutes") is not None]
    out["minutes"] = round(sum(minutes), 1) if minutes else None
    out["minutes_recorded_for"] = len(minutes)
    return out


def build_report(
    index: dict,
    keys: dict[str, dict],
    findings: dict[str, dict],
    runs: dict[str, dict],
    bar: dict | None = None,
) -> dict:
    """The whole report. `keys`, `findings`, `runs` are keyed by document id."""
    if not isinstance(index, dict) or not isinstance(index.get("documents"), list):
        raise ReportError("the set's index.json has no documents")
    modes = {r.get("mode") for r in runs.values()}
    if len(modes) > 1:
        raise ReportError(
            "the runs mix modes (main and checklists off): report one mode at a time"
        )
    mode = modes.pop() if modes else None
    rows = []
    for entry in index["documents"]:
        doc_id = entry["id"]
        if doc_id not in keys:
            raise ReportError(f"{doc_id}: no answer key was supplied")
        rows.append(
            sheet_report(entry, keys[doc_id], findings.get(doc_id), runs.get(doc_id))
        )
    open_rows = [r for r in rows if not r["held_out"]]
    held = [r for r in rows if r["held_out"]]
    by_group = {
        group: _totals([r for r in open_rows if r["group"] == group])
        for group in sorted({r["group"] for r in open_rows})
    }
    report = {
        "format": REPORT_FORMAT,
        "mode": mode,
        "mode_words": MODE_WORDS.get(mode, "no run record: mode not stated"),
        "models": sorted({r["model"] for r in rows if r.get("run") and r.get("model")}),
        "sheets": [{k: v for k, v in r.items() if k != "held_out"} for r in open_rows],
        "totals": {
            "tuning": _totals(open_rows),
            "held_out": _totals(held),
            "all": _totals(rows),
            "by_group": by_group,
        },
    }
    report["blocked"] = blocked(report)
    if bar is not None:
        report["bar"] = {
            "wanted": bar,
            "status": bar_status(report["totals"]["all"], bar),
        }
    return report


#: The Stage E pass mark (owner decision, order 170.1, final): on the R1 KJO
#: answer key and the R2 blind set. A PF1 set has NO pass mark until the owner
#: sets one after its baseline; `--bar stage-e` shows these four numbers against
#: this bar for a set that is scored for it.
STAGE_E_BAR = {
    "recall": 0.85,
    "precision": 0.80,
    "false_meets": 0,
    "citations_valid": 1.0,
}


def bar_status(totals: dict, bar: dict) -> dict:
    """{"recall": "meets"|"BELOW"|"cannot tell", ...}. A number with no
    denominator is "cannot tell", never a pass."""

    def at_least(value, wanted):
        return (
            "cannot tell"
            if value is None
            else ("meets" if value >= wanted else "BELOW")
        )

    return {
        "recall": at_least(totals["recall"], bar["recall"]),
        "precision": at_least(totals["precision"], bar["precision"]),
        "false_meets": "meets"
        if totals["false_meets"] <= bar["false_meets"]
        else "BELOW",
        "citations_valid": at_least(
            totals["citation_validity"], bar["citations_valid"]
        ),
    }


def blocked(report: dict) -> list[str]:
    """What stops the hard rule: any false Meets on a planted defect, anywhere
    (held-out sheets included - their totals count)."""
    n = report["totals"]["all"]["false_meets"]
    return [f"{n} false Meets on planted defects (the rule is 0)"] if n else []


def _pct(n: int, d: int) -> str:
    return f"{n} of {d}" + (f" ({round(100 * n / d)}%)" if d else "")


def render(report: dict) -> str:
    """Markdown, counts only, ready to post on the tracking comment."""
    lines = [f"**PF1 report - {report['mode_words']}**"]
    if report["models"]:
        lines.append(f"Model: {', '.join(report['models'])}.")
    lines += [
        "",
        "| Sheet | Type | Layout | Defects caught | Plain fail | **False Meets** | "
        "Correct items Meets / wrongly flagged | Decided | Citations | Pages | Min |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["sheets"]:
        if not r["run"]:
            lines.append(
                f"| {r['id']} | {r['equipment_type']} | {r['layout']} | no run | | | | | | | |"
            )
            continue
        pages = (
            "?" if r["pages_read"] is None else f"{r['pages_read']}"
        ) + f"/{r['pages_total']}"
        done = "" if r["finished"] else " INCOMPLETE"
        lines.append(
            f"| {r['id']} | {r['equipment_type']} | {r['layout']} | "
            f"{r['defects_caught']} of {r['defects']} | {r['defects_caught_plain_fail']} | "
            f"**{r['false_meets']}** | {r['correct_confirmed_meets']} of {r['correct_items']} / "
            f"{r['correct_wrongly_flagged']} | {r['keyed_decided']} of {r['keyed_items']} | "
            f"{r['citations_valid']} of {r['citations_checked']} | {pages}{done} | "
            f"{'-' if r['minutes'] is None else r['minutes']} |"
        )
    lines.append("")
    for label, t in (
        ("Tuning types", report["totals"]["tuning"]),
        ("Held-out types (totals only)", report["totals"]["held_out"]),
        ("All sheets", report["totals"]["all"]),
    ):
        if not t["sheets"]:
            continue
        lines.append(
            f"**{label}** ({t['sheets_run']} of {t['sheets']} sheets run"
            f"{', ' + str(t['incomplete_runs']) + ' incomplete' if t['incomplete_runs'] else ''}): "
            f"defects caught {_pct(t['defects_caught'], t['defects'])} "
            f"({t['defects_caught_plain_fail']} as a plain Does-not-meet); "
            f"**false Meets on planted defects {t['false_meets']}** (rule: 0); "
            f"correct items confirmed Meets {_pct(t['correct_confirmed_meets'], t['correct_items'])}, "
            f"wrongly flagged {t['correct_wrongly_flagged']}; "
            f"keyed items decided {_pct(t['keyed_decided'], t['keyed_items'])}; "
            f"citations valid {_pct(t['citations_valid'], t['citations_checked'])}; "
            f"minutes {t['minutes'] if t['minutes'] is not None else 'not recorded'}"
            f"{'' if t['minutes'] is None else ' (' + str(t['minutes_recorded_for']) + ' sheets)'}."
        )
    t = report["totals"]["all"]
    if t["sheets_run"]:
        ratio = lambda v: "cannot tell" if v is None else f"{round(100 * v)}%"  # noqa: E731
        lines.append(
            f"**The four numbers (all sheets run):** recall {ratio(t['recall'])}, "
            f"precision {ratio(t['precision'])}, false Meets {t['false_meets']}, "
            f"citations valid {ratio(t['citation_validity'])}."
        )
        lines.append(
            "AI use: "
            + ("; ".join(t["ai_use"]) if t["ai_use"] else "not recorded")
            + (
                f" ({t['ai_use_not_recorded']} sheet(s) without a record)"
                if t["ai_use"] and t["ai_use_not_recorded"]
                else ""
            )
            + "."
        )
    if "bar" in report:
        wanted = report["bar"]["wanted"]
        lines.append(
            "Against the Stage E pass mark (recall >= "
            f"{round(100 * wanted['recall'])}%, precision >= {round(100 * wanted['precision'])}%, "
            "0 false Meets, 100% valid citations): "
            + ", ".join(
                f"{k.replace('_', ' ')} {v}" for k, v in report["bar"]["status"].items()
            )
            + "."
        )
    for group, t in report["totals"]["by_group"].items():
        lines.append(
            f"- {group} group: defects caught {_pct(t['defects_caught'], t['defects'])}, "
            f"false Meets {t['false_meets']}, correct items confirmed Meets "
            f"{_pct(t['correct_confirmed_meets'], t['correct_items'])}."
        )
    lines.append("")
    lines.append(
        "BLOCKED: " + "; ".join(report["blocked"])
        if report["blocked"]
        else "Hard rule holds: 0 false Meets on planted defects."
    )
    lines.append(
        "The first run of a set is the baseline: no pass or fail until the owner sets the target."
    )
    return "\n".join(lines) + "\n"


def outcome_facts(outcome: dict | None) -> dict:
    """From a run's stored outcome (`review_runs.outcome_json`): the page counts
    and the AI use a run record states. Pure; numbers and engine names only.
    `pages_read` is the pages not left unread (a page read with no checklist
    field counts as read); None when the run stored no page total."""
    outcome = outcome or {}
    cov = outcome.get("page_coverage") or {}
    total = cov.get("pages_total")
    unread = set(cov.get("pages_not_read_into_fields") or []) | set(
        cov.get("pages_ai_not_read") or []
    )
    split = outcome.get("requirement_split") or {}
    reader = split.get("reader") or {}
    matcher = outcome.get("ai_matcher") or {}
    ai = {
        "reader": reader.get("engine"),
        "reader_model": reader.get("model"),
        "matcher": matcher.get("engine"),
        "matcher_model": matcher.get("model"),
    }
    ai["claude"] = any("claude" in str(v or "").lower() for v in ai.values())
    return {
        "pages_total": total,
        "pages_read": None if total is None else max(0, total - len(unread)),
        "ai": {k: v for k, v in ai.items() if v not in (None, "")},
    }


def complete_record(record: dict, outcome: dict | None, mode: str) -> dict:
    """A runner's record plus what the report needs: the declared `mode`, the
    page counts and the AI use. The runner's own fields are kept."""
    if mode not in MODES:
        raise ReportError(f"mode must be one of {', '.join(MODES)}")
    return {**record, "mode": mode, **outcome_facts(outcome)}


def load_set(
    set_dir: str | Path, runs_dir: str | Path
) -> tuple[dict, dict, dict, dict]:
    """(index, keys, findings, runs) from the folders; a missing findings or run
    file means the sheet was not run."""
    root, runs_root = Path(set_dir), Path(runs_dir)
    index = _read(root / "index.json", "the set's index.json")
    keys, findings, runs = {}, {}, {}
    for entry in index.get("documents") or []:
        doc_id = entry["id"]
        keys[doc_id] = rs.load_key(root / entry["key"])
        found = runs_root / f"{doc_id}.findings.json"
        if found.exists():
            findings[doc_id] = rs.load_findings(found)
        record = runs_root / f"{doc_id}.run.json"
        if record.exists():
            runs[doc_id] = load_run_record(record)
    return index, keys, findings, runs
