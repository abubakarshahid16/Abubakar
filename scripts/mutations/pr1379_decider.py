"""#892 items 10 and 11 (PR 1379): a comment an engineer accepted names them; an accepted AI or web
item is confirmed. `crs_mapping.py` is in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_892_decider_byline.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1379-01",
        phase=1379,
        description="the accepter is ignored again: only confirmed_by counts as a decision",
        path=APP / "crs_decider.py",
        anchor='    if finding.get("approval_status") != "accepted":\n        return None\n    return finding.get("approved_by")\n',
        replacement="    return None\n",
        target=_T,
        keyword="accepted",
        tags=_TAGS,
    ),
    Mutation(
        id="M1379-02",
        phase=1379,
        description="an approver on a pending row confirms it",
        path=APP / "crs_decider.py",
        anchor='    if finding.get("approval_status") != "accepted":\n        return None\n',
        replacement="    if False:\n        return None\n",
        target=_T,
        keyword="approver_on_a_pending_row",
        tags=_TAGS,
    ),
    Mutation(
        id="M1379-03",
        phase=1379,
        description="an AI or web item an engineer accepted stays an unconfirmed draft",
        path=APP / "crs_mapping.py",
        anchor="        confirmed = bool(crs_decider.decider(f))\n",
        replacement='        confirmed = bool(f.get("confirmed_by"))\n',
        target=_T,
        keyword="ai_item_the_engineer_accepted",
        tags=_TAGS,
    ),
    Mutation(
        id="M1379-04",
        phase=1379,
        description="the accepter's display name is no longer looked up",
        path=APP / "main.py",
        anchor="    confirmers = {d for f in findings if (d := crs_mapping_mod.crs_decider.decider(f))}\n",
        replacement='    confirmers = {f["confirmed_by"] for f in findings if f.get("confirmed_by")}\n',
        target=_T,
        keyword="real_crs_content",
        tags=_TAGS,
    ),
)
