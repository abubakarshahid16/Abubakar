"""Order 14 (17 Nov 2026), the datasheet WRONG list W-D6, W-D7, W-D8, W-D11: a point that carries no finding of its own is never part of
a comment; a contents or reference-list entry is never a requirement; one source per row; a form the paper is not on is "form not held".
Invented books, fields, forms and values only (public repo)."""

from __future__ import annotations

import sqlite3

import pytest

from app import crs_ai_words as words
from app import crs_comments, crs_no_finding, crs_one, rule_text_place, untrusted_value
from app import review_points_content as content

# ------------------------------------------------------------------------------------------------ helpers


def _p(i, name, rank, tile=None, **kw) -> dict:
    from app.review_points import TILE_OF_RANK

    return {"id": f"p{i}", "name": name, "rank": rank, "tile": tile or TILE_OF_RANK[rank], "tags": [], "decision": {"state": None},
            "source": kw.pop("source", "rule_check"), "pill": kw.pop("pill", "Question"), **kw}  # fmt: skip


def _ai(i, name, rank, line: dict, **kw) -> dict:
    return _p(
        i,
        name,
        rank,
        source="ai_review",
        _line={"source": "skill", "item_id": f"S-X-{i}", **line},
        **kw,
    )


def _aside(points) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c, kind in crs_comments.set_aside(points):
        out.setdefault(kind, []).extend(c["member_ids"])
    return out


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE chunks (id TEXT, document_id TEXT, page_start INT, page_end INT, section TEXT, kind TEXT, text TEXT, context TEXT);"
        "CREATE TABLE standard_requirements (id TEXT, requirement_text TEXT, source_text TEXT, chunk_id TEXT);"
        "CREATE TABLE documents (id TEXT, filename TEXT);"
    )
    return conn


# ------------------------------------------------------------------------------------------------ W-D6: no finding, no comment


def test_a_book_missing_point_is_not_a_comment_even_on_a_field_that_has_a_finding():
    missing = _p(
        1,
        "Invented flow",
        4,
        _book_missing="BOOK-9",
        action="Book missing: BOOK-9 (clause not named by the reviewer).",
    )
    question = _p(
        2,
        "Invented flow",
        4,
        rule_book="STD-1",
        clause="4.1",
        rule_text="invented rule",
        action="Contractor to state it.",
    )
    alone = _p(3, "Invented speed", 4, _book_missing="BOOK-9")
    got = crs_comments.group([missing, question, alone])
    assert [(c["name"], c["member_ids"]) for c in got] == [
        ("Invented flow", ["p2"])
    ]  # the comment holds only the finding
    assert _aside([missing, question, alone]) == {
        crs_no_finding.KIND_BOOK_NOT_HELD: ["p1", "p3"]
    }


def test_a_line_given_no_rule_text_is_not_a_comment_but_a_general_note_and_a_line_with_rule_words_are():
    empty = _ai(
        1,
        "Invented sizing",
        4,
        {"ai_verdict": "Query", "requirement": None, "clause_quote": None},
        rule_book="STD-1",
    )
    general = _p(
        2,
        "Invented note",
        4,
        source="ai_review",
        _line={"general": True, "item_id": "G-1"},
    )
    worded = _ai(
        3,
        "Invented testing",
        4,
        {"ai_verdict": "Query", "requirement": "The test shall be witnessed."},
        rule_book="STD-1",
    )
    pts = [empty, general, worded]
    assert {i for c in crs_comments.group(pts) for i in c["member_ids"]} == {"p2", "p3"}
    assert _aside(pts) == {crs_no_finding.KIND_NO_RULE_TEXT: ["p1"]}


def _held_check(i, name, detail, *, code="other", evidence="12.5", **f) -> dict:
    finding = {"origin": "datasheet_check", "compliance_status": "NEEDS_ENGINEER_REVIEW", "hold_reason_code": code, "finding": detail,
               "contractor_evidence_text": evidence, **f}  # fmt: skip
    return _p(i, name, 4, _finding=finding, action=detail)


def test_a_check_that_read_the_value_compliant_is_ticked_never_a_comment_unless_the_value_is_open():
    held = untrusted_value.hold_results(
        [
            {
                "status": "COMPLIANT",
                "fact_id": "f1",
                "rule_id": "x",
                "detail": "Invented value is stated.",
            }
        ],
        [
            {
                "id": "f1",
                "field_label": "Invented field",
                "reading_conflict": "two readings differ",
            }
        ],
        {"roles": {}},
        None,
    )[0]  # the writer's own words: the reader below can never drift from them
    read_met = _held_check(1, "Invented ratio", held["detail"])
    unproven = _held_check(
        2,
        "Invented body",
        "Invented body is stated.",
        code="rule_not_proven",
        rule_said="COMPLIANT",
    )
    deferred = _held_check(
        3, "Invented temperature", held["detail"], code="deferred_marker"
    )
    marked = _held_check(
        4, "Invented pressure", held["detail"], evidence="By Contractor"
    )
    not_met = _held_check(
        5, "Invented density", held["detail"].replace("COMPLIANT", "NON_COMPLIANT")
    )
    pts = [read_met, unproven, deferred, marked, not_met]
    assert _aside(pts) == {crs_no_finding.KIND_CODE_READ_MET: ["p1", "p2"]}
    assert {i for c in crs_comments.group(pts) for i in c["member_ids"]} == {
        "p3",
        "p4",
        "p5",
    }


def test_a_met_point_is_shown_where_met_lines_belong_unless_it_answers_the_same_rule_as_the_finding():
    rule_a = {"rule_book": "STD-1", "clause": "4.1", "rule_text": "invented rule A"}
    question = _p(1, "Invented casing", 4, **rule_a)
    met_other = _p(
        2,
        "Invented casing",
        5,
        rule_book="STD-1",
        clause="4.2",
        rule_text="invented rule B",
        pill="Met · one reader",
    )
    met_same = _p(3, "Invented casing", 5, pill="Met · one reader", **rule_a)
    pts = [question, met_other, met_same]
    got = crs_comments.group(pts)
    assert [c["member_ids"] for c in got] == [
        ["p1", "p3"]
    ]  # the same rule stays: a disagreement is never hidden
    assert _aside(pts) == {words.KIND_NOTHING_TO_CHANGE: ["p2"]}
    assert sum(c["n_points"] for c in got) + sum(
        len(v) for v in _aside(pts).values()
    ) == len(pts)  # nothing dropped


def test_an_engineers_kept_point_is_never_set_apart():
    kept = _p(1, "Invented flow", 4, _book_missing="BOOK-9", decision={"state": "keep"})
    assert crs_no_finding.kind_of(kept) is None


# ------------------------------------------------------------------------------------------------ W-D7: where the text sits


def test_a_contents_or_reference_list_entry_is_never_a_requirement_and_a_real_requirement_never_lost():
    nar = rule_text_place.not_a_requirement
    assert (
        nar("8 Invented Requirements", chunk=("toc", None, None))
        == rule_text_place.CONTENTS
    )
    assert (
        nar(
            "ISO 12345 Invented valves", chunk=("prose", "2 Normative references", None)
        )
        == rule_text_place.REFERENCE_LIST
    )
    assert (
        nar("ISO 12345 Invented valves", chunk=("prose", None, "Part 1 > References"))
        == rule_text_place.REFERENCE_LIST
    )
    listed = "Invented References API 9991 Invented pumps; ISO 12345 Invented seals; ASTM A999 Invented steel"
    assert nar(listed) == rule_text_place.REFERENCE_LIST
    # a list the reader cut that runs on into a legend with a requirement word: it OPENS in the list, so it is the list
    assert (
        nar(listed + " Yes (Y) the part is required to be bought from a listed maker")
        == rule_text_place.REFERENCE_LIST
    )
    # NEVER LOST: a requirement word wherever the chunk sits; a requirement that names other books after its "shall"
    assert (
        nar("The relief valve shall be sized to ISO 12345.", chunk=("toc", None, None))
        is None
    )
    assert (
        nar("Valves shall be tested. References: API 9991 and ISO 12345 apply.") is None
    )
    assert nar("Invented pump curve", chunk=("prose", "4 Design", None)) is None
    assert (
        nar("API 9991 Invented pumps") is None
    )  # one citation, no heading: not recognised from the text alone


def test_a_quote_taken_from_a_contents_page_is_a_contents_entry():
    conn = _db()
    conn.execute(
        "INSERT INTO chunks VALUES ('c1', 'b1', 1, 1, NULL, 'toc', '1 Scope .... 2\n8 Invented Requirements .... 9', NULL)"
    )
    conn.execute(
        "INSERT INTO chunks VALUES ('c2', 'b1', 9, 9, '8 Invented Requirements', 'prose', 'Invented Requirements apply.', NULL)"
    )
    assert (
        rule_text_place.not_a_requirement(
            "Invented Requirements", conn=conn, book_id="b1", page=1
        )
        == rule_text_place.CONTENTS
    )
    assert (
        rule_text_place.not_a_requirement(
            "Invented Requirements", conn=conn, book_id="b1", page=9
        )
        is None
    )


def test_mark_sets_a_contents_rule_apart_with_honest_words():
    conn = _db()
    conn.execute("INSERT INTO chunks VALUES ('c1', 'b1', 2, 2, NULL, 'toc', 'x', NULL)")
    conn.execute(
        "INSERT INTO standard_requirements VALUES ('r1', 'Invented heading', 'Invented heading', 'c1')"
    )
    p = _p(1, "Invented other", 4, rule_book="STD-1", _finding={"requirement_id": "r1", "requirement_source_text": "Invented heading"},
           action="Clarification requested: please confirm Invented other.")  # fmt: skip
    crs_no_finding.mark(conn, [p], "paper")
    assert p["_not_a_requirement"] == rule_text_place.CONTENTS and p[
        "action"
    ].startswith("Nothing to ask: the rule's text is a contents")
    assert _aside([p]) == {crs_no_finding.KIND_NOT_A_REQUIREMENT: ["p1"]}
    hidden = _p(
        2, "Invented other", 4, _finding={"requirement_id": "r1"}, action="kept"
    )  # a book the caller may not read: untouched
    crs_no_finding.mark(conn, [hidden], "paper")
    assert hidden["action"] == "kept" and "_not_a_requirement" not in hidden


# ------------------------------------------------------------------------------------------------ W-D8: one source, said once


def test_the_clause_column_and_the_action_name_one_clause():
    row = {"standard_reference": "ISO 99999 cl. UG-99(g) (p.12)"}
    assert (
        content.rule_ref(row, {"standard_clause": "7.77"})["clause"] == "UG-99(g)"
    )  # the reference the action prints wins
    assert (
        content.rule_ref(
            {"standard_reference": "ISO 99999 (p.12)"}, {"standard_clause": "7.77"}
        )["clause"]
        == "7.77"
    )
    assert (
        content.rule_ref(
            {"standard_reference": "ISO 99999 4.1"}, {"standard_clause": "4.1"}
        )["clause"]
        == ""
    )  # said once


def test_a_repeated_point_is_listed_once_with_its_count_and_an_empty_action_says_none_recorded():
    lead = _p(1, "Invented seal", 4, action="Contractor to state it.")
    same = [
        _p(
            i,
            "Invented seal",
            4,
            rule_book="STD-1",
            clause="6.1",
            action="Engineer to check.",
        )
        for i in (2, 3, 4)
    ]
    c = crs_comments.group([lead, *same])[0]
    note = crs_one.comment_note(c, [lead, *same])
    assert note.count("Also:") == 1 and "(3 points say this)" in note
    assert (
        crs_one.full_texts(_p(5, "Invented seal", 4, action=None))["action"]
        == "none recorded (Question)"
    )


def test_two_ai_lines_on_one_verified_paper_label_are_one_comment():
    a = _ai(
        1,
        "INVENTED FLOW",
        4,
        {"source": "rule", "field": "INVENTED FLOW", "requirement": "rule one"},
        rule_book="STD-1",
        clause="4.1",
        rule_text="rule one",
    )
    b = _ai(
        2,
        "INVENTED FLOW",
        4,
        {"source": "rule", "field": "INVENTED FLOW", "requirement": "rule two"},
        rule_book="STD-1",
        clause="6.7",
        rule_text="rule two",
    )
    c = _ai(
        3,
        "INVENTED HEAD",
        4,
        {"source": "rule", "field": None, "requirement": "rule three"},
        rule_book="STD-1",
        clause="6.8",
        rule_text="rule three",
    )
    got = crs_comments.group([a, b, c])
    assert sorted(len(g["member_ids"]) for g in got) == [1, 2]


# ------------------------------------------------------------------------------------------------ W-D11: a form not held


def test_a_rule_that_puts_the_paper_on_a_form_it_is_not_on_says_form_not_held():
    assert crs_no_finding.forms_named(
        "Data shall be listed on forms XF-1234, Invented Sheet."
    ) == ["XF-1234"]
    named = crs_no_finding.forms_named(
        "The code shall be specified on the Data Sheet(s) XF-1100, XF-1100-M and XF-1200."
    )
    assert named == ["XF-1100", "XF-1100-M", "XF-1200"]
    assert (
        crs_no_finding.forms_named(
            "The maker shall submit a completed Form XF-77 to the owner."
        )
        == []
    )  # a deliverable, not the format
    conn = _db()
    conn.execute(
        "INSERT INTO chunks VALUES ('k1', 'paper', 1, 1, NULL, 'prose', 'DATA SHEET FOR INVENTED VALVES', NULL)"
    )
    line = {
        "source": "skill",
        "ai_verdict": "Fail",
        "clause_quote": "Data shall be listed on forms XF-1234, Invented Sheet.",
    }
    p = _ai(
        1,
        "Invented form",
        4,
        line,
        rule_book="STD-1",
        action="Contractor to confirm or justify the form.",
    )
    crs_no_finding.mark(conn, [p], "paper")
    assert p["_form_not_held"] == ["XF-1234"] and p["action"].startswith(
        "Form not held: the rule names form XF-1234"
    )
    assert _aside([p]) == {crs_no_finding.KIND_FORM_NOT_HELD: ["p1"]}
    on_it = _ai(2, "Invented form", 4, dict(line), rule_book="STD-1", action="kept")
    conn.execute(
        "INSERT INTO chunks VALUES ('k2', 'paper2', 1, 1, NULL, 'prose', 'FORM XF 1234 REV 2', NULL)"
    )
    crs_no_finding.mark(
        conn, [on_it], "paper2"
    )  # the paper IS on the form: nothing changes
    assert on_it["action"] == "kept"
    held = _ai(3, "Invented form", 4, dict(line), rule_book="STD-1", action="kept")
    conn.execute("INSERT INTO documents VALUES ('d9', 'XF-1234 blank form.pdf')")
    crs_no_finding.mark(
        conn, [held], "paper"
    )  # the library holds the form: it can be checked, nothing changes
    assert held["action"] == "kept"


@pytest.fixture(autouse=True)
def _vocabulary():
    rule_text_place.reload_vocabulary()
    yield
