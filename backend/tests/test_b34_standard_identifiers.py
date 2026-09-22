"""B34: a standard's NUMBER is its name, not a measurement - and only real
standard-number shapes get that exemption.

The defect, reproduced live on 2026-09-21: a Focused summary over the right
coatings passages came back EMPTY, because "SAES-H-004 outlines a total system
minimum of 150 micrometers [S4]" was deleted as "carries a number no cited span
contains: 4.0" - the "004" of the standard's name read as the quantity 4. The
same answer path had always exempted "doc17.pdf". This corpus is Saudi Aramco
standards, so nearly every good sentence names one.

The fix is a CLOSED grammar (synthesis._STANDARD_IDENTIFIER), built from the
identifier shapes that occur in the indexed text. These tests pin both halves:

  * every admitted family is exempt, so a true sentence naming it survives;
  * nothing else is - a lookalike, a rare family, lowercase, an extra digit -
    and above all a FABRICATED VALUE DISGUISED AS A STANDARD NUMBER is still
    rejected: "per SAES-H-150, apply 150 micrometers" over a passage without
    150 must be removed. The grammar strips the identifier's own text, never
    other tokens that happen to share its digits.

And the third condition: a removed sentence is REPORTED (`removed`, with
"value N not in cited passage"), never silently deleted, and never shown as
part of the answer.
"""

import pytest

from app.schemas import AnalysisRecommendation, AnalysisSummary
from app.synthesis import (
    Generation,
    claimed_numbers,
    recommend,
    strip_reference_numerals,
    summarise,
    summary_to_api,
)

QUESTION = "what is the minimum coating thickness"


class Stub:
    """A model that always says `reply`."""

    def __init__(self, reply: str):
        self.reply = reply

    def __call__(self, system: str, prompt: str) -> Generation:
        return Generation(text=self.reply, truncated=False)


def ev(evidence_id: str, text: str, filename: str = "SAES-H-001.pdf", page: int = 64):
    return {"evidence_id": evidence_id, "document_id": f"doc_{evidence_id}",
            "filename": filename, "page_start": page, "page_end": page,
            "section": "4.1", "exact_span": text, "text_source": "extracted"}


#: A second, number-free passage. `summarise` refuses a single passage on
#: purpose (one item would only turn its verbatim text into prose), so every
#: fixture carries two - and this one can never supply a number.
PLAIN = ev("e2", "Coating shall be applied by brush or spray.", page=65)


#: A passage whose ONLY numbers are 150 and 500. Any other number a sentence
#: claims over it is unsupported.
PASSAGE = [ev("e1", "Total system: minimum 150 micrometers; maximum 500 micrometers."), PLAIN]

# ------------------------------------------------ admitted families survive

ADMITTED = [
    "SAES-H-004",      # SAES, 3 digits - 9,083 occurrences
    "SAES-H-002V",     # SAES, 3 digits + suffix letter - 99
    "SAES-R-1101",     # SAES, 4 digits - 39
    "SAES-B-14",       # SAES, 2 digits - 18
    "32-SAMSS-004",    # SAMSS - 2,363
    "SAEP-1021",       # SAEP, 4 digits - 164
    "SAEP-041",        # SAEP, 3 digits - 1,338
    "SABP-A-001",      # SABP - 170
    "SAER-1972",       # SAER, 4 digits - 124
    "SAER-11714",      # SAER, 5 digits - 1
]


@pytest.mark.parametrize("identifier", ADMITTED)
def test_a_true_sentence_naming_a_real_standard_survives(identifier):
    sentence = f"{identifier} requires a minimum of 150 micrometers [S1]."
    assert claimed_numbers(sentence) == {"150.0"}, strip_reference_numerals(sentence)
    out = summarise(QUESTION, PASSAGE, Stub(sentence))
    assert out.text is not None, out.dropped_sentences
    assert identifier in out.text
    assert out.dropped_sentences == ()


def test_the_live_sentence_that_was_deleted_now_survives():
    """The claim from the 2026-09-21 reproduction, over a passage carrying its
    measurement. (Live, it opened "In contrast," - a connective the fragment
    rule rightly refuses at the head of an answer, so it is quoted without.)"""
    sentence = ("SAES-H-004 outlines a total system minimum of 150 "
                "micrometers for general structural steel applications [S1].")
    out = summarise(QUESTION, PASSAGE, Stub(sentence))
    assert out.text is not None, out.dropped_sentences


def test_a_filename_is_still_exempt_as_before():
    """The pre-existing exemption, unchanged: "doc17.pdf" names a file."""
    assert claimed_numbers("doc17.pdf requires 150 micrometers [S1].") == {"150.0"}


# ------------------------------------- the grammar is closed, not permissive


def test_a_fabricated_value_disguised_as_a_standard_number_is_still_rejected():
    """THE CASE CONDITION 1 NAMES. 150 is in the identifier AND in the claim;
    the passage has no 150. The identifier is exempt, the measurement is not."""
    passage = [ev("e1", "Total system: minimum 500 micrometers."), PLAIN]
    sentence = "Per SAES-H-150, apply 150 micrometers [S1]."
    out = summarise(QUESTION, passage, Stub(sentence))
    assert out.text is None, "a fabricated value reached the reader"
    assert out.dropped_sentences == ((sentence, "value 150 not in cited passage"),)


#: (lookalike, the first value it is held to). Each is outside the grammar, so
#: its digits stay claimed and the passage - which carries only 500 - cannot
#: support them.
NOT_A_STANDARD_NUMBER = [
    ("X-150", "150"),          # not a family at all
    ("SATIP-P-150", "150"),    # a real family, too rare to admit (2 occurrences)
    ("saes-h-150", "150"),     # lowercase: the corpus writes these in capitals
    ("SAES-H-15000", "15000"), # five digits: no SAES has five
    ("SAES-H-150-2", "150"),   # a trailing segment: not the identifier's shape
    ("SAES-150", "150"),       # missing the letter segment
    ("3-SAMSS-150", "3"),      # one-digit SAMSS prefix: not admitted
]


@pytest.mark.parametrize("lookalike, held_to", NOT_A_STANDARD_NUMBER)
def test_a_lookalike_keeps_its_digits_and_is_held_to_them(lookalike, held_to):
    """Anything outside the closed grammar is held to its numbers. The
    passage carries 500 only, so the lookalike's 150 is unsupported."""
    passage = [ev("e1", "Total system: minimum 500 micrometers."), PLAIN]
    sentence = f"Per {lookalike}, apply 500 micrometers [S1]."
    out = summarise(QUESTION, passage, Stub(sentence))
    assert out.text is None, f"{lookalike} was treated as a standard number"
    assert out.dropped_sentences[0][1] == f"value {held_to} not in cited passage"


# ------------------------------------------------ removed, never silent


def test_removed_sentences_are_reported_and_excluded_from_the_answer():
    """Condition 3. One sentence is supported, one invents 300: the answer
    keeps the first, excludes the second, and `removed` names why."""
    reply = ("SAES-H-001 requires a minimum of 150 micrometers [S1]. "
             "SAES-H-001 also requires three coats of 300 micrometers [S1].")
    out = summarise(QUESTION, PASSAGE, Stub(reply))
    api = summary_to_api(out)
    assert api["summary"] is not None
    assert "300" not in api["summary"], "the removed value reached the answer"
    assert api["removed"] == [{
        "sentence": "SAES-H-001 also requires three coats of 300 micrometers [S1].",
        "reason": "value 300 not in cited passage",
    }]


def test_the_summary_response_model_carries_removed():
    """The wire schema declares `removed`, so the route cannot drop it."""
    assert "removed" in AnalysisSummary.model_fields
    assert "dropped_sentences" not in AnalysisSummary.model_fields


def test_a_recommendation_reports_what_it_removed_even_when_nothing_survives():
    """The one path that discarded removals. Every sentence here invents a
    number, so no recommendation survives - and the reasons must still come
    back, because that is when a reader most needs them."""
    removed: list[tuple[str, str]] = []
    rec = recommend(QUESTION, PASSAGE,
                    Stub("Verify three coats of 300 micrometers [S1]."),
                    removed_out=removed)
    assert rec is None
    assert removed == [("Verify three coats of 300 micrometers [S1].",
                        "value 300 not in cited passage")]


def test_a_recommendation_keeps_the_supported_advice_and_reports_the_rest():
    removed: list[tuple[str, str]] = []
    rec = recommend(QUESTION, PASSAGE,
                    Stub("Verify the 150 micrometer minimum [S1]. "
                         "Then check the 300 micrometer topcoat [S1]."),
                    removed_out=removed)
    assert rec is not None and "300" not in rec.text
    assert removed == [("Then check the 300 micrometer topcoat [S1].",
                        "value 300 not in cited passage")]


def test_the_recommendation_response_model_carries_removed():
    assert "removed" in AnalysisRecommendation.model_fields
