"""One datasheet field read more than once (order 142 fix C, PR #1185).

The matcher's tie rule (`comparison._resolve_hits`) treats two equally
specific hits as "more than one submitted field is named". When every hit is
the SAME canonical field about the same item (or none) - the sheet states one
field on two pages, or twice - that is one field, and the only question is
whether its copies agree. All blank: one blank field. All copies filled with
the same value: one field, the others named. Different values, or a value on
one copy and a blank on another: still a tie for an engineer, and a number is
never picked between two numbers.

`comparison` imports this module, so this module imports `comparison` inside
the functions that need it.
"""

from __future__ import annotations


def _copy_label(fact: dict, fallback: str) -> str:
    return f"{fact.get('field_label') or fallback} (page {fact.get('page')})"


def _value_signature(fact: dict) -> tuple:
    """What one filled copy of a field says, for "do the copies agree".

    The stored normalised number and unit when the reader gave them; a range
    by its two ends; otherwise the stated words (`raw_value`, or
    `field_value` for a categorical field) with case and spacing folded. The
    gauge/absolute reference and the table column the reader kept are part of
    it, so two columns of one table are never "the same copy". A copy that
    states nothing readable agrees with no other copy: its own id is its
    signature, so it can never be merged into "the same value"."""
    from . import comparison as c

    unit = " ".join(str(fact.get("raw_unit") or "").lower().split())
    kept = (
        str(fact.get("unit_reference") or "").lower(),
        str(fact.get("value_column") or "").lower(),
    )
    if c.fact_range(fact) is not None:
        low, high = c.fact_range(fact)
        return ("range", low, high, unit, *kept)
    number = fact.get("normalized_value")
    if number is not None:
        try:
            return (
                "number",
                float(number),
                str(fact.get("normalized_unit") or unit).lower(),
                *kept,
            )
        except (TypeError, ValueError):
            pass  # not a number after all: compared by its words below
    words = " ".join(
        str(fact.get("raw_value") or fact.get("field_value") or "").lower().split()
    )
    return ("text", words, unit, *kept) if words else ("unread", fact.get("id"))


def _copy_value_text(fact: dict) -> str:
    from . import comparison as c

    if fact.get("is_blank"):
        return "left blank"
    if c.fact_range(fact) is not None and fact.get("raw_value") in (None, ""):
        text = f"{fact.get('value_min')} to {fact.get('value_max')}"
    else:
        text = str(fact.get("raw_value") or fact.get("field_value") or "").strip()
    unit = str(fact.get("raw_unit") or "").strip()
    return f"{text} {unit}".strip()


def resolve(best: list[dict], refused: list[dict]) -> dict:
    """The same canonical field found more than once on the sheet.

    All blank: one blank field. All copies filled with the same value: one
    field, the others named. Different values - or a value on one copy and a
    blank ("to be provided") on another - stay a tie for an engineer: a
    number is never picked between two numbers, and a stated value never
    hides a copy that leaves the field open. Each copy is then named once,
    with its page and value, instead of the same name repeated."""
    from . import comparison as c

    ordered = sorted(
        best,
        key=lambda h: (h["fact"].get("page") or 0, h["fact"].get("field_label") or ""),
    )
    filled = [h for h in ordered if not h["fact"].get("is_blank")]
    mixed = bool(filled) and len(filled) < len(ordered)
    if mixed or len({_value_signature(h["fact"]) for h in filled}) > 1:
        return {
            "fact": None,
            "matched_phrase": None,
            "method": None,
            "reason": c.AMBIGUOUS_MATCH,
            "refused": refused,
            "same_field_copies": True,
            "candidates": sorted(
                {
                    f"{_copy_label(h['fact'], h['name'])}: {_copy_value_text(h['fact'])}"
                    for h in ordered
                }
            ),
        }
    chosen, name = ordered[0], ordered[0]["name"]
    return {
        "fact": chosen["fact"],
        "matched_phrase": chosen["name"],
        "method": c.METHOD_CONTAINMENT,
        "reason": None,
        "refused": refused,
        "synonym": chosen["synonym"],
        "same_field_copies": True,
        "candidates": sorted(
            {_copy_label(h["fact"], name) for h in ordered if h is not chosen}
        ),
    }


def ambiguous_rationale(match: dict) -> str:
    """The engineer's question for a tie: two copies of one field that
    disagree, or two different fields."""
    from . import comparison as c

    if match.get("same_field_copies"):
        found = (
            f"{c.AMBIGUOUS_MATCH}: the submitted field this requirement names is read "
            f"more than once, with different values ({'; '.join(match['candidates'])}); "
        )
    else:
        found = (
            f"{c.AMBIGUOUS_MATCH}: more than one submitted field is named "
            f"inside this requirement ({', '.join(match['candidates'])}); "
        )
    return (
        found + "no value was chosen, because choosing one arbitrarily "
        "would attach a real number to the wrong requirement"
    )


def copies_notes(match: dict) -> list[str]:
    """The note naming the other copies of a field that was matched."""
    if match.get("same_field_copies") and match.get("candidates"):
        return [
            "the same field is also on the sheet, with the same "
            f"value or blank: {', '.join(match['candidates'])}"
        ]
    return []
