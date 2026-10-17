"""#622: the search index does not read a decimal comma after a leading zero
as a thousands separator.

What was wrong: `keyword._THOUSANDS` and `_QUERY_TOKEN` took any
`\\d{1,3}(,\\d{3})+` as a thousands-separated number, so "0,030" (0.030 mm,
a European decimal) was aliased in the index as "0030" - a number the sheet
never states - and a question "0,030" asked for "0030". numparse got the
rule in #619 (a thousands group never starts with a zero); this is the same
rule in the index. Invented text only. The live index is rebuilt at the next
planned reindex, not here.
"""
from __future__ import annotations

from app import keyword, numparse
from tests.test_keyword_tokenizer import FILLER, _hits, _indexed, temp_storage  # noqa: F401


def test_a_decimal_comma_after_a_leading_zero_is_not_aliased_as_a_thousands_number():
    text = keyword.index_text("Minimum wall tolerance 0,030 mm, and 3,300 kW rated.")
    assert "0030" not in text.split(), "0,030 was aliased as the number 0030"
    assert "3300" in text.split(), "a real thousands number lost its alias"


def test_the_query_side_asks_for_the_phrase_only_and_keeps_the_token_whole():
    """cloud-2's note on #1050: the question token stays "0,030" (not a bare
    "030", which would match "1,030" too); the index is asked for the phrase
    "0 030" and never for the alias "0030"."""
    assert keyword._THOUSANDS.fullmatch("0,030") is None
    assert keyword._THOUSANDS.fullmatch("3,300") is not None
    assert [m.group(0) for m in keyword._QUERY_TOKEN.finditer("0,030 and 3,300")] == \
        ["0,030", "and", "3,300"]
    match = keyword.build_match_query("tolerance 0,030")
    assert '"0 030"' in match and "0030" not in match, match
    assert '"030"' not in match, "a bare 030 would match 1,030 as well"
    wide = keyword.build_match_query("rated 3,300")
    assert '"3 300"' in wide and '"3300"' in wide, wide


def test_rule_8_the_leading_zero_rule_is_the_one_numparse_uses():
    """One rule in three homes (keyword, numparse, claims): a lone leading
    zero is not a thousands group; anything else is. If either side drifts,
    this fails."""
    for text, thousands in (("0,030", False), ("1,030", True), ("3,300", True),
                            ("012,345", True), ("0,5", False)):
        assert (keyword._THOUSANDS.fullmatch(text) is not None) is thousands, text
        assert (numparse._strip_thousands(text) != text) is thousands, text


def test_a_sheet_stating_0_comma_030_is_found_and_0030_is_not_invented():
    _indexed("n", [("1", "Wall thickness tolerance is 0,030 mm."),
                   ("2", "The motor is rated 3,300 kW continuous."),
                   ("3", "Flow is 1,030 m3/h at the rated point."),   # the distractor: its tokens hold 030 too
                   FILLER])
    assert _hits("0,030") == {"n-c0"}, "1,030 answered a question about 0,030"
    assert _hits("1,030") == {"n-c2"}
    assert _hits("0030") == set(), "a number the sheet never states was found"
    assert _hits("3,300") == {"n-c1"} and _hits("3300") == {"n-c1"}
