"""The Review dashboard's counts and recent list with the general reviews in them (order 14, owner 18 Nov 2026, update 5).

The earlier counters read the earlier method's runs only, so a signed general review showed as nothing or as "awaiting an engineer's
code". Here, for each paper the caller may read, the NEWEST review is the one counted, whichever method made it: a general review is
"signed off" or "not signed off yet" by the engineer's sign-off record (`aim_review_signoff`), an earlier-method run keeps its own
rules (an engineer's final code). Counts of a general review are the results page's own (`aim_review_runs.counts_of`).

Rule 5: only papers the caller may read (an intersection with the grants). Ids, counts, status words and times; no document text.
Read only: no model, no network, no write.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import aim_review_runs

SIGNED, NOT_SIGNED, CHANGED = "signed", "not_signed", "changed"
STOPPED_EARLY = "the review stopped early"
FAILED = "the run failed"


def signoff_state(conn, run_id: str) -> str:
    """ "signed" while the sign-off still matches the engineer's decisions, "changed" when a decision came after it, else "not_signed"
    (`aim_review_face.signoff_state`, its one home)."""
    from . import aim_review_face

    return aim_review_face.signoff_state(conn, run_id)


@dataclass
class Newest:
    """The newest review of each paper the caller may read, newest first: ("old", run) or ("general", summary row)."""

    ordered: list = field(default_factory=list)
    all_runs: int = 0

    @property
    def old(self) -> list[dict]:
        return [x for kind, x in self.ordered if kind == "old"]

    @property
    def general(self) -> list[dict]:
        return [x for kind, x in self.ordered if kind == "general"]

    def running_general(self) -> int:
        return sum(1 for g in self.general if g["status"] == "running")

    def awaiting_general(self) -> int:
        """Finished and not (still) signed off."""
        return sum(
            1
            for g in self.general
            if g["status"] == "completed" and g["general_signoff"] != SIGNED
        )

    def signed_general(self) -> int:
        return sum(
            1
            for g in self.general
            if g["status"] == "completed" and g["general_signoff"] == SIGNED
        )

    def reasons(self) -> dict[str, int]:
        """Why a general review needs attention: it failed, or it stopped early (it holds the points it reached)."""
        out: dict[str, int] = {}
        for g in self.general:
            if g["status"] == "failed":
                out[FAILED] = out.get(FAILED, 0) + 1
            elif (g.get("general_counts") or {}).get("stopped"):
                out[STOPPED_EARLY] = out.get(STOPPED_EARLY, 0) + 1
        return out


def newest(
    conn, allowed: frozenset[str], old_latest: list[dict], old_total: int
) -> Newest:
    """Join the earlier method's latest run of each paper (`old_latest`, newest first) with each paper's newest general run."""
    best: dict[str, tuple[str, str, dict]] = {}
    for run in old_latest:
        best[run["submittal_document_id"]] = (
            "old",
            str(run.get("created_at") or ""),
            run,
        )
    for entry in aim_review_runs.entries(conn, allowed, newest_only=True):
        entry["general_signoff"] = (
            signoff_state(conn, entry["review_run_id"])
            if entry["status"] == "completed"
            else None
        )
        stamp = str(entry.get("created_at") or "")
        held = best.get(entry["submittal_document_id"])
        if held is None or stamp >= held[1]:
            best[entry["submittal_document_id"]] = ("general", stamp, entry)
    ordered = sorted(best.values(), key=lambda x: x[1], reverse=True)
    return Newest(
        ordered=[(kind, item) for kind, _, item in ordered],
        all_runs=old_total + aim_review_runs.total(conn, allowed),
    )
