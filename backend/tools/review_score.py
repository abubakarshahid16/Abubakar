"""The north-star review score (#676): did a review find the real defects, and
only those?

P1 scores chat answers. This scores a REVIEW RUN's findings against an ANSWER
KEY (format `review-answer-key/1`, documented in `eval/review/README.md`). The
numbers, each with its denominator and none of them folded into another:

  recall             defects found / defects in the key
  precision          correct findings / findings the key can judge
  false compliant    defects a finding called COMPLIANT. Must be 0.
  false not-applic.  items that apply (defect, met, trap) a finding called
                     NOT_APPLICABLE
  trap false flags   traps (look wrong, are fine) a finding flagged / traps
  citation validity  findings whose cited page (and clause) really contain the
                     requirement / findings checked. NOT CHECKED without page
                     text: never reported as 100%.

A finding is matched to a key item by standard + clause (the finding's clause
equals the item's or is a subclause of it) and, when the item names a field, by
that field's words appearing in the finding's requirement or matched phrase.
Each finding answers at most one item (the most specific). A finding no item
matches is "not judged by the key"; it counts against precision only when the
key says it covers the whole sheet (`complete_for_flags`).

Pure: no database, no network, no model, no document text in the RESULT (item
ids and counts only). `scripts/review_score.py` supplies the findings.
Nothing here opens, names or defaults to any hidden-exam folder: a key is
always passed in by the person running it.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Callable

KEY_FORMAT = "review-answer-key/1"
FINDINGS_FORMAT = "review-findings/1"
BASELINE_FORMAT = "review-baseline/1"

DEFECT, MET, TRAP, NOT_APPLICABLE_ITEM = "defect", "met", "trap", "not_applicable"
ITEM_KINDS = (DEFECT, MET, TRAP, NOT_APPLICABLE_ITEM)
SOURCES = ("invented", "engineer_confirmed", "hidden_exam")

#: A finding that asks a human, or says a requirement is not met.
FLAG_STATUSES = frozenset({"NON_COMPLIANT", "MISSING_INFORMATION", "CONDITIONAL", "NEEDS_ENGINEER_REVIEW"})
OK_STATUS = "COMPLIANT"
NA_STATUS = "NOT_APPLICABLE"

#: The proposed world-class bar (owner to confirm; Claude's recommendation, not
#: a measurement). Read from `eval/review/baseline.json` when present.
PROPOSED_BAR = {"recall": 0.8, "trap_false_flag_rate": 0.1, "false_compliant": 0, "citations_valid": 1.0}


class KeyError_(ValueError):
    """The answer key or findings file cannot be scored as written."""


# --------------------------------------------------------------------- loading

def _fold(text: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9.]+", " ", str(text or "").lower()).split())


def _words(text: object) -> list[str]:
    return [w for w in _fold(text).replace(".", " ").split() if len(w) >= 2 or w.isdigit()]


def load_key(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeyError_(f"the answer key could not be read: {type(exc).__name__}") from exc
    return validate_key(data)


def validate_key(data: object) -> dict:
    if not isinstance(data, dict) or data.get("format") != KEY_FORMAT:
        raise KeyError_(f"the answer key must be a JSON object with format {KEY_FORMAT!r}")
    source = data.get("source")
    if source not in SOURCES:
        raise KeyError_(f"source must be one of {', '.join(SOURCES)}")
    if source == "engineer_confirmed" and not str(data.get("approved_by") or "").strip():
        raise KeyError_("an engineer_confirmed key must name the engineer who approved it (approved_by)")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise KeyError_("the answer key has no items")
    seen: set[str] = set()
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise KeyError_(f"item {n} is not an object")
        iid = str(item.get("id") or "").strip()
        if not iid or iid in seen:
            raise KeyError_(f"item {n} needs a unique id")
        seen.add(iid)
        if item.get("kind") not in ITEM_KINDS:
            raise KeyError_(f"item {iid}: kind must be one of {', '.join(ITEM_KINDS)}")
        if not str(item.get("standard") or "").strip() or not str(item.get("clause") or "").strip():
            raise KeyError_(f"item {iid}: standard and clause are required")
    return data


#: A clause number right after a standard identifier in a CRS comment:
#: "API 520-I 5.3.3", "SAES-J-600 clause 8", "(API RP 520 Part I, section 5.2)".
_CLAUSE_AFTER = re.compile(
    r"^[\s,;:()\[\]-]{0,4}(?:(?:clause|cl|section|sec|para(?:graph)?|\u00a7)\.?\s*)?"
    r"(\d+(?:\.\d+)*[a-z]?)\b", re.IGNORECASE)
CRS_HEADER = "company comment"


def key_from_crs(rows: list[tuple], *, name: str, approved_by: str) -> tuple[dict, list[dict]]:
    """#747: a DRAFT answer key from a real Comment Resolution Sheet (the
    client's template: a header row with "COMPANY Comments"). Each comment
    becomes one `defect` item: the standard and the clause it names (the first
    standard followed by a clause number), and the field from "Page
    No./Section" ("p.3 - Set pressure"). A comment whose standard or clause
    cannot be read is NOT guessed: it is returned in the to-complete list with
    its row number only, never its text. The key is `engineer_confirmed`
    (the comments are a named engineer's) but every item's `note` says it was
    drafted by code: the merger checks each before scoring."""
    from app import datasheets
    if not str(approved_by or "").strip():
        raise KeyError_("approved_by is required: the engineer (or CRS) the comments come from")
    header_at = next((i for i, row in enumerate(rows)
                      if any(str(c or "").strip().lower().startswith(CRS_HEADER) for c in row)), None)
    if header_at is None:
        raise KeyError_("no 'COMPANY Comments' header row: not a CRS in the client template")
    head = [str(c or "").strip().lower() for c in rows[header_at]]

    def col(prefix: str) -> int | None:
        return next((i for i, h in enumerate(head) if h.startswith(prefix)), None)

    c_item, c_page, c_comment, c_std = col("item"), col("page"), col(CRS_HEADER), col("standard")
    cell = lambda row, c: str(row[c] or "").strip() if c is not None and c < len(row) else ""  # noqa: E731
    items: list[dict] = []
    todo: list[dict] = []
    for n, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        comment = cell(row, c_comment)
        if not comment:
            continue
        standard = clause = None
        for text in (comment, cell(row, c_std)):
            for spelling, _start, end in datasheets.referenced_standard_spans(text):
                standard = standard or spelling
                m = _CLAUSE_AFTER.match(text[end:])
                if m:
                    standard, clause = spelling, m.group(1)
                    break
            if clause:
                break
        item_no = cell(row, c_item)
        if not standard or not clause:
            todo.append({"row": n, "item_no": item_no or None,
                         "missing": "standard" if not standard else "clause"})
            continue
        page = cell(row, c_page)
        field = page.split(" - ", 1)[1].strip() if " - " in page else ""
        item = {"id": f"crs-{item_no or n}", "kind": DEFECT, "standard": standard, "clause": clause,
                "note": f"drafted by code from CRS row {n}; check standard, clause and field before scoring"}
        if field:
            item["field"] = field
        items.append(item)
    key = {"format": KEY_FORMAT, "name": name, "source": "engineer_confirmed",
           "approved_by": approved_by.strip(), "complete_for_flags": False, "items": items}
    return key, todo


def load_findings(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeyError_(f"the findings could not be read: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or data.get("format") != FINDINGS_FORMAT or not isinstance(data.get("findings"), list):
        raise KeyError_(f"the findings file must be a JSON object with format {FINDINGS_FORMAT!r} and a findings list")
    return data


# -------------------------------------------------------------------- matching

def _clause_under(finding_clause: str, item_clause: str) -> bool:
    """`4.2.1` is under `4.2`; `4.2` is under `4.2`; `4.20` is not under `4.2`."""
    f, i = _fold(finding_clause).replace(" ", ""), _fold(item_clause).replace(" ", "")
    return bool(f) and bool(i) and (f == i or f.startswith(i + "."))


def _standard_matches(finding: dict, item: dict) -> bool:
    wanted = _fold(item["standard"])
    have = _fold(f"{finding.get('standard') or ''} {finding.get('standard_number') or ''}")
    if bool(wanted) and wanted in have:
        return True
    # #747: a key drafted from a real CRS names the standard as the engineer
    # wrote it ("API RP 520 Part I"); the finding names the library's file
    # ("API-520-I.pdf"). The project's one identifier rule decides.
    from app import standard_ids
    return any(standard_ids.same_standard(item["standard"], str(other))
               for other in (finding.get("standard"), finding.get("standard_number")) if other)


def _field_matches(finding: dict, item: dict) -> bool:
    field = item.get("field")
    if not field:
        return True
    text = _fold(f"{finding.get('field') or ''} {finding.get('requirement_text') or ''}")
    return all(w in text.split() for w in _words(field))


def _specificity(item: dict) -> tuple[int, int]:
    return (1 if item.get("field") else 0, len(_fold(item["clause"])))


def match_item(finding: dict, items: list[dict]) -> dict | None:
    """The most specific key item this finding answers, or None."""
    hits = [it for it in items
            if _standard_matches(finding, it) and _clause_under(finding.get("clause") or "", it["clause"])
            and _field_matches(finding, it)]
    return max(hits, key=_specificity) if hits else None


# --------------------------------------------------------------------- citation

def _squash(text: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def citation_valid(finding: dict, page_text: str | None) -> bool | None:
    """Does the cited page (and clause) really contain the requirement?
    None when the page text is not available (not checked)."""
    if page_text is None:
        return None
    source = _squash(finding.get("requirement_text"))
    if not source:
        return False
    page = _squash(page_text)
    contained = source in page
    if not contained and "|" in str(finding.get("requirement_text") or ""):
        contained = all(w in set(page.split()) for w in source.split())      # a table row read cell by cell
    if not contained:
        return False
    clause = _squash(finding.get("clause"))
    return not clause or clause in page


# ---------------------------------------------------------------------- scoring

def _ratio(n: int, d: int) -> float | None:
    return (n / d) if d else None


def score(key: dict, findings_doc: dict,
          page_lookup: Callable[[object, object], str | None] | None = None) -> dict:
    """Score the findings against the key. `page_lookup(standard_document_id,
    page)` returns the cited page's text or None; without it citation validity
    is NOT CHECKED."""
    key = validate_key(key)
    items = key["items"]
    by_id = {it["id"]: it for it in items}
    findings = findings_doc.get("findings") or []

    matched: dict[str, list[dict]] = defaultdict(list)
    unmatched: list[dict] = []
    for f in findings:
        item = match_item(f, items)
        (matched[item["id"]].append(f) if item else unmatched.append(f))

    def statuses(item_id: str) -> set[str]:
        return {str(f.get("compliance_status") or "") for f in matched.get(item_id, [])}

    defects = [it for it in items if it["kind"] == DEFECT]
    found = [it for it in defects if statuses(it["id"]) & FLAG_STATUSES]
    missed = [it for it in defects if not statuses(it["id"]) & FLAG_STATUSES]
    false_compliant = [it for it in defects if OK_STATUS in statuses(it["id"])]
    applying = [it for it in items if it["kind"] in (DEFECT, MET, TRAP)]
    false_na = [it for it in applying if NA_STATUS in statuses(it["id"])]
    traps = [it for it in items if it["kind"] == TRAP]
    flagged_traps = [it for it in traps if statuses(it["id"]) & FLAG_STATUSES]

    correct = wrong = other_status = 0
    for item_id, fs in matched.items():
        kind = by_id[item_id]["kind"]
        for f in fs:
            s = str(f.get("compliance_status") or "")
            if s in FLAG_STATUSES:
                ok = kind == DEFECT
            elif s == OK_STATUS:
                ok = kind in (MET, TRAP)
            elif s == NA_STATUS:
                ok = kind == NOT_APPLICABLE_ITEM
            else:
                other_status += 1
                continue
            correct += ok
            wrong += not ok
    unmatched_flags = [f for f in unmatched if str(f.get("compliance_status") or "") in FLAG_STATUSES]
    if key.get("complete_for_flags"):
        wrong += len(unmatched_flags)
    judged = correct + wrong

    checked = valid = 0
    for f in findings:
        if page_lookup is not None:
            if not f.get("standard_document_id") and not f.get("page"):
                continue
            verdict = citation_valid(f, page_lookup(f.get("standard_document_id"), f.get("page")))
        else:
            # An export made next to the database already carries its verdict
            # (a boolean, never page text). Absent or null: not checked.
            verdict = f.get("citation_valid")
        if verdict is None:
            continue
        checked += 1
        valid += bool(verdict)

    return {
        "key": key.get("name"), "source": key["source"], "model": findings_doc.get("model"),
        "findings": len(findings), "items": len(items),
        "defects": len(defects), "defects_found": len(found),
        "recall": _ratio(len(found), len(defects)),
        "missed_ids": sorted(it["id"] for it in missed),
        "judged_findings": judged, "correct_findings": correct,
        "precision": _ratio(correct, judged),
        "findings_other_status": other_status,
        "findings_not_judged_by_key": 0 if key.get("complete_for_flags") else len(unmatched_flags),
        "unmatched_findings": len(unmatched),
        "complete_for_flags": bool(key.get("complete_for_flags")),
        "false_compliant": len(false_compliant),
        "false_compliant_ids": sorted(it["id"] for it in false_compliant),
        "false_not_applicable": len(false_na),
        "false_not_applicable_ids": sorted(it["id"] for it in false_na),
        "traps": len(traps), "traps_flagged": len(flagged_traps),
        "trap_false_flag_rate": _ratio(len(flagged_traps), len(traps)),
        "trap_flagged_ids": sorted(it["id"] for it in flagged_traps),
        "citations_checked": checked, "citations_valid": valid,
        "citation_validity": _ratio(valid, checked),
        "citations_checked_note": None if checked else "not checked: no page text or stored verdict was supplied",
    }


# ------------------------------------------------------- baseline, gate, bar

def baseline_key(result: dict) -> str:
    return f"{result.get('model') or 'unknown model'}|{result.get('key')}"


def load_baseline(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"format": BASELINE_FORMAT, "margin": 0.05, "baselines": {}, "bar": dict(PROPOSED_BAR)}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("format") != BASELINE_FORMAT:
        raise KeyError_(f"the baseline must have format {BASELINE_FORMAT!r}")
    data.setdefault("margin", 0.05)
    data.setdefault("baselines", {})
    data.setdefault("bar", dict(PROPOSED_BAR))
    return data


def baseline_entry(result: dict, recorded: str) -> dict:
    return {k: result[k] for k in ("recall", "precision", "false_compliant", "citation_validity", "defects",
                                   "judged_findings")} | {"recorded": recorded}


def check(result: dict, baseline: dict) -> list[str]:
    """Why this score must BLOCK a merge. Empty means it passes. Any false
    compliant blocks, with or without a baseline; recall, precision and citation
    validity may not fall more than the margin below the stored baseline."""
    reasons = []
    if result["false_compliant"]:
        reasons.append(f"{result['false_compliant']} defect(s) were called COMPLIANT "
                       f"({', '.join(result['false_compliant_ids'])}); the limit is 0")
    entry = (baseline.get("baselines") or {}).get(baseline_key(result))
    margin = float(baseline.get("margin", 0.05))
    if entry:
        for name in ("recall", "precision", "citation_validity"):
            now, before = result.get(name), entry.get(name)
            if before is not None and now is None:
                reasons.append(f"{name} was {before:.0%} in the baseline and cannot be computed now")
            elif before is not None and now is not None and now < before - margin:
                reasons.append(f"{name} fell from {before:.0%} to {now:.0%} (more than {margin:.0%} allowed)")
    return reasons


def bar_status(result: dict, bar: dict | None = None) -> dict[str, bool | None]:
    """Each metric against the PROPOSED bar (owner to confirm). None = cannot tell."""
    bar = bar or PROPOSED_BAR

    def at_least(v, t):
        return None if v is None else v >= t

    def at_most(v, t):
        return None if v is None else v <= t
    return {
        "recall": at_least(result["recall"], bar["recall"]),
        "trap_false_flag_rate": at_most(result["trap_false_flag_rate"], bar["trap_false_flag_rate"]),
        "false_compliant": result["false_compliant"] <= bar["false_compliant"],
        "citations_valid": at_least(result["citation_validity"], bar["citations_valid"]),
    }
