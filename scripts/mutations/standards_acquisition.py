"""Mutations of `backend/app/standards_acquisition.py`."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_standards_acquisition.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1377", phase=1377, description='a company standard is pointed at a web site',
             path=APP / "standards_acquisition.py", anchor='    if _COMPANY.search(identifier or ""):',
             replacement='    if False:', target=_T, keyword='company_standard_is_never_pointed', tags=("honesty",)),
    Mutation(id="M1378", phase=1377, description='a request can be recorded for a standard nobody cited',
             path=APP / "standards_acquisition.py", anchor='    if not key or key not in listed:',
             replacement='    if not key:', target=_T, keyword='nobody_cited_is_refused', tags=("honesty",)),
    Mutation(id="M1379", phase=1377, description='a submittal can be recorded as an external standard copy',
             path=APP / "standards_acquisition.py", anchor='    if doc is None or doc["document_role"] != "COMPANY_STANDARD":',
             replacement='    if doc is None:', target=_T, keyword='needs_a_source_and_a_readable_standard', tags=("honesty",)),
    Mutation(id="M1380", phase=1377, description='a replaced file inherits the provenance record',
             path=APP / "standards_acquisition.py", anchor='    out["current"] = row["sha256"] == row["current_sha256"]',
             replacement='    out["current"] = True', target=_T, keyword='replaced_file_does_not_inherit', tags=("honesty",)),
    Mutation(id="M1381", phase=1377, description='a recorded request is not shown on the list',
             path=APP / "standards_acquisition.py", anchor='            "status": rec.get("status") or MISSING_LOCALLY,',
             replacement='            "status": MISSING_LOCALLY,', target=_T, keyword='request_is_recorded_under', tags=("honesty",)),
    Mutation(id="M1382", phase=1377, description='a provenance record with no source is accepted',
             path=APP / "standards_acquisition.py", anchor='    if not obtained_from:\n        raise',
             replacement='    if False:\n        raise', target=_T, keyword='needs_a_source_and_a_readable_standard', tags=("honesty",)),
    Mutation(id="M1383", phase=1377, description='provenance can be recorded on a standard the caller cannot read',
             path=APP / "standards_acquisition.py", anchor='    if document_id not in allowed_document_ids:',
             replacement='    if False:', target=_T, keyword='needs_a_source_and_a_readable_standard', tags=("honesty",)),
)
