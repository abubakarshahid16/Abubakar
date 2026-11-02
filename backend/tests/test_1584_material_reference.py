"""#1584: an owner-signed grade table for a rule that forbids a material. Invented sheet values; the grades are public
designations, not from any document; a fake Batch; no real call."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
import pytest

from app import coverage_pair, db, material_reference, rule_typed_check
from app.config import settings
from app.material_reference import Entry, Table, family_of, is_not, tokens
from tests.test_805_review_reads_v2 import (  # noqa: F401
    QUERY,
    _one,
    _reason,
    _review,
    _rule,
    _sheet,
    switched_on,
)
from tests.test_805_rule_field_naming import Roles
from tests.test_805_rule_typed_check import NOT_COPPER, _typed
from tests.test_1584_standards_compiler import lane  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import import_rule_approvals as importer
import propose_material_reference as script

STEEL = Entry("ASTM A216", "WCB", "carbon steel", False)
GREY = Entry("ASTM A48", "Class 30", "cast iron", False)
DUCTILE = Entry("ASTM A395", "60-40-18", "cast iron", False)
MALLEABLE = Entry("ASTM A47", "32510", "cast iron", False)
BARE = Entry("ASTM A351", "CF8M", "stainless steel", True)
TABLE = Table("v1", (STEEL, GREY, DUCTILE, MALLEABLE, BARE))
FORBID = ["cast iron"]


@pytest.mark.parametrize(
    "value", ["ASTM A48 Class 30", "A395 60-40-18", "ASTM A 47 Gr 32510"]
)
def test_grey_ductile_and_malleable_grades_fail(value):
    assert is_not(TABLE, FORBID, value)[0] == "NON_COMPLIANT"


@pytest.mark.parametrize(
    "value", ["ASTM A216 WCB", "ASTM A 216 Gr WCB", "A216-WCB", "astm a216 grade wcb"]
)
def test_a_steel_grade_passes_however_it_is_spaced(value):
    assert is_not(TABLE, FORBID, value)[0] == "COMPLIANT"


@pytest.mark.parametrize(
    "value",
    [
        "ASTM A999 ZZZ",  # unknown
        "WCB",  # a bare grade the table does not call unambiguous
        "A216 WC",  # a partial token
        "A2160 WCB",  # a partial token the other way
        "A216 WCBX",
        "ASTM A216 WCB / ASTM A48 Class 30",  # several specifications
        "A216 WCB lined",  # words beside it
        "see note 4",
        "",
    ],
)
def test_anything_else_is_no_family_so_a_query(value):
    assert family_of(TABLE, value) is None
    assert is_not(TABLE, FORBID, value)[0] is None


def test_a_bare_grade_matches_only_where_the_table_says_it_is_unambiguous():
    assert family_of(TABLE, "CF8M") == "stainless steel"


def test_a_grade_the_table_gives_two_families_is_no_family():
    two = Table("v", (STEEL, Entry("ASTM A216", "WCB", "cast iron", False)))
    assert family_of(two, "A216 WCB") is None


def test_a_narrower_word_in_the_rule_decides_nothing():
    assert is_not(TABLE, ["ductile iron"], "ASTM A216 WCB")[0] is None


def test_a_finding_names_the_table_version_and_says_it_is_not_confirmed():
    words = is_not(TABLE, FORBID, "ASTM A216 WCB")[1]
    assert (
        "owner-signed reference, not engineer-confirmed" in words
        and "version v1" in words
    )


def test_tokens_are_whole():
    assert tokens("ASTM A 216 Gr. WCB") == ("a216", "wcb")


# ------------------------------------------------------------------------------------------- proposing


def _proposal():
    return {
        "entries": [
            {
                "specification": e.specification,
                "grade": e.grade,
                "family": e.family,
                "bare_grade_unambiguous": e.bare,
            }
            for e in TABLE.entries
        ]
        + [
            {
                "specification": "ASTM A1",
                "grade": "B",
                "family": "cheese",
                "bare_grade_unambiguous": False,
            }
        ]
    }


def _propose(client, **kw):
    return material_reference.propose(
        db.connect(), client=client, sleep=lambda _s: None, **kw
    )


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(settings, "material_reference_engine", "claude")
    monkeypatch.setattr(settings, "material_reference_enabled", True)


def _sign(*entries, tier="owner", decision="approve"):
    conn = db.connect()
    wanted = {(e.specification, e.grade) for e in entries}
    rows = [
        r
        for r in material_reference.sheet_rows(conn)
        if (r["Specification"], r["Grade"]) in wanted
    ]
    with conn:
        material_reference.record(
            conn,
            [{"entry_id": r["Entry id"], "decision": decision} for r in rows],
            "owner-1",
            tier,
            "d",
        )


def test_an_estimate_sends_nothing_writes_nothing_needs_no_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    client = Roles(_proposal())
    report = _propose(client, estimate_only=True)
    assert (
        client.created == []
        and report["status"] == "estimate"
        and report["worst_usd"] > 0
    )
    assert not material_reference.has_schema(db.connect())


def test_engine_off_sends_nothing():
    client = Roles(_proposal())
    with pytest.raises(material_reference.SwitchedOff):
        _propose(client)
    assert client.created == []


def test_what_is_sent_is_general_knowledge_and_names_no_document(engine):
    client = Roles(_proposal())
    report = _propose(client)
    assert report["status"] == "done" and (report["kept"], report["dropped"]) == (5, 1)
    assert len(client.created[0]) == 1
    sent = client.created[0][0]["params"]
    assert report["document_text_sent"] == 0
    assert json.dumps(sent["messages"]).count("List the table now.") == 1
    assert material_reference.SYSTEM in json.dumps(sent, ensure_ascii=False).replace(
        "\\", ""
    )


def test_a_limit_already_spent_says_why(engine):
    client = Roles(_proposal())
    report = _propose(client, max_usd=0.0)
    assert (
        client.created == []
        and report["status"] == "over_budget"
        and "--max-usd" in report["why"]
    )


def test_every_entry_lands_unsigned(engine):
    _propose(Roles(_proposal()))
    assert material_reference.signed(db.connect()).entries == ()


def test_only_the_owners_last_tick_signs(engine):
    _propose(Roles(_proposal()))
    conn = db.connect()
    _sign(STEEL, tier="engineer")
    assert material_reference.signed(conn).entries == ()
    _sign(STEEL)
    assert material_reference.signed(conn).entries == (STEEL,)
    first = material_reference.signed(conn).version
    _sign(GREY)
    assert material_reference.signed(conn).version != first
    _sign(STEEL, decision="reject")
    assert STEEL not in material_reference.signed(conn).entries


def test_the_tables_cannot_be_rewritten(engine):
    _propose(Roles(_proposal()))
    with pytest.raises(Exception, match="append-only"):
        with db.connect() as conn:
            conn.execute("UPDATE material_reference_entry SET family = 'cast iron'")


# ------------------------------------------------------------------------------------------- end to end


def _body(words):
    return _sheet(label="Body material", value=words)


def _forbid():
    return _typed(NOT_COPPER, rule_typed_check.IS_NOT, ["cast iron"])


def _world(monkeypatch, value, *signed_entries):
    run, scope = _body(value)
    _propose(Roles(_proposal()))
    _sign(*signed_entries)
    return run, scope


def test_a_signed_steel_grade_passes_end_to_end_and_the_finding_says_whose_table(
    engine, monkeypatch
):
    run, scope = _world(monkeypatch, "ASTM A216 WCB", STEEL)
    row = _one(_review(monkeypatch, run, scope, _forbid()))
    assert row["compliance_status"] == "COMPLIANT", row["finding"]
    assert "owner-signed reference, not engineer-confirmed" in row["finding"]
    line = coverage_pair.for_run(db.connect(), run)["rulebook_v2"]["line"]
    assert "owner-signed reference" in line and "not engineer-confirmed" in line


def test_a_signed_iron_grade_fails_end_to_end(engine, monkeypatch):
    run, scope = _world(monkeypatch, "ASTM A395 60-40-18", DUCTILE)
    row = _one(_review(monkeypatch, run, scope, _forbid()))
    assert row["compliance_status"] == "NON_COMPLIANT", row["finding"]


def test_an_unticked_entry_never_decides(engine, monkeypatch):
    run, scope = _world(monkeypatch, "ASTM A216 WCB", GREY)
    row = _one(_review(monkeypatch, run, scope, _forbid()))
    assert row["compliance_status"] == QUERY and _reason(row) == "value_unclear"


def test_an_unknown_grade_is_a_query(engine, monkeypatch):
    run, scope = _world(monkeypatch, "ASTM A999 ZZZ", STEEL)
    assert (
        _one(_review(monkeypatch, run, scope, _forbid()))["compliance_status"] == QUERY
    )


def test_switch_off_the_table_is_not_read(monkeypatch):
    monkeypatch.setattr(settings, "material_reference_engine", "claude")
    run, scope = _world(monkeypatch, "ASTM A216 WCB", STEEL)
    assert settings.material_reference_enabled is False
    row = _one(_review(monkeypatch, run, scope, _forbid()))
    assert row["compliance_status"] == QUERY and "owner-signed" not in row["finding"]


def test_the_switches_are_off_by_default():
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["material_reference_enabled"].default is False
    assert fields["material_reference_engine"].default == "off"


# ------------------------------------------------------------------------------------------- the sheet


def _file(tmp_path, *ticks):
    conn = db.connect()
    path = tmp_path / "list.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Cover"
    book["Cover"].append([importer.COVER_TYPE, "Pressure Safety Valve"])
    book.create_sheet("Rules").append(
        [
            *list(importer.READ_COLUMNS),
            importer.C_CHECK,
            importer.C_TICK,
            importer.C_COMMENT,
        ]
    )
    material_reference.add_sheet(book, conn)
    sheet = book[material_reference.SHEET]
    header = [c.value for c in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        for spec, grade, tick in ticks:
            if row[0].value == spec and row[1].value == grade:
                row[header.index(material_reference.C_TICK)].value = tick
    book.save(path)
    return path, book


def _reference_refusal(path):
    conn = db.connect()
    cover = {}
    for row in openpyxl.load_workbook(path)["Cover"].iter_rows(values_only=True):
        cover[row[0]] = row[1]
    return importer._material_sheet(conn, path, cover, "owner-1")


def test_a_new_sheet_has_a_row_per_entry_and_no_tick(engine, tmp_path):
    _propose(Roles(_proposal()))
    path, _book = _file(tmp_path)
    rows = list(
        openpyxl.load_workbook(path)[material_reference.SHEET].iter_rows(
            values_only=True
        )
    )
    assert len(rows) == 6 and rows[1][4] == "AI proposed"
    assert all(r[7] is None for r in rows[1:])


def test_a_tick_becomes_a_decision_and_an_empty_one_does_not(engine, tmp_path):
    _propose(Roles(_proposal()))
    path, _book = _file(tmp_path, ("ASTM A216", "WCB", importer.OK))
    decisions, refused = _reference_refusal(path)
    assert (
        refused is None
        and len(decisions) == 1
        and decisions[0]["decision"] == "approve"
    )


def test_a_stale_sheet_is_refused(engine, tmp_path):
    _propose(Roles(_proposal()))
    path, _book = _file(tmp_path, ("ASTM A216", "WCB", importer.OK))
    material_reference.store_proposal(
        db.connect(),
        {
            "entries": [
                {
                    "specification": "ASTM A105",
                    "grade": "N",
                    "family": "carbon steel",
                    "bare_grade_unambiguous": False,
                }
            ]
        },
        "m",
    )
    decisions, refused = _reference_refusal(path)
    assert decisions == [] and refused[0] == importer.EXIT_STALE


def test_an_edited_row_is_refused(engine, tmp_path):
    _propose(Roles(_proposal()))
    path, book = _file(tmp_path)
    sheet = book[material_reference.SHEET]
    header = [c.value for c in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        if row[0].value == "ASTM A48":
            row[header.index(material_reference.C_FAMILY)].value = "carbon steel"
    book.save(path)
    decisions, refused = _reference_refusal(path)
    assert decisions == [] and refused[0] == importer.EXIT_EDITED


def test_the_counts_print_no_value(engine, tmp_path):
    _body("ASTM A216 WCB")
    _propose(Roles(_proposal()))
    said = script.count_on(
        db.connect(),
        settings.db_path,
        "sub-1",
        "body_material",
        "Pressure Safety Valve",
    )
    assert (
        said["values"] == 1
        and said["in_the_table_signed_or_not"] == 1
        and said["in_the_signed_table"] == 0
    )
    assert "WCB" not in json.dumps(said)
