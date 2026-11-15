"""U5 polish of the redesigned review page's list: one chip per rule BOOK (by identity), a point's name is the field and not its tag
list, and repeated questions group. Invented data only."""

from __future__ import annotations

from app import review_points, review_points_service
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, points_of
from tests.test_crs_endpoint import _client, _submittal, temp_db  # noqa: F401 - fixture
from tests.test_b1_review_points import on  # noqa: F401 - autouse switch fixture


# ------------------------------------------------------------------------------------------------ names without tag lists


def test_a_bracketed_list_of_tags_leaves_the_name_and_a_unit_stays():
    assert review_points.split_tags("Set pressure (TG-1, TG-2, TG-3)") == (
        "Set pressure",
        ["TG-1", "TG-2", "TG-3"],
    )
    assert review_points.split_tags("Capacity [P-1A; P-1B; ... ]") == ("Capacity", ["P-1A", "P-1B"])
    assert review_points.split_tags("Design pressure (barg)") == ("Design pressure (barg)", [])
    assert review_points.split_tags("Gap (2 mm)") == ("Gap (2 mm)", [])
    assert review_points.split_tags("Orifice (A-12)") == ("Orifice", ["A-12"])
    assert review_points.split_tags("Flow (m3/h)") == ("Flow (m3/h)", [])


def test_the_collapsed_name_carries_no_tags_and_the_opened_point_has_them():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(doc, [mk("R-1", "Query", None, why="a b", field="Set pressure (TG-1, TG-2, TG-3, TG-4)")])
    pt = points_of(_client(doc, "doc_std"), doc)["points"][0]
    assert pt["name"] == "Set pressure"
    assert pt["tags"] == ["TG-1", "TG-2", "TG-3", "TG-4"]


# ------------------------------------------------------------------------------------------------ one chip per rule book


def test_a_book_is_one_chip_by_identity_whatever_its_clause_and_page_strings_say():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(
        doc,
        [
            mk("R-1", "Query", None, why="a b", standard="STD-A-001 4.1.2 (p.5)", clause="4.1.2"),
            mk("R-2", "Query", None, why="a b", standard="STD-A-001 (p.164)", clause="9.9"),
            mk("R-3", "Fail", "Fail", standard="STD-A-001 4.1; 4.2; 4.3", clause="4.1"),
        ],
    )
    got = points_of(_client(doc, "doc_std"), doc)
    assert got["counts"]["rule_books"] == [{"id": "doc_std", "name": "STD-A-001", "points": 3}]
    assert {p["rule_book"] for p in got["points"]} == {"STD-A-001"}
    assert [b["id"] for p in got["points"] for b in p["books"]] == ["doc_std"] * 3
    assert got["counts"]["no_rule_book_points"] == 0


def test_a_point_that_cites_two_books_counts_once_for_each_and_one_with_none_goes_under_no_rule_book():
    both = {"id": "a", "books": [{"id": "d1", "name": "Book One"}, {"id": "d2", "name": "Book Two"}, {"id": "d1", "name": "Book One"}], "tile": "questions", "rank": 4, "group_key": None}
    none = {"id": "b", "books": [], "tile": "questions", "rank": 4, "group_key": None}
    only = {"id": "c", "books": [{"id": "d1", "name": "Book One"}], "tile": "questions", "rank": 4, "group_key": None}
    c = review_points.counts([both, none, only], two_reader_possible=True, not_held=[])
    assert c["rule_books"] == [
        {"id": "d1", "name": "Book One", "points": 2},
        {"id": "d2", "name": "Book Two", "points": 1},
    ]
    assert c["no_rule_book_points"] == 1
    assert c["several_books_points"] == 1  # the chips add up to 3 for 3 points only because one point is counted twice


def test_books_resolve_by_document_and_an_unreadable_one_is_not_named():
    _submittal("doc_std", "STD-A-001.pdf")
    pts = [{"_book_docs": ["doc_std"], "rule_book": "STD-A-001 4.1 (p.5)", "clause": "4.1"}, {"_book_docs": ["doc_std"], "rule_book": "x", "clause": "1"}]
    review_points_service.resolve_books(pts, frozenset({"doc_std"}))
    assert pts[0]["books"] == [{"id": "doc_std", "name": "STD-A-001"}] and pts[0]["rule_book"] == "STD-A-001"
    review_points_service.resolve_books(pts, frozenset())
    assert pts[1]["books"] == [] and pts[1]["rule_book"] is None and pts[1]["clause"] is None


# ------------------------------------------------------------------------------------------------ repeated questions group


def test_the_same_field_on_several_pages_against_the_same_clause_is_one_group():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(
        doc,
        [
            mk("R-1", "Query", None, why="a b", field="Set pressure (TG-1, TG-2)", paper_page=2),
            mk("R-2", "Query", None, why="a b", field="Set pressure (TG-3, TG-4)", paper_page=5),
            mk("R-3", "Query", None, why="a b", field="Set pressure (TG-5, TG-6)", paper_page=9),
            mk("R-4", "Query", None, why="a b", field="Set temperature", paper_page=2),
        ],
    )
    got = points_of(_client(doc, "doc_std"), doc)
    alike = [p for p in got["points"] if p["n_alike"] > 1]
    assert len(alike) == 3 and len({p["group_key"] for p in alike}) == 1
    assert {p["pill"] for p in alike} == {"Question · 3 alike"}
    assert sorted(p["page"] for p in alike) == [2, 5, 9]
    assert got["counts"]["tiles"]["questions"]["groups"] == 2  # the group, and the other field alone


def test_a_different_clause_or_field_or_book_is_not_the_same_question():
    key = review_points.group_key
    base = key("ai_review", 4, "d1", "4.1", "r", "set pressure")
    assert base is not None
    assert key("ai_review", 4, "d1", "4.2", "r", "set pressure") != base
    assert key("ai_review", 4, "d1", "4.1", "r", "set temperature") != base
    assert key("ai_review", 4, "d2", "4.1", "r", "set pressure") != base
    assert key("ai_review", 4, None, "4.1", "r", "set pressure") is None
    assert key("ai_review", 1, "d1", "4.1", "r", "set pressure") is None  # a proven Fail never joins a group


# ------------------------------------------------------------------------------------------------ R48g: reasons keep groups apart


def test_questions_with_different_reasons_are_never_one_group():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(
        doc,
        [
            mk("R-1", "Query", None, why="the value is blank", field="Set pressure (TG-1, TG-2)", paper_page=2),
            mk("R-2", "Query", None, why="the values conflict", field="Set pressure (TG-3, TG-4)", paper_page=3),
            mk("R-3", "Query", None, why="held for a condition", field="Set pressure (TG-5, TG-6)", paper_page=4),
            mk("R-4", "Query", None, why="the value is blank", field="Set pressure (TG-7, TG-8)", paper_page=5),
        ],
    )
    pts = points_of(_client(doc, "doc_std"), doc)["points"]
    assert len({p["group_key"] for p in pts}) == 3  # blank x2 is one group, the other two reasons stand alone
    by_reason = sorted(p["n_alike"] for p in pts)
    assert by_reason == [1, 1, 2, 2]


def test_the_reason_fallback_is_in_the_key():
    a = review_points.group_key("ai_review", 4, "d1", "4.1", "the value is blank", "set pressure")
    b = review_points.group_key("ai_review", 4, "d1", "4.1", "the values conflict", "set pressure")
    assert a != b


# ------------------------------------------------------------------------------------------------ R48g: a point with one unreadable book


def test_a_point_citing_a_readable_and_an_unreadable_book_is_counted_under_the_first_and_in_the_unreadable_count():
    _submittal("doc_std", "STD-A-001.pdf")
    pts = [
        {"id": "a", "_book_docs": ["doc_std", "doc_secret"], "tile": "questions", "rank": 4, "group_key": None},
        {"id": "b", "_book_docs": ["doc_secret"], "tile": "questions", "rank": 4, "group_key": None},
        {"id": "c", "_book_docs": ["doc_std"], "tile": "questions", "rank": 4, "group_key": None},
    ]
    review_points_service.resolve_books(pts, frozenset({"doc_std"}))
    c = review_points.counts(pts, two_reader_possible=True, not_held=[])
    assert c["rule_books"] == [{"id": "doc_std", "name": "STD-A-001", "points": 2}]
    assert c["other_rule_books_points"] == 2  # a and b
    assert "doc_secret" not in str(c) and "secret" not in str(pts[0]["books"])


def test_decided_counts_points_not_groups():
    from tests.test_b1_review_points import decide

    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(doc, [mk(f"R-{i}", "Query", None, why="the value is blank", field=f"Set pressure (TG-{i}, TG-{i + 10})", paper_page=i + 1) for i in (1, 2, 3)])
    client = _client(doc, "doc_std")
    pts = points_of(client, doc)["points"]
    assert {p["n_alike"] for p in pts} == {3}
    assert decide(client, doc, pts[0]["id"], "keep").status_code == 200
    assert decide(client, doc, pts[1]["id"], "keep").status_code == 200
    got = points_of(client, doc)
    assert (got["decided"], got["of"]) == (2, 3)  # two members decided, not "one group"
