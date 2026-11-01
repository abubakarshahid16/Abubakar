"""#1481 heat exchanger kit preparation (parked kit): the data file's limits and the kit's own wording and type.

The shared kit mechanism (`kit_core`) is covered by M1506-01..06; these entries cover what the exchanger kit adds.
"""

from __future__ import annotations

from ._base import APP, Mutation

KIT = APP / "exchanger_kit.py"
DATA = APP / "reference" / "exchanger_kit_draft.json"
TARGET = "tests/test_1481_exchanger_kit_prep.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1513-01",
        phase=1513,
        description="the joint efficiency floor of the exchanger card is lowered from 0.85",
        path=DATA,
        anchor='"value": 0.85',
        replacement='"value": 0.5',
        target=TARGET,
        keyword="planted or limit or each_held",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1513-02",
        phase=1513,
        description="the design pressure margin factor of the exchanger card is lowered from 1.05 to 1.00",
        path=DATA,
        anchor='"percent": 105',
        replacement='"percent": 100',
        target=TARGET,
        keyword="planted or limit or each_held",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1513-03",
        phase=1513,
        description="the 28 C design temperature margin of the exchanger card is dropped",
        path=DATA,
        anchor='"at_least": 28,',
        replacement='"at_least": 0,',
        target=TARGET,
        keyword="planted or limit or each_held",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1513-04",
        phase=1513,
        description="the plausible range of the joint efficiency card is widened: a joint efficiency printed as 70 is judged as 70, not asked",
        path=DATA,
        anchor='"max": 1\n',
        replacement='"max": 100\n',
        target=TARGET,
        keyword="planted or bound",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1513-05",
        phase=1513,
        description="a card that needs a clause no held standard has (the test pressure) loses its needs note and is loaded",
        path=DATA,
        anchor='"needs": "a clause that requires the test pressure',
        replacement='"x": "a clause that requires the test pressure',
        target=TARGET,
        keyword="needs or only_the_cards",
        tags=("honesty",),
    ),
    Mutation(
        id="M1513-06",
        phase=1513,
        description="the exchanger kit loads onto the pressure vessel checklist",
        path=KIT,
        anchor='EQUIPMENT_TYPE = "Heat Exchanger"',
        replacement='EQUIPMENT_TYPE = "Pressure Vessel"',
        target=TARGET,
        keyword="switch",
        tags=("honesty",),
    ),
    Mutation(
        id="M1513-07",
        phase=1513,
        description="an exchanger row no longer carries the exchanger wording",
        path=KIT,
        anchor='    "DRAFT exchanger kit card: the clause number is as stored in the library and "',
        replacement='    "DRAFT kit card: the clause number is as stored in the library and "',
        target=TARGET,
        keyword="words or draft or other_kits",
        tags=("honesty",),
    ),
)
