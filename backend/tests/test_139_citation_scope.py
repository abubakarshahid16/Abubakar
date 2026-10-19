"""#139: a code cited for ONE ITEM applies through the cited clauses only, and
a standard's sentence with no datasheet field behind it is never a CRS line.

Found on a pump review (order 139): the datasheet cited a pressure-vessel code
only for its spot-radiography paragraph, and every requirement of the whole
code was checked against the pump sheet; 158 CRS lines had no datasheet page -
the standard's sentences printed as comments on the sheet. Invented standards,
clause ids and datasheet text only (rule 13: nothing here names a real
document or layout).
"""

from __future__ import annotations

import uuid

import pytest

from app import (
    comparison,
    crs_mapping,
    datasheets,
    db,
    scope_ledger,
    standard_ids,
    standards,
    subject_scope,
    submittal_review,
)
from app.config import settings

NOW = "2026-10-19T00:00:00Z"


def _qualifiers(text: str, cited: str) -> list[tuple[str, str]]:
    start = text.index(cited)
    return standard_ids.clause_qualifiers(text, start, start + len(cited))


# ------------------------------------------------------------ the citation's clauses


def test_clauses_printed_after_a_citation_are_read():
    assert _qualifiers("Hydrotest: XYZ-100 Section 4", "XYZ-100") == [("number", "4")]
    assert _qualifiers(
        "QRS 12, ZT-31 (for full examination) and ZT-32 (for spot examination) next",
        "QRS 12",
    ) == [("lettered", "ZT-31"), ("lettered", "ZT-32")]
    assert _qualifiers("XYZ-100, Articles 3 and 17", "XYZ-100") == [
        ("article", "3"),
        ("article", "17"),
    ]
    assert _qualifiers("XYZ-100 Annex B (normative)", "XYZ-100") == [("appendix", "B")]
    assert _qualifiers("XYZ-100, para. 6.3.1 and 6.4", "XYZ-100") == [
        ("number", "6.3.1"),
        ("number", "6.4"),
    ]


def test_a_clause_printed_before_a_citation_with_of_is_read():
    assert _qualifiers("Marking per clause 4.2 of XYZ-100.", "XYZ-100") == [
        ("number", "4.2")
    ]


def test_a_bare_citation_names_no_clause():
    # the whole standard is cited: a form-item number, an edition, a table
    # or an unrelated word after it is not a clause
    for text in (
        "Design to XYZ-100.",
        "XYZ-100 (6.1.2) balance",
        "XYZ-100 11 / ABC 7",
        "XYZ-100, Table 3",
        "XYZ-100 latest edition",
        "ZT-31 XYZ-100 applies",
    ):
        assert _qualifiers(text, "XYZ-100") == [], text


# --------------------------------------------------------- the gate on the standard's text

PAGES = [
    (
        1,
        "CONTENTS\nZT-30 General Rules\nZT-31 Full Examination\nZT-32 Spot Examination\n",
    ),
    (
        2,
        "ZT-30\nGENERAL RULES\nEach joint shall be marked with the welder number.\n"
        "ZT-31\nFULL EXAMINATION\nEvery butt joint shall be examined over its full length.\n",
    ),
    (
        3,
        "ZT-32\nSPOT EXAMINATION\n(a) One spot shall be examined for each twenty metres of weld.\n"
        "(b) A rejected spot shall be followed by two further spots in the same in-\n"
        "crement of weld.\nZT-31 - ZT-32\n",
    ),
    (
        4,
        "ZT-33\nHARDNESS TESTING\nHardness shall not exceed the value in the material table.\n",
    ),
]


def _req(rid, page, text, clause=None):
    return {
        "id": rid,
        "standard_document_id": "std",
        "page": page,
        "clause": clause,
        "requirement_text": text,
        "source_text": text,
    }


GENERAL = _req("general", 2, "Each joint shall be marked with the welder number.")
FULL = _req("full", 2, "Every butt joint shall be examined over its full length.")
SPOT = _req("spot", 3, "(a) One spot shall be examined for each twenty metres of weld.")
SPOT_B = _req(
    "spot_b",
    3,
    "(b) A rejected spot shall be followed by two further spots in the same "
    "increment of weld.",
)
HARD = _req("hard", 4, "Hardness shall not exceed the value in the material table.")
OTHER = {**HARD, "id": "other", "standard_document_id": "another"}


def _gate(clauses, reqs=(GENERAL, FULL, SPOT, SPOT_B, HARD, OTHER)):
    return subject_scope.citation_gate(
        list(reqs),
        cited={"std": {"clauses": clauses, "pages": [5]}}
        if clauses is not None
        else {},
        standard_labels={"std": "QRS 12"},
        pages_of=lambda sid: PAGES,
    )


def test_a_cited_clause_narrows_its_standard_to_that_clause():
    out = _gate([("lettered", "ZT-32")])
    # the cited paragraph (both of its items, one split over a line break),
    # and every requirement of any other standard
    assert [r["id"] for r in out["kept"]] == ["spot", "spot_b", "other"]
    assert {i["requirement"]["id"] for i in out["items"]} == {"general", "full", "hard"}
    assert all(i["code"] == "outside_cited_clauses" for i in out["items"])
    assert "cites QRS 12 only for ZT-32 (page 5)" in out["items"][0]["detail"]
    [summary] = out["summary"]
    assert (
        summary["kept"] == 2
        and summary["not_applied"] == 3
        and summary["clauses_not_found"] == []
    )
    assert out["items"][0]["code"] in scope_ledger.REASONS


def test_no_cited_clause_leaves_every_requirement_a_check():
    out = _gate(None)
    assert [r["id"] for r in out["kept"]] == [
        "general",
        "full",
        "spot",
        "spot_b",
        "hard",
        "other",
    ]
    assert out["items"] == []


def test_a_clause_the_standard_does_not_show_narrows_nothing():
    # a tag or a typo next to the citation is not a clause of this standard
    out = _gate([("lettered", "PX-101")])
    assert len(out["kept"]) == 6 and out["items"] == []
    assert out["summary"][0]["clauses_not_found"] == ["PX-101"]


def test_a_stored_clause_number_inside_the_cited_clause_is_kept():
    stray = _req(
        "stray",
        9,
        "Words that appear on no page of the standard at all.",
        clause="ZT-32(c)",
    )
    out = _gate([("lettered", "ZT-32")], reqs=(stray, HARD))
    assert [r["id"] for r in out["kept"]] == ["stray"]


def test_a_requirement_that_cannot_be_placed_on_a_page_touching_the_clause_stays():
    short = _req("short", 3, "See (a).")  # too short to place for certain
    out = _gate([("lettered", "ZT-32")], reqs=(short,))
    assert [r["id"] for r in out["kept"]] == ["short"]


def test_numbered_clauses_end_at_the_next_clause_of_their_level():
    pages = [
        (
            1,
            "4 Design\n4.1 Pressure\nThe design pressure shall be stated.\n"
            "4.2 Temperature\nThe design temperature shall be stated.\n"
            "4.2.1 Minimum\nThe minimum metal temperature shall be stated.\n"
            "5 Testing\nThe test pressure shall be recorded.\n",
        )
    ]
    reqs = [
        _req(k, 1, t)
        for k, t in (
            ("p", "The design pressure shall be stated."),
            ("t", "The design temperature shall be stated."),
            ("m", "The minimum metal temperature shall be stated."),
            ("x", "The test pressure shall be recorded."),
        )
    ]
    out = subject_scope.citation_gate(
        reqs,
        cited={"std": {"clauses": [("number", "4.2")], "pages": []}},
        standard_labels={},
        pages_of=lambda sid: pages,
    )
    assert [r["id"] for r in out["kept"]] == ["t", "m"]


# ------------------------------------------------------------- end to end on a review


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "citation_scope.sqlite")
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, filename, role, pages, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',?,?)",
            (doc_id, filename, f"sha-{doc_id}", filename, len(pages), NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        for page, text in pages:
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (doc_id, page, text, len(text)),
            )
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
                "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,?,?,?,NULL,'prose',"
                "?,1,?,1)",
                (
                    f"{doc_id}-{page}",
                    doc_id,
                    filename,
                    page,
                    page,
                    page,
                    text,
                    f"h-{doc_id}-{page}",
                ),
            )


def _review(datasheet_line: str):
    _doc("std", "XYZ-100.pdf", "COMPANY_STANDARD", PAGES, document_number="XYZ-100")
    _doc(
        "sub",
        "sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        [(1, f"WELD EXAMINATION\n{datasheet_line}\nDESIGN PRESSURE 10 barg\n")],
        equipment_type="Widget",
    )
    ids = {}
    for key, req in (("full", FULL), ("spot", SPOT), ("hard", HARD)):
        ids[key] = standards.create_requirement(
            standard_document_id="std",
            chunk_id=f"std-{req['page']}",
            clause=None,
            page=req["page"],
            requirement_text=req["requirement_text"],
            source_text=req["source_text"],
            structured={"requirement_type": "statement"},
        )["id"]
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Design pressure",
        raw_value="10 barg",
        page=1,
    )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'pending',?,?)",
            (run, "sub", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_method,included,created_at) VALUES (?,?,?,'referenced',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    result = comparison.run_comparison(
        run, allowed_document_ids=frozenset({"std", "sub"})
    )
    return (
        result,
        {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)},
        ids,
    )


def test_a_review_applies_only_the_cited_clause(temp_storage):
    result, stored, ids = _review(
        "Spot examination to XYZ-100, ZT-32 (for spot examination)"
    )
    assert stored[ids["spot"]]["state"] == scope_ledger.CHECKED
    for key in ("full", "hard"):
        assert stored[ids[key]]["state"] == scope_ledger.DOES_NOT_APPLY
        assert stored[ids[key]]["reason_code"] == "outside_cited_clauses"
        # a requirement outside the cited clause never reaches a finding
        assert not any(f.get("requirement_id") == ids[key] for f in result["findings"])
    [summary] = result["requirement_split"]["cited_clauses"]
    assert summary["clauses"] == ["ZT-32"] and summary["not_applied"] == 2


def test_a_review_of_a_bare_citation_applies_the_whole_standard(temp_storage):
    _result, stored, ids = _review("Examination to XYZ-100")
    assert all(
        stored[ids[k]]["state"] == scope_ledger.CHECKED
        for k in ("full", "spot", "hard")
    )


# ------------------------------------------- a standard's sentence is not a datasheet field


def _finding(fid, **extra):
    return {
        "id": fid,
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "standard_name": "XYZ-100.pdf",
        "standard_clause": "ZT-40",
        "standard_page": 7,
        "severity": "minor",
        "requirement_source_text": f"The fabricator shall keep record {fid}.",
        "ai_rationale": "ambiguous_match: more than one submitted field is named inside this "
        "requirement (fabricator, fabricator); no value was chosen",
        **extra,
    }


def test_a_question_with_no_datasheet_field_is_a_review_note_not_a_crs_line():
    unplaced = _finding("u1")
    on_sheet = _finding(
        "p1", fact_id="fact-1", contractor_page=2, matched_phrase="Fabricator"
    )
    rows = crs_mapping.build_crs_rows([unplaced, on_sheet], [], "sheet.pdf")
    assert [r["finding_id"] for r in rows] == ["p1"]
    assert all((r["page_section"] or "").startswith("p.") for r in rows)
    notes = crs_mapping.build_review_notes([unplaced, on_sheet], [])
    [note] = [n for n in notes if n["note"] == crs_mapping.NOTE_FIELD_NOT_IDENTIFIED]
    assert note["count"] == 1 and note["standard"] == "XYZ-100.pdf"
    assert "XYZ-100 cl. ZT-40 (p.7)" in note["detail"]


def test_an_engineer_confirmed_question_stays_their_crs_line():
    confirmed = _finding("c1", confirmed_by="eng-1")
    rows = crs_mapping.build_crs_rows([confirmed], [], "sheet.pdf")
    assert [r["finding_id"] for r in rows] == ["c1"]
    assert not [
        n
        for n in crs_mapping.build_review_notes([confirmed], [])
        if n["note"] == crs_mapping.NOTE_FIELD_NOT_IDENTIFIED
    ]


def test_a_missing_value_is_still_a_crs_line_never_dropped():
    # "not mentioned" is a comment to the contractor, never compliant and never hidden
    missing = {
        **_finding("m1"),
        "compliance_status": "MISSING_INFORMATION",
        "ai_rationale": "",
    }
    rows = crs_mapping.build_crs_rows([missing], [], "sheet.pdf")
    assert [r["row_kind"] for r in rows] == [crs_mapping.ROW_KIND_MISSING_INFORMATION]
