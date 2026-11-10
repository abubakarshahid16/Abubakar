"""Owner order 11 Nov 2026, owner answer (#805): behind CRS_BY_CONTRACTOR_ONE_ROW_ENABLED (off), the contractor
(issue) copy folds the rows held only because a value is marked deferred (hold reason `deferred_marker`) into ONE
query row naming every field with its tag, page and number; the internal copy keeps one row per field; switch off,
every export path is as on main. `crs_mapping.py` and `crs_export.py` are in the danger zone (rule 6); the new
`crs_by_contractor.py` is what they call. Ids M1738-01.. (named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_B = APP / "crs_by_contractor.py"
_M = APP / "crs_mapping.py"
_E = APP / "crs_export.py"
_Q = APP / "crs_export_quality.py"
_T = "tests/test_by_contractor_one_row.py"
_TAGS = ("honesty", "critical")


def _m(n: str, desc: str, path, anchor: str, repl: str, kw: str) -> Mutation:
    return Mutation(
        id=f"M1738-{n}",
        phase=1738,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the rows carry the deferred entries with the switch OFF (off is no longer main's rows)",
        _B,
        "    if not enabled() or not group:\n        return None\n",
        "    if not group:\n        return None\n",
        "switch_off_no_row_carries_the_deferred_entries",
    ),
    _m(
        "02",
        "the contractor copy is folded with the switch OFF",
        _B,
        "    if not enabled():\n        return rows\n",
        "    if False:\n        return rows\n",
        "switch_off_every_export_path",
    ),
    _m(
        "03",
        "a row held for another reason is folded as if its value were deferred",
        _B,
        "        if hold_reason.of(f) != hold_reason.DEFERRED_MARKER:\n            return None\n",
        "        if False:\n            return None\n",
        "not_held_only_for_a_deferred_value or one_deferred_and_one_other",
    ),
    _m(
        "04",
        "a finding with the engineer's own words is folded (their comment vanishes into the query row)",
        _B,
        'if f.get("compliance_status") != _HELD or f.get("engineer_comment"):',
        'if f.get("compliance_status") != _HELD:',
        "engineer_worded_finding_keeps_its_own_row",
    ),
    _m(
        "05",
        "a row the engineer edited is folded",
        _B,
        '    if row.get("edited") or row.get("engineer_worded"):\n        return False\n',
        "",
        "closed_number_keeps_its_own_row and edit",
    ),
    _m(
        "06",
        "a row with a contractor reply is folded (the reply is lost)",
        _B,
        '    if str(row.get("crs_response") or "").strip():\n        return False\n',
        "",
        "closed_number_keeps_its_own_row and answer",
    ),
    _m(
        "07",
        "a row with a closed number is folded",
        _B,
        '    if str(row.get("crs_status") or "").startswith(_CLOSED):\n        return False\n',
        "",
        "closed_number_keeps_its_own_row and shut",
    ),
    _m(
        "08",
        "a row merged with another finding after mapping is folded (that finding's comment is lost)",
        _B,
        '    return stands_on == sorted(e["finding_id"] for e in entries)\n',
        "    return True\n",
        "merged_with_another_finding",
    ),
    _m(
        "09",
        "the query row names only the first field (rows lost)",
        _B,
        '"comment": "\\n".join([LEAD, *dict.fromkeys(lines)]),',
        '"comment": "\\n".join([LEAD, *dict.fromkeys(lines[:1])]),',
        "has_one_query_row_naming_every_field",
    ),
    _m(
        "10",
        "a single deferred row is reworded into a query row of one",
        _B,
        "    if len(at) < 2:\n        return rows\n",
        "    if len(at) < 1:\n        return rows\n",
        "one_deferred_row_alone",
    ),
    _m(
        "11",
        "the query row moves to the end of the sheet instead of the first member's place",
        _B,
        "        query if i == at[0] else r\n        for i, r in enumerate(rows)\n"
        "        if i == at[0] or i not in folded\n",
        "        r\n        for i, r in enumerate(rows + [query])\n"
        "        if i >= len(rows) or i not in folded\n",
        "takes_the_first_members_place",
    ),
    _m(
        "12",
        "build_crs_rows never marks a deferred row (the switch does nothing)",
        _M,
        "            crs_by_contractor.mark(rows[-1], group, _field_label, word_pages.at)\n",
        "",
        "each_deferred_row_carries_its_field_tag_and_page",
    ),
    _m(
        "13",
        "the contractor copy is never folded (the switch does nothing)",
        _E,
        "        findings = crs_by_contractor.one_row(findings)  # owner 11 Nov; off: as it was\n",
        "",
        "contractor_copy_has_one_query_row or prints_the_query_row",
    ),
    _m(
        "14",
        "the internal copy is folded too (it must keep one row per field)",
        _E,
        '    qon = bool(meta.get("export_quality", quality.enabled()))  # #1503\n',
        "    findings = crs_by_contractor.one_row(findings)\n"
        '    qon = bool(meta.get("export_quality", quality.enabled()))  # #1503\n',
        "internal_copy_keeps_one_row_per_field",
    ),
    _m(
        "15",
        "export quality cuts the query row at 350 characters (later fields leave its comment)",
        _Q,
        '        if entry["comment_missing"] or crs_by_contractor.is_query(entry["comment"]):\n',
        '        if entry["comment_missing"]:\n',
        "long_query_row_keeps_every_field",
    ),
)
