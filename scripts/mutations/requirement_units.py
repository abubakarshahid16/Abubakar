"""Mutations of the #193 requirement-unit grammar."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_193_requirement_units.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M865", phase=75, description="#193: flow units are unknown again, so fire-water limits lose their unit",
             path=APP / "claims.py", anchor='    "l/s": None, "l/min": None, "l/m2s": None, "l/(m2s)": None, "l/m2/s": None,\n',
             replacement="", target=_T, keyword="printed_unit_is_kept", tags=("extraction",)),
    Mutation(id="M866", phase=75, description="#193: absolute and gauge kPa/psi are unknown again",
             path=APP / "claims.py", anchor='    "psia": "pressure", "kpag": "pressure", "kpaa": "pressure", "bara": "pressure",\n',
             replacement="", target=_T, keyword="printed_unit_is_kept or absolute_and_gauge", tags=("extraction",)),
    Mutation(id="M867", phase=75, description="#193: absolute pressure converted like gauge - 13 psia compares with 13 psig",
             path=APP / "claims.py", anchor='    "psia": "pressure", "kpag": "pressure", "kpaa": "pressure", "bara": "pressure",\n',
             replacement='    "kpag": "pressure", "kpaa": "pressure", "bara": "pressure",\n',
             target=_T, keyword="absolute_and_gauge", tags=("honesty",)),
    Mutation(id="M868", phase=75, description="#193: a unit glued to its conversion '(20,000' is thrown away",
             path=APP / "requirements_3b.py",
             anchor='    cleaned = re.split(r"\\((?=\\s*\\d)", cleaned, maxsplit=1)[0].rstrip()\n',
             replacement="", target=_T, keyword="printed_unit_is_kept", tags=("extraction",)),
    Mutation(id="M869", phase=75, description="#193: any bracket ends the unit, so dB(A) becomes dB",
             path=APP / "requirements_3b.py",
             anchor='    cleaned = re.split(r"\\((?=\\s*\\d)", cleaned, maxsplit=1)[0].rstrip()\n',
             replacement='    cleaned = re.split(r"\\(", cleaned, maxsplit=1)[0].rstrip()\n',
             target=_T, keyword="already_worked or printed_unit_is_kept", tags=("extraction",)),
)
