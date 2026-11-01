"""#1482 TRANSMITTAL KIT. INVENTED transmittals, held documents and required-submissions list
only (CLAUDE.md rules 1 and 3: the real list is client data and never enters a test). No model,
no socket. Each test fails without the code it names.
"""

from __future__ import annotations

import json

import pytest

from app import access, crs_mapping, db, procedure_text, spec_kit, transmittal_kit
from app.config import settings
from tests.test_1479_spec_kit import _doc, _rows
from tests.test_b3_page_ledger import _review, temp_storage  # noqa: F401 - autouse


@pytest.fixture(autouse=True)
def _resolver():
    yield
    access.set_user_resolver(None)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "transmittal_kit_enabled", True)


HEADER = (
    "TRANSMITTAL\n"
    "Transmittal No: TRN-0001\n"
    "Date: 01/02/2026\n"
    "From: Invented Contractor Ltd\n"
    "To: Invented Owner Co\n"
    "Purpose of Issue: For review\n"
)
TABLE = (
    "Doc No        Title             Rev    Sheets\n"
    "ABC-100-001   Pump datasheet    3      2\n"
    "ABC-100-002   Valve datasheet   1      1\n"
)
HELD = (("ABC-100-001", "3", 2), ("ABC-100-002", "1", 1))


def _transmittal(header=HEADER, table=TABLE):
    _doc("doc_tr", [header + "\n" + table], "transmittal", number="TRN-0001")
    return "doc_tr"


def _held(doc_id, number, rev, pages):
    cover = f"Document No: {number}\nRevision: {rev}\nInvented datasheet cover"
    _doc(
        doc_id,
        [cover] + [f"page {n}" for n in range(2, pages + 1)],
        "datasheet",
        number=number,
    )
    return doc_id


def _world(header=HEADER, table=TABLE, held=HELD, extra=()):
    sub = _transmittal(header, table)
    ids = [_held(f"doc_h{i}", n, r, p) for i, (n, r, p) in enumerate(held, 1)]
    ids += list(extra)
    run, scope = _review(sub)
    return sub, run, frozenset(scope | set(ids))


def _defects(run):
    return [
        r
        for r in _rows(run)
        if not r["ai_rationale"].startswith(transmittal_kit.NOTE_CODE)
    ]


def _notes(run):
    return [
        r for r in _rows(run) if r["ai_rationale"].startswith(transmittal_kit.NOTE_CODE)
    ]


def _items(run):
    return sorted(r["requirement_id"].split(":", 2)[2] for r in _defects(run))


def test_switch_off_changes_nothing():
    _sub, run, scope = _world(header=HEADER.replace("Date: 01/02/2026\n", ""))
    transmittal_kit.for_review(run, scope)
    assert _rows(run) == []


def test_a_complete_transmittal_has_no_defect_rows(on):
    _sub, run, scope = _world()
    transmittal_kit.for_review(run, scope)
    assert _defects(run) == []


def test_exactly_the_four_planted_defects_are_flagged_and_none_is_a_pass(on):
    header = HEADER.replace("Date: 01/02/2026\n", "").replace(
        "Purpose of Issue: For review", "Purpose of Issue:"
    )
    table = TABLE.replace("Valve datasheet   1 ", "Valve datasheet   2 ").replace(
        "Pump datasheet    3      2", "Pump datasheet    3      5"
    )
    _sub, run, scope = _world(header=header, table=table)
    transmittal_kit.for_review(run, scope)
    rows = _defects(run)
    assert _items(run) == [
        "header:date",
        "header:purpose",
        "revision:ABC-100-002",
        "sheets:ABC-100-001",
    ]
    assert {r["compliance_status"] for r in rows} == {"NEEDS_ENGINEER_REVIEW"}
    by = {r["requirement_id"].split(":", 2)[2]: r for r in rows}
    assert "not stated" in by["header:date"]["finding"]
    assert "not stated" in by["header:purpose"]["finding"]
    rev = by["revision:ABC-100-002"]["finding"]
    assert "2" in rev and "1" in rev and "page 1" in rev
    sheets = by["sheets:ABC-100-001"]["finding"]
    assert "5" in sheets and "2" in sheets


def test_a_listed_table_in_tables_json_is_read_like_a_text_table(on):
    sub = _transmittal(table="")
    grid = [
        ["Document Number", "Description", "Revision", "No. of Sheets"],
        ["ABC-100-001", "Pump datasheet", "3", "2"],
        ["ABC-100-002", "Valve datasheet", "9", "1"],
    ]
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET tables_json = ? WHERE document_id = ? AND page_no = 1",
            (json.dumps({"v": 1, "tables": [{"rows": grid, "lines": []}]}), sub),
        )
    _held("doc_h1", "ABC-100-001", "3", 2)
    _held("doc_h2", "ABC-100-002", "1", 1)
    run, scope = _review(sub)
    transmittal_kit.for_review(run, scope | {"doc_h1", "doc_h2"})
    assert _items(run) == ["revision:ABC-100-002"]


REQUIRED_PAGE = (
    "Required submissions\n"
    "Item   Document Type            Due\n"
    "1      Pump datasheet           15/02/2026\n"
    "2      Relief valve calculation 01/03/2026\n"
)


def test_a_required_list_flags_a_missing_and_an_extra_item(on, monkeypatch):
    _doc("doc_req", [REQUIRED_PAGE], "specification", number="REQ-1")
    _sub, run, scope = _world(extra=("doc_req",))
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, scope)
    assert _items(run) == [
        "extra:ABC-100-002",
        "not_transmitted:relief valve calculation",
    ]
    by = {r["requirement_id"].split(":", 2)[2]: r for r in _defects(run)}
    missing = by["not_transmitted:relief valve calculation"]["finding"]
    assert "not transmitted - engineer to confirm whether due" in missing
    assert "01/03/2026" in missing and "page 1" in missing
    assert "Pump datasheet" not in missing


def test_no_required_list_named_is_one_note_and_no_step_4_rows(on):
    _sub, run, scope = _world()
    transmittal_kit.for_review(run, scope)
    notes = spec_kit.notes(_rows(run))
    assert any("no required-submissions list named" in n["note"] for n in notes)
    assert [i for i in _items(run) if i.startswith(("extra", "not_transmitted"))] == []


def test_a_document_outside_the_allowed_ids_is_never_read(on, monkeypatch):
    # doc_h2 would be a revision mismatch and doc_req a required list, but neither is allowed
    _doc("doc_req", [REQUIRED_PAGE], "specification", number="REQ-1")
    table = TABLE.replace("Valve datasheet   1 ", "Valve datasheet   2 ")
    sub = _transmittal(table=table)
    _held("doc_h1", "ABC-100-001", "3", 2)
    _held("doc_h2", "ABC-100-002", "1", 1)
    run, scope = _review(sub)
    allowed = frozenset(scope | {"doc_h1"})
    read = []
    real = procedure_text.load_pages
    monkeypatch.setattr(
        procedure_text, "load_pages", lambda d: (read.append(d), real(d))[1]
    )
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, allowed)
    assert "doc_h2" not in read and "doc_req" not in read
    assert _items(run) == []
    assert any(
        "not in the documents you may read" in n["note"]
        for n in spec_kit.notes(_rows(run))
    )


def test_another_kind_is_not_touched(on):
    _doc("doc_x", [HEADER + TABLE], "datasheet", number="DS-1")
    run, scope = _review("doc_x")
    transmittal_kit.for_review(run, scope)
    assert _rows(run) == []


def test_rows_reach_the_crs_as_transmittal_engineer_rows_and_notes_are_not_lines(on):
    header = HEADER.replace("Date: 01/02/2026\n", "")
    _sub, run, scope = _world(header=header)
    transmittal_kit.for_review(run, scope)
    rows = _rows(run)
    assert all(spec_kit.is_row(r) for r in rows)
    assert all(spec_kit.is_unfound(r) for r in _notes(run))
    assert not any(spec_kit.is_unfound(r) for r in _defects(run))
    assert spec_kit.noun_of(_defects(run)[0]) == "transmittal"
    built = [
        b
        for b in crs_mapping.build_crs_rows(rows, [], "tr.pdf")
        if b.get("row_kind") == "spec_kit"
    ]
    assert len(built) == len(_defects(run)) == 1
    assert built[0]["comment_by"].startswith("Transmittal check")
    assert built[0]["comment"] in crs_mapping.WAITING_COMMENTS


# ---------------------------------------------------------------- review 1536 round 2


def _req(item):
    return {"item": item, "due": "", "page": 1, "quote": item, "document": "d"}


def _entry(docno, title):
    return {"cells": {"docno": docno, "title": title}, "page": 1, "quote": title}


@pytest.mark.parametrize(
    "title,docno,item",
    [
        ("Report", "R-1", "Relief valve report"),
        ("Piping", "P-1", "Piping stress analysis"),
        ("Calculation", "C-1", "Relief valve calculation"),
        ("Datasheet", "D-1", "Pump datasheet"),
        ("Misc", "DATASHEET-3", "Pump datasheet"),
        ("Pump datasheet", "X-1", "Pump datasheet vibration analysis"),
    ],
)
def test_a_generic_listed_title_or_number_never_covers_a_specific_item(
    title, docno, item
):
    assert not transmittal_kit._covers(_req(item), _entry(docno, title))
    rows = transmittal_kit.required_rows([_req(item)], [_entry(docno, title)], "b")
    assert [r["item"].split(":")[0] for r in rows] == ["not_transmitted", "extra"]


def test_a_specific_title_covers_its_item_and_a_generic_item_covers_nothing():
    assert transmittal_kit._covers(
        _req("Relief valve calculation"), _entry("X", "Relief valve sizing calculation")
    )
    assert not transmittal_kit._covers(_req("Datasheet"), _entry("X", "Pump datasheet"))


def test_one_listed_document_covers_one_required_item_unless_the_words_match():
    listed = [_entry("X-1", "Pump relief valve")]
    rows = transmittal_kit.required_rows(
        [_req("Pump"), _req("Relief valve")], listed, "b"
    )
    assert [r["item"] for r in rows] == ["not_transmitted:relief valve"]
    twice = transmittal_kit.required_rows(
        [_req("Pump datasheet"), _req("Pump datasheet")],
        [_entry("X-1", "Pump datasheet")],
        "b",
    )
    assert twice == []


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("0", "00", True),
        ("1", "01", True),
        ("A", "a", True),
        ("A", "B", False),
        ("1", "2", False),
        ("A", "1", False),
        ("0", "1", False),
    ],
)
def test_same_rev(a, b, same):
    assert transmittal_kit._same_rev(a, b) is same


def test_has_number_is_a_whole_token_not_a_substring():
    assert transmittal_kit._has_number("Document No: ABC-100-001", "ABC-100-001")
    assert transmittal_kit._has_number("Doc abc 100 001x abc-100-001", "ABC-100-001")
    assert not transmittal_kit._has_number("Document No: ABC-100-0011", "ABC-100-001")
    assert not transmittal_kit._has_number("XABC-100-001", "ABC-100-001")


def test_no_revision_on_the_held_cover_is_a_row(on):
    sub = _transmittal()
    _doc(
        "doc_h1",
        ["Document No: ABC-100-001\nInvented cover", "page 2"],
        "datasheet",
        number="ABC-100-001",
    )
    _held("doc_h2", "ABC-100-002", "1", 1)
    run, scope = _review(sub)
    transmittal_kit.for_review(run, scope | {"doc_h1", "doc_h2"})
    assert _items(run) == ["revision:ABC-100-001"]
    row = _defects(run)[0]
    assert "no revision read" in row["finding"]


def test_two_held_documents_with_one_number_are_ambiguous_and_not_compared(on):
    sub = _transmittal(
        table=TABLE.replace("Pump datasheet    3      2", "Pump datasheet    9      9")
    )
    _held("doc_a", "ABC-100-001", "3", 2)
    _held("doc_b", "ABC-100-001", "4", 3)
    _held("doc_h2", "ABC-100-002", "1", 1)
    run, scope = _review(sub)
    transmittal_kit.for_review(run, scope | {"doc_a", "doc_b", "doc_h2"})
    assert _items(run) == ["ambiguous:ABC-100-001"]


def test_a_number_only_in_the_title_block_of_another_document_is_not_a_holder(on):
    # page 1 carries the number only in a 'supersedes' line, and a number longer than it
    _doc(
        "doc_s",
        ["Document No: ABC-100-777\nSupersedes: ABC-100-001\nRevision: 7"],
        "datasheet",
        number="ABC-100-777",
    )
    _doc(
        "doc_l",
        ["Document No: ABC-100-0011\nRevision: 7"],
        "datasheet",
        number="ABC-100-0011",
    )
    held = transmittal_kit.holders(["ABC-100-001"], ["doc_s", "doc_l"])
    assert held == {"ABC-100-001": []}
    _held("doc_ok", "ABC-100-001", "3", 2)
    assert transmittal_kit.holders(["ABC-100-001"], ["doc_s", "doc_l", "doc_ok"]) == {
        "ABC-100-001": ["doc_ok"]
    }


def test_a_number_in_the_body_but_not_the_title_block_is_not_a_holder():
    body = "\n".join(f"line {i}" for i in range(30))
    _doc(
        "doc_b",
        [
            f"Cover\nInvented title\n{body}\nsee ABC-100-001 in body\n"
            + "\n".join(f"tail {i}" for i in range(30))
        ],
        "datasheet",
        number="ABC-100-999",
    )
    assert transmittal_kit.holders(["ABC-100-001"], ["doc_b"]) == {"ABC-100-001": []}


def test_not_held_and_no_table_notes(on):
    sub = _transmittal(table=TABLE)
    run, scope = _review(sub)  # nothing held
    transmittal_kit.for_review(run, scope)
    texts = [n["note"] for n in spec_kit.notes(_rows(run))]
    assert any("2 of 2 listed documents were not found" in t for t in texts)


def test_no_table_note(on):
    _doc("doc_t2", [HEADER], "transmittal", number="TRN-2")
    run2, scope2 = _review("doc_t2")
    transmittal_kit.for_review(run2, scope2)
    texts = [n["note"] for n in spec_kit.notes(_rows(run2))]
    assert any("No table of listed documents" in t for t in texts)


def test_spec_kit_stores_at_most_one_not_run_row_per_run(on, monkeypatch):
    monkeypatch.setattr(settings, "spec_kit_enabled", True)
    _doc(
        "doc_sp",
        ["Plain text with nothing"],
        "specification",
        number="S-1",
        equipment="unknown thing",
    )
    run, scope = _review("doc_sp")
    spec_kit.for_review(run, scope)
    not_run = [r for r in _rows(run) if r["ai_rationale"].startswith(spec_kit.NOT_RUN)]
    assert len(not_run) == 1
    assert len(spec_kit.notes(_rows(run))) == 1


def test_a_type_word_of_the_required_item_must_be_in_the_listed_title():
    item = _req("Pump datasheet")
    assert not transmittal_kit._covers(item, _entry("X", "Pump"))
    assert transmittal_kit._covers(item, _entry("X", "Pump Datasheet Rev 2"))
    assert transmittal_kit._covers(
        _req("Index of the pumps"), _entry("X", "Index pumps")
    )


def test_a_number_found_only_in_the_body_is_not_the_documents_own_number():
    # the number is on page 1 (the cheap filter passes) but outside the title block
    lines = ["Cover", "Invented title"] + [f"body {i}" for i in range(40)]
    lines += ["calculation per ABC-100-001"] + [f"tail {i}" for i in range(40)]
    _doc("doc_body", ["\n".join(lines)], "datasheet", number="ABC-100-999")
    assert "ABC-100-001" in procedure_text.load_pages("doc_body")[0][1]
    assert transmittal_kit.holders(["ABC-100-001"], ["doc_body"]) == {"ABC-100-001": []}


# ---------------------------------------------------------------- #1482 proof: nothing matched
# A transmittal extracted as a PIPE table (one row per line, '|' between cells - a .docx table
# reads this way) had no header field and no listed document read, so every required item was
# "not transmitted", and each such row carried the LIST's quote as the transmittal's page 1.

PIPE_HEADER = (
    "DOCUMENT TRANSMITTAL\n"
    "| Transmittal No. | TRN-0001 |\n"
    "| Date | 01/02/2026 |\n"
    "| From | Invented Contractor Ltd |\n"
    "| To | Invented Owner Co |\n"
    "| Purpose of issue | For review |\n"
)
PIPE_TABLE = (
    "| No. | Document No. | Title | Rev. | Sheets |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| 1 | ABC-100-001 | Pump datasheet | 3 | 2 |\n"
    "| 2 | ABC-100-002 | Valve datasheet | 1 | 1 |\n"
)


def test_a_complete_pipe_table_transmittal_is_read_and_has_no_defect_rows(on):
    _sub, run, scope = _world(header=PIPE_HEADER, table=PIPE_TABLE)
    transmittal_kit.for_review(run, scope)
    assert _defects(run) == []
    assert not any(
        "No table of listed" in n["note"] for n in spec_kit.notes(_rows(run))
    )


def test_the_planted_defects_of_a_pipe_table_transmittal_are_flagged(on):
    header = PIPE_HEADER.replace("| Date | 01/02/2026 |", "| Date |  |").replace(
        "| Purpose of issue | For review |", "| Purpose of issue | |"
    )
    table = PIPE_TABLE.replace(
        "| Valve datasheet | 1 |", "| Valve datasheet | 2 |"
    ).replace("| Pump datasheet | 3 | 2 |", "| Pump datasheet | 3 | 5 |")
    _sub, run, scope = _world(header=header, table=table)
    transmittal_kit.for_review(run, scope)
    assert _items(run) == [
        "header:date",
        "header:purpose",
        "revision:ABC-100-002",
        "sheets:ABC-100-001",
    ]
    assert {r["compliance_status"] for r in _defects(run)} == {"NEEDS_ENGINEER_REVIEW"}
    by = {r["requirement_id"].split(":", 2)[2]: r for r in _defects(run)}
    assert "the label is on page 1 with no value" in by["header:date"]["finding"]


def test_another_transmittal_listing_the_same_numbers_is_not_a_holder(on):
    # an earlier transmittal lists the same numbers: it is not the held document
    _doc("doc_tr_old", [HEADER + "\n" + TABLE], "transmittal", number="TRN-0000")
    _sub, run, scope = _world(header=PIPE_HEADER, table=PIPE_TABLE)
    assert transmittal_kit.holders(["ABC-100-001"], ["doc_tr_old", "doc_h1"]) == {
        "ABC-100-001": ["doc_h1"]
    }
    transmittal_kit.for_review(run, scope | {"doc_tr_old"})
    assert _defects(run) == []


def test_a_listed_row_without_a_document_number_is_counted_in_a_note(on):
    table = PIPE_TABLE + "| 3 | Invented procedure | Invented procedure | 0 | 4 |\n"
    _sub, run, scope = _world(header=PIPE_HEADER, table=table)
    transmittal_kit.for_review(run, scope)
    texts = [n["note"] for n in spec_kit.notes(_rows(run))]
    assert any(
        "1 of 3 rows of the listed-documents table carry no document number" in t
        for t in texts
    )


@pytest.mark.parametrize(
    "header_line,field",
    [
        ("| Date | Document No. | Title | Rev. |", "date"),
        ("| From | To | Document No. | Title |", "from"),
        ("| From | To | Document No. | Title |", "to"),
        ("| To | Date |", "to"),
    ],
)
def test_a_table_header_row_is_never_a_header_fields_value(header_line, field, on):
    # an undated transmittal (no Date/From/To line) must not look dated from a column name
    header = "\n".join(
        ln
        for ln in PIPE_HEADER.splitlines()
        if not ln.startswith(("| Date", "| From", "| To"))
    )
    table = header_line + "\n| 01/02/2026 | ABC-100-001 | Pump datasheet | 3 |\n"
    pages = [(1, header + "\n" + table)]
    assert transmittal_kit.header_fields(pages).get(field, ("",))[0] == ""
    assert f"header:{field}" in {r["item"] for r in transmittal_kit.header_rows(pages)}


def test_a_header_field_value_next_to_its_label_is_still_read():
    pages = [(1, "| Date | 01/02/2026 | Ref | TRN-0001 |\n| To | Invented Owner Co |")]
    got = transmittal_kit.header_fields(pages)
    assert got["date"][0] == "01/02/2026"
    assert got["to"][0] == "Invented Owner Co"


@pytest.mark.parametrize(
    "cover,rev",
    [
        ("Document No: ABC-100-001\nREV NO\nInvented cover\nRev. 2", "2"),
        ("Document No: ABC-100-001\nRev Num 2\nInvented cover", "2"),
        ("Document No: ABC-100-001\nRevision: Rev 2\nInvented cover", "2"),
        ("Document No: ABC-100-001\nRevised for review\nRevision: 3", "3"),
        ("Document No: ABC-100-001\nSupersedes Rev B\nRevision: 3", "3"),
        ("Document No: ABC-100-001\nRev. 0 first issue\nRev. 1 second issue", None),
    ],
)
def test_the_cover_revision_is_the_one_revision_the_cover_states(cover, rev, on):
    _doc("doc_c", [cover], "datasheet", number="ABC-100-001")
    got = transmittal_kit.cover_revision("doc_c")
    assert (got[0] if got else None) == rev


def test_a_transmittal_left_out_as_a_holder_is_said_so_even_when_only_suggested(on):
    _doc("doc_tr_old", [HEADER + "\n" + TABLE], "transmittal", number="TRN-0000")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_kinds SET state = 'suggested' WHERE document_id = 'doc_tr_old'"
        )
    _sub, run, scope = _world(header=PIPE_HEADER, table=PIPE_TABLE)
    transmittal_kit.for_review(run, scope | {"doc_tr_old"})
    assert _defects(run) == []
    texts = [n["note"] for n in spec_kit.notes(_rows(run))]
    assert any(
        "1 document(s) you may read carry a listed number" in t
        and "routed as transmittals" in t
        for t in texts
    )


def test_a_missing_required_item_cites_the_list_not_the_transmittal(on, monkeypatch):
    _doc("doc_req", [REQUIRED_PAGE], "specification", number="REQ-1")
    _sub, run, scope = _world(header=PIPE_HEADER, table=PIPE_TABLE, extra=("doc_req",))
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, scope)
    assert _items(run) == [
        "extra:ABC-100-002",
        "not_transmitted:relief valve calculation",
    ]
    by = {r["requirement_id"].split(":", 2)[2]: r for r in _defects(run)}
    missing = by["not_transmitted:relief valve calculation"]
    assert missing["contractor_page"] is None
    assert missing["contractor_evidence_text"] is None
    # a structured citation that resolves: the list's document, page and verified text
    assert missing["standard_document_id"] == "doc_req"
    assert missing["standard_page"] == 1
    quote = missing["requirement_source_text"]
    assert "Relief valve calculation" in quote
    page_text = procedure_text.load_pages("doc_req")[0][1]
    assert " ".join(quote.split()) in " ".join(page_text.split())
    assert "named on" not in missing["finding"]
    assert missing["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    extra = by["extra:ABC-100-002"]
    assert extra["contractor_page"] == 1
    assert "ABC-100-002" in extra["contractor_evidence_text"]
    assert extra["standard_document_id"] is None


def test_a_list_quote_not_found_on_its_page_is_named_not_cited(on, monkeypatch):
    # the list is a stored grid: its row quote ('a | b | c') is not the page's text
    _doc("doc_req", ["Required submissions"], "specification", number="REQ-1")
    grid = [["Item", "Document Type", "Due"], ["2", "Relief valve calculation", "x"]]
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET tables_json = ? WHERE document_id = 'doc_req'",
            (json.dumps({"v": 1, "tables": [{"rows": grid, "lines": []}]}),),
        )
    _sub, run, scope = _world(header=PIPE_HEADER, table=PIPE_TABLE, extra=("doc_req",))
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, scope)
    by = {r["requirement_id"].split(":", 2)[2]: r for r in _defects(run)}
    missing = by["not_transmitted:relief valve calculation"]
    assert "named on required-submissions list doc_req page 1" in missing["finding"]
    assert missing["standard_document_id"] is None
    assert missing["contractor_page"] is None


def test_a_stored_grid_item_found_on_its_page_is_cited_by_its_own_cell(on, monkeypatch):
    _doc(
        "doc_req",
        ["Required submissions\nItem 2 Relief valve calculation due x"],
        "specification",
        number="REQ-1",
    )
    grid = [["Item", "Document Type", "Due"], ["2", "Relief valve calculation", "x"]]
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET tables_json = ? WHERE document_id = 'doc_req'",
            (json.dumps({"v": 1, "tables": [{"rows": grid, "lines": []}]}),),
        )
    _sub, run, scope = _world(header=PIPE_HEADER, table=PIPE_TABLE, extra=("doc_req",))
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, scope)
    by = {r["requirement_id"].split(":", 2)[2]: r for r in _defects(run)}
    missing = by["not_transmitted:relief valve calculation"]
    assert missing["standard_document_id"] == "doc_req"
    assert missing["standard_page"] == 1
    assert missing["requirement_source_text"] == "Relief valve calculation"
