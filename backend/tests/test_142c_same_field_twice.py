"""Order 142 fix C: one datasheet field read twice (two pages, or twice on one
page) is ONE field, not "more than one submitted field is named".

The old tie rule took any two equally long matches as a tie unless they were
the same field about different named items, so a field captured twice with the
same value went to the engineer as AMBIGUOUS_MATCH with a rationale repeating
one name ("X, X"). Now the copies are compared with each other: same value (or
all blank) is one field, the other copies are named; different values stay an
engineer's question, each copy named once with its page and value - and so
does a value on one copy beside a blank ("to be provided") on another.

Invented field names and values only (CLAUDE.md rules 1 and 3).
Mutation proofs: M1185-01 .. M1185-07 (scripts/mutations/pr1185_same_field_twice.py).
"""

from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, standards, submittal_review
from app.config import settings

NOW = "2026-10-19T00:00:00Z"
SUBJECT = "the flange rating shall be at least"


def requirement(subject=SUBJECT, **over):
    base = {
        "requirement_type": "numeric_limit",
        "value": 300.0,
        "unit": "psi",
        "raw_value": "300",
        "raw_unit": "psi",
        "subject": subject,
        "operator": ">=",
    }
    return {**base, **over}


def fact(field_name, fid, *, page=1, value=300.0, raw="300", unit="psi", **over):
    base = {
        "id": fid,
        "field_name": field_name,
        "field_label": field_name,
        "page": page,
        "normalized_value": value,
        "normalized_unit": unit,
        "raw_value": raw,
        "raw_unit": unit,
    }
    return {**base, **over}


def blank(field_name, fid, *, page=1, **over):
    return {
        "id": fid,
        "field_name": field_name,
        "field_label": field_name,
        "page": page,
        "normalized_value": None,
        "normalized_unit": None,
        "raw_value": None,
        "raw_unit": None,
        "is_blank": 1,
        **over,
    }


def match(facts, req=None):
    return comparison.match_by_containment(req or requirement(), facts)


# ------------------------------------------------------------ the five cases


def test_same_field_twice_with_the_same_value_is_one_field():
    got = match(
        [fact("flange rating", "a", page=2), fact("flange rating", "b", page=5)]
    )

    assert got["reason"] is None
    assert got["method"] == comparison.METHOD_CONTAINMENT
    assert got["fact"]["id"] == "a"  # first by (page, label)
    assert got["candidates"] == ["flange rating (page 5)"]  # the other copy, named
    assert got["same_field_copies"] is True


def test_the_same_value_spelled_differently_is_still_the_same_value():
    got = match(
        [
            fact("flange rating", "a", page=2, raw="300", unit="psi"),
            fact("flange rating", "b", page=5, raw="300.0", unit="PSI"),
        ]
    )

    assert got["reason"] is None and got["fact"]["id"] == "a"


def test_same_field_twice_both_blank_is_one_blank_field():
    got = match(
        [blank("flange rating", "b", page=5), blank("flange rating", "a", page=2)]
    )

    assert got["reason"] is None
    assert got["fact"]["id"] == "a"
    assert got["method"] == comparison.METHOD_CONTAINMENT
    assert got["candidates"] == ["flange rating (page 5)"]


def test_one_filled_copy_and_a_blank_copy_uses_the_filled_one():
    got = match(
        [fact("flange rating", "a", page=5), blank("flange rating", "b", page=2)]
    )
    # the numeric pass never takes a blank while a number hits, so the
    # blank is not a copy here at all
    assert got["reason"] is None and got["fact"]["id"] == "a"

    both = comparison.match_by_containment(
        requirement(),
        [
            fact("flange rating", "a", page=5),
            fact("flange rating", "c", page=6),
            blank("flange rating", "b", page=2),
        ],
    )
    assert both["reason"] is None and both["fact"]["id"] == "a"


def test_same_field_twice_with_different_values_is_still_an_engineer_question():
    got = match(
        [
            fact("flange rating", "a", page=2, value=150.0, raw="150"),
            fact("flange rating", "b", page=5, value=300.0, raw="300"),
        ]
    )

    assert got["fact"] is None
    assert got["reason"] == comparison.AMBIGUOUS_MATCH
    assert got["same_field_copies"] is True
    # one entry per copy, with its page and value; the name is not repeated bare
    assert got["candidates"] == [
        "flange rating (page 2): 150 psi",
        "flange rating (page 5): 300 psi",
    ]


def test_the_same_number_in_a_different_unit_is_a_different_value():
    got = match(
        [
            fact("flange rating", "a", page=2, value=300.0, raw="300", unit="psi"),
            fact("flange rating", "b", page=5, value=300.0, raw="300", unit="bar"),
        ]
    )

    assert got["fact"] is None and got["reason"] == comparison.AMBIGUOUS_MATCH


def test_categorical_copies_compare_by_their_words():
    def cat(fid, page, words):
        return {
            "id": fid,
            "field_name": "casing material",
            "field_label": "Casing material",
            "page": page,
            "field_value": words,
            "raw_value": None,
            "raw_unit": None,
        }

    req = requirement(
        "the casing material shall be carbon steel", requirement_type="statement"
    )
    same = comparison.match_statement(
        req, [cat("a", 2, "Cast iron"), cat("b", 5, "cast  IRON")]
    )
    differ = comparison.match_statement(
        req, [cat("a", 2, "Cast iron"), cat("b", 5, "Carbon steel")]
    )

    assert same["reason"] is None and same["fact"]["id"] == "a"
    assert differ["fact"] is None and differ["reason"] == comparison.AMBIGUOUS_MATCH
    assert differ["candidates"] == [
        "Casing material (page 2): Cast iron",
        "Casing material (page 5): Carbon steel",
    ]


def test_a_value_beside_a_blank_copy_is_an_engineer_question_on_the_statement_path():
    # the statement path takes blanks and filled copies together: one copy
    # states the rating, another leaves it to be provided - not one field
    req = requirement(
        "nozzle flanges shall have a minimum pressure rating of class 300",
        requirement_type="statement",
        raw_value="Class 300",
        raw_unit=None,
        value=None,
        unit=None,
    )
    stated = {
        "id": "a",
        "field_name": "flange rating",
        "field_label": "flange rating",
        "page": 2,
        "raw_value": "Class 300",
        "raw_unit": None,
    }
    open_copy = {
        **stated,
        "id": "b",
        "page": 5,
        "raw_value": "By vendor",
        "is_blank": 1,
    }
    got = comparison.match_statement(req, [stated, open_copy])

    assert got["fact"] is None and got["reason"] == comparison.AMBIGUOUS_MATCH
    assert got["same_field_copies"] is True
    assert got["candidates"] == [
        "flange rating (page 2): Class 300",
        "flange rating (page 5): left blank",
    ]


def test_a_minimum_and_a_maximum_of_the_same_number_are_not_one_copy():
    # ">= 10" and "<= 10" share one normalised number but are two statements
    got = match(
        [
            fact("flange rating", "a", page=1, value=10.0, raw=">= 10", unit="bar"),
            fact("flange rating", "b", page=2, value=10.0, raw="<= 10", unit="bar"),
        ]
    )

    assert got["fact"] is None and got["reason"] == comparison.AMBIGUOUS_MATCH
    assert got["same_field_copies"] is True

    same = match(
        [
            fact("flange rating", "a", page=1, value=10.0, raw=">= 10", unit="bar"),
            fact("flange rating", "b", page=2, value=10.0, raw="≥ 10", unit="bar"),
        ]
    )
    assert same["reason"] is None and same["fact"]["id"] == "a"


def test_two_table_columns_with_the_same_number_are_not_one_copy():
    got = match(
        [
            fact("flange rating", "a", page=2, value_column="maximum"),
            fact("flange rating", "b", page=2, value_column="rated"),
        ]
    )

    assert got["fact"] is None and got["reason"] == comparison.AMBIGUOUS_MATCH


def test_two_copies_with_different_values_are_never_picked_between():
    got = match(
        [
            fact("flange rating", "a", page=2, value=300.0, raw="300"),
            fact("flange rating", "b", page=2, value=300.5, raw="300.5"),
        ]
    )

    assert got["fact"] is None and got["reason"] == comparison.AMBIGUOUS_MATCH


def test_two_different_field_names_of_equal_length_stay_ambiguous_with_old_wording():
    got = match(
        [fact("shell thickness", "a"), fact("crown thickness", "b")],
        requirement("the shell thickness and the crown thickness shall exceed"),
    )

    assert got["fact"] is None and got["reason"] == comparison.AMBIGUOUS_MATCH
    assert got["candidates"] == ["crown thickness", "shell thickness"]
    assert "same_field_copies" not in got


def test_the_same_field_about_different_items_keeps_the_per_item_behaviour():
    req = requirement("the nozzle size shall be at least")
    got = match(
        [
            fact("n1 size", "a", equipment_tag="N1"),
            fact("n2 size", "b", equipment_tag="N2"),
        ],
        req,
    )

    assert got["reason"] is None and got["fact"] is not None
    assert [f["id"] for f in got["items"]] == ["a", "b"]
    assert "same_field_copies" not in got


# ------------------------------------------------- through the findings builder


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "c142.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, filename, role, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',9,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
    return doc_id


def _chunk(chunk_id, doc_id, page):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
            "section,kind,text,token_count,content_hash,retrievable)"
            " VALUES (?,?,?,?,?,?,NULL,'prose','x',1,?,1)",
            (chunk_id, doc_id, "f.pdf", page, page, page, f"h-{chunk_id}"),
        )
    return chunk_id


def _run_with_copies(copies):
    """A review whose sheet states 'Flange rating' once per (page, raw value)."""
    spec = _doc("spec", "SPEC-X.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", spec, 1)
    req_id = standards.create_requirement(
        standard_document_id=spec,
        chunk_id=sc,
        clause="5.1",
        page=1,
        requirement_text="The flange rating shall be at least 300 psi.",
        source_text="The flange rating shall be at least 300 psi.",
        structured={
            "requirement_type": "numeric_limit",
            "operator": ">=",
            "value": 300.0,
            "unit": "psi",
            "raw_value": "300",
            "raw_unit": "psi",
            "field": "flange rating",
            "subject": "flange rating",
        },
    )["id"]
    for page, raw in copies:
        datasheets.create_fact(
            submittal_document_id=sub,
            chunk_id=_chunk(f"fc{page}", sub, page),
            field_label="Flange rating",
            raw_value=raw,
            page=page,
        )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'pending',?,?)",
            (run, sub, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,"
            "standard_document_id,selection_method,included,created_at)"
            " VALUES (?,?,?,'rule',1,?)",
            (str(uuid.uuid4()), run, spec, NOW),
        )
    scope = frozenset({spec, sub})
    comparison.run_comparison(run, allowed_document_ids=scope)
    return [
        f
        for f in comparison.list_findings(run, allowed_document_ids=scope)
        if f["requirement_id"] == req_id
    ]


def test_end_to_end_a_field_read_twice_with_one_value_is_compared(temp_storage):
    findings = _run_with_copies([(2, "350 psi"), (5, "350 psi")])

    assert len(findings) == 1
    got = findings[0]
    assert got["compliance_status"] == comparison.COMPLIANT
    assert comparison.AMBIGUOUS_MATCH not in (got["finding"] or "")
    # the other copy is named, on the rationale (the finding's own text is the
    # reason only: order 159 keeps the program's pairing note off it)
    assert "page 5" in (got["ai_rationale"] or "")


def test_end_to_end_a_field_read_twice_with_two_values_goes_to_the_engineer(
    temp_storage,
):
    findings = _run_with_copies([(2, "350 psi"), (5, "250 psi")])

    assert len(findings) == 1
    got = findings[0]
    assert got["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    text = got["finding"] or ""
    assert comparison.AMBIGUOUS_MATCH in text
    assert "read more than once, with different values" in text
    assert "(page 2): 350 psi" in text and "(page 5): 250 psi" in text
    assert "more than one submitted field is named" not in text
