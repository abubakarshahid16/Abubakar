"""Order 159 (PR number to be set): the pairing note stays off the contractor
copy. `comparison.py` is in the danger zone (rule 6); `crs_mapping.py` too."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_159_method_notes.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1204-01",
        phase=1204,
        description="the pairing notes are written without the marker, so nothing can tell them from the reason",
        path=APP / "comparison.py",
        anchor="""reason, note = verdict.get("rationale") or "", method_notes.wrap(notes)""",
        replacement='''reason, note = verdict.get("rationale") or "", "(" + "; ".join(notes) + ")"''',
        target=_T,
        keyword="synonym_pairing_keeps_its_note_off",
        tags=("honesty",),
    ),
    Mutation(
        id="M1204-02",
        phase=1204,
        description="the contractor comment's reason is built from the whole rationale, pairing note included",
        path=APP / "crs_mapping.py",
        anchor="""text = " ".join(method_notes.reason_of(finding).split())""",
        replacement="""text = " ".join(str(finding.get("ai_rationale") or "").split())""",
        target=_T,
        keyword="kept_off_too",
        tags=("honesty",),
    ),
    Mutation(
        id="M1204-03",
        phase=1204,
        description="the pairing note is dropped from the finding, so the engineer's internal copy loses it",
        path=APP / "comparison.py",
        anchor="""verdict = {**verdict, "rationale": f"{reason} {note}"}""",
        replacement="""verdict = {**verdict, "rationale": f"{reason}"}""",
        target=_T,
        keyword="internal_copy_keeps_the_note",
        tags=("honesty",),
    ),
    Mutation(
        id="M1204-04",
        phase=1204,
        description="the finding column is written from the whole rationale, pairing note included, so the screen's Edit comment starts from it",
        path=APP / "comparison.py",
        anchor=""""finding": comment or method_notes.split_method_notes(rationale)[0],""",
        replacement=""""finding": comment or rationale,""",
        target=_T,
        keyword="finding_column_carries_the_reason_only",
        tags=("honesty",),
    ),
)
