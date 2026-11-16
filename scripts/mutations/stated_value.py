"""PR 1155 (order 124 item 9): a finding's text quotes a long stated value as
a marked excerpt (`stated_value`), never a raw table chunk, while the verdict
is still worked out from the whole value. `comparison.py` and
`datasheet_checks.py` are in the danger zone (rule 6); each entry puts back
the whole chunk, or lets the excerpt decide, and the tests must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_124_9_stated_values.py"
_C = APP / "comparison.py"
_D = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1155-01",
        phase=1155,
        description="a clause that asks for a statement quotes the whole raw chunk",
        path=_C,
        anchor='f"datasheet, and the sheet states it: {stated_value.stated(stated)}"),',
        replacement='f"datasheet, and the sheet states it: {stated}"),',
        target=_T,
        keyword="statement_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-02",
        phase=1155,
        description="a value the clause does not name is quoted as the whole raw chunk",
        path=_C,
        anchor="the sheet states {stated_value.stated(stated)!r}; the clause names",
        replacement="the sheet states {stated!r}; the clause names",
        target=_T,
        keyword="statement_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-03",
        phase=1155,
        description="a nominal value's finding quotes the whole raw chunk",
        path=_C,
        anchor='    observed = stated_value.flat(fact.get("field_value") or fact.get("raw_value"))\n',
        replacement='    observed = " ".join(str(fact.get("field_value") or fact.get("raw_value") or "").split())\n',
        target=_T,
        keyword="nominal_value_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-04",
        phase=1155,
        description="a range against an exact value quotes the whole raw chunk",
        path=_C,
        anchor='            quoted = stated_value.flat(fact.get("field_value"))\n',
        replacement='            quoted = " ".join((fact.get("field_value") or "").split())\n',
        target=_T,
        keyword="submitted_range_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-05",
        phase=1155,
        description="the range a limit was compared at the end of is quoted whole",
        path=_C,
        anchor='"compared_from": stated_value.flat(fact.get("field_value"))}',
        replacement='"compared_from": " ".join((fact.get("field_value") or "").split())}',
        target=_T,
        keyword="submitted_range_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-06",
        phase=1155,
        description="a value that is not a number is quoted as the whole raw chunk",
        path=_C,
        anchor="value {stated_value.stated(value)!r} could not be read as a",
        replacement="value {value!r} could not be read as a",
        target=_T,
        keyword="not_a_number_is_quoted_as_an_excerpt",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-07",
        phase=1155,
        description="every checklist sentence quotes the whole raw chunk",
        path=_D,
        anchor="from .stated_value import said as _said\n",
        replacement="from .stated_value import fact_value as _said\n",
        target=_T,
        keyword="checklist_item_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-08",
        phase=1155,
        description="a stated checklist field quotes the whole raw chunk",
        path=_D,
        anchor=(
            "    where = f\"{_label(fact, field)} {_said(fact)} (page {fact.get('page')})\"\n"
            '    if kind == "required":\n'
        ),
        replacement=(
            "    where = f\"{_label(fact, field)} {_shown(fact)} (page {fact.get('page')})\"\n"
            '    if kind == "required":\n'
        ),
        target=_T,
        keyword="checklist_item_quotes_a_long_value",
        tags=("honesty",),
    ),
    Mutation(
        id="M1155-09",
        phase=1155,
        description="the excerpt, not the whole value, decides an allowed-values item",
        path=_D,
        anchor="        stated = _fold(_shown(fact))\n        ok = any(",
        replacement="        stated = _fold(_said(fact))\n        ok = any(",
        target=_T,
        keyword="whole_value_decides",
        tags=("honesty", "critical"),
    ),
)
