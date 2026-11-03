"""The shared mechanism of an equipment KIT: a box list and DRAFT rule cards read from a data file (#1478 pump, #1480 vessel, #1481 exchanger).

A kit is preparation only: no engineer sign-off, no real document of that type yet. Each kit is OFF unless its own
`settings.<name>_kit_draft_enabled` is on. Local only: no model, no network, no database.

  * `Kit.boxes()` / `Kit.cards()`  - the data file, always readable (tests and `kit_report`).
  * `Kit.loader_items(...)`        - what `datasheet_checks.checklist_for` appends to the equipment type's checklist
                                     when the switch is ON: draft cards with a held requirement that no committed
                                     item already asks for. Switch OFF: `[]`, so live reviews are unchanged.
  * `Kit.kit_report()`             - each card run through the real `datasheet_checks.evaluate` (via `rule_cards`).
  * `rows(...)` / `with_kit(...)`  - the two hooks `datasheet_checks` calls; they serve every kit in `KITS`.

Cards never decide: `card_trust.why_not` answers "not a committed card" for every id here, and no kit type is in
`card_trust.DECIDING_TYPES`. A kit row is ALWAYS held for the engineer (`held`), whatever `rule_auto_use_enabled` says.
"""

from __future__ import annotations

import json
from pathlib import Path

REFERENCE = Path(__file__).resolve().parent / "reference"


def _same_rule(a: dict, b: dict) -> bool:
    return (
        a.get("kind") == b.get("kind")
        and (a.get("field") or a.get("left")) == (b.get("field") or b.get("left"))
        and a.get("right") == b.get("right")
    )


def _needs() -> str:
    from . import rule_cards

    return rule_cards.NEEDS


class Kit:
    def __init__(self, name: str, equipment_type: str, path: Path, words: str):
        self.name = name
        self.equipment_type = equipment_type
        self.path = path
        self.words = words
        self._cache: dict | None = None

    @property
    def flag(self) -> str:
        return f"{self.name}_kit_draft_enabled"

    def enabled(self) -> bool:
        from .config import settings

        return bool(getattr(settings, self.flag))

    def data(self) -> dict:
        if self._cache is None:
            self._cache = json.loads(self.path.read_text(encoding="utf-8"))
        return self._cache

    def boxes(self) -> list[dict]:
        return list(self.data()["boxes"])

    def cards(self) -> list[dict]:
        return [dict(c) for c in self.data()["cards"]]

    def loader_items(self, key: str, existing: list[dict]) -> list[dict]:
        """The draft cards `checklist_for` appends for this kit's checklist. Only with the switch ON, only a card a
        held standard requires (not one that `needs` a standard we do not hold), and never a second copy of a rule
        the checklist already holds (that would print one finding twice)."""
        if key != self.equipment_type or not self.enabled():
            return []
        out = []
        for card in self.cards():
            if card.get("needs"):
                continue
            if any(_same_rule(card["rule"], e["rule"]) for e in [*existing, *out]):
                continue
            out.append({**card, "kit": self.name, "local": True})
        return out

    def _cases(self, card: dict) -> list[dict]:
        from . import rule_cards

        return [
            {
                "name": t["name"],
                "kind": "written",
                "facts": [
                    rule_cards._fact(
                        f[0],
                        f[1],
                        unit=f[2],
                        blank=f[1] if f[1] in ("*", "TBA") else None,
                    )
                    for f in t["facts"]
                ],
                "text": "",
                "expect": t["expect"],
            }
            for t in card.get("tests") or []
        ]

    def run_kit_card(self, card: dict) -> dict:
        """One card through `rule_cards.run_card` (the real checking code). Its status can be `tested` (the code
        passed the generated or written cases) or `draft`; `draft` is also kept as the card's own flag: a tested
        draft card is still not signed off."""
        from . import rule_cards

        result = rule_cards.run_card(
            {**card, "tests": self._cases(card)}, self.equipment_type
        )
        return {
            **result,
            "draft": bool(card.get("draft")),
            "standard": card["source"]["standard"],
        }

    def kit_report(self) -> dict:
        needs = _needs()
        runs = [self.run_kit_card(c) for c in self.cards()]
        return {
            "cards": len(runs),
            "tested": sum(r["status"] == "tested" for r in runs),
            "draft_needs_standard": sum(
                r["status"] == "draft" and r["why"].startswith(needs) for r in runs
            ),
            "draft_other": [
                r["id"]
                for r in runs
                if r["status"] == "draft" and not r["why"].startswith(needs)
            ],
            "all_draft": all(r["draft"] for r in runs),
            "boxes": len(self.boxes()),
            "runs": runs,
        }


#: Every kit, filled in by the kit modules (`pump_kit`, `vessel_kit`, `exchanger_kit`) as they are imported (`_kits` imports them).
KITS: list[Kit] = []


def register(kit: Kit) -> Kit:
    KITS.append(kit)
    return kit


def _kits() -> list[Kit]:
    from . import (  # noqa: F401  (importing a kit module registers it)
        exchanger_kit,
        pump_kit,
        vessel_kit,
    )

    return KITS


def with_kit(key: str, items: list[dict]) -> list[dict]:
    """`items` plus the draft kit cards of every kit for this type (none while its switch is off)."""
    from .draft_items import read

    out = list(items)
    for kit in _kits():
        out += kit.loader_items(key, out)
    return read(key, out)


def without_stated(results: list[dict]) -> list[dict]:
    """`results` less a draft item's stated value (it gives no verdict and no row; see `draft_items`)."""
    from .draft_items import without_stated as keep

    return keep(results)


def held(result: dict, item: dict) -> dict:
    """A kit card's result is ALWAYS held for the engineer, whatever `rule_auto_use_enabled` says: status
    NEEDS_ENGINEER_REVIEW, the computed status kept as `rule_said` and the numbers kept in the text. It is
    forced draft and local, so a later sign-off of the checklist cannot make it ENGINEER_CONFIRMED."""
    if not item.get("kit"):
        return result
    words = next(
        (k.words for k in _kits() if k.name == item["kit"]),
        "DRAFT kit card: the clause number is as stored in the library and not yet verified by an engineer",
    )
    out = {**result, "draft": True, "local": True, "kit": item["kit"]}
    out["text"] = f"{result['text']} [{words}]"
    if result["status"] in ("COMPLIANT", "NON_COMPLIANT"):
        out["status"] = "NEEDS_ENGINEER_REVIEW"
        out["rule_said"] = result["status"]
        out["detail"] = (
            f"The numbers read: {result['detail']} (held for the engineer: draft kit card)"
        )
    return out


def _with_bounds(item: dict, rules: dict) -> dict:
    """A card may carry `plausible: {min, max}` for its own field (a scale the sheet can print two ways, such as a joint
    efficiency of 0.85 or 85): a value outside it is an engineer's question, never judged. Only this card sees it;
    the committed role table is not touched."""
    bounds = item.get("plausible")
    field = (item.get("rule") or {}).get("field")
    if not bounds or not field:
        return rules
    role = (rules.get("roles") or {}).get(field) or {}
    return {**rules, "roles": {**rules["roles"], field: {**role, "plausible": bounds}}}


def rows(checklist, roles, common, tag, rules, page_texts) -> list[dict]:
    """The checklist's results for one tag, kit cards held (see `held`)."""
    from .datasheet_checks import evaluate_item
    from .draft_items import hold as hold_draft_item

    return [
        held(
            hold_draft_item(
                evaluate_item(
                    item,
                    roles,
                    common,
                    tag,
                    _with_bounds(item, rules),
                    draft=checklist["draft"],
                    page_texts=page_texts,
                ),
                item,
            ),
            item,
        )
        for item in checklist["items"]
    ]
