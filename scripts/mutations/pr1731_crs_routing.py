"""Mutations of the CRS routing by hold reason (owner order 10 Nov, step 4; Part of
#805 Cycle 2; PR 1731). `crs_routing` decides which rows reach the engineer's CRS,
like `compliance_list` (PR 1665), so its guards are mutation-tested the same way."""

from __future__ import annotations

from ._base import APP, Mutation

_R = APP / "crs_routing.py"
_CL = APP / "compliance_list.py"
_T = "tests/test_crs_routing.py"


def _m(n, description, anchor, replacement, keyword, path=_R) -> Mutation:
    return Mutation(
        id=f"M1731-{n:02d}",
        phase=1731,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=("crs", "honesty"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the switch off still moves findings off the CRS",
        '    if not enabled() or finding.get("origin") != _DATASHEET:\n',
        '    if finding.get("origin") != _DATASHEET:\n',
        "switch_off",
    ),
    _m(
        2,
        "a two-value applicability row leaves the CRS (owner: it stays)",
        "    {hold_reason.APPLICABILITY_NOT_STATED, hold_reason.APPLICABILITY_NOT_STATED_ABSENT}\n",
        "    {hold_reason.APPLICABILITY_NOT_STATED, hold_reason.APPLICABILITY_NOT_STATED_ABSENT,"
        " hold_reason.APPLICABILITY_SEVERAL_VALUES}\n",
        "stay_on_the_crs",
    ),
    _m(
        3,
        "a 'By Contractor' (deferred) row leaves the CRS (owner: it stays)",
        "    if code in R2_CODES:\n",
        "    if code in R2_CODES or code == hold_reason.DEFERRED_MARKER:\n",
        "stay_on_the_crs",
    ),
    _m(
        4,
        "R3 moves a value whose fact carries a placeholder mark",
        "    return fact is not None and not fact_is_placeholder(fact)\n",
        "    return fact is not None\n",
        "r3_needs",
    ),
    _m(
        5,
        "R3 moves a value checked by a signed or person-approved rule",
        "        and _draft_only(finding)\n",
        "        and True\n",
        "r3_needs",
    ),
    _m(
        6,
        "a finding an engineer confirmed is moved off the CRS",
        '    if finding.get("compliance_status") != _HELD or finding.get("confirmed_by"):\n',
        '    if finding.get("compliance_status") != _HELD:\n',
        "exactly_its_rows or r3_needs",
    ),
    _m(
        7,
        "R1 moves a 'did not reference' row the held project specification requires",
        '        if entry is None or entry.get("unsure") or required(ident):\n',
        '        if entry is None or entry.get("unsure"):\n',
        "r1_stays",
    ),
    _m(
        8,
        "R1 moves a clarification row (equipment type unsure)",
        '        if entry is None or entry.get("unsure") or required(ident):\n',
        "        if entry is None or required(ident):\n",
        "r1_stays or exactly_its_rows",
    ),
    _m(
        9,
        "a decided or issued standards row is moved",
        '            if row.get("comment_key") in keep\n',
        "            if False\n",
        "decided_issued_or_confirmed",
    ),
    _m(
        10,
        "a machine draft's number counts as issued and keeps the row",
        '    issued = {k for k, record in records.items() if record.get("issued", 1)}\n',
        "    issued = set(records)\n",
        "kept_keys",
    ),
    _m(
        11,
        "an unverified quote of the project specification keeps a 'did not reference' row",
        "    return [quote for quote, passage in pairs if quote_verified(quote, passage)]\n",
        "    return [quote for quote, passage in pairs]\n",
        "verified_quote",
    ),
    _m(
        12,
        "the internal list is not written when only the routing switch is on",
        "    if not (enabled() or crs_routing.enabled()) or not run_id:\n",
        "    if not enabled() or not run_id:\n",
        "internal_list_shows",
        _CL,
    ),
    _m(
        13,
        "a moved finding's line on the internal list hides its reason",
        "                STATUS if _draft_pass(f) else crs_routing.status_words(f),\n",
        "                STATUS,\n",
        "internal_list_shows",
        _CL,
    ),
    _m(
        14,
        "the standards rows are never routed (R1 and R4 lost)",
        "    return crs_routing.standards(rows, notes, check, run_id, crs_scope, allowed)\n",
        "    return rows, notes\n",
        "r4_is_listed or exactly_its_rows",
        APP / "export_status.py",
    ),
)
