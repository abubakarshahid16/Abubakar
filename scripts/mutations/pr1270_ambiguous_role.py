"""#900: a field name that fits two roles is read as the role the sheet's equipment
type checks. `datasheet_checks.py` is in the danger zone (rule 6). PR #1270: ids
M1270-01 onwards, phase 1270."""
from __future__ import annotations
from ._base import APP, Mutation
_T = "tests/test_900_ambiguous_role.py"
_TAGS = ("honesty", "900")
MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1270-01",
        phase=1270,
        description="the review forgets the roles its equipment type checks, first match wins again",
        path=APP / "datasheet_checks.py",
        anchor='        role = role_of(fact.get("field_name") or "", rules, wanted)\n',
        replacement='        role = role_of(fact.get("field_name") or "", rules)\n',
        target=_T,
        keyword="valve",
        tags=_TAGS,
    ),
    Mutation(
        id="M1270-02",
        phase=1270,
        description="a preferred role is ignored when a name fits several roles",
        path=APP / "datasheet_roles.py",
        anchor="    return next((r for r in found if r in prefer), found[0] if found else None)\n",
        replacement="    return found[0] if found else None\n",
        target=_T,
        keyword="valve or fits_two_roles or generic",
        tags=_TAGS,
    ),
    Mutation(
        id="M1270-03",
        phase=1270,
        description="the roles a type checks are no longer read from its checklist",
        path=APP / "datasheet_roles.py",
        anchor="    walk([[i.get(\"rule\"), i.get(\"condition\")] for i in items])\n",
        replacement="    walk([])\n",
        target=_T,
        keyword="wanted or valve",
        tags=_TAGS,
    ),
    Mutation(
        id="M1270-04",
        phase=1270,
        description="a name that fits several roles is read as the last one, not the first",
        path=APP / "datasheet_roles.py",
        anchor="    return next((r for r in found if r in prefer), found[0] if found else None)\n",
        replacement="    return next((r for r in found if r in prefer), found[-1] if found else None)\n",
        target=_T,
        keyword="table_order or pump_role",
        tags=_TAGS,
    ),
)
