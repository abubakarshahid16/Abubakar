"""Which paper carries a knowledge item (18 Nov 2026: the strict judges marked relief-study items WRONG on a vessel datasheet: a
not-held book that governs a neighbouring paper was written into this paper's checklist). The knowledge step says for each item
"this paper" or the kind of paper that states it; code keeps only this paper's items and sets the rest aside, on the checklist's
set-aside list, as "for <kind> paper". No answer keeps the item, as before."""

from __future__ import annotations

#: The answer for an item THIS paper carries. The build rewords "this paper" to "a paper of this type" in every task it sends
#: (`checklist._for_type`), so the asked word is "HERE"; the other forms are kept too.
HERE = ("here", "this paper", "a paper of this type", "this type", "this kind")


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
        carried = " ".join(
            str(r.get("carried_by") or "").split()
        )  # whole: never cut without a mark
        if carried and not carried.lower().startswith(HERE):
            elsewhere.append(
                {
                    "topic": it["topic"],
                    "why": f"for {carried.removesuffix(' paper')} paper",
                }
            )
            continue
        added.append(it)
    return added, elsewhere


#: The words of the silent-loss guard (18 Nov 2026: a prompt rewording set every knowledge item aside and nothing said so).
NONE_WRITTEN = "knowledge items: 0"


def say_none(model, names: str, cause: str) -> None:
    """When books are needed but not held and the knowledge step writes NO item, the run's calls say so (a code note, no model,
    no cost): "knowledge items: 0 of N expected (cause)". Shown in the run record and on the How-made tab."""
    import logging

    from .engine import CallRecord

    expected = len([n for n in str(names or "").split("; ") if n.strip()])
    if not expected:
        return
    words = f"{NONE_WRITTEN} of {expected} expected ({cause})"
    logging.getLogger(__name__).warning("general review: %s", words)
    meter = getattr(model, "meter", None)
    if meter is not None and hasattr(meter, "calls"):
        meter.calls.append(
            CallRecord(
                step="aim_checklist_knowledge",
                model="code",
                prompt_chars=0,
                ok=False,
                code=words,
            )
        )


def set_aside(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """(items kept, set-aside rows {topic, why}) for the checklist step's own knowledge items: one whose "carried_by" names another
    paper (a schedule of the same package, a study) is not checked here, as for the knowledge step's items. No answer keeps it."""
    kept, aside = [], []
    for it in items:
        carried = str(it.get("carried_by") or "").strip()
        if (
            it.get("source") != "held standard"
            and carried
            and not carried.lower().startswith(HERE)
        ):
            aside.append(
                {
                    "topic": it.get("topic") or "",
                    "why": f"for {carried.removesuffix(' paper')} paper",
                }
            )
        else:
            kept.append(it)
    return kept, aside
