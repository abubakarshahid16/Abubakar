"""R26 step 10 (#763, roadmap R4 #768): what the engineers' decisions say
about the review's own comments.

Every finding an engineer decides is feedback: CONFIRMED or ACCEPTED (the
comment stands), EDITED (it stands in the engineer's words), REJECTED or "not
applicable" (it should not have been raised). This counts them, per standard
and per rule, so the precision of each rule is a measured fact rather than an
impression - and lists the rules engineers keep rejecting as CANDIDATES for a
checklist or guard change.

THE ENGINEER DECIDES, NOTHING LEARNS SILENTLY. A candidate changes nothing
by itself: it is a line in this report for an engineer to act on (edit the
checklist, tighten a gate) through the normal review of a change.

HONESTY RULES (CLAUDE.md rule 4):
  * every count states its boundary - the findings of the documents the
    caller may read, and since when;
  * no percentage: precision is "kept of decided" ("7 of 9"), both numbers;
  * an undecided finding is not counted as right or wrong - it is pending;
  * a standard the caller may not read is not named.

Read only. Opens no socket, calls no model.
"""
from __future__ import annotations

import re

from .db import connect

ACCEPTED, EDITED, REJECTED, PENDING = "accepted", "edited", "rejected", "pending"
#: A rule engineers rejected at least this often, and more often than they
#: kept it, is listed as a candidate for review.
CANDIDATE_MIN_REJECTED = 2

_CHECK_RULE = re.compile(r"^Datasheet check ([A-Za-z0-9.\-]+):")
_ORIGIN_NAMES = {"datasheet_check": "Datasheet checklist",
                 "ai_engineering_check": "AI engineering check",
                 "web_standard_check": "Web standards check"}


def decision(finding: dict) -> str:
    """What the engineer decided about one finding. A rejection wins over any
    earlier confirmation; an edit is kept, in the engineer's words."""
    if finding.get("approval_status") == "rejected" or finding.get("disposition") in (
            "rejected", "not_applicable"):
        return REJECTED
    if str(finding.get("engineer_comment") or "").strip():
        return EDITED
    if (finding.get("confirmed_by") or finding.get("approval_status") == "accepted"
            or finding.get("disposition") in ("accepted", "partially_accepted")):
        return ACCEPTED
    return PENDING


def _source(finding: dict, names: dict[str, str], allowed: frozenset[str]) -> str:
    origin = finding.get("origin") or ""
    if origin in _ORIGIN_NAMES:
        return _ORIGIN_NAMES[origin]
    standard = finding.get("standard_document_id")
    if not standard:
        return "No standard (the review's own checks)"
    if standard not in allowed:
        return "A standard outside your access"
    return names.get(standard) or "A standard no longer held"


def rule_of(finding: dict, source: str) -> str:
    """The rule a finding came from, in words an engineer recognises: a
    checklist item's id, a standard's clause, or the check that raised it."""
    match = _CHECK_RULE.match(str(finding.get("requirement_source_text") or ""))
    if match:
        return f"{source} {match.group(1)}"
    if finding.get("origin") in _ORIGIN_NAMES:
        return source
    clause = str(finding.get("standard_clause") or "").strip()
    return f"{source} cl. {clause}" if clause else f"{source} (no clause)"


def _empty() -> dict:
    return {ACCEPTED: 0, EDITED: 0, REJECTED: 0, PENDING: 0}


def _row(name: str, counts: dict) -> dict:
    kept = counts[ACCEPTED] + counts[EDITED]
    decided = kept + counts[REJECTED]
    return {"name": name, **counts, "kept": kept, "decided": decided,
            "precision": f"{kept} of {decided} kept" if decided else "none decided yet"}


def report(*, allowed_document_ids: frozenset[str], since: str | None = None) -> dict:
    """The feedback report over the findings of the documents the caller may
    read (`allowed_document_ids`), optionally since an ISO date."""
    allowed = frozenset(allowed_document_ids)
    if not allowed:
        rows = []
    else:
        marks = ",".join("?" for _ in allowed)
        sql = (f"SELECT * FROM review_findings WHERE document_id IN ({marks})"
               " AND review_run_id IS NOT NULL")
        args: list = sorted(allowed)
        if since:
            sql += " AND created_at >= ?"
            args.append(since)
        rows = [dict(r) for r in connect().execute(sql, args)]
    names = {r["id"]: r["filename"] for r in connect().execute("SELECT id, filename FROM documents")}
    by_source: dict[str, dict] = {}
    by_rule: dict[str, dict] = {}
    totals = _empty()
    for finding in rows:
        made = decision(finding)
        source = _source(finding, names, allowed)
        rule = rule_of(finding, source)
        totals[made] += 1
        by_source.setdefault(source, _empty())[made] += 1
        by_rule.setdefault(rule, _empty())[made] += 1
    rules = sorted((_row(name, c) for name, c in by_rule.items()),
                   key=lambda r: (-r[REJECTED], r["name"]))
    candidates = [r for r in rules if r[REJECTED] >= CANDIDATE_MIN_REJECTED and r[REJECTED] > r["kept"]]
    decided = totals[ACCEPTED] + totals[EDITED] + totals[REJECTED]
    return {
        "boundary": (f"Engineers' decisions on the {len(rows)} review finding(s) of the documents "
                     f"you can read{f' since {since}' if since else ''}: {decided} decided, "
                     f"{totals[PENDING]} not yet decided."),
        "totals": _row("All findings", totals),
        "by_standard": sorted((_row(name, c) for name, c in by_source.items()),
                              key=lambda r: (-r["decided"], r["name"])),
        "by_rule": rules,
        "candidates": [{**r, "note": (f"Rejected {r[REJECTED]} times, kept {r['kept']}: a candidate "
                                      "for an engineer to review (checklist or guard change). "
                                      "Nothing changes automatically.")}
                       for r in candidates],
    }
