"""What is left of an answer after the checker removed claims must not be hollow.

Found on screen 2026-10-06 (Claude tier): a lead-in ending in a colon or
"e.g." with nothing after it, "(pipelines): 1" (a label whose claim was gone,
leaving only its marker), a bullet of bare citation numbers, and "Let me
confirm directly." kept as if it were an answer. Invented text only.
"""

from app import answer

PASSAGES = [
    {"chunk_id": "c1",
     "text": "The heat treatment shall follow welding for all low alloy pipe spools."},
    {"chunk_id": "c2",
     "text": "Vessels in caustic service shall be stress relieved after fabrication."},
]
GOOD = '[S1 "heat treatment shall follow welding"]'
GOOD2 = '[S2 "stress relieved after fabrication"]'
BAD = '[S2 "this quote is not on the page at all"]'


def _clean(text):
    return answer.verify_claims(text, PASSAGES)


# ---- (a) hollow fragments -------------------------------------------------


def test_a_lead_in_whose_claims_were_removed_is_not_left_dangling():
    text = ("The library holds other standards instead:\n"
            f"- Vessels are covered. {BAD}\n"
            f"- The tank wall is 12 mm. {GOOD}")
    clean, verification, _claims, removed = _clean(text)
    assert "instead" not in clean
    assert clean == ""
    assert verification["verified"] == 0 and removed == 2


def test_a_sentence_ending_in_e_g_with_its_example_removed_is_dropped():
    text = (f"Heat treatment follows welding {GOOD}.\n"
            "Specific services are listed, e.g.")
    clean, _v, _c, _r = _clean(text)
    assert "e.g." not in clean
    assert clean == "Heat treatment follows welding [S1]."


def test_a_bullet_of_only_citation_numbers_is_dropped():
    text = f'- Heat treatment follows welding {GOOD}\n- [S1]\n- [S2 "stress relieved after fabrication"]'
    clean, verification, _c, _r = _clean(text)
    assert clean.splitlines() == ["- Heat treatment follows welding [S1]"]
    assert verification["verified"] == 1


def test_a_label_whose_claim_is_gone_leaves_no_bare_marker():
    text = (f"Heat treatment follows welding {GOOD}\n"
            "Related standards:\n"
            f"- Pipelines: {GOOD}\n"
            f"- Tanks: {GOOD2}")
    clean, verification, claims, _r = _clean(text)
    assert clean == "Heat treatment follows welding [S1]"
    assert verification == {"verified": 1, "total": 1, "method": "quote found on the page"}
    assert [c["n"] for c in claims] == [1]


# ---- (b) filler narration -----------------------------------------------


def test_narration_that_promises_an_action_is_removed():
    text = f"Heat treatment follows welding {GOOD}. Let me confirm directly.\nI will now check the other standards."
    clean, _v, _c, _r = _clean(text)
    assert clean == "Heat treatment follows welding [S1]."


# ---- safety: nothing real is touched -------------------------------------


def test_a_real_claim_with_a_citation_is_untouched():
    text = f"Vessels in caustic service are stress relieved. {GOOD2}"
    clean, verification, _c, removed = _clean(text)
    assert clean == "Vessels in caustic service are stress relieved. [S2]"
    assert verification["verified"] == 1 and removed == 0


def test_a_lead_in_with_surviving_bullets_is_kept():
    text = ("The standard says the following:\n"
            f"- Heat treatment follows welding {GOOD}\n"
            f"- Vessels in caustic service are relieved {GOOD2}")
    clean, _v, _c, _r = _clean(text)
    assert clean.splitlines()[0] == "The standard says the following:"
    assert len(clean.splitlines()) == 3


def test_quoted_text_with_a_colon_is_untouched():
    text = f'Heat treatment follows welding {GOOD}.\nThe page reads "Note: see below:"'
    clean, _v, _c, _r = _clean(text)
    assert clean.splitlines()[-1] == 'The page reads "Note: see below:"'


def test_let_me_know_is_an_offer_not_narration():
    clean, _v, _c, _r = _clean("Let me know if you want the other standards.")
    assert clean == "Let me know if you want the other standards."


def test_the_streaming_call_keeps_a_lead_in_that_is_alone_in_its_sentence():
    clean, _v, _c, _r = answer.verify_claims("Related standards:", PASSAGES, final=False)
    assert clean == "Related standards:"


def test_an_answer_of_only_hollow_fragments_becomes_the_honest_refusal():
    from app import chat_claude_first

    class _Response:
        text = "Let me check.\nRelated standards:\n- [S1]\n- [S2]"
        cost_usd = 0.0
        provider = "claude"
        model_tag = "m"
        truncated = False

    out = chat_claude_first._finish(_Response(), PASSAGES, [], 0.0, None)
    assert out["answer_type"] == "insufficient_evidence"
    assert out["answer"] is None


# ---- (c) refusal wording -------------------------------------------------


def _empty_search(monkeypatch):
    monkeypatch.setattr(answer.search_mod, "search", lambda *a, **k: {
        "hits": [], "mode": "keyword", "reranked": False, "timings": {},
        "total": 0, "seconds": 0.0})


def test_the_unscoped_refusal_states_what_was_searched(monkeypatch):
    _empty_search(monkeypatch)
    out = answer.answer("what does STD-A-001 say about PWHT",
                        allowed_document_ids=frozenset({"d1", "d2", "d3"}))
    assert out["answer_type"] == "insufficient_evidence"
    assert out["reason"] == "nothing in the 3 documents you can read matched this question"


def test_the_unscoped_refusal_with_no_readable_documents_says_no_passage(monkeypatch):
    _empty_search(monkeypatch)
    out = answer.answer("what does STD-A-001 say about PWHT", allowed_document_ids=frozenset())
    assert out["reason"] == "no passage you can read matched this question"


def test_the_scoped_refusal_keeps_its_wording_when_the_document_cannot_be_described(monkeypatch):
    _empty_search(monkeypatch)
    monkeypatch.setattr(answer.lexical, "searched_scope", lambda doc, allowed: "the indexed documents")
    out = answer.answer("what does STD-A-001 say about PWHT", document_id="d1",
                        allowed_document_ids=frozenset({"d1"}))
    assert out["reason"] == "none of the indexed documents mention this topic"


def test_a_scoped_refusal_names_the_document_it_searched(monkeypatch):
    _empty_search(monkeypatch)
    monkeypatch.setattr(answer.lexical, "searched_scope",
                        lambda doc, allowed: "STD-A-001.pdf (76 passages searched)")
    out = answer.answer("what does STD-A-001 say about PWHT", document_id="d1",
                        allowed_document_ids=frozenset({"d1"}))
    assert out["reason"] == "STD-A-001.pdf (76 passages searched) has nothing on this topic"


def test_narration_before_a_tool_call_is_kept_and_only_the_last_round_is_cleaned():
    text = "Let me check the documents first.\n\nHere is what I found.\n\nLet me confirm directly."
    kept_all, *_ = answer.verify_claims(text, [], narration_from_line=None)
    assert "Let me check the documents first." in kept_all
    assert "Let me confirm directly." in kept_all
    last_only, *_ = answer.verify_claims(text, [], narration_from_line=4)
    assert "Let me check the documents first." in last_only
    assert "Let me confirm directly." not in last_only
