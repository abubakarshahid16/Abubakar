"""The CRS column "AI suggests (internal)" (order 305.4, part B).

A row an engineer must decide often carries a suggestion the review already worked out: a rule that is not yet
proven said "meets" or "does not meet" and was HELD (`rule_said`, #947), or the row is a question for the engineer.
This column shows that suggestion beside the row, with the value read, the rule's own words and the clause, so the
engineer sees what the system would say and then decides. It is NOT a verdict: the verdict cell, the status, the
priority and the contractor's copy never read it. Internal copy only (the column name ends "(internal)").

  Pass   the held rule said the sheet meets the requirement
  Fail   the held rule said it does not
  Query  the row is a question for the engineer and no rule gave a suggestion
  (blank) anything else: a verdict code gave, a missing value, a row with nothing to suggest - null renders as nothing

Pure; every word comes from fields already on the finding.
"""

from __future__ import annotations

COLUMN = "AI suggests (internal)"
WIDTH = 46.0
_WORD = {"COMPLIANT": "Pass", "NON_COMPLIANT": "Fail"}
NOTE = "suggestion only, not a verdict; the engineer decides"
_RULE_CHARS = 140


def _word(finding: dict) -> str:
    said = finding.get("rule_said")
    if said in _WORD:
        return _WORD[said]
    return (
        "Query" if finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW" else ""
    )


def words(finding: dict, clause: str) -> str:
    """One finding's suggestion, or "". `clause` is the row's Standard Reference as the CRS prints it."""
    word = _word(finding)
    if not word:
        return ""
    bits = []
    value = str(finding.get("contractor_evidence_text") or "").strip()
    field = str(finding.get("contractor_section") or "").strip()
    if value:
        bits.append(f"sheet: {field + ' = ' if field else ''}{value}")
    rule = " ".join(str(finding.get("requirement_source_text") or "").split())
    if rule:
        bits.append(f"rule: {rule[:_RULE_CHARS]}")
    if clause:
        bits.append(f"clause: {clause}")
    return f"{word} ({'; '.join(bits)}) - {NOTE}" if bits else f"{word} - {NOTE}"


def for_group(group: list[dict], reference) -> str:
    """The suggestions of a row's findings, once each, one per line. `reference` is the CRS's own clause text."""
    lines = (words(f, reference(f)) for f in group)
    return "\n".join(dict.fromkeys(line for line in lines if line))
