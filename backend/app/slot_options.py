"""A heading over options that each have a drawn slot (#882, M-03 CRS).

`MINIMUM FLOW` on one line and `STABLE ____   THERMAL ____` on the next: paired
left to right, the heading took `STABLE` as its VALUE (a value nobody wrote),
`STABLE`'s own slot was dropped as an answer with no label, and `THERMAL`
stood alone as a fragment of its field. Read off the drawing, nothing else: a
cell with no slot of its own, followed by two or more (label, drawn slot)
pairs, is the heading of those options, and each is filed as
"<heading> - <option>". The cells arrive from `datasheets.split_label_value`
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


def pairs_at(
    parts: list[str],
    slot: list[bool],
    index: int,
    is_label: Callable[[str], bool],
    finish: Callable[[str, str], tuple[str, str] | None],
) -> tuple[list[tuple[str, str]], int] | None:
    """`(pairs, cells used)` when `parts[index]` is a heading over options,
    else None. `finish` is the reader's last check on every pair."""
    options = count(parts, slot, index + 1, is_label)
    if options < MIN_OPTIONS or not is_label(parts[index]):
        return None
    heading = parts[index]
    made = (
        finish(f"{heading} - {parts[index + 1 + 2 * k]}", parts[index + 2 + 2 * k])
        for k in range(options)
    )
    return [pair for pair in made if pair is not None], 1 + 2 * options
