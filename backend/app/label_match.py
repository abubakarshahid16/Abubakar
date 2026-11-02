"""Two general ways a datasheet field the sheet DOES give was reported missing or in conflict (switch
`datasheet_label_join_enabled`, off by default; finding on the TEMA exchanger proof run 79c0c68d).

1. SPLIT ABBREVIATIONS. The reader's normalised name drops dots to spaces, so a printed "O.D." is stored as
   "o d" and the role pattern `tube o.d.` (which allows a dot, not a space) never saw it: "Tube outside
   diameter was not found" while "tube o d  1. in" sat in the facts. `joined_letters` joins a run of single
   letters ("tube o d" -> "tube od"); it is tried ONLY when the name matches no role as stored, and the joined
   name must then match a role's own pattern, so an unrelated label gains nothing.
2. A UNIT LEFT OFF ONE COPY. The same field printed on two pages, once "650" and once "650. F" (or "0.0625"
   and "0.0625 in"), was "two different values". `drop_unit_less_twins` removes a reading with NO unit when
   the readings that have a unit agree with each other and state the same number, so the united reading
   stands. Two different numbers stay two values; so do two readings that disagree on the unit.

Neither fix decides anything: a "required" box says the field is stated, a comparison still needs a unit on one
scale (a unit-less value is never compared), and nothing here makes a field up. No label or layout is named.
"""

from __future__ import annotations

import re

from . import claims, numparse

_SINGLE = re.compile(r"^[a-z]$")


def joined_letters(name: str) -> str:
    """`name` with every run of two or more single-letter words joined ("tube o d" -> "tube od")."""
    out: list[str] = []
    run: list[str] = []
    for word in str(name or "").split():
        if _SINGLE.match(word):
            run.append(word)
            continue
        out.extend(["".join(run)] if len(run) > 1 else run)
        run = []
        out.append(word)
    out.extend(["".join(run)] if len(run) > 1 else run)
    return " ".join(out)


def _number(fact: dict) -> float | None:
    raw = fact.get("raw_value")
    return None if raw in (None, "") else claims.parse_value(str(raw))


def _has_unit(fact: dict) -> bool:
    return bool(str(fact.get("raw_unit") or "").strip())


def _plain(fact: dict) -> bool:
    """True when nothing around the printed number changes its meaning (same test as `same_value`)."""
    from .same_value import _around_the_number, _plain_note

    around = _around_the_number(fact)
    return around is not None and _plain_note(*around)


def unit_readings(found: list[dict]) -> list[dict]:
    """The readings the unit check (DS-U1) looks at: with the switch on, without the unit-less copy
    `_one` already united with its twin that has the unit (rule 8: both homes read the field alike).
    """
    from .config import settings

    if not settings.datasheet_label_join_enabled:
        return found
    return drop_unit_less_twins(found)


def drop_unit_less_twins(found: list[dict]) -> list[dict]:
    """`found` without the readings that carry no unit where readings with a unit state the same number.
    Unchanged when no such pair exists or the united readings do not all agree on number and unit."""
    united = [f for f in found if _has_unit(f) and _number(f) is not None]
    bare = [f for f in found if not _has_unit(f)]
    # "max 650", "not 650": a bound or negation is another value
    if not all(_plain(f) for f in bare):
        return found
    if not united or not bare or len(united) + len(bare) != len(found):
        return found
    units = {numparse.fold_unit(f["raw_unit"]) for f in united}
    numbers = {_number(f) for f in united}
    if len(units) != 1 or len(numbers) != 1:
        return found
    if any(_number(f) not in numbers for f in bare):
        return found
    return united
