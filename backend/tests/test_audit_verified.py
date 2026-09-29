"""A wrong number must never reach the reader labelled "verified".

Audit 2026-09-30 (fix/audit-verified). Four verified defects, each with the
text that reproduced it. All data here is synthetic. Mutations proving each
test is not vacuous: scripts/mutations/audit_verified.py (M1450-M1459).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app import answer as answer_mod
from app import answerability, synthesis
from app import chat_claude_first as ccf
from app.model_evidence import claim_quote_verified

PIPING = [{"text": "The minimum wall thickness shall be 3 mm for piping in accordance "
                   "with clause 6. Design pressure 17.24 barg."}]


# ------------------------------------------------ 1. a quote must mean something

def test_a_one_word_quote_does_not_verify_a_claim():
    """'[S1 "the"]' is on every page. The figure here IS on the page, so only
    the quote rule can reject it."""
    page = [{"text": "the design pressure is 10 barg"}]
    clean, verification, claims, removed = answer_mod.verify_claims(
        'The design pressure is 10 barg [S1 "the"].', page)
    assert clean == "" and verification["verified"] == 0 and removed == 1 and claims == []


def test_a_two_word_quote_is_not_enough_but_three_words_are():
    page = "The minimum wall thickness shall be 3 mm."
    assert not claim_quote_verified("wall thickness", page)
    assert claim_quote_verified("minimum wall thickness", page)


def test_a_quote_ending_inside_a_longer_number_is_not_found():
    """'design pressure is 10' is a substring of 'design pressure is 100'."""
    page = [{"text": "The design pressure is 100 barg and the test pressure 10 barg."}]
    clean, verification, _claims, _removed = answer_mod.verify_claims(
        'The design pressure is 10 barg [S1 "design pressure is 10"].', page)
    assert verification["verified"] == 0 and clean == ""
    # the other side: the same quote on its own word boundary verifies
    assert claim_quote_verified("design pressure is 10", "design pressure is 10 barg")


def test_a_quote_across_a_line_break_hyphen_verifies():
    """The PDF text layer splits 'thickness' as 'thick-\\nness'; the model
    quotes the word as printed."""
    page = "The minimum wall thick-\nness shall be 3 mm."
    assert claim_quote_verified("minimum wall thickness shall", page)
    assert claim_quote_verified("carbon-steel pipe shall", "all carbon-\nsteel pipe shall be")


def test_the_answer_judge_rejects_a_two_word_quote():
    """Rule 8: the answerability judge accepted a model 'yes' on the same bare
    substring test - a two-word quote proves nothing either."""
    result = {"passage": {"chunk_id": "c1", "text": "Surfaces shall be blast cleaned to a "
                                                   "profile of 50 to 75 micrometres."}}
    current = {"verdict": answerability.SUPPORTED, "reason": "structural", "evidence": []}

    class Fake:
        def __init__(self, quote):
            self.quote = quote

        def reason(self, packet):
            from app.reasoning_provider import Response
            reply = json.dumps({"answers": True, "passage": 1, "quote": self.quote})
            return Response(text=reply,
                            provider="ollama", model_tag="fake", digest="d",
                            prompt_sha256="p", wall_time_s=0.0, finish_reason="stop")

    short = answerability.judge("profile?", result, current, Fake("a profile"))
    assert short["judge"]["accepted"] is False
    long_ = answerability.judge("profile?", result, current, Fake("a profile of 50 to 75"))
    assert long_["judge"]["accepted"] is True


# ------------------------------- 2. the sentence's figures must be on the page

def test_a_verified_quote_does_not_vouch_for_a_different_figure():
    clean, verification, claims, removed = answer_mod.verify_claims(
        'The minimum wall thickness is 6 mm [S1 "minimum wall thickness"].', PIPING)
    assert clean == "" and verification["verified"] == 0 and removed == 1 and claims == []


def test_a_verified_quote_with_the_right_figure_is_kept():
    clean, verification, _claims, _removed = answer_mod.verify_claims(
        'The minimum wall thickness is 3 mm [S1 "minimum wall thickness"].', PIPING)
    assert clean == "The minimum wall thickness is 3 mm [S1]."
    assert verification == {"verified": 1, "total": 1, "method": "quote found on the page"}


# ----------------------- 3. references stripped on both sides; only real rounding

def test_a_clause_number_in_the_passage_does_not_support_a_figure():
    clean, removed = answer_mod.ground_numbers("The minimum wall thickness is 6 mm [S1].", PIPING)
    assert clean == "" and removed == [{"value": "6", "cited": [1]}]


def test_a_clause_number_in_the_span_does_not_support_a_summary_figure():
    """Rule 8: the synthesis lane compared against the same unstripped spans."""
    kept, dropped = synthesis._cite("The minimum wall thickness is 6 mm [S1].",
                                    [{"evidence_id": "e1", **PIPING[0]}])
    assert kept == () and dropped and "6" in dropped[0][1]
    kept, _dropped = synthesis._cite("The minimum wall thickness is 3 mm [S1].",
                                     [{"evidence_id": "e1", **PIPING[0]}])
    assert len(kept) == 1


def test_a_more_precise_different_figure_is_not_a_rounding():
    clean, removed = answer_mod.ground_numbers("The design pressure is 17.4 barg [S1].", PIPING)
    assert clean == "" and removed[0]["value"] == "17.4"


def test_a_genuine_rounding_is_still_kept():
    for claim in ("17.2", "17"):
        text = f"The design pressure is {claim} barg [S1]."
        assert answer_mod.ground_numbers(text, PIPING) == (text, [])


# ---------------------------- 4. an image-only citation label is not a figure

IMAGE_PAGE = {"filename": "DS.pdf", "page_start": 4, "page_end": 4, "read_from_image": True,
              "has_text_layer": False, "text": "[page 4 read from image]", "document_id": "d1"}


def _finish(text: str, sources: list[dict]) -> dict:
    response = SimpleNamespace(text=text, provider="claude", model_tag="claude-test",
                               cost_usd=0.0, truncated=False)
    return ccf._finish(response, sources, [], 0.0, None)


def test_an_image_only_point_is_kept_labelled_and_the_notice_counts_it():
    body = _finish("The nameplate shows a stamp from the inspector [S1].", [IMAGE_PAGE])
    assert body["answer"] == ("The nameplate shows a stamp from the inspector "
                              "[DS.pdf, page 4, read from image - check the page].")
    assert body["notices"] == ["1 point(s) were read from a page image with no text layer "
                               "- check the page"]
    assert body["verification"]["verified"] == 0


def test_the_image_notice_never_counts_a_removed_point():
    """A sentence citing the image page AND a text page with a bad quote is
    removed - so the notice must not announce it as kept."""
    text_page = {"filename": "S.pdf", "page_start": 1, "page_end": 1, "text": "Design pressure 10 barg."}
    body = _finish('The nameplate is stamped [S1] [S2 "a quote that is nowhere"]. '
                   'The design pressure is 10 barg [S2 "Design pressure 10 barg"].',
                   [IMAGE_PAGE, text_page])
    assert body["answer"] == "The design pressure is 10 barg [S2]."
    assert "notices" not in body


def test_verify_claims_keeps_an_image_only_sentence_unverified():
    clean, verification, claims, removed = answer_mod.verify_claims(
        "The nameplate shows a stamp from the inspector [S1].", [IMAGE_PAGE])
    assert clean == "The nameplate shows a stamp from the inspector [S1]."
    assert verification["verified"] == 0 and verification["image_only"] == 1
    assert claims == [] and removed == 0
