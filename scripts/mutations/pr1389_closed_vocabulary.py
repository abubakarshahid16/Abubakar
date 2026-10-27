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
        "02",
        "a stored name is used without checking the requirement's current text",
        '        and field_naming.quote_verified(v.get("quote"), wanted_ids.get(k, ""))\n',
        "",
        "edited_sentence_loses",
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
)
