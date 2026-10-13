"""PR #943 (A9/#923): datasheet_checks.store writes review_run_id/origin/
compliance_status in the SAME insert as the finding (no more second UPDATE).
Danger zone: a wrong verdict or an invisible-to-its-run finding reaches the
engineer directly."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_923_atomic_writes.py"
_D = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M943-01", phase=943,
             description="a stored datasheet-check finding loses its run id (invisible to its own run)",
             path=_D,
             anchor='            "review_run_id": review_run_id, "origin": ORIGIN, "compliance_status": status,',
             replacement='            "review_run_id": None, "origin": ORIGIN, "compliance_status": status,',
             target=_T, keyword="store_writes_the_extra_fields", tags=("checklist", "critical")),
    Mutation(id="M943-02", phase=943,
             description="a stored datasheet-check finding loses its compliance verdict",
             path=_D,
             anchor='            "review_run_id": review_run_id, "origin": ORIGIN, "compliance_status": status,',
             replacement='            "review_run_id": review_run_id, "origin": ORIGIN, "compliance_status": None,',
             target=_T, keyword="store_writes_the_extra_fields", tags=("checklist", "critical")),
)
