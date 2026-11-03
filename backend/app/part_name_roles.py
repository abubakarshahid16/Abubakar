"""Test B (part of #805), behind FORM_PART_NAME_ROLES_ENABLED: a part printed ALONE fills its field, under strict rules.

THE DEFECT. A materials list prints "IMPELLER: <material>" and a sentence prints "... A DOUBLE MECHANICAL SEAL". The form
reader's label gate wants "impeller material" / "seal type" in the quote (`claude_datasheet._field_in_quote`, audit M2:
half the label's words, at least two), so correct answers were refused as `label_not_in_quote`, and the stored facts that
carry the printed label ("IMPELLER") sit under no role, so the check said "no label found".

THE RULES (all must hold; the label gate protects against putting a value on the wrong role, so this stays strict):
  1. the role's data names the part (`part_names`); every part word of the field is a WHOLE word of the quote;
  2. the quote holds no OTHER role's part word (two parts in one quote never fill anything);
  3. for a "<part> material" field: the part word is the label of the cell, i.e. the quote opens with it (after a row
     number or a bullet), and the value follows it directly; the value is MADE ONLY of recognised material tokens
     (`material_value`): any other word (not, same, as, at, vendor, see, or ...) means no fill, and an alternative is
     never one value; an "impeller wear ring" row is another part and never fills "impeller material";
  4. for a "<part> type" field: the value is exactly one phrase of the closed list `seal_type_phrases`, it ends the
     quote, and the quote holds no negation;
  5. stored facts (`with_roles`): a bare part-name fact fills only if its value reads as a material, it is not blank, and
     ONE distinct value exists for that part in the whole document; two values means no fill; a role that already
     has a fact under its own name is left alone.
Nothing here knows a sheet: the part words and material words are reference data (rule 13).
"""

from __future__ import annotations

import re

from .config import settings


def enabled() -> bool:
    return bool(settings.form_part_name_roles_enabled)


def _words(text) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _parts_of(role: str, rules: dict) -> list[str]:
    return [w.lower() for w in (rules["roles"].get(role, {}).get("part_names") or [])]


def _all_part_words(rules: dict) -> set[str]:
    return {
        w.lower()
        for spec in rules["roles"].values()
        for w in (spec.get("part_names") or [])
    }


_SEPARATORS = re.compile(r"[\s/,;()&+\-\.:]+")


def _tokens(value) -> list[str]:
    text = str(value or "").lower().replace("ni-resist", "niresist")
    text = re.sub(r"\bs\.s\.?", "ss", text)
    return [t for t in _SEPARATORS.split(text) if t]


def _grade_like(token: str) -> bool:
    """A grade or spec code: letters and digits together (a216, cf8m, 5a, s32760) or three to five digits (316, 4140)."""
    has_digit, has_letter = (
        any(c.isdigit() for c in token),
        any(c.isalpha() for c in token),
    )
    return (has_digit and has_letter) or (token.isdigit() and 3 <= len(token) <= 5)


def material_value(value, rules: dict) -> bool:
    """The value is MADE ONLY of recognised material tokens (names, modifiers, spec words, grade codes) and holds at
    least one material name or grade code. Any other word (not, same, as, at, vendor, works, see, per, or, and, a
    number alone ...) means it is not a material: prose, a negation, a cross-reference or an alternative never fills."""
    nouns = {w.lower() for w in rules.get("material_nouns", [])}
    others = {
        w.lower()
        for w in (
            *rules.get("material_modifiers", []),
            *rules.get("material_spec_words", []),
        )
    }
    tokens = _tokens(value)
    if not tokens:
        return False
    strong = False
    for token in tokens:
        if token in nouns or _grade_like(token):
            strong = True
        elif token not in others:
            return False
    return strong


def seal_type_value(value, quote_words: list[str], rules: dict) -> bool:
    """The value is exactly one phrase of the closed list of seal types, and the quote holds no negation."""
    phrases = {" ".join(_words(p)) for p in rules.get("seal_type_phrases", [])}
    negations = {w.lower() for w in rules.get("seal_negations", [])}
    return " ".join(_words(value)) in phrases and not (negations & set(quote_words))


def accepts(role: str, value: str, printed: str, rules: dict) -> bool:
    """The form reader's label gate, relaxed for a bare part name. `printed` is the folded quote."""
    if not enabled() or not value:
        return False
    parts = _parts_of(role, rules)
    kind = role.rsplit("_", 1)[-1]
    if not parts or kind not in ("material", "type"):
        return False
    quote_words = _words(printed)
    others = _all_part_words(rules) - set(parts)
    if any(o in quote_words for o in others):
        return False  # rule 2: another role's part is in the same quote
    value_words = _words(value)
    if kind == "material":
        if not material_value(value, rules):
            return False
        for part in parts:
            # rule 3: the quote opens with the part (a row number or bullet may come first) and the value follows it
            opening = re.match(
                r"^\W*(?:\d+\W+)?" + re.escape(part) + r"\b\W*(.*)$",
                str(printed or "").strip(),
                re.IGNORECASE,
            )
            if opening and _words(opening.group(1)) == value_words:
                return True
        return False
    # kind == "type": a sentence that states it, with a value from the closed list that ends the quote
    for part in parts:
        if (
            part in quote_words
            and part in value_words
            and quote_words[-len(value_words) :] == value_words
            and seal_type_value(value, quote_words, rules)
        ):
            return True
    return False


def with_roles(facts: list[dict], rules: dict, wanted) -> list[dict]:
    """`facts`, with each bare part-name fact that satisfies the rules renamed to its role's words. Switch off: as given."""
    if not enabled():
        return facts
    named = {}
    for role in wanted:
        spec = rules["roles"].get(role) or {}
        if role.endswith("_material") and spec.get("part_names"):
            for part in spec["part_names"]:
                named[part.lower()] = role
    if not named:
        return facts
    bare: dict[str, list[dict]] = {}
    for fact in facts:
        name = " ".join(_words(fact.get("field_name")))
        if (
            name in named
            and not fact.get("is_blank")
            and material_value(fact.get("field_value"), rules)
        ):
            bare.setdefault(named[name], []).append(fact)
    own = {" ".join(_words(f.get("field_name"))) for f in facts}
    out = list(facts)
    for role, found in bare.items():
        if " ".join(role.split("_")) in own:
            continue  # a fact under the role's own name already speaks for it
        if len({" ".join(_words(f.get("field_value"))) for f in found}) != 1:
            continue  # two values for one part: no fill
        for fact in found:
            out[out.index(fact)] = {
                **fact,
                "field_name": " ".join(role.split("_")),
                "part_name_filled": True,
            }
    return out
