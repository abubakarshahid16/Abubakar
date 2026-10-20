"""A heading over options that each have a drawn slot (#882, M-03 CRS).

`MINIMUM FLOW` on one line and `STABLE ____   THERMAL ____` on the next: paired
left to right, the heading took `STABLE` as its VALUE (a value nobody wrote),
`STABLE`'s own slot was dropped as an answer with no label, and `THERMAL`
stood alone as a fragment of its field. Read off the drawing, nothing else: a
cell with no slot of its own, followed by two or more (label, drawn slot)
pairs, is the heading of those options (unless the cell before it is a label with
no slot, whose value it then is), and each is filed as "<heading> - <option>". The cells arrive from `datasheets.split_label_value`
with a parallel list saying which of them were written on a drawn answer line.
"""

from __future__ import annotations

from collections.abc import Callable

#: How many (label, slot) pairs make a list of options. One pair is an
#: ordinary label and its slot, read as before.
MIN_OPTIONS = 2


def count(
    parts: list[str], slot: list[bool], start: int, is_label: Callable[[str], bool]
) -> int:
    """How many (label, drawn slot) pairs run on from `parts[start]`: a cell
    that reads as a label and has no slot of its own, then a cell written on a
    drawn answer line. The count stops at the first pair that is not one."""
    found = 0
    while (
        start + 1 < len(parts)
        and not slot[start]
        and slot[start + 1]
        and is_label(parts[start])
    ):
        found += 1
        start += 2
    return found


def fold(
    parts: list[str], slot: list[bool], is_label: Callable[[str], bool]
) -> tuple[list[str], list[bool]]:
    """The cells with each heading-over-options folded into the options' own
    labels: `[HEAD, A, ___, B, ___]` becomes `[HEAD - A, ___, HEAD - B, ___]`,
    so the ordinary pairing reads each option with its slot. Every other cell
    is passed through unchanged, in the same order."""
    out_parts: list[str] = []
    out_slot: list[bool] = []
    index = 0
    while index < len(parts):
        options = count(parts, slot, index + 1, is_label)
        # A cell right after a label with no slot of its own is that label's
        # VALUE (`Fluid handled | Water | Pressure ____ Temperature ____`),
        # never the heading of what follows.
        follows_a_label = (
            index > 0 and not slot[index - 1] and is_label(parts[index - 1])
        )
        if (
            slot[index]
            or follows_a_label
            or options < MIN_OPTIONS
            or not is_label(parts[index])
        ):
            out_parts.append(parts[index])
            out_slot.append(slot[index])
            index += 1
            continue
        for k in range(options):
            out_parts += [
                f"{parts[index]} - {parts[index + 1 + 2 * k]}",
                parts[index + 2 + 2 * k],
            ]
            out_slot += [False, True]
        index += 1 + 2 * options
    return out_parts, out_slot
