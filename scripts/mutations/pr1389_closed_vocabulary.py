"""Order 259.5 (PR 1389): numeric limits named against a closed vocabulary. `field_vocabulary.py`
decides a pairing that rides the comparison path, so it gets entries (cloud's question).
Ids M1389-01 onwards, phase 1389."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_259_closed_vocabulary.py"
_P = APP / "field_vocabulary.py"
_TAGS = ("honesty", "o259")


def _m(n, description, anchor, replacement, keyword):
    return Mutation(
        id=f"M1389-{n}",
        phase=1389,
        description=description,
        path=_P,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a quote with an extra quantity word (drop, margin, min/max) still names the quantity",
        "            return all(w in _NEUTRAL for w in rest)\n",
        "            return True\n",
        "refuses_another_or_opposite",
    ),
    _m(
        "03",
        "a reply that cannot be read is stored as final (every item unmapped)",
        "        if response.schema_errors or response.truncated:\n",
        "        if False:\n",
        "reply_that_cannot_be_read",
    ),
    _m(
        "04",
        "with nothing stored a review makes a model call even without the geometry reader",
        "        if settings.geometry_reader_enabled:\n            return field_naming.ensure_names(requirements, facts)\n",
        "        if True:\n            return field_naming.ensure_names(requirements, facts)\n",
        "no_model_call",
    ),
    _m(
        "05",
        "a number in a unit of another kind (a duration for a pressure) fits the name",
        "    if (not wanted and have) or (wanted and not set(wanted) & have):\n        return False\n",
        "",
        "limit_of_the_named_quantity",
    ),
    _m(
        "06",
        "any words may stand between the name and its number",
        "            w in _LIMIT_WORDS for w in _WORD.findall(between)\n",
        "            True for w in _WORD.findall(between)\n",
        "limit_of_the_named_quantity",
    ),
    _m(
        "07",
        "a number standing before the name needs no tight gap to it",
        "    return all(w in unit_words or w in _NEUTRAL for w in _WORD.findall(gap))\n",
        "    return True\n",
        "limit_of_the_named_quantity",
    ),
    _m(
        "08",
        "a stored name is kept when its number no longer fits",
        "        and number_fits(\n",
        "        and not number_fits(\n",
        "number_no_longer_fits",
    ),
    _m(
        "09",
        "the offline pass does not apply the number gate to a model's answer",
        "    if not number_fits(\n        items[i][1], quote, dictionary[field], raw_value, raw_unit, families\n    ):\n        return unmapped  # gate 4\n",
        "",
        "duration_is_not_stored",
    ),
    _m(
        "10",
        "a figure ahead of the sentence's main 'shall' (the rule's condition) is taken as its limit",
        "        if modal and at + len(q) + m.start() < modal.start():\n            return False\n",
        "",
        "ahead_of_the_main_shall",
    ),
)
