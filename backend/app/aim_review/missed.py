"""ROLE 5 OF THE NINE ROLES, THE CHECKLIST ASKS WHAT THE JUDGE MISSED (lead-4, 26 Nov 2026; behind the nine-role gate `updates.nine_roles`, off).

The general review builds its checklist BEFORE the judge and the judge answers every item; that order stays as it is. After the
judge, this step asks ONCE MORE, as the checklist role, only the items the judge left "not judged" (its batch failed, or its answer
named no finding for the item): they go through the SAME judge step (`steps.s4_judge`, the same prompt, the same decisions, the
same exit), under their own step name `STEP` so the role record counts them as role 5 and the money ledger gives them their own
USD 5 line (the run stays at most USD 15). An item the second ask answers takes the new lines in its place; one it does not
answer keeps its "not judged" line with the reason. An item held back on purpose (its book not on the list shown, a company book
the paper does not cite) is never asked: it was never left unjudged. Nothing is asked when the run is stopping. Code only here."""

from __future__ import annotations

from . import NOT_JUDGED

#: The step name of role 5's calls (`roles.ROLE_OF_STEP`): the judge's request and answer shape, under the checklist role.
STEP = "aim_checklist_missed"
#: The code note on a line this step ANSWERED (team file only: the code note of "All points"; never comment text, never in
#: the contractor copy); read by `roles._review_counts` for the role's count. A line still unanswered keeps its exact "not judged".
ASKED_AGAIN = "asked again by the checklist after the judge"


class _AsChecklist:
    """The run's model, with the judge's calls sent under `STEP` (everything else is the run's own model's)."""

    def __init__(self, model) -> None:
        self.model = model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def ask(self, **kw):
        return self.model.ask(**{**kw, "step": STEP})


def missed(items: list[dict], lines: list[dict]) -> list[dict]:
    """The items whose every line is "not judged" (an item with any other line was judged)."""
    by_id: dict[str, list[dict]] = {}
    for ln in lines:
        by_id.setdefault(str(ln.get("item_id")), []).append(ln)
    return [
        it
        for it in items
        if by_id.get(str(it["id"]))
        and all(ln.get("code") == NOT_JUDGED for ln in by_id[str(it["id"])])
    ]


def ask_again(
    model,
    paper,
    checklist: dict,
    text,
    items: list[dict],
    lines: list[dict],
    stop: str,
    **judge,
) -> tuple[list[dict], str]:
    """`(lines, stop)` with the judge's "not judged" items asked once more as role 5; `stop` unchanged when nothing is asked.
    `judge`: the judge's own keyword arguments (windows, lead, cancelled, progress, scope)."""
    from . import steps as S

    again = [] if stop else missed(items, lines)
    if not again:
        return lines, stop
    new, stop = S.s4_judge(
        _AsChecklist(model), paper, checklist, text, items=again, **judge
    )
    fresh: dict[str, list[dict]] = {}
    for ln in new:
        fresh.setdefault(str(ln.get("item_id")), []).append(ln)
    out, placed = [], set()
    for ln in lines:
        key = str(ln.get("item_id"))
        if key not in fresh:
            out.append(ln)
        elif (
            key not in placed
        ):  # the item's new lines take its "not judged" line's place, in order
            answered = [_marked(x) for x in fresh[key] if x.get("code") != NOT_JUDGED]
            out += answered or [
                ln
            ]  # still unanswered: its "not judged" line, as it was
            placed.add(key)
    return out, stop


def _marked(line: dict) -> dict:
    """The line with `ASKED_AGAIN` added to its code note (its other notes kept, in order)."""
    return dict(line, code="; ".join(x for x in (line.get("code"), ASKED_AGAIN) if x))
