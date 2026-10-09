"""#658: the 404 for a run the caller cannot read stays identical (code, message,
every other field) to the 404 for a missing run; only the timestamp may differ.
Ids M4911-M4912."""
from __future__ import annotations

from ._base import APP, Mutation

_TAG = ("w7", "access")
_T = "tests/test_w1_crs_draft_and_upload_discipline.py"
_A = '''            errors.NOT_FOUND, "no review run with that id"))
    return run'''

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4911", phase=4911, description="the 404 message names the run id (a hidden run reads differently from a missing one)",
             path=APP / "claude_api.py", anchor=_A,
             replacement='''            errors.NOT_FOUND, f"no review run {review_run_id} for you"))
    return run''',
             target=_T, keyword="same_404_as_a_missing_one", tags=_TAG),
    Mutation(id="M4912", phase=4912, description="the 404 carries the run id in document_id",
             path=APP / "claude_api.py", anchor=_A,
             replacement='''            errors.NOT_FOUND, "no review run with that id", document_id=review_run_id))
    return run''',
             target=_T, keyword="same_404_as_a_missing_one", tags=_TAG),
)
