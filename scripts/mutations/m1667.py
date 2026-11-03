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
        path=APP / "word_fold.py",
        anchor='unicodedata.normalize("NFKD", ch)',
        replacement='unicodedata.normalize("NFC", ch)',
        target="tests/test_ai_review_proposals.py",
        keyword="in_any_unicode_style",
        tags=_TAGS,
    ),
    Mutation(
        id="M1667-04",
        phase=1667,
        description="the fold no longer decomposes: an accented or combining letter inside a verdict word keeps the word hidden",
        path=APP / "word_fold.py",
        anchor='            unicodedata.normalize("NFKD", ch)\n            if decompose\n            else unicodedata.normalize("NFKC", ch)',
        replacement='            unicodedata.normalize("NFKC", ch)\n            if decompose\n            else unicodedata.normalize("NFKC", ch)',
        target="tests/test_ai_review_proposals.py",
        keyword="no_spelling_of_a_verdict_word_leaks",
        tags=_TAGS,
    ),
    Mutation(
        id="M1667-05",
        phase=1667,
        description="the space NFKD makes for a spacing accent is kept, so a word split by an accent is not read",
        path=APP / "word_fold.py",
        anchor="            d = d[1:]  # that space is NFKD's, not the text's",
        replacement="            pass",
        target="tests/test_ai_review_proposals.py",
        keyword="no_spelling_of_a_verdict_word_leaks",
        tags=_TAGS,
    ),
)
