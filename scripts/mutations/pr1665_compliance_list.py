"""Mutations of the Compliance list (owner 3 Nov 11:40 b, PR 1665)."""

from __future__ import annotations

from ._base import REPO, Mutation

_CL = REPO / "backend" / "app" / "compliance_list.py"
_T = "tests/test_compliance_list.py"
_GUARD = 'finding.get("trust_label") in PERSON_LABELS or not _value_given(finding)'

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1665-01",
        phase=1665,
        description="the contractor copy gets the Compliance list sheet",
        path=REPO / "backend" / "app" / "crs_export.py",
        anchor="    if internal:  # owner 3 Nov (b): draft-rule values with nothing found\n",
        replacement="    if True:  # owner 3 Nov (b): draft-rule values with nothing found\n",
        target=_T,
        keyword="contractor_copy_never_does",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1665-02",
        phase=1665,
        description="a row an engineer confirmed is listed, so it disappears from the CRS",
        path=_CL,
        anchor='        or finding.get("confirmed_by")\n',
        replacement="",
        target=_T,
        keyword="never_listed",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1665-03",
        phase=1665,
        description="a value that was not read is listed, so its row disappears",
        path=_CL,
        anchor=_GUARD,
        replacement='finding.get("trust_label") in PERSON_LABELS',
        target=_T,
        keyword="never_listed",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1665-04",
        phase=1665,
        description="a safety field is shown as no issue found instead of its open tick",
        path=_CL,
        anchor="SAFETY_STATUS if is_safety(f) else STATUS",
        replacement="STATUS",
        target=_T,
        keyword="never_no_issue_and_keeps_its_open_tick",
        tags=("crs", "safety"),
    ),
    Mutation(
        id="M1665-05",
        phase=1665,
        description="a listed finding still makes a CRS row",
        path=REPO / "backend" / "app" / "crs_mapping.py",
        anchor='    return finding.get("approval_status") == "rejected" or listed(finding)\n',
        replacement='    return finding.get("approval_status") == "rejected"\n',
        target=_T,
        keyword="makes_no_crs_group",
        tags=("crs", "honesty"),
    ),
)
