"""Update 7, builder C (review of update 6a, B1): ordinary upper-case datasheet words are never cited standards. A company
standard number counts only for a FAMILY the library holds, with a document-number shape; a bare "STD" next to a size,
schedule, material or maker word is never one. Invented names and numbers only."""

from __future__ import annotations

import pytest

from app import standard_ids as S
from app.aim_review import book_names as BN
from tests.test_aim_method_helpers import PAPER, _doc, open_aim_db


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _paper_says(conn, text: str) -> None:
    with conn:
        conn.execute(
            "UPDATE pages SET text = text || ? WHERE document_id = ? AND page_no = 1",
            ("\n" + text + "\n", PAPER),
        )


def _hold_family_book(conn, number: str) -> None:
    with conn:
        _doc(
            conn,
            "doc_xy_held",
            f"{number}.pdf",
            "COMPANY_STANDARD",
            {1: f"{number} invented company standard text"},
        )
        conn.execute(
            "UPDATE document_classification SET document_number = ? WHERE document_id = 'doc_xy_held'",
            (number,),
        )


def _cited_not_held(conn) -> list[str]:
    return [
        p["field"] for p in BN.cited_points(BN.with_cited_not_held(conn, PAPER, [], []))
    ]


def test_ordinary_upper_case_datasheet_words_are_not_cited_standards(aim_db):
    """The reviewer's test (failed on 3eaeed3f with three false points)."""
    _paper_says(aim_db, "PIPE SCH STD 40\nMFR STD 316 SS\nVENDOR STD 2 COATS")
    assert _cited_not_held(aim_db) == []


@pytest.mark.parametrize(
    "line",
    [
        "PIPE SCH STD 40",
        "MFR STD 316 SS",
        "VENDOR STD 2 COATS",
        "MOTOR IS STD 4 POLE",
        "XY SCH STD 40",  # a held family, but a schedule
        "XY STD 316 SS",  # a held family, but a material grade
        "XY MFR STD 104",  # a held family, but the maker's own standard
        "Tags 21-PV-1234 and 21-XY-STD-104-X.",  # an equipment tag
        "XY STD 104-X",  # a code, not a part number
        "QQ STD 104",  # a family the library does not hold
    ],
)
def test_near_misses_are_never_cited_standards(line):
    assert S.find_citations(line) == []
    assert S.company_citations(line, frozenset({"XY"})) == []


def test_a_company_number_of_a_held_family_is_read_whole_and_alone():
    assert S.company_citations("PIPING CLASS PER XY STD 104", frozenset({"XY"})) == [
        ("XY STD 104", 17, 27)
    ]
    assert (
        S.company_citations("Relief design per XY-MECH-STD-104.", frozenset({"XY"}))[0][
            0
        ]
        == "XY-MECH-STD-104"
    )
    assert (
        S.company_citations("XY STD 104-2 applies", frozenset({"XY"}))[0][0]
        == "XY STD 104-2"
    )
    assert (
        S.company_family("XY-MECH-STD-102") == "XY"
        and S.company_family("ISO 99101") is None
    )


def test_a_held_family_number_not_held_is_cited_not_held_and_a_held_one_is_not(aim_db):
    _hold_family_book(aim_db, "XY-STD-102")
    _paper_says(
        aim_db, "PIPING CLASS PER XY STD 104\nPIPE SCH STD 40\nLINING PER XY STD 102"
    )
    assert _cited_not_held(aim_db) == [
        "XY STD 104"
    ]  # 102 is held; the schedule line is no standard


def test_a_number_at_the_end_of_a_line_is_read_and_the_next_line_does_not_count():
    text = "PIPING CLASS PER XY STD 104\nPIPE SCH STD 40\nXY\nSTD 105"
    assert [c[0] for c in S.company_citations(text, frozenset({"XY"}))] == [
        "XY STD 104"
    ]


@pytest.mark.parametrize(
    "word", ["and", "or", "of", "the", "is", "to", "in", "per", "as", "AND", "OF"]
)
def test_a_true_citation_followed_by_a_joining_word_is_still_read(word):
    """Review of 7a, M1: a joining word AFTER the number leaves a true citation of a held family a citation."""
    found = [
        c[0]
        for c in S.company_citations(
            f"Design to XY STD 104 {word} XY STD 105.", frozenset({"XY"})
        )
    ]
    assert found == ["XY STD 104", "XY STD 105"]


def test_a_dash_joined_citation_followed_by_of_is_read():
    assert [
        c[0]
        for c in S.company_citations(
            "Per XY-MECH-STD-104 of latest revision", frozenset({"XY"})
        )
    ] == ["XY-MECH-STD-104"]


@pytest.mark.parametrize(
    "line",
    [
        "XY STD 316 SS",
        "XY STD 2 COATS",
        "XY STD 4 POLE",
        "XY STD 50 MM",
        "XY SCH STD 40",
        "XY MFR STD 104",
        "XY IS STD 104 and more",
    ],
)
def test_the_false_std_cases_stay_fixed(line):
    """The words that make STD a size, unit, material, schedule or maker's own standard still block it."""
    assert S.company_citations(line, frozenset({"XY"})) == []
