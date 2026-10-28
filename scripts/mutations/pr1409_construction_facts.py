"""Order 264.8 step 1 (PR 1409): a Part applies when a stated datasheet fact settles its construction.
`ai_applicability` decides what leaves the engineer's questions, so the settle path gets entries
(cloud-2's condition v). Ids M1409-01 onwards, phase 1409."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_2648_construction_facts.py"
_SC = APP / "scope_construction.py"
_TAGS = ("honesty", "o2648")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1409-{n}",
        phase=1409,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the gate no longer asks the sheet first: a settled Part waits for the model again",
        APP / "ai_applicability.py",
        "    if settled := scope_construction.settle(construction, facts):  # order 264.8\n",
        "    if False:  # order 264.8\n",
        "applies_when_the_shell_material",
    ),
    _m(
        "02",
        "a layer (cladding, a lining) settles the base material",
        _SC,
        "        or _LAYER.search(value.lower())\n",
        "",
        "a_layer_on_the_base_never_settles",
    ),
    _m(
        "03",
        "a fact in ANY field settles a material family (a tube or a gasket is taken for the vessel)",
        _SC,
        '            not in family["roles"]\n        ):\n            return False\n',
        "            is None\n        ):\n            return False\n",
        "tube_or_a_seal_material",
    ),
    _m(
        "04",
        "a fact with no page settles a Part (a claim without a resolving page)",
        _SC,
        '        or fact.get("page") is None\n',
        "",
        "no_page_settles_nothing",
    ),
    _m(
        "05",
        "a blank field settles a Part",
        _SC,
        '        fact.get("is_blank")\n        or not value\n',
        "        not value\n",
        "blank_field_settles_nothing",
    ),
    _m(
        "06",
        "the words of the phrase need only ONE word of an entry to name a family",
        _SC,
        "        all(any(s.startswith(word) for s in stems) for word in words)\n",
        "        any(any(s.startswith(word) for s in stems) for word in words)\n",
        "no_family_names",
    ),
    _m(
        "07",
        "the review notes print the same settled fact once per Part question",
        APP / "absence.py",
        "        if key in seen:\n            continue\n",
        "",
        "once_per_fact",
    ),
    _m(
        "08",
        "a negated hit ('not welded') settles the Part",
        _SC,
        "        not _negated(value, m.start())\n",
        "        True\n",
        "negated_hit_settles_nothing",
    ),
    _m(
        "10",
        "a mixed vessel (another material family on the shell or heads) still settles a material family",
        _SC,
        "            if any(_hits(r, fact, rules) for r in rivals for fact in facts):\n                continue\n",
        "",
        "mixed_vessel_settles_no_material_family",
    ),
)
