"""PR #NNN (#892 item 1): every CRS row names every stored finding it stands
on. `crs_mapping.py` and `crs_export.py` are in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_892_crs_finding_ids.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="MNNN-01", phase=NNN,
             description="a grouped CRS row names only its leader's finding again",
             path=APP / "crs_mapping.py",
             anchor='    return list(dict.fromkeys(str(f["id"]) for f in group if f.get("id")))\n',
             replacement='    return [str(group[0]["id"])] if group and group[0].get("id") else []\n',
             target=_T, keyword="grouped_row_names_every or each_listed_once",
             tags=("honesty",)),
    Mutation(id="MNNN-02", phase=NNN,
             description="the CRS view drops the finding ids from every row",
             path=APP / "crs_export.py",
             anchor='            "finding_ids": row_finding_ids(finding),\n',
             replacement="",
             target=_T, keyword="grouped_row_names_every or names_none or single_id",
             tags=("honesty",)),
    Mutation(id="MNNN-03", phase=NNN,
             description="a row sent with only its single finding_id lists no finding",
             path=APP / "crs_export.py",
             anchor='    if not ids and finding.get("finding_id"):\n        ids = [str(finding["finding_id"])]\n',
             replacement="",
             target=_T, keyword="single_id",
             tags=("honesty",)),
)
