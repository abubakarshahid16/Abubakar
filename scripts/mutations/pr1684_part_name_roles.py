"""Mutations of the part-name roles (test B, part of #805; PR 1684)."""

from __future__ import annotations

from ._base import REPO, Mutation

_P = REPO / "backend" / "app" / "part_name_roles.py"
_T = "tests/test_part_name_roles.py"


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1684-{n:02d}",
        phase=1684,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=("datasheet", "label_gate"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "two different parts in one quote still fill a field",
        _P,
        "    if any(o in quote_words for o in others):\n        return False  # rule 2: another role's part is in the same quote\n",
        "    if False:\n        return False\n",
        "two_parts_in_one_quote",
    ),
    _m(
        2,
        "a part word anywhere in the quote is enough: a longer phrase fills the field",
        _P,
        "            if opening and _words(opening.group(1)) == value_words:\n",
        "            if opening or part in quote_words:\n",
        "longer_phrase",
    ),
    _m(
        3,
        "a value that is not a material fills a material field",
        _P,
        "        if not material_value(value, rules):\n            return False\n",
        "        if False:\n            return False\n",
        "not_a_material",
    ),
    _m(
        4,
        "two different values for one part still fill the role",
        _P,
        '        if len({" ".join(_words(f.get("field_value"))) for f in found}) != 1:\n            continue  # two values for one part: no fill\n',
        "        if False:\n            continue\n",
        "two_different_values",
    ),
    _m(
        5,
        "a fact already under the role's own name is overwritten",
        _P,
        '        if " ".join(role.split("_")) in own:\n            continue  # a fact under the role\'s own name already speaks for it\n',
        "        if False:\n            continue\n",
        "already_named",
    ),
    _m(
        6,
        "the switch is ignored for stored facts",
        _P,
        "    if not enabled():\n        return facts\n",
        "    if False:\n        return facts\n",
        "switch_off_changes_nothing",
    ),
    _m(
        7,
        "the stored-facts check never asks for the part-name roles",
        REPO / "backend" / "app" / "datasheet_checks.py",
        "    for fact in datasheet_roles.with_roles(facts, rules, wanted):\n",
        "    for fact in facts:\n",
        "finds_the_material",
    ),
    _m(
        8,
        "the form reader's label gate never takes the relaxed rule",
        REPO / "backend" / "app" / "form_reader.py",
        "    if not label_in_quote(f, printed, rules) and not part_name_roles.accepts(\n        f.key, value, printed, rules\n    ):\n",
        "    if not label_in_quote(f, printed, rules):\n",
        "bare_part_row",
    ),
    _m(
        9,
        "a word that is not a material token is ignored, so prose fills a material",
        _P,
        "        elif token not in others:\n            return False\n",
        "        elif False:\n            return False\n",
        "not_only_material_tokens",
    ),
    _m(
        10,
        "a seal value outside the closed list of seal types fills seal type",
        _P,
        '    return " ".join(_words(value)) in phrases and not (negations & set(quote_words))\n',
        "    return not (negations & set(quote_words))\n",
        "negated_or_not_a_listed_type",
    ),
    _m(
        11,
        "a negation in the seal sentence is ignored",
        _P,
        '    return " ".join(_words(value)) in phrases and not (negations & set(quote_words))\n',
        '    return " ".join(_words(value)) in phrases\n',
        "negated_or_not_a_listed_type",
    ),
)
