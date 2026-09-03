"""Content-quality gate and document lifecycle."""
import pytest

from app import states
from app.chunker import build_chunks, content_quality, reads_like_language, Block
from app.config import settings

GOOD = (
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the "
    "bearing housing. Readings shall be taken at operating speed with the pump at "
    "rated flow, and any exceedance reported to the area engineer."
)
GOOD_WITH_CODES = "8.2 Case Study: The Therac-25 accident and its aftermath"
GARBAGE = (
    "eabeb2terfcb 1t a 2 1t ea1s 1s(1s b) eabeb2t erfcb1t a 2 1t ea1s s1s 2 B t "
    "ea2/4t a erfc a 21t ea1s s erfc a 21t ea1s a 21t3 ea2/4t ea 1s 1s 1 1t"
)
SYMBOL_SOUP = "f(t) 38. J0(kt) 39. 40. 41. 42. 43. 44. 45. 46. 47. 48. 49. 50."


def test_ordinary_engineering_prose_passes():
    assert reads_like_language(GOOD)


def test_heading_with_a_colon_and_a_product_code_passes():
    """'Study:' and 'Therac-25' must still count as words."""
    assert reads_like_language(GOOD_WITH_CODES), content_quality(GOOD_WITH_CODES)["reasons"]


def test_symbol_font_gibberish_is_rejected():
    q = content_quality(GARBAGE)
    assert not q["ok"]
    assert q["reasons"]


def test_numbered_symbol_soup_is_rejected():
    assert not reads_like_language(SYMBOL_SOUP)


def test_control_characters_are_rejected():
    assert not reads_like_language("d(t \x02 t0) e\x02st0 \x07 t 0 f (\x0e)g(t \x02 \x0e) d\x0e")


def test_empty_text_is_rejected():
    assert not reads_like_language("   ")


# ------------------------------------------------- overlap must not duplicate


def test_overlap_never_makes_a_chunk_a_substring_of_the_next():
    """106 adjacent pairs on book2 were strict substrings of each other.

    Cause: text with no sentence terminators extracts as one enormous
    'sentence', and the overlap logic carried the entire previous chunk
    forward. That is duplication, not overlap.
    """
    # one long run with no sentence-ending punctuation, like a symbol table
    blob = " ".join(f"tok{i}" for i in range(1200))
    chunks = build_chunks([Block("prose", blob, 5, 5, None)])
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:]):
        ta, tb = a.text.strip(), b.text.strip()
        assert ta not in tb, "a chunk is a strict substring of the next - duplication"
        assert tb not in ta, "a chunk is a strict substring of the previous - duplication"


def test_overlap_stays_within_its_budget():
    sents = [f"Sentence {i} about pumps and vibration limits." for i in range(60)]
    chunks = build_chunks([Block("prose", " ".join(sents), 1, 1, None)])
    for a, b in zip(chunks, chunks[1:]):
        shared = set(a.text.split()) & set(b.text.split())
        assert len(shared) < settings.chunk_target_tokens, "overlap swallowed the whole chunk"


# ------------------------------------------------------------ state machine


def test_a_document_that_finishes_reaches_a_terminal_state():
    assert states.is_terminal(states.READY)
    assert states.is_terminal(states.FAILED)
    assert not states.is_terminal(states.PARTIALLY_SEARCHABLE)


def test_keyword_index_makes_a_document_answerable_before_embedding():
    """Answering must never block on embedding being finished."""
    assert states.is_answerable(states.PARTIALLY_SEARCHABLE)
    assert states.is_answerable(states.READY)
    assert not states.is_answerable(states.CHUNKING)
    assert not states.is_answerable(states.INDEXING_KEYWORD)


def test_a_partially_processed_document_is_never_labelled_ready():
    assert states.label(states.PARTIALLY_SEARCHABLE, 340, 2831) == \
        "partially searchable - 340/2831 embedded"
    assert states.label(states.READY, 2831, 2831) == "ready"


def test_illegal_transitions_are_rejected():
    states.check_transition(states.CHUNKING, states.INDEXING_KEYWORD)
    states.check_transition(states.INDEXING_KEYWORD, states.PARTIALLY_SEARCHABLE)
    states.check_transition(states.PARTIALLY_SEARCHABLE, states.READY)
    with pytest.raises(states.IllegalTransition):
        states.check_transition(states.QUEUED, states.READY)      # cannot skip work
    with pytest.raises(states.IllegalTransition):
        states.check_transition(states.CHUNKING, states.READY)
    with pytest.raises(states.IllegalTransition):
        states.check_transition(states.QUEUED, "made_up_state")
