"""Heat exchanger kit PREPARATION (parked kit #1481): the box list and the DRAFT rule cards, read from `reference/exchanger_kit_draft.json`.

Same mechanism as the pump and vessel kits (`kit_core`). The exchanger kit is PARKED (milestone 58): its proof waits
for 2 real exchanger documents. Everything is a draft and OFF unless `settings.exchanger_kit_draft_enabled` is on.
Cards never decide, and a kit row is always held for the engineer.
"""

from __future__ import annotations

from . import kit_core

KIT_PATH = kit_core.REFERENCE / "exchanger_kit_draft.json"
EQUIPMENT_TYPE = "Heat Exchanger"

KIT_WORDS = (
    "DRAFT exchanger kit card: the clause number is as stored in the library and "
    "not yet verified by an engineer"
)

KIT = kit_core.register(kit_core.Kit("exchanger", EQUIPMENT_TYPE, KIT_PATH, KIT_WORDS))

_data = KIT.data
boxes = KIT.boxes
cards = KIT.cards
loader_items = KIT.loader_items
run_kit_card = KIT.run_kit_card
kit_report = KIT.kit_report
