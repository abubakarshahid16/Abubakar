"""The honesty check must not eat the honest content.

Observed live on the Analysis screen: a Focused summary over two passages was
reduced to ONE sentence beginning "It also mandates..." - a fragment. Three
sentences had been removed, each tagged "carries a number no cited span
contains: 17.0" / "20.0". The numbers were "Document 17" and "Document 20":
document references, read by the numeric-claim gate as measurements.

Three rules under test, and each test here goes red when its rule is deleted:

  * a numeral that REFERS ("Document 17", "clause 6.1", "Table 1", "page 183",
    "doc17.pdf", "r5") is not held against the cited spans - and a numeral that
    MEASURES ("50 mm", "1 hour", "30 percent", "8 inches (200 mm)") still is.
    Both directions are tested, because a false negative here reintroduces
    fabricated measurements, the defect the gate exists to prevent;
  * a rendered summary never opens with a dangling reference. A whole sentence
    is promoted ahead of it, or the summary is refused;
  * three failures no longer wear one sentence. "the model reported the sources
    do not support a summary" is said ONLY when the model said so. An empty,
    truncated-to-nothing or garbled completion is named for what it is, and the
    raw completion is kept so the refusal can be checked against it.
"""

import pytest

from app import synthesis
from app.synthesis import (
    FRAGMENT_REASON,
    REFUSAL_EMPTY,
    REFUSAL_EMPTY_TRUNCATED,
    REFUSAL_MALFORMED,
    REFUSAL_MODEL_DECLINED,
    Generation,
    claimed_numbers,
    describe_unreachable,
    is_fragment,
    strip_reference_numerals,
    summarise,
    summary_to_api,
)

QUESTION = "what does each document require for incident response"

#: The reason string the gate emits. Asserted by prefix so a test cannot pass
#: because the sentence was dropped for some OTHER reason.
NUMBER_REASON = "carries a number no cited span contains"


def ev(evidence_id, text, filename="doc17.pdf", page=1):
    return {
        "evidence_id": evidence_id,
        "document_id": f"doc_{filename}",
        "filename": filename,
        "page_start": page,
        "page_end": page,
        "section": None,
        "exact_span": text,
        "text_source": "extracted",
    }


class Stub:
    def __init__(self, *replies, truncated=False, raise_=None):
        self.replies = list(replies)
        self.truncated = truncated
        self.raise_ = raise_
        self.calls = []

    def __call__(self, system, prompt):
        self.calls.append((system, prompt))
        if self.raise_ is not None:
            raise self.raise_
        text = self.replies.pop(0) if self.replies else ""
        return Generation(text=text, truncated=self.truncated)


#: The live case. NEITHER span contains 17 or 20 - the numbers exist only in
#: the model's document references.
DOC17 = ev("e17", "The organisation shall develop and maintain an incident "
                  "response policy that addresses purpose, scope and roles.",
           "doc17.pdf", 4)
DOC20 = ev("e20", "Incident handling shall be coordinated with contingency "
                  "planning activities and tested annually.", "doc20.pdf", 9)
LIVE = [DOC17, DOC20]

LIVE_REPLY = (
    "Document 17 requires an incident response policy [S1]. "
    "Document 20 requires incident handling to be coordinated with contingency "
    "planning [S2]. "
    "Documents 17 and 20 both require annual testing of the capability [S2]. "
    "It also mandates that the policy address roles [S1]."
)


# --------------------------------------------- 1. the extractor, before and after


def test_the_raw_extractor_reads_document_17_as_the_number_17():
    """The proof the brief asked for: `_numbers` - the extractor behind the
    gate - reads "Document 17" as the measurement 17.0. This is the behaviour
    `claimed_numbers` now sits in front of; the raw extractor is unchanged and
    still used on the SPANS, where more numbers can only help a sentence."""
    sentence = "Document 17 requires an incident response policy [S1]."
    assert synthesis._numbers(synthesis._CITATION.sub("", sentence)) == {"17.0"}
    assert claimed_numbers(sentence) == set()


# ------------------------------------------- 2(b). references are not measurements


@pytest.mark.parametrize(
    "sentence",
    [
        "Document 17 requires an incident response policy [S1].",
        "Document 1 and Document 2 both require it [S1][S2].",
        "Documents 17 and 20 both require it [S1][S2].",
        "doc17 requires an incident response policy [S1].",
        "doc17.pdf requires an incident response policy [S1].",
        "NORSOK_M-501_r5.pdf requires it [S1].",
        "The policy is required [S1].",  # [S1] alone was never a number; still not
        "Section 4 requires an incident response policy [S1].",
        "Sections 4 and 5 require it [S1].",
        "Sections 4-6 require it [S1].",
        "clause 6.1 requires it [S1].",
        "Clause 6.1.2 requires it [S1].",
        "Table 1 lists the roles [S1].",
        "Figure 3 shows the escalation path [S1].",
        "Fig. 3 shows the escalation path [S1].",
        "Revision 2 supersedes the earlier text [S1].",
        "rev. 2 supersedes the earlier text [S1].",
        "r5 supersedes r4 [S1].",
        "See page 183 for the policy [S1].",
        "See p.183 for the policy [S1].",
        "See pp. 183-185 for the policy [S1].",
        "See pages 183 to 185 for the policy [S1].",
        "Annex 2 and Appendix 3 list the roles [S1].",
        "Source 1 requires an incident response policy [S1].",
    ],
    ids=lambda s: s.split(" [")[0][:40],
)
def test_a_reference_numeral_is_not_held_against_the_span(sentence):
    """Unit level: none of these sentences claims a number. Then end to end:
    each SURVIVES over spans that contain none of its digits."""
    assert claimed_numbers(sentence) == set(), strip_reference_numerals(sentence)
    out = summarise(QUESTION, LIVE, Stub(sentence))
    assert out.text is not None, out.dropped_sentences
    assert not any(NUMBER_REASON in r for _, r in out.dropped_sentences)


@pytest.mark.parametrize(
    "sentence, number",
    [
        ("The minimum thickness is 50 mm [S1].", "50.0"),
        ("The gap shall not exceed 2 mm [S1].", "2.0"),
        ("The system must be restored within 1 hour [S1].", "1.0"),
        ("Capacity is reduced by 30 percent [S1].", "30.0"),
        ("Cover shall be 8 inches (200 mm) [S1].", "8.0"),
        ("The converted value is 0.28 mm [S1].", "0.28"),
        ("Adhesion shall be 9,0 MPa [S1].", "9.0"),
        # A measurement standing NEXT TO a reference is still a measurement.
        ("Section 4 requires 50 mm of cover [S1].", "50.0"),
        ("Section 4 and 50 mm of cover are required [S1].", "50.0"),
        ("clause 6.1 requires 6.1 MPa adhesion [S1].", "6.1"),
        ("Table 1 requires 3 layers [S1].", "3.0"),
        ("Document 17 requires restoration within 4 hours [S1].", "4.0"),
        ("doc17.pdf requires 2 mm [S1].", "2.0"),
        ("page 183 gives 30 percent [S1].", "30.0"),
    ],
    ids=lambda s: str(s).split(" [")[0][:40],
)
def test_a_real_measurement_is_still_dropped_when_no_cited_span_contains_it(sentence, number):
    """The other direction, and the one that matters more: none of the
    reference patterns may swallow a quantity. The spans here contain no
    digits at all, so the sentence must be dropped with the number named."""
    assert number in claimed_numbers(sentence), strip_reference_numerals(sentence)
    out = summarise(QUESTION, LIVE, Stub(sentence))
    assert out.text is None, "a fabricated measurement reached the reader"
    # The gate names the first unsupported number in sort order; "8 inches
    # (200 mm)" reports 200.0. Every number named must be one the sentence
    # actually claims, and the sentence itself must be the one dropped.
    assert out.dropped_sentences[0][0] == sentence
    reason = out.dropped_sentences[0][1]
    assert reason.startswith(f"{NUMBER_REASON}: "), reason
    assert reason.split(": ", 1)[1] in claimed_numbers(sentence)


def test_an_abbreviated_reference_is_not_split_from_its_number():
    """"Fig. 3" split at the full stop is an uncited "Fig." plus a sentence
    claiming the number 3 - the same false drop by another door. The join is
    narrow: only when the next piece starts with a digit, so "etc." at a real
    sentence end still ends the sentence."""
    assert synthesis.split_sentences("See Fig. 3 for the path [S1]. Cover is 50 mm [S1].") == [
        "See Fig. 3 for the path [S1].", "Cover is 50 mm [S1]."]
    assert synthesis.split_sentences("Use grade A etc. 3 layers are needed [S1].") == [
        "Use grade A etc.", "3 layers are needed [S1]."]
    assert synthesis.split_sentences("It is 5 mm. 3 layers [S1].") == [
        "It is 5 mm.", "3 layers [S1]."]


def test_a_real_measurement_the_span_supports_survives_beside_a_reference():
    """The exclusion must not have made a supported measurement unsupportable:
    the sentence's numbers shrink, the span's never do."""
    evidence = [ev("a", "Cover shall be 50 mm.", "doc17.pdf", 4),
                ev("b", "Adhesion shall be 9,0 MPa.", "doc20.pdf", 9)]
    out = summarise(QUESTION, evidence, Stub(
        "Section 4 of doc17.pdf requires 50 mm of cover [S1]. "
        "Table 1 of Document 20 requires 9,0 MPa [S2]."))
    assert out.text is not None, out.dropped_sentences
    assert len(out.findings) == 2
    assert out.dropped_sentences == ()


def test_a_reference_beside_an_unsupported_number_does_not_shield_it():
    """Stripping "Section 4" must leave exactly the measurement behind; the
    reported number is the measurement, never the reference."""
    out = summarise(QUESTION, LIVE, Stub("Section 4 requires 50 mm [S1]."))
    assert out.text is None
    assert out.dropped_sentences == (
        ("Section 4 requires 50 mm [S1].", f"{NUMBER_REASON}: 50.0"),
    )


# --------------------------------------------- 5. the live Document 17/20 case


def test_the_live_document_17_and_20_case_survives_whole():
    """Three sentences naming Document 17 and Document 20, over spans that
    contain neither number. Before the fix: one fragment and three removals
    tagged 17.0 / 20.0. After: all four sentences, opening with a whole one."""
    out = summarise(QUESTION, LIVE, Stub(LIVE_REPLY))
    assert out.text is not None, out.dropped_sentences
    assert not any(NUMBER_REASON in r for _, r in out.dropped_sentences), out.dropped_sentences
    assert len(out.findings) == 4
    assert out.text.startswith("Document 17 requires an incident response policy")
    assert "Document 20 requires incident handling" in out.text
    assert "Documents 17 and 20 both require" in out.text
    assert "It also mandates" in out.text  # kept, but not first
    assert out.cited_evidence_ids == ("e17", "e20")


# --------------------------------------------------------- 3. the fragment guard


@pytest.mark.parametrize("opener", [
    "It also", "In contrast", "Additionally", "Furthermore", "Moreover", "However",
    "The former", "The latter", "Also", "In addition", "Similarly", "Likewise",
])
def test_a_connective_opener_is_a_fragment_wherever_it_stands(opener):
    assert is_fragment(f"{opener} mandates a policy [S1].", displaced=False)
    assert is_fragment(f"{opener}, a policy is mandated [S1].", displaced=True)


@pytest.mark.parametrize("opener", ["This", "These", "Such", "That", "Those"])
def test_a_demonstrative_is_a_fragment_only_when_displaced(opener):
    """"This standard requires..." is a fine opener when the model led with
    it, and a dangling one when the sentence it pointed at was removed."""
    assert is_fragment(f"{opener} requires a policy [S1].", displaced=True)
    assert not is_fragment(f"{opener} requires a policy [S1].", displaced=False)


def test_a_word_that_merely_starts_with_an_opener_is_not_one():
    assert not is_fragment("Thistle Ltd requires a policy [S1].", displaced=True)
    assert not is_fragment("Alsoft is the vendor [S1].", displaced=False)
    assert not is_fragment("Italy requires a policy [S1].", displaced=True)


def test_a_whole_sentence_is_promoted_ahead_of_a_fragment_left_standing_first():
    """The first sentence is dropped (999 mm is in no span). "It also..." is
    now first and dangling; the self-contained third sentence is promoted, the
    fragment follows it, nothing true is lost."""
    reply = ("The cover shall be 999 mm [S1]. "
             "It also mandates that the policy address roles [S1]. "
             "Incident handling shall be coordinated with contingency planning [S2].")
    out = summarise(QUESTION, LIVE, Stub(reply))
    assert out.text is not None
    assert out.text.startswith("Incident handling shall be coordinated"), out.text
    assert [f.text for f in out.findings] == [
        "Incident handling shall be coordinated with contingency planning [S2].",
        "It also mandates that the policy address roles [S1].",
    ]
    assert out.dropped_sentences == (
        ("The cover shall be 999 mm [S1].", f"{NUMBER_REASON}: 999.0"),
    )


def test_a_displaced_demonstrative_is_promoted_over_by_a_whole_sentence():
    reply = ("The cover shall be 999 mm [S1]. "
             "This must be tested annually [S2]. "
             "The policy shall address purpose, scope and roles [S1].")
    out = summarise(QUESTION, LIVE, Stub(reply))
    assert out.text.startswith("The policy shall address"), out.text
    assert "This must be tested annually" in out.text


def test_a_demonstrative_the_model_led_with_is_not_displaced_and_stays_first():
    out = summarise(QUESTION, LIVE, Stub(
        "This policy shall address purpose, scope and roles [S1]. "
        "Incident handling shall be coordinated with contingency planning [S2]."))
    assert out.text.startswith("This policy shall address"), out.text
    assert out.dropped_sentences == ()


def test_a_summary_made_only_of_fragments_is_refused_and_says_why():
    """The live outcome - one sentence, "It also mandates..." - must not be
    rendered. With nothing whole to promote, the fragments are dropped and
    reported and the summary is refused."""
    reply = ("The cover shall be 999 mm [S1]. "
             "It also mandates that the policy address roles [S1].")
    out = summarise(QUESTION, LIVE, Stub(reply))
    assert out.text is None
    assert out.findings == ()
    assert out.refusal and "continued a sentence that was removed" in out.refusal
    assert ("It also mandates that the policy address roles [S1].", FRAGMENT_REASON) \
        in out.dropped_sentences
    api = summary_to_api(out)
    assert api["summary"] is None and api["documented_findings"] == []


def test_the_fragment_guard_does_not_fire_when_nothing_was_removed_and_nothing_dangles():
    out = summarise(QUESTION, LIVE, Stub(
        "The policy shall address roles [S1]. Handling is coordinated with "
        "contingency planning [S2]."))
    assert len(out.findings) == 2 and out.dropped_sentences == ()


# --------------------------------------- 4. three failures, three sentences


def test_the_model_declining_is_reported_as_the_model_declining():
    model = Stub("INSUFFICIENT EVIDENCE")
    out = summarise(QUESTION, LIVE, model)
    assert out.text is None
    assert out.refusal == REFUSAL_MODEL_DECLINED
    assert out.raw_completion == "INSUFFICIENT EVIDENCE"


def test_an_empty_completion_is_not_reported_as_the_models_judgement():
    """What a 4B model on a machine with no free memory returns after its
    load times out: a 200 with an empty `response`. The model said nothing."""
    out = summarise(QUESTION, LIVE, Stub(""))
    assert out.text is None
    assert out.refusal == REFUSAL_EMPTY
    assert "reported the sources" not in out.refusal
    assert "nothing usable" in out.refusal
    assert out.raw_completion == ""
    assert out.truncated is False


def test_a_completion_truncated_to_nothing_says_so():
    out = summarise(QUESTION, LIVE, Stub("", truncated=True))
    assert out.text is None
    assert out.refusal == REFUSAL_EMPTY_TRUNCATED
    assert "reported the sources" not in out.refusal
    assert "length limit" in out.refusal
    assert out.truncated is True


def test_a_completion_cut_inside_its_first_marker_is_truncated_to_nothing():
    """The half-marker strip can leave nothing behind. The reader is told the
    cap did it, not that the model judged the evidence."""
    out = summarise(QUESTION, LIVE, Stub("[S", truncated=True))
    assert out.refusal == REFUSAL_EMPTY_TRUNCATED
    assert out.raw_completion == "[S"


@pytest.mark.parametrize("garbage", ["...", "--- ---", "??? !!!", "​ ​"])
def test_a_completion_with_no_readable_sentence_is_malformed_not_a_judgement(garbage):
    out = summarise(QUESTION, LIVE, Stub(garbage))
    assert out.text is None
    assert out.refusal == REFUSAL_MALFORMED
    assert "reported the sources" not in out.refusal
    assert out.raw_completion == garbage


def test_the_word_insufficient_inside_readable_prose_still_counts_as_declining():
    """The token is the model's own signal and is honoured wherever it appears
    in readable text - unchanged behaviour, pinned so the split above cannot
    have narrowed it."""
    out = summarise(QUESTION, LIVE, Stub("Insufficient evidence to summarise [S1]."))
    assert out.refusal == REFUSAL_MODEL_DECLINED


def test_an_unreachable_model_raises_through_and_is_never_the_declined_sentence():
    """(iii) is the route's to render: `generate` raising must propagate so the
    caller can say "could not be reached", and must never be swallowed into a
    Summary that claims the model judged the sources."""
    class Unreachable(Exception):
        pass

    with pytest.raises(Unreachable):
        summarise(QUESTION, LIVE, Stub(raise_=Unreachable("ReadTimeout")))
    wording = describe_unreachable("ReadTimeout")
    assert "could not be reached" in wording and "ReadTimeout" in wording
    assert "reported the sources" not in wording
    assert wording != REFUSAL_MODEL_DECLINED


def test_the_three_refusals_are_three_different_sentences():
    assert len({REFUSAL_MODEL_DECLINED, REFUSAL_EMPTY, REFUSAL_EMPTY_TRUNCATED,
                REFUSAL_MALFORMED, describe_unreachable("x")}) == 5


def test_the_raw_completion_is_kept_on_success_and_on_refusal_and_in_the_api():
    ok = summarise(QUESTION, LIVE, Stub(LIVE_REPLY))
    assert ok.raw_completion == LIVE_REPLY
    assert summary_to_api(ok)["raw_completion"] == LIVE_REPLY
    none_cited = summarise(QUESTION, LIVE, Stub("Nothing is cited here."))
    assert none_cited.text is None and none_cited.raw_completion == "Nothing is cited here."
    # No generation ran, so there is no completion to report.
    assert summarise(QUESTION, LIVE[:1], Stub("x [S1].")).raw_completion is None


# ------------------------------------------------------------ 2(a). the prompt


def test_both_prompts_tell_the_model_to_name_documents_by_filename():
    for prompt in (synthesis.SUMMARY_SYSTEM_PROMPT, synthesis.RECOMMENDATION_SYSTEM_PROMPT):
        assert "filename" in prompt
        assert "doc17.pdf" in prompt
        assert 'never "Document 17"' in prompt


def test_the_source_header_gives_the_model_the_filename_to_use():
    model = Stub(LIVE_REPLY)
    summarise(QUESTION, LIVE, model)
    _system, prompt = model.calls[0]
    assert "[S1] (doc17.pdf, page 4)" in prompt
    assert "[S2] (doc20.pdf, page 9)" in prompt
