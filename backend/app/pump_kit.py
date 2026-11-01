"""#1478 pump kit PREPARATION: the box list and the DRAFT rule cards, read from `reference/pump_kit_draft.json`.

The mechanism is shared (`kit_core`, also used by `vessel_kit`); this module only names the pump kit and keeps its
public names. Everything is a draft (no engineer sign-off, no real pump document yet) and OFF unless
`settings.pump_kit_draft_enabled` is on. Cards never decide: `card_trust.why_not` answers "not a committed card"
for every id here, and the pump type is not in `card_trust.DECIDING_TYPES`.
"""

from __future__ import annotations

from . import kit_core

KIT_PATH = kit_core.REFERENCE / "pump_kit_draft.json"
EQUIPMENT_TYPE = "Centrifugal Pump"

KIT_WORDS = (
    "DRAFT pump kit card: the clause number is as stored in the library and "
    "not yet verified by an engineer"
)

KIT = kit_core.register(kit_core.Kit("pump", EQUIPMENT_TYPE, KIT_PATH, KIT_WORDS))

_data = KIT.data
boxes = KIT.boxes
cards = KIT.cards
loader_items = KIT.loader_items
run_kit_card = KIT.run_kit_card
kit_report = KIT.kit_report
with_kit = kit_core.with_kit
held = kit_core.held
rows = kit_core.rows


def rule_cards_needs() -> str:
    return kit_core._needs()
