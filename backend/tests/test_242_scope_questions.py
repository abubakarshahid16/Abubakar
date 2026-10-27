"""Order 242.2: a division's scope reading is a real sentence, and the engineer
is asked ONE question per construction Part.

On 216400C the standard-scope step moved 804 requirements of one standard out of
the listed findings on "conditions" that were table fragments, and the real
ones (Part UW, welded) left 420 requirements in the scope record only. Now a
reading whose quote is not a sentence is refused (the Part is compared, with the
"scope not confirmed" note), and a Part whose real scope the datasheet does not
settle is one line, "Question for the engineer". Invented text only.
"""

from __future__ import annotations

import pytest

from app import absence, ai_applicability, scope_quote, scope_type_words
from tests.test_141_division_scope import (
    LIMITED,
    PAGES,
    SPECIAL,
    FakeModel,
    temp_storage,  # noqa: F401 - used through usefixtures
)

pytestmark = pytest.mark.usefixtures("temp_storage")
UNSURE_TYPE = {"equipment_is": "not stated", "quote": "", "is_that": "unsure"}
SECOND = {
    **SPECIAL,
    "id": "zz2",
    "requirement_text": "Impregnated tubes shall be pressure tested at 30 bar.",
    "source_text": "ZZ-3 Impregnated tubes shall be pressure tested at 30 bar.",
}
GARBLED_PAGES = [
    (1, PAGES[0][1]),
    (
        2,
        "PART ZZ\nREQUIREMENTS FOR VESSELS CONSTRUCTED OF GRAPHITE\nZZ-1 SCOPE\n"
        "Subpart 2 do not contain these properties ...\n"
        "ZZ-2 Impregnated tubes shall withstand at least 20 bar.\n",
    ),
]


def _gate(model, pages, reqs):
    return ai_applicability.division_gate(
        [dict(r) for r in reqs],
        classification={"equipment_type": "Pressure vessel"},
        facts=[],
        standard_labels={"std": "STD-VESSEL-0001"},
        provider=model,
        pages_of=lambda sid: pages,
    )


def _ids(rows):
    return [r["requirement"]["id"] if "requirement" in r else r["id"] for r in rows]


REAL = "The rules in Part ZZ are applicable to vessels constructed of graphite and graphite compounds."


@pytest.mark.parametrize(
    ("quote", "construction"),
    [
        ("Subpart 2 do not contain these properties ...", "Subpart 2"),
        ("UHA SA-480 Pipe SA-333", "UHA SA-480 Pipe"),
        ("see Table 3 below", "Table 3 below"),
        ("1.5 2.0 3.0 4.5 6.0 7.5 9.0 10.5", "1.5 2.0 3.0"),
        ("applies to welded vessels", ""),
    ],
)
def test_a_fragment_is_not_a_scope_sentence(quote, construction):
    scope = {"limited": "yes", "quote": quote, "construction": construction}
    assert scope_quote.problems(scope)


def test_a_real_scope_sentence_is_accepted():
    scope = {
        "limited": "yes",
        "quote": REAL,
        "construction": "constructed of graphite and graphite compounds",
    }
    assert scope_quote.problems(scope) == []
    assert (
        scope_quote.problems({"limited": "no", "quote": None, "construction": None})
        == []
    )


def test_a_garbled_scope_reading_no_longer_holds_the_part():
    model = FakeModel(
        {
            "limited": "yes",
            "construction": "Subpart 2",
            "quote": "Subpart 2 do not contain these properties ...",
        },
        UNSURE_TYPE,
    )
    out = _gate(model, GARBLED_PAGES, (SPECIAL, SECOND))
    assert _ids(out["kept"]) == ["zz", "zz2"] and out["held"] == []
    assert out["summary"]["scope_quote_refused"] == 1
    assert out["notes"]["zz"] == scope_type_words.SCOPE_NOT_CONFIRMED
    assert "questions" not in out["summary"]


def test_a_real_part_the_datasheet_does_not_settle_is_one_question_with_its_count():
    out = _gate(FakeModel(LIMITED, UNSURE_TYPE), PAGES, (SPECIAL, SECOND))
    assert sorted(_ids(out["held"])) == ["zz", "zz2"]
    [question] = out["summary"]["questions"]
    assert question["requirements"] == 2 and question["standard"] == "STD-VESSEL-0001"
    assert question["part"].startswith("PART ZZ") and question["page"] == 2
    assert question["construction"] == LIMITED["construction"]


def test_the_question_is_one_line_in_the_review_notes():
    out = _gate(FakeModel(LIMITED, UNSURE_TYPE), PAGES, (SPECIAL, SECOND))
    lines = absence.split_lines({"division_scope": out["summary"]})
    [line] = [ln for ln in lines if ln.startswith("Question for the engineer")]
    assert "2 requirement(s) wait on the answer" in line
    assert "does not state how the equipment is built" in line


def test_more_questions_than_the_sheet_prints_say_how_many_more():
    questions = [
        {
            "part": f"PART {n}",
            "standard": "S",
            "construction": "x",
            "requirements": 10 - n,
        }
        for n in range(7)
    ]
    lines = absence.scope_question_lines(questions)
    assert len(lines) == absence.MAX_SCOPE_QUESTIONS + 1
    assert lines[-1].startswith("2 more Part question(s)")
    assert absence.scope_question_lines(None) == []
