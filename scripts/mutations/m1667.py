"""#1667 (lane 6): the AI review pass never removes a Fail, read from the result and severity a row carries."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_review_real_rows.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1667-01",
        phase=1667,
        description="the row no longer carries the result behind it, so a failed self-check looks like a question",
        path=APP / "ai_review_proposals.py",
        anchor='                "NON_COMPLIANT" if any(is_fail_word(f) for f in known) else known[0]',
        replacement="                known[0]",
        target=_T,
        keyword="worst_result",
        tags=_TAGS,
    ),
    Mutation(
        id="M1667-02",
        phase=1667,
        description="the verifier trusts the row kind alone and ignores the carried result and severity",
        path=APP / "ai_review_proposals.py",
        anchor='        or is_fail_word(row.get("compliance_status"))\n',
        replacement="",
        target=_T,
        keyword="is_a_fail_whatever_its_label",
        tags=_TAGS,
    ),
    Mutation(
        id="M1667-03",
        phase=1667,
        description="the verdict filter's fold is the number normaliser, so styled letters (bold, circled, long s...) read as no word",
        path=APP / "numparse.py",
        anchor='    folded = unicodedata.normalize("NFKC", str(text or ""))\n    kept = "".join(',
        replacement='    folded = normalise_text(str(text or ""))\n    kept = "".join(',
        target="tests/test_ai_review_proposals.py",
        keyword="in_any_unicode_style",
        tags=_TAGS,
    ),
)
