"""PR #807 (#805 Stage A): a met checklist item is stored as a COMPLIANT
finding. Danger zone: `datasheet_checks` decides what the engineer sees as
"Meets" and which results become rows."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_805_checklist_meets.py"
_D = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M807-01", phase=807, description="a met checklist item is not stored",
             path=_D, anchor='              and (x["status"] != COMPLIANT or x.get("checklist"))):',
             replacement='              and x["status"] != COMPLIANT):',
             target=_T, keyword="every_met_checklist_item", tags=("checklist",)),
    Mutation(id="M807-02", phase=807, description="every pass is stored, not only checklist items",
             path=_D, anchor='              and (x["status"] != COMPLIANT or x.get("checklist"))):',
             replacement='              and True):',
             target=_T, keyword="other_passes", tags=("checklist", "honesty")),
    Mutation(id="M807-03", phase=807, description="the stored finding loses its clause",
             path=_D, anchor='''                 f"{r['standard']} {r['clause']}" if r.get("clause") else None, finding["id"]))''',
             replacement='''                 None, finding["id"]))''',
             target=_T, keyword="every_met_checklist_item", tags=("checklist",)),
    Mutation(id="M807-04", phase=807, description="a draft checklist's result is not marked draft",
             path=_D, anchor='''    text = f"{item['text']} ({cite}{'; ' + DRAFT_MARK if draft else ''})"''',
             replacement='''    text = f"{item['text']} ({cite})"''',
             target=_T, keyword="draft_checklists_findings", tags=("checklist", "honesty")),
    Mutation(id="M807-05", phase=807, description="a signed checklist's result is marked draft",
             path=_D, anchor='''    text = f"{item['text']} ({cite}{'; ' + DRAFT_MARK if draft else ''})"''',
             replacement='''    text = f"{item['text']} ({cite}; {DRAFT_MARK})"''',
             target=_T, keyword="signed_checklist", tags=("checklist", "honesty")),
)
