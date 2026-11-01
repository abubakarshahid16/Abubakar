"""PR 1516 (#1484): the CRS byline and waiting comment of a kit row use the document kind's noun;
backend/tests/test_1484_parked_kits.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1484_parked_kits.py"
_TAG = ("pr1516", "crs", "kind_lane")
_M = APP / "crs_draft_lanes.py"
_L = APP / "crs_draft_lanes.py"
_S = APP / "spec_kit.py"


def _m(n, desc, path, anchor, repl, kw):
    return Mutation(
        id=f"M1516-{n:02d}",
        phase=1516,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a drawing kit row keeps the Specification byline",
        _M,
        "    if origin == SPEC_ORIGIN:\n        confirmed, unconfirmed, comment = spec_lane_words(noun)\n",
        "    if False:\n        confirmed, unconfirmed, comment = spec_lane_words(noun)\n",
        "byline_and_waiting_comment_say_drawing",
    ),
    _m(
        2,
        "the lane words ignore the kind's noun",
        _L,
        "    name = noun.capitalize()\n",
        '    name = "Specification"\n',
        "byline_and_waiting_comment_say_drawing",
    ),
    _m(
        3,
        "the drawing waiting comment is not in the waiting set, so it would be read as real text",
        _L,
        "    | {spec_lane_words(n)[2] for n in KIND_NOUNS}\n",
        "    | set()\n",
        "waiting_comment_say_drawing",
    ),
    _m(
        4,
        "the noun of a kit row is always specification",
        _S,
        "    if len(parts) >= 3 and parts[0] == ORIGIN and parts[1] in kind_kits():\n",
        "    if False:\n",
        "byline_and_waiting_comment_say_drawing",
    ),
    _m(
        5,
        "a parked kind's rows are stored without their kind in the requirement id",
        _S,
        "    prefix = (\n"
        '        f"{ORIGIN}:{kind}:"\n'
        "        if kind in kind_kits() or kind in KIND_NOUNS\n"
        '        else f"{ORIGIN}:"\n'
        "    )\n",
        '    prefix = f"{ORIGIN}:"\n',
        "byline_and_waiting_comment_say_drawing",
    ),
)
