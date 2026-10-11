"""PR #792 (planner 2026-10-11, the reader job): the checklist's role names are
the reader's field labels. Only the reference JSON is in the danger zone; the
reader's own changes (datasheets.py) were hand-checked in the PR."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_reader_named_fields.py"
_J = APP / "reference" / "datasheet_checks.json"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M792-01", phase=792, description="the trim is not read under the names a valve sheet prints",
             path=_J, anchor='        "^(nozzle|disc|disk) ?(/ ?base|base|insert) material$",\n',
             replacement="",
             target=_T, keyword="trim_is_read", tags=("checklist",)),
    Mutation(id="M792-02", phase=792, description="a disc HOLDER is read as the trim",
             path=_J, anchor='        "^(nozzle|disc|disk) ?(/ ?base|base|insert) material$",\n',
             replacement='        "^(nozzle|disc|disk) ?(/ ?base|base|insert|holder) material$",\n',
             target=_T, keyword="trim_is_read", tags=("checklist", "honesty")),
)
