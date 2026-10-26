"""PR 1306 (order 225): a checklist finding carries its standard and the page of
the clause it cites; a page not located is never guessed or invented."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_225_standard_clause_page.py"
_P = APP / "standard_clause_page.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1306-01",
        phase=1306,
        description="the located standard and page are never written on the checklist findings",
        path=APP / "datasheet_checks.py",
        anchor="    standard_clause_page.attach(review_run_id, written)\n",
        replacement="",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1306-02",
        phase=1306,
        description="a clause with no located page prints a page anyway on the comment sheet",
        path=APP / "crs_mapping.py",
        anchor='        return f"{check}: {cited} (p.{page})" if cited and page else check\n',
        replacement='        return f"{check}: {cited} (p.{page})" if cited else check\n',
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1306-03",
        phase=1306,
        description="a contents page counts as the page of the clause",
        path=_P,
        anchor='        return not _CONTENTS_TAIL.search(m.group("rest"))\n',
        replacement="        return True\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1306-04",
        phase=1306,
        description="a clause on two real pages is given the first one: a guessed page",
        path=_P,
        anchor="    return next(iter(pages)) if len(pages) == 1 else None\n",
        replacement="    return min(pages) if pages else None\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1306-05",
        phase=1306,
        description="two standards that both are the label: one is picked",
        path=_P,
        anchor="    return next(iter(found)) if len(found) == 1 else None\n",
        replacement="    return min(found) if found else None\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1306-06",
        phase=1306,
        description="clause 3.2 is read as clause 3.26 (a prefix of the number is enough)",
        path=_P,
        anchor='    if m and m.group("id") == clause:\n',
        replacement='    if m and m.group("id").startswith(clause):\n',
        target=_T,
        tags=("honesty",),
    ),
)
