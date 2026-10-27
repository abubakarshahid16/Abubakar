"""The flow-rate rows of the one unit table (`claims._UNIT_TABLE`).

A mass or volume flow is a quantity per unit of time, and the same flow is
written many ways: 1.0 kg/s is 3600 kg/h, 60 l/min is 3.6 m3/h. Until #1290 only
kg/h and m3/h were converted, so a limit in kg/s against a value in kg/h came
back "not the same quantity" and went to the engineer although it is a plain
comparison.

Every row is built from two exact facts: how much mass or volume the numerator
unit is, and how many of the time unit make an hour. Both are definitions
(1 lb = 0.45359237 kg, 1 ft = 0.3048 m, 1 US gallon = 231 in3), so nothing
here is a rounding. What is NOT here, on purpose: "nm3", "sm3", "scf" (a volume
at a reference condition is not a volume), "ton"/"tons" (short or long),
plain "gal" and "bbl" (US or imperial; oil or beer), and "month"/"year"
(not a fixed number of hours). Those stay recognised-not-converted, so they
never compare with anything but their own spelling.
"""

from __future__ import annotations

from fractions import Fraction

#: numerator spelling -> kilograms in one of it.
_MASS: dict[str, Fraction] = {
    "g": Fraction(1, 1000),
    "kg": Fraction(1),
    "t": Fraction(1000),
    "tonne": Fraction(1000),
    "tonnes": Fraction(1000),
    "lb": Fraction(45359237, 100000000),
    "lbs": Fraction(45359237, 100000000),
}
#: numerator spelling -> cubic metres in one of it.
_VOLUME: dict[str, Fraction] = {
    "ml": Fraction(1, 1000000),
    "cm3": Fraction(1, 1000000),
    "l": Fraction(1, 1000),
    "m3": Fraction(1),
    "ft3": Fraction(28316846592, 10**12),
    "usgal": Fraction(3785411784, 10**12),
}
#: time spelling -> how many of it make an hour, inverted: "per minute" is 60
#: times "per hour", so the factor to the per-hour base is that many.
_PER_HOUR: dict[str, Fraction] = {
    "h": Fraction(1),
    "hr": Fraction(1),
    "hrs": Fraction(1),
    "hour": Fraction(1),
    "min": Fraction(60),
    "s": Fraction(3600),
    "sec": Fraction(3600),
    "d": Fraction(1, 24),
    "day": Fraction(1, 24),
}

#: spelling -> (dimension, base unit, factor to the base), as `_UNIT_TABLE` rows.
TABLE: dict[str, tuple[str, str, float]] = {
    f"{numerator}/{per}": (dimension, base, float(amount * hours))
    for dimension, base, numerators in (
        ("mass_flow", "kg/h", _MASS),
        ("volumetric_flow", "m3/h", _VOLUME),
    )
    for numerator, amount in numerators.items()
    for per, hours in _PER_HOUR.items()
}

#: One-word spellings of a rate above: "USGPM" is a US gallon per minute, exact like its long form.
for _alias, _long in {"usgpm": "usgal/min"}.items():
    TABLE[_alias] = TABLE[_long]
