"""Units whose case is their meaning (#1618), the one home of that rule.

Every other unit folds to lower case, because a sheet printed in capitals still
means "BAR" and "MM". These spellings do not: the folded spelling belongs to the
other unit, up to 10^9 away. `mpa`, `mw`, `mwh` and `mj` are the mega units; `ma`,
`mv`, `mg` and `ml` the milli ones; `ms` is the millisecond, not the millisiemens.
Written out, not a pattern: "mL" is the same unit as "ml", and "MM" on a capitals
sheet is mm. Any code that lower-cases a unit before reading it calls `fold_unit`.

RECOGNISED, NOT CONVERTED, on purpose. A pressure printed in mPa is far more
likely a mistyped MPa than a real millipascal, and converting it would pass any
maximum. With no number it gets no verdict and the engineer reads it. Two values
in one of these units still compare as written.
"""

from __future__ import annotations

import re

from .numparse import CASE_KEPT_UNITS

#: Unit -> dimension (`claims._UNCONVERTED_UNITS`). Bare "mWh" is absent because
#: bare "MWh" is not a unit either; it is here only as the top of a rate.
UNCONVERTED: dict[str, str | None] = {
    "mPa": "pressure",
    "mPA": "pressure",
    "mW": None,
    "mJ": None,
    "mS": None,
    "MA": "current",
    "MV": "voltage",
    "Mg": None,
    "ML": None,
    "mPa·s": "viscosity",
    "mPa.s": "viscosity",
    "mPa-s": "viscosity",
    "mPas": "viscosity",
    "pa·s": "viscosity",
    "pa.s": "viscosity",
    "pa-s": "viscosity",
}

#: The reference suffix forms (`claims._REFERENCE_SUFFIX`).
REFERENCE_SUFFIX = {
    "mPag": ("mPa", "gauge"),
    "mPaa": ("mPa", "absolute"),
    "mPaG": ("mPa", "gauge"),
    "mPaA": ("mPa", "absolute"),
}

#: What makes a pascal unit a viscosity, not a pressure: "5 mPa.s", "5 Pa·s".
#: Lower case only and no gap after the full stop, so "5 MPa. Second" stays a
#: pressure. "5 mPa s" is the SI spelling with a space.
_PASCAL_SECOND = re.compile(r"(?:\s?[·⋅]\s?|\s|[.\-])s(?:ec)?(?![A-Za-z0-9])")


def fold_unit(unit: object) -> str:
    """A unit in lower case and single-spaced, EXCEPT one in `CASE_KEPT_UNITS`:
    that keeps its case, with no spaces, and only what follows its slash folds
    ("mW / M2" is "mW/m2")."""
    text = " ".join(str(unit or "").split())
    top, slash, rest = text.replace(" ", "").partition("/")
    return top + slash + rest.lower() if top in CASE_KEPT_UNITS else text.lower()


def unit_in_match(match: re.Match, group: str = "unit") -> str | None:
    """`unit_at` for a regex match that captured a unit in `group`."""
    unit = match.group(group)
    return unit_at(match.string, unit, match.end(group)) if unit else unit


def calc_key(unit: str | None) -> str:
    """A unit as a calculation's table spells it (`datasheet_checks`)."""
    key = fold_unit(unit).replace(" ", "").replace("²", "2").replace("³", "3")
    return key.replace("°", "deg").replace("μ", "u").replace("µ", "u")


def unit_at(sentence: str, unit: str, end: int) -> str:
    """The unit a measurement pattern stopped at, `end` being where it stopped. The
    pattern stops at a pascal, so a pascal-second is read whole here: "5 MPa.s" has
    no table entry and is then no measurement, never 5 MPa."""
    if unit.lower() not in ("pa", "kpa", "mpa"):
        return unit
    second = _PASCAL_SECOND.match(sentence, end)
    if second is None:
        return unit
    tail = second.group(0).replace("⋅", "·")
    # A space alone is the multiplication dot.
    return unit + (
        "·" + tail.strip()
        if tail[0].isspace() and "·" not in tail
        else tail.replace(" ", "")
    )
