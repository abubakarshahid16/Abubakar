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


# ------------------------------------------- table-aware gate (P0-4 regression)

from app.quality import assess, looks_like_table, normalise_text  # noqa: E402

REAL_TABLE = """TABLE 2.2
h  0.05
xn
yn
2.00
4.0000
2.05
4.0900
2.10
4.1842
2.15
4.2826"""

ROW_WISE_TABLE = "0.00 30.0000 30.0000 30.0000 30.0000 30.0000 30.0000 30.0000 2.00"

UNLABELLED_TABLE = "\n".join(
    ["1790", "3.929", "1800", "5.308", "1810", "7.240", "1820", "9.638", "1830", "12.866"]
)

SYMBOL_NOISE = (
    "eabeb2terfcb 1t a 2 1t ea1s 1s(1s b) eabeb2t erfcb1t a 2 1t ea1s s1s 2 B t "
    "ea2/4t a erfc a 21t ea1s s erfc a 21t ea1s a 21t3 ea2/4t ea 1s 1s 1 1t"
)


def test_a_labelled_table_with_header_and_numeric_rows_stays_retrievable():
    """Engineering specifications are mostly tables. Excluding them means the
    chatbot cannot answer a large share of real questions."""
    assert assess(REAL_TABLE, "table")["ok"]
    assert looks_like_table(REAL_TABLE)["is_table"]


def test_a_table_with_no_caption_is_still_a_table():
    """A chunk starting mid-table has no label - its first line is data."""
    assert assess(UNLABELLED_TABLE, "table")["ok"]


def test_a_table_extracted_row_wise_onto_one_line_is_still_a_table():
    """Every line-based metric is zero here; the token ratio carries it."""
    assert assess(ROW_WISE_TABLE, "table")["ok"]


def test_tables_are_not_judged_by_prose_signals():
    """The old gate scored prose averages, so it rejected 47 of 48 real tables."""
    assert assess(REAL_TABLE, "table")["ok"]
    # the same text judged as prose has no readable clause, yet must survive
    assert assess(REAL_TABLE, "prose")["ok"]


def test_symbol_font_noise_is_still_rejected():
    assert not assess(SYMBOL_NOISE, "prose")["ok"]


def test_real_content_survives_even_when_surrounded_by_numerals():
    """Page 332 of book2 vanished: mostly exercise numbers, but it contains a
    real clause and must be retrievable."""
    page = (
        "15. 16. In Problems 17-20 the given vectors are solutions of a system "
        "X AX. Determine whether the vectors form a fundamental set on the "
        "interval. 17. 18. 19. 20."
    )
    assert assess(page, "prose")["ok"]


def test_control_characters_are_normalised_before_judging():
    """Symbol-font control bytes made real content look like gibberish."""
    dirty = "d(t \x02 t0)\x08 the given vectors are solutions of a system"
    assert "\x02" not in normalise_text(dirty)
    assert "\n" in normalise_text("a\nb")      # layout survives
    assert assess(dirty, "prose")["ok"]
