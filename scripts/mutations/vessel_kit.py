"""#1480 vessel kit preparation (parked kit) and the shared kit mechanism it runs on (`kit_core`)."""

from __future__ import annotations

from ._base import APP, Mutation

KIT = APP / "kit_core.py"
DATA = APP / "reference" / "vessel_kit_draft.json"
TARGET = "tests/test_1480_vessel_kit_prep.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1506-01",
        phase=1506,
        description="a kit's switch is ignored: its draft cards join the live checklist while it is off",
        path=KIT,
        anchor="        if key != self.equipment_type or not self.enabled():",
        replacement="        if key != self.equipment_type:",
        target=TARGET,
        keyword="switch_off",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1506-02",
        phase=1506,
        description="a kit row that fails or passes is no longer turned into an engineer's question",
        path=KIT,
        anchor='        out["status"] = "NEEDS_ENGINEER_REVIEW"\n',
        replacement="        pass\n",
        target=TARGET,
        keyword="always_held",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1506-03",
        phase=1506,
        description="a card that needs a standard we do not hold is loaded into the live checklist",
        path=KIT,
        anchor='            if card.get("needs"):\n                continue\n',
        replacement="            if False:\n                continue\n",
        target=TARGET,
        keyword="only_the_cards",
        tags=("honesty",),
    ),
    Mutation(
        id="M1506-04",
        phase=1506,
        description="a kit card repeats a rule the committed checklist already asks (one finding printed twice)",
        path=KIT,
        anchor='            if any(_same_rule(card["rule"], e["rule"]) for e in [*existing, *out]):',
        replacement="            if False:",
        target=TARGET,
        keyword="only_the_cards",
        tags=("honesty",),
    ),
    Mutation(
        id="M1506-05",
        phase=1506,
        description="a card's own plausible range is ignored: a joint efficiency printed as 70 passes as 0.85 or more",
        path=KIT,
        anchor='    bounds = item.get("plausible")\n',
        replacement="    bounds = None\n",
        target=TARGET,
        keyword="percentage or planted or bound",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1506-06",
        phase=1506,
        description="a vessel row carries the wording of another kit",
        path=KIT,
        anchor='(k.words for k in _kits() if k.name == item["kit"]),',
        replacement="(k.words for k in _kits()),",
        target=TARGET,
        keyword="words",
        tags=("honesty",),
    ),
    Mutation(
        id="M1506-07",
        phase=1506,
        description="the joint efficiency floor of the vessel card is lowered from 0.85",
        path=DATA,
        anchor='"value": 0.85',
        replacement='"value": 0.5',
        target=TARGET,
        keyword="planted or limit or each_held",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1506-08",
        phase=1506,
        description="the design pressure margin factor of the vessel card is lowered from 1.05 to 1.00",
        path=DATA,
        anchor='"percent": 105',
        replacement='"percent": 100',
        target=TARGET,
        keyword="planted or limit or each_held",
        tags=("honesty", "critical"),
    ),
)
