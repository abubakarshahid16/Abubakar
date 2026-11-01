"""#1476 / PR 1489 procedure path: each entry deletes one decision line;
backend/tests/test_procedure_path.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_procedure_path.py"
_TAG = ("c1_1489", "procedure_path")
_C = APP / "comparison.py"
_P = APP / "procedure_text.py"


def _m(n, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M1489-{n:02d}", phase=1489, description=desc, path=path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(1, "a procedure-evidence demand is sent to another document again", _C,
       "    if procedure_pages is not None and requirement.get(\n"
       '            "required_evidence_type") in procedure_text.OWN_TEXT_EVIDENCE:\n',
       "    if False:\n", "procedure_evidence_demand"),
    _m(2, "an unmatched statement of a procedure is sent away again", _C,
       '        if procedure_pages is not None and requirement.get("requirement_type") == requirements_3b.STATEMENT:\n',
       "        if False:\n", "found_requirement or nothing_found"),
    _m(3, "a certificate or drawing demand is checked against the procedure text", _C,
       "    if procedure_pages is not None and requirement.get(\n"
       '            "required_evidence_type") in procedure_text.OWN_TEXT_EVIDENCE:\n',
       "    if procedure_pages is not None and requirement.get(\n"
       '            "required_evidence_type"):\n', "certificate_or_drawing"),
    _m(4, "nothing found no longer says contractor to show where", _P,
       '"status": "MISSING_INFORMATION"', '"status": "NEEDS_ENGINEER_REVIEW"', "nothing_found"),
    _m(5, "a found passage becomes COMPLIANT", _P,
       '"status": "NEEDS_ENGINEER_REVIEW"', '"status": "COMPLIANT"', "never_compliant or found_requirement"),
    _m(6, "the switch is ignored", _P,
       "    if not settings.procedure_path_enabled or not document_id:\n",
       "    if not document_id:\n", "switch_is_off"),
    _m(7, "a procedure demand is checked against the text only when a document is listed as one", _P,
       "    return document_id in listed or document_kind(document_id) in PROCEDURE_KINDS\n",
       "    return True\n", "switch_is_off"),
)
