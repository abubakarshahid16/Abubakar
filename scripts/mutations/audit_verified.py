"""Mutations for fix/audit-verified (audit 2026-09-30): a wrong number must
never reach the reader labelled "verified" / "quote found on the page".

Each entry puts one verified defect back; tests/test_audit_verified.py must
notice.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_audit_verified.py"
_PHASE = 1450

MUTATIONS: tuple[Mutation, ...] = (
    # ---- 1. a claim's quote must be meaningful evidence ---------------------
    Mutation(
        id="M1450", phase=_PHASE,
        description="a one-word quote ('the') verifies a claim again",
        path=APP / "model_evidence.py",
        anchor="MIN_CLAIM_QUOTE_WORDS = 3\n",
        replacement="MIN_CLAIM_QUOTE_WORDS = 1\n",
        target=_T, keyword="one_word_quote or two_word_quote",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1451", phase=_PHASE,
        description="a quote may end inside a longer number ('is 10' found in 'is 100')",
        path=APP / "model_evidence.py",
        anchor='            (r"(?<!\\w)" if re.match(r"\\w", frag) else "") + re.escape(frag)\n'
               '            + (r"(?!\\w)" if re.search(r"\\w$", frag) else ""))\n',
        replacement="            re.escape(frag))\n",
        target=_T, keyword="ending_inside_a_longer_number",
        tags=("honesty",),
    ),
    Mutation(
        id="M1452", phase=_PHASE,
        description="a word the PDF hyphenated across a line no longer matches its quote",
        path=APP / "model_evidence.py",
        anchor="    if not _LINE_BREAK_HYPHEN.search(text):\n",
        replacement="    if True:\n",
        target=_T, keyword="line_break_hyphen",
    ),
    Mutation(
        id="M1453", phase=_PHASE,
        description="rule 8: the answer judge accepts a two-word quote again",
        path=APP / "answerability.py",
        anchor='not claim_quote_verified(out["quote"], passages[n - 1].get("text")):',
        replacement='(out["quote"] or "") not in (passages[n - 1].get("text") or ""):',
        target=_T, keyword="judge_rejects_a_two_word_quote",
        tags=("honesty",),
    ),
    Mutation(
        id="M2043", phase=_PHASE,
        description="an ellipsis quote's pieces may appear in any order on the page",
        path=APP / "model_evidence.py",
        anchor="        pos = m.end()\n",
        replacement="        pos = 0\n",
        target=_T, keyword="ellipsis_fragments_must_appear_in_order",
        tags=("honesty",),
    ),
    # ---- 2. every figure in a claim must be in a cited passage --------------
    Mutation(
        id="M1454", phase=_PHASE,
        description="a verified quote vouches for any figure in its sentence again "
                    "('6 mm [S1 \"minimum wall thickness\"]' over a page saying 3 mm)",
        path=APP / "answer.py",
        anchor="            if figures_removed:\n                lost_tail = True\n"
               "                note(segment, \"a figure in it is not on the cited page\")\n"
               "                continue\n",
        replacement="",
        target=_T, keyword="does_not_vouch_for_a_different_figure",
        tags=("honesty", "critical"),
    ),
    # ---- 3. references stripped on both sides; only genuine rounding -------
    Mutation(
        id="M1455", phase=_PHASE,
        description="the passage's 'clause 6' supports the answer's '6 mm' again",
        path=APP / "answer.py",
        anchor='                spans = (synthesis.span_numbers(" ".join(',
        replacement='                spans = (synthesis._numbers(" ".join(',
        target=_T, keyword="clause_number_in_the_passage",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1456", phase=_PHASE,
        description="rule 8: the synthesis lane lets a span's clause number support a figure",
        path=APP / "synthesis.py",
        anchor="        supported = span_numbers(spans)\n",
        replacement="        supported = _numbers(spans)\n",
        target=_T, keyword="clause_number_in_the_span",
        tags=("honesty",),
    ),
    Mutation(
        id="M1457", phase=_PHASE,
        description="the 1% relative tolerance returns: '17.4' passes for a page saying 17.24",
        path=APP / "answer.py",
        anchor="        if not span_value.is_finite() or _decimals(span_value) <= places:\n",
        replacement="        if abs(claimed_value - span_value) <= Decimal('0.01') * max(abs(claimed_value), "
                    "abs(span_value)):\n            return True\n"
                    "        if not span_value.is_finite() or _decimals(span_value) <= places:\n",
        target=_T, keyword="more_precise_different_figure",
        tags=("honesty",),
    ),
    # ---- 4. an image-only citation label is never a claim figure -----------
    Mutation(
        id="M1458", phase=_PHASE,
        description="the pre-fix order: relabel image-only citations BEFORE verify_claims "
                    "and count the labels - 'page 4' is read as an uncited figure, the point "
                    "is dropped, and the notice still says it was kept",
        path=APP / "chat_claude_first.py",
        anchor="        text, verification, claims, removed = answer_mod.verify_claims(\n"
               "            text, sources, narration_from_line=first_last_line, dropped=dropped_points,\n"
               "            question=question)\n"
               "        text, _labels = _relabel_image_only_citations(text, sources)\n"
               "        # The notice counts the POINTS that were kept unverified, not the\n"
               "        # labels written - so it can never announce a point that was removed.\n"
               "        image_relabelled = verification.get(\"image_only\", 0)\n",
        replacement="        text, image_relabelled = _relabel_image_only_citations(text, sources)\n"
                    "        text, verification, claims, removed = answer_mod.verify_claims(text, sources)\n",
        target=_T, keyword="image_only_point_is_kept or never_counts_a_removed_point",
        tags=("honesty",),
    ),
    Mutation(
        id="M1459", phase=_PHASE,
        description="verify_claims no longer knows an image-only page: its citation "
                    "is held to a quote it cannot have and the point is dropped",
        path=APP / "answer.py",
        anchor="            from_image = [m for m in cites if _image_only(passages[int(m.group(1)) - 1])]\n",
        replacement="            from_image = []\n",
        target=_T, keyword="image_only_point_is_kept or keeps_an_image_only_sentence",
        tags=("honesty",),
    ),
)
