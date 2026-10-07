"""W1: standard-derived text must not reach a caller with no grant on the standard.

Two routes skipped the rule `review.withhold_unreadable_standards` applies to a
read: the structured search (it matched on, and returned, the finding and the
requirement wording) and the review PDF export (it printed them). A grant on
the SUBMITTAL is not a grant on the STANDARD.
"""

from __future__ import annotations

import pymupdf

from tests.r2_security_support import h, temp_storage, world  # noqa: F401
from tests.test_r2_security_s2_standard_withheld import SECRETS, _run_with_finding


def _hits(world, user: str, q: str) -> list[dict]:
    r = world.get("/api/search/structured", params={"q": q, "kind": "finding"},
                  headers=h(user))
    assert r.status_code == 200, r.text
    return r.json()["results"]


def _pdf_text(world, user: str) -> str:
    r = world.post("/api/reviews/report", json={"document_id": "doc_sub"},
                   headers=h(user))
    assert r.status_code == 200, r.text
    with pymupdf.open(stream=r.content, filetype="pdf") as pdf:
        return "\n".join(page.get_text() for page in pdf)


def test_structured_search_does_not_match_or_return_withheld_standard_text(world):
    _run_with_finding()
    for q in ("design pressure", "6,900", "Outside the"):
        assert _hits(world, "u_sub", q) == [], \
            f"search for {q!r} matched a finding whose standard the caller cannot read"


def test_structured_search_still_finds_it_for_a_caller_granted_the_standard(world):
    _run_with_finding()
    assert len(_hits(world, "u_full", "design pressure")) == 1
    assert len(_hits(world, "u_admin", "design pressure")) == 1


def test_review_pdf_withholds_the_standard_from_a_submittal_only_reader(world):
    _run_with_finding()
    text = _pdf_text(world, "u_sub").lower()
    for secret in SECRETS:
        assert secret.lower() not in text, f"{secret!r} printed in the PDF"


def test_review_pdf_still_prints_the_standard_for_a_caller_granted_it(world):
    _run_with_finding()
    text = _pdf_text(world, "u_full")
    assert "6,900" in text
