"""Which paper carries a knowledge item (18 Nov 2026: the strict judges marked relief-study items WRONG on a vessel datasheet: a
not-held book that governs a neighbouring paper was written into this paper's checklist). The knowledge step says for each item
"this paper" or the kind of paper that states it; code keeps only this paper's items and sets the rest aside, on the checklist's
set-aside list, as "for <kind> paper". No answer keeps the item, as before."""

from __future__ import annotations

#: The words of a knowledge item that THIS paper carries (the model's "carried_by").
THIS_PAPER = "this paper"


def knowledge_rows(
    rows, most: int, clean, source: str
) -> tuple[list[dict], list[dict]]:
    """(items THIS paper carries, set-aside rows {topic, why: "for <kind> paper"}): an item whose value another kind of paper
    states (a study, another item's datasheet) is not checked here; it stays on the checklist's set-aside list. No answer
    for "carried_by" keeps the item (as before)."""
    added, elsewhere = [], []
    for r in [r for r in rows or [] if isinstance(r, dict)][:most]:
        it = clean(
            {**r, "source": source}
        )  # labelled first: no book, no quote, no clause number
        it["stands_in_for"] = it["stands_in_for"] or "engineering practice"
        carried = " ".join(str(r.get("carried_by") or "").split())[:80]
        if carried and not carried.lower().startswith(THIS_PAPER):
            elsewhere.append(
                {
                    "topic": it["topic"],
                    "why": f"for {carried.removesuffix(' paper')} paper",
                }
            )
            continue
        added.append(it)
    return added, elsewhere
