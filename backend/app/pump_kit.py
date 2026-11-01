"""#1478 pump kit PREPARATION: the box list and the DRAFT rule cards, read from `reference/pump_kit_draft.json`.

Everything here is a draft (no engineer sign-off, no real pump document yet) and is OFF unless
`settings.pump_kit_draft_enabled` is on. Local only: no model, no network, no database.

  * `boxes()` / `cards()`      - the data file, always readable (tests and `kit_report`).
  * `loader_items(...)`        - what `datasheet_checks.checklist_for` appends to the Centrifugal Pump checklist
                                 when the switch is ON: draft cards with a held requirement that no committed item
                                 already asks for. Switch OFF: `[]`, so live reviews are unchanged.
  * `kit_report()`             - each card run through the real `datasheet_checks.evaluate` (via `rule_cards`).

Cards never decide: `card_trust.why_not` answers "not a committed card" for every id here, and the pump type is not
in `card_trust.DECIDING_TYPES`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

KIT_PATH = Path(__file__).resolve().parent / "reference" / "pump_kit_draft.json"
EQUIPMENT_TYPE = "Centrifugal Pump"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(KIT_PATH.read_text(encoding="utf-8"))


def boxes() -> list[dict]:
    return list(_data()["boxes"])


def cards() -> list[dict]:
    return [dict(c) for c in _data()["cards"]]


def _same_rule(a: dict, b: dict) -> bool:
    return (
        a.get("kind") == b.get("kind")
        and (a.get("field") or a.get("left")) == (b.get("field") or b.get("left"))
        and a.get("right") == b.get("right")
    )


def loader_items(key: str, existing: list[dict]) -> list[dict]:
    """The draft cards `checklist_for` appends for the pump checklist. Only with the switch ON, only a card a held
    standard requires (not one that `needs` a standard we do not hold), and never a second copy of a rule the
    checklist already holds (that would print one finding twice)."""
    from .config import settings

    if key != EQUIPMENT_TYPE or not settings.pump_kit_draft_enabled:
        return []
    out = []
    for card in cards():
        if card.get("needs"):
            continue
        if any(_same_rule(card["rule"], e["rule"]) for e in [*existing, *out]):
            continue
        out.append({**card, "kit": "pump", "local": True})
    return out


def with_kit(key: str, items: list[dict]) -> list[dict]:
    """`items` plus the draft kit cards (none while the switch is off)."""
    return items + loader_items(key, items)


def _cases(card: dict) -> list[dict]:
    from . import rule_cards

    return [
        {
            "name": t["name"],
            "kind": "written",
            "facts": [
                rule_cards._fact(
                    f[0], f[1], unit=f[2], blank=f[1] if f[1] in ("*", "TBA") else None
                )
                for f in t["facts"]
            ],
            "text": "",
            "expect": t["expect"],
        }
        for t in card.get("tests") or []
    ]


def run_kit_card(card: dict) -> dict:
    """One card through `rule_cards.run_card` (the real checking code). Its status can be `tested` (the code passed
    the generated or written cases) or `draft`; `draft` is also kept as the card's own flag: a tested draft card is
    still not signed off."""
    from . import rule_cards

    result = rule_cards.run_card({**card, "tests": _cases(card)}, EQUIPMENT_TYPE)
    return {
        **result,
        "draft": bool(card.get("draft")),
        "standard": card["source"]["standard"],
    }


def kit_report() -> dict:
    runs = [run_kit_card(c) for c in cards()]
    return {
        "cards": len(runs),
        "tested": sum(r["status"] == "tested" for r in runs),
        "draft_needs_standard": sum(
            r["status"] == "draft" and r["why"].startswith(rule_cards_needs())
            for r in runs
        ),
        "draft_other": [
            r["id"]
            for r in runs
            if r["status"] == "draft" and not r["why"].startswith(rule_cards_needs())
        ],
        "all_draft": all(r["draft"] for r in runs),
        "boxes": len(boxes()),
        "runs": runs,
    }


def rule_cards_needs() -> str:
    from . import rule_cards

    return rule_cards.NEEDS


KIT_WORDS = (
    "DRAFT pump kit card: the clause number is as stored in the library and "
    "not yet verified by an engineer"
)


def held(result: dict, item: dict) -> dict:
    """A kit card's result is ALWAYS held for the engineer, whatever `rule_auto_use_enabled` says: status
    NEEDS_ENGINEER_REVIEW, the computed status kept as `rule_said` and the numbers kept in the text. It is
    forced draft and local, so a later sign-off of the pump checklist cannot make it ENGINEER_CONFIRMED."""
    if not item.get("kit"):
        return result
    out = {**result, "draft": True, "local": True, "kit": "pump"}
    out["text"] = f"{result['text']} [{KIT_WORDS}]"
    if result["status"] in ("COMPLIANT", "NON_COMPLIANT"):
        out["status"] = "NEEDS_ENGINEER_REVIEW"
        out["rule_said"] = result["status"]
        out["detail"] = (
            f"The numbers read: {result['detail']} (held for the engineer: draft kit card)"
        )
    return out


def rows(checklist, roles, common, tag, rules, page_texts) -> list[dict]:
    """The checklist's results for one tag, kit cards held (see `held`)."""
    from .datasheet_checks import evaluate_item

    return [
        held(
            evaluate_item(
                item,
                roles,
                common,
                tag,
                rules,
                draft=checklist["draft"],
                page_texts=page_texts,
            ),
            item,
        )
        for item in checklist["items"]
    ]
