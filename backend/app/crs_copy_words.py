"""The copy words of the CRS routes, in ONE home (V2, audit item 13).

The rule-check routes said `internal` or `issue`; the AI-review route said `internal` or `contractor`; the screens and the
owner say "company copy" and "contractor copy". A natural word answered 422. Now every route takes the same four words and
maps them to the copy it already knew:

    internal, company     -> the company's internal copy
    contractor, issue     -> the copy that goes to the contractor (the rule-check route calls it `issue`)

Any other word is refused (422) exactly as before. Nothing about WHAT a copy holds changes here: only the spelling.

The same home says whether the OLDER per-review files are offered at all (owner order, 16 Nov 2026): they do not state "N points
reviewed, N in this file", so while the redesigned page is on they are refused unless `OLD_CRS_DOWNLOAD_ENABLED` is on.
"""

from __future__ import annotations

from fastapi import HTTPException

from . import errors
from .config import settings

INTERNAL_WORDS = ("internal", "company")
CONTRACTOR_WORDS = ("contractor", "issue")
ALL_WORDS = INTERNAL_WORDS + CONTRACTOR_WORDS


def _check(word: str) -> str:
    low = (word or "").strip().lower()
    if low not in ALL_WORDS:
        raise HTTPException(
            status_code=422,
            detail=f"copy must be one of: {', '.join(ALL_WORDS)}",
        )
    return low


def rule_check_copy(word: str) -> str:
    """`internal` or `issue`: the words the rule-check CRS code uses."""
    return "internal" if _check(word) in INTERNAL_WORDS else "issue"


def agent_copy(word: str) -> str:
    """`internal` or `contractor`: the words the AI-review CRS code uses."""
    return "internal" if _check(word) in INTERNAL_WORDS else "contractor"


#: The plain sentence of a refused older file: what is off and where the file is now.
OLD_FILE_OFF = (
    "This older per-review CRS file is switched off. Use the CRS file on the review page: one file for the paper, "
    "which states its counts on its first sheet."
)


def old_file_offered() -> bool:
    """Whether the older per-review CRS files are served (owner order, 16 Nov 2026). While the redesigned page is off there is no
    one-CRS file, so they stay; while it is on, only `OLD_CRS_DOWNLOAD_ENABLED` brings them back."""
    return bool(settings.old_crs_download_enabled or not settings.review_page_v2_enabled)


def refuse_old_file_when_off() -> None:
    """404 with `OLD_FILE_OFF` when the older files are not offered (like a switched-off route); nothing otherwise."""
    if not old_file_offered():
        raise HTTPException(status_code=404, detail=errors.safe_error(errors.NOT_FOUND, OLD_FILE_OFF))
