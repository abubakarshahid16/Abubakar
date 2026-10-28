"""Is the standard behind a CRS row cited in the datasheet? (order 283.3, Part of #645)

A KOC sheet cites API 610, KOC-ME-008 and the NACE/ISO sour-service standard; it
never names SAES. A row that rests only on an SAES rule is the company's own
practice, not something the sheet or the contractor was told to meet. Until the
owner says SAES applies to the project, such a row says so and leaves the
judgement to the engineer; it is never worded as a plain "does not meet".

"Cited" is the list `applicability.standards_check` already builds: the standard
numbers PRINTED in the datasheet text. It is not "the project requires it". A row
is marked only when every fact needed is known: a standard name that parses to a
known family, a check that holds the cited list, and no cited standard that is the
same one. Anything else stays unmarked: unknown is never "not cited".
"""

from __future__ import annotations

from . import standard_ids

LABEL = "Company practice, not cited in this datasheet: engineer to judge."
_CHECK_ORIGIN = "datasheet_check"  # a kind B check names its own checklist source


def _not_cited(finding: dict, cited: list[str], required: list[str]) -> bool:
    name = str(finding.get("standard_name") or "")
    if finding.get("origin") == _CHECK_ORIGIN or standard_ids.parse(name) is None:
        return False
    return not any(standard_ids.same_standard(c, name) for c in [*cited, *required])


def holds_label(row: dict) -> bool:
    """A labelled row whose comment is still the machine's labelled text."""
    return row.get("standard_cited") is False and str(
        row.get("comment") or ""
    ).startswith(LABEL)


def mark(rows: list[dict], findings: list[dict], standards_check: dict | None) -> int:
    """Label, in place, every finding row whose standards are ALL known and none cited
    in the datasheet. Returns how many rows were marked."""
    cited = (standards_check or {}).get("cited")
    if not cited:
        return 0
    required = [r["identifier"] for r in (standards_check or {}).get("required") or []]
    by_id = {f["id"]: f for f in findings if f.get("id")}
    marked = 0
    for row in rows:
        group = [by_id[i] for i in row.get("finding_ids") or [] if i in by_id]
        if not group or row.get("standard_cited") is False:
            continue
        if not all(_not_cited(f, cited, required) for f in group):
            continue
        row["standard_cited"] = False
        if not row.get("edited"):
            row["comment"] = f"{LABEL} {row['comment']}"
            row["ai_comment"] = f"{LABEL} {row.get('ai_comment', '')}".strip()
        marked += 1
    return marked
