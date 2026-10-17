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

from app import keyword
from tests.test_keyword_tokenizer import FILLER, _hits, _indexed, temp_storage  # noqa: F401


def test_a_decimal_comma_after_a_leading_zero_is_not_aliased_as_a_thousands_number():
    text = keyword.index_text("Minimum wall tolerance 0,030 mm, and 3,300 kW rated.")
    assert "0030" not in text.split(), "0,030 was aliased as the number 0030"
    assert "3300" in text.split(), "a real thousands number lost its alias"


def test_the_query_side_follows_the_same_rule():
    assert keyword._THOUSANDS.fullmatch("0,030") is None
    assert keyword._THOUSANDS.fullmatch("3,300") is not None
    assert [m.group(0) for m in keyword._QUERY_TOKEN.finditer("0,030 and 3,300")] == \
        ["030", "and", "3,300"]
    match = keyword.build_match_query("tolerance 0,030")
    assert "0030" not in match, "the question asked the index for 0030"


def test_a_sheet_stating_0_comma_030_is_found_and_0030_is_not_invented():
    _indexed("n", [("1", "Wall thickness tolerance is 0,030 mm."),
                   ("2", "The motor is rated 3,300 kW continuous."), FILLER])
    assert _hits("0,030") == {"n-c0"}
    assert _hits("0030") == set(), "a number the sheet never states was found"
    assert _hits("3,300") == {"n-c1"} and _hits("3300") == {"n-c1"}
