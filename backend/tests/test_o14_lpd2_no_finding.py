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


def test_a_held_check_is_never_set_apart_only_code_on_a_trusted_reading_makes_a_met():
    """Lead (review of PR #1889): a value "read compliant" on a reading in conflict, or under a rule not yet proven, is not proven by
    code: it stays a question."""
    held = untrusted_value.hold_results(
        [{"status": "COMPLIANT", "fact_id": "f1", "rule_id": "x", "detail": "Invented value is stated."}],
        [{"id": "f1", "field_label": "Invented field", "reading_conflict": "two readings differ"}], {"roles": {}}, None,
    )[0]  # fmt: skip
    conflict = _held_check(1, "Invented ratio", held["detail"])
    unproven = _held_check(
        2,
        "Invented body",
        "Invented body is stated.",
        code="rule_not_proven",
        rule_said="COMPLIANT",
    )
    pts = [conflict, unproven]
    assert _aside(pts) == {}
    assert {i for c in crs_comments.group(pts) for i in c["member_ids"]} == {"p1", "p2"}


def _missing(i, name, **f) -> dict:
    row = {
        "row_kind": f.pop("row_kind", "datasheet_check"),
        "comment": f.pop(
            "comment", "Invented own ask. Contractor to provide the value."
        ),
    }
    return _p(i, name, 4, _book_missing="BOOK-9", _book_missing_words="Book missing: BOOK-9 (clause not named by the reviewer)",
              action="Book missing: BOOK-9 (clause not named by the reviewer). The rule cannot be checked until the book is held; engineer to check.",
              _row=row, _finding=f)  # fmt: skip


def test_any_ask_or_concern_in_the_points_own_record_stays_a_comment_whatever_the_book_state():
    """Lead (reviews of PR #1889): the point's own record decides FIRST. Information missing, two values that conflict, an engineering
    check's ask, a held check, a standard not cited, a "not compliant" record: each stays a comment; only an EMPTY record is set apart.
    An open request says its own ask before the book."""
    placeholder = _missing(1, "Invented speed", compliance_status="MISSING_INFORMATION")
    two_values = _missing(
        2,
        "Invented flow",
        compliance_status="NEEDS_ENGINEER_REVIEW",
        hold_reason_code="field_several_values",
    )
    eng_check = _missing(
        3,
        "Invented guard",
        row_kind="ai_engineering_check",
        comment="Contractor to confirm the guard material.",
    )
    held = _missing(
        4,
        "Invented head",
        compliance_status="NEEDS_ENGINEER_REVIEW",
        hold_reason_code="rule_not_proven",
    )
    not_cited = _missing(
        5,
        "STD-9",
        row_kind="standard_not_cited",
        comment="Contractor did not reference STD-9.",
    )
    not_compliant = _missing(
        6, "Invented seal", row_kind="clause_review", reason_code="NON_COMPLIANT"
    )
    empty = _missing(7, "Invented tag", row_kind="clause_review")
    pts = [placeholder, two_values, eng_check, held, not_cited, not_compliant, empty]
    crs_no_finding.mark(_db(), pts, "paper", frozenset())
    assert {i for c in crs_comments.group(pts) for i in c["member_ids"]} == {
        f"p{n}" for n in range(1, 7)
    }
    assert _aside(pts) == {crs_no_finding.KIND_BOOK_NOT_HELD: ["p7"]}
    assert placeholder["action"] == (
        "Invented own ask. Contractor to provide the value (Book missing: BOOK-9 (clause not named by the reviewer): not checked against it.)"
    )
    assert eng_check["action"].startswith(
        "Contractor to confirm the guard material (Book missing"
    )


def test_an_ai_fail_absent_or_any_ai_words_on_a_rule_not_yet_approved_stay_a_comment():
    """Lead (last review of PR #1889): any AI Fail, not met or absent stays a comment, rule approved or not; so does any AI line that
    wrote words to the contractor and did not judge the rule met. Only "met" or a line with no words is set apart."""
    na = {"other_kind": words.KIND_UNAPPROVED}
    fail = _ai(
        1,
        "Invented seal",
        8,
        {"ai_verdict": "Fail", "reason_code": "not_met", "comment": "Provide it."},
        **na,
    )
    absent = _ai(
        2, "Invented plan", 8, {"ai_verdict": "Fail", "reason_code": "absent"}, **na
    )
    worded = _ai(
        3,
        "Invented pipe",
        8,
        {
            "ai_verdict": "Query",
            "reason_code": "not_applicable",
            "comment": "Confirm whether it applies.",
        },
        **na,
    )
    met = _ai(
        4,
        "Invented gear",
        8,
        {"ai_verdict": "Pass", "reason_code": "met", "comment": "Nothing."},
        **na,
    )
    silent = _ai(
        5,
        "Invented fire",
        8,
        {"ai_verdict": "Query", "reason_code": "not_applicable"},
        **na,
    )
    unread = _p(
        6, "Invented page", 8, other_kind=words.KIND_NOT_REVIEWED
    )  # a rule-check "not reviewed" row: no record of an ask
    pts = [fail, absent, worded, met, silent, unread]
    assert {i for c in crs_comments.group(pts) for i in c["member_ids"]} == {
        "p1",
        "p2",
        "p3",
    }
    assert _aside(pts) == {
        words.KIND_UNAPPROVED: ["p4", "p5"],
        words.KIND_NOT_REVIEWED: ["p6"],
    }
    kept = crs_comments.group(
        pts
    )  # each kept field is a QUESTION for the engineer, never a "does not apply" comment (gate G3)
    assert {c["tile"] for c in kept} == {"questions"}
    assert all(c["pill"] == f"Question · {words.KIND_UNAPPROVED}" for c in kept)


def test_a_met_point_is_shown_where_met_lines_belong_unless_it_answers_the_same_rule_as_the_finding():
    rule_a = {"rule_book": "STD-1", "clause": "4.1", "rule_text": "invented rule A"}
    verified = {"quotes_checked": {"paper": True, "clause": True}}
    question = _p(1, "Invented casing", 4, **rule_a)
    one_reader = _ai(
        2,
        "Invented casing",
        5,
        {"ai_verdict": "Pass", "reason_code": "met", "field": "Invented casing"},
        rule_book="STD-1",
        clause="4.2",
        rule_text="b",
    )
    met_same = _ai(
        3,
        "Invented casing",
        5,
        {"ai_verdict": "Pass", "reason_code": "met", "field": "Invented casing"},
        **rule_a,
    )
    proven = _p(4, "Invented casing", 7, rule_book="STD-1", clause="4.3", rule_text="c")
    two_ok = _ai(
        5,
        "Invented casing",
        6,
        {
            "ai_verdict": "Pass",
            "reason_code": "met",
            "field": "Invented casing",
            **verified,
        },
        rule_book="STD-1",
        clause="4.4",
        rule_text="d",
    )
    two_unverified = _ai(
        6,
        "Invented casing",
        6,
        {"ai_verdict": "Pass", "reason_code": "met", "field": "Invented casing"},
        rule_book="STD-1",
        clause="4.5",
        rule_text="e",
    )
    pts = [question, one_reader, met_same, proven, two_ok, two_unverified]
    got = crs_comments.group(pts)
    assert [c["member_ids"] for c in got] == [
        ["p1", "p3"]
    ]  # the same rule stays: a disagreement is never hidden
    assert _aside(pts) == {
        crs_no_finding.KIND_AI_THINKS_MET: ["p2", "p6"],
        words.KIND_NOTHING_TO_CHANGE: ["p4", "p5"],
    }
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
    # NEVER LOST (lead, review of PR #1889): a text with a requirement word is never "not a requirement", wherever it sits
    assert (
        nar(listed + " Yes (Y) the part is required to be bought from a listed maker")
        is None
    )
    assert nar("References: API 9991 and ISO 12345 shall be met for all pumps") is None
    assert (
        rule_text_place.place_of_text(listed + " Each part shall be tested.") is None
    )  # the text test on its own too
    normative = "Normative references API 9991 Invented pumps; ISO 12345 Invented seals 4.1 The set pressure shall not exceed 10 bar"
    assert (
        nar(normative) is None
        and nar(normative, chunk=("references", "2 Normative references", None)) is None
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


def test_a_contents_rule_is_noted_on_its_comment_and_every_text_of_the_line_is_read():
    """Lead (last review of PR #1889): a contents or reference-list "rule" is noted, never set apart and never "nothing to ask"; every
    text of the line is read (the book's quote AND the stored requirement): a requirement word in any of them and nothing is noted."""
    conn = _db()
    conn.execute(
        "INSERT INTO chunks VALUES ('c1', 'b1', 2, 2, NULL, 'toc', '8 Invented Heading .... 9', NULL)"
    )
    conn.execute(
        "INSERT INTO standard_requirements VALUES ('r1', 'Invented Heading', 'Invented Heading', 'c1')"
    )
    p = _p(1, "Invented other", 4, rule_book="STD-1", _finding={"requirement_id": "r1", "requirement_source_text": "Invented Heading"},
           action="Clarification requested.")  # fmt: skip
    crs_no_finding.mark(conn, [p], "paper")
    assert p["_not_a_requirement"] == rule_text_place.CONTENTS
    assert p["action"].startswith(
        "Clarification requested. (The rule's text is a contents entry"
    )
    assert _aside([p]) == {} and crs_comments.group([p])[0]["member_ids"] == ["p1"]
    line = {"source": "skill", "ai_verdict": "Query", "clause_quote": "Invented Heading", "clause_book": {"page": 2},
            "standard_document_id": "b1", "requirement": "The set pressure shall not exceed 10 bar.", "comment": "Give it."}  # fmt: skip
    worded = _ai(
        2, "Invented set", 4, line, rule_book="STD-1", action="Contractor to give it."
    )
    crs_no_finding.mark(conn, [worded], "paper")
    assert (
        worded["action"] == "Contractor to give it."
        and "_not_a_requirement" not in worded
    )
    hidden = _p(
        3, "Invented other", 4, _finding={"requirement_id": "r1"}, action="kept"
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


def test_the_not_a_comment_sheet_shows_each_lines_own_ask():
    pts = [
        _p(1, "Invented", 8, action="Engineer to look."),
        _p(2, "Invented", 8, action="Engineer to look."),
        _p(3, "Invented", 8),
    ]
    assert crs_one.aside_actions(pts) == "Engineer to look."
    assert crs_one.aside_actions(pts[2:]) == crs_one.NO_ACTION


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
    crs_no_finding.mark(conn, [p], "paper", frozenset())
    assert p["_form_not_held"] == ["XF-1234"] and p["action"].startswith(
        "Form not held: the rule names form XF-1234"
    )
    assert _aside([p]) == {} and crs_comments.group([p])[0]["member_ids"] == [
        "p1"
    ]  # still a comment: never set apart
    on_it = _ai(2, "Invented form", 4, dict(line), rule_book="STD-1", action="kept")
    conn.execute(
        "INSERT INTO chunks VALUES ('k2', 'paper2', 1, 1, NULL, 'prose', 'FORM XF 1234 REV 2', NULL)"
    )
    crs_no_finding.mark(
        conn, [on_it], "paper2"
    )  # the paper IS on the form: nothing changes
    assert on_it["action"] == "kept"
    conn.execute("INSERT INTO documents VALUES ('d9', 'XF-1234 blank form.pdf')")
    hidden = _ai(4, "Invented form", 4, dict(line), rule_book="STD-1", action="kept")
    crs_no_finding.mark(
        conn, [hidden], "paper", frozenset({"paper"})
    )  # rule 5: a file the caller may not read is never looked at
    assert hidden.get("_form_not_held") == ["XF-1234"]
    held = _ai(3, "Invented form", 4, dict(line), rule_book="STD-1", action="kept")
    crs_no_finding.mark(
        conn, [held], "paper", frozenset({"d9"})
    )  # a held form the caller may read: it can be checked, nothing changes
    assert held["action"] == "kept"


def test_a_rule_that_also_asks_something_else_stays_a_comment_with_the_form_noted():
    """Lead (review of PR #1889): only a FORM-ONLY rule becomes "Form not held"; a rule that also holds another requirement stays a
    comment for that requirement, the form part noted."""
    conn = _db()
    conn.execute(
        "INSERT INTO chunks VALUES ('k1', 'paper', 1, 1, NULL, 'prose', 'DATA SHEET FOR INVENTED PUMPS', NULL)"
    )
    quote = ("The liquid shall be identified from the table with its \u201cMaterials Code(s).\u201d The applicable material code "
             "shall be specified on the Data Sheet(s) XF-2741 and XF-2745.")  # fmt: skip
    p = _ai(
        1,
        "Invented casing",
        4,
        {"source": "rule", "clause_quote": quote},
        rule_book="STD-1",
        action="Contractor to state the code.",
    )
    crs_no_finding.mark(conn, [p], "paper", frozenset())
    assert "_form_not_held" not in p and p["_form_note"] == ["XF-2741", "XF-2745"]
    assert p["action"].startswith(
        "Contractor to state the code. (Form not held: the rule also names form XF-2741, XF-2745"
    )
    assert _aside([p]) == {} and crs_comments.group([p])[0]["member_ids"] == ["p1"]


@pytest.fixture(autouse=True)
def _vocabulary():
    rule_text_place.reload_vocabulary()
    yield
