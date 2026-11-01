"""A rule's equipment scope is read from its own clause text and heading chain; unknown
stays unknown; the switch off writes nothing; the re-extraction script works on copies
only, under the heavy lock. Invented standards and rules only."""

# ruff: noqa: I001
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from app import db, heavy_lock, rule_equipment_scope as res, standards
from app.config import settings
from tests.test_partial_standards import temp_storage as review_storage  # noqa: F401
from tests.test_applicability import _doc, temp_storage  # noqa: F401

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "reextract_rule_equipment_scope.py"
)


def _r(text, clause=None, section=None, page=3):
    return {
        "requirement_text": text,
        "clause": clause,
        "chunk_section": section,
        "page": page,
    }


def test_pump_clause_is_a_pump_with_its_quote_and_page():
    s = res.scope_of(
        _r("This clause applies to centrifugal pumps handling hydrocarbons.")
    )
    assert s["types"] == ["pump"] and s["method"] == res.WORDING and s["page"] == 3
    assert "centrifugal pumps" in s["quote"]


def test_leading_for_names_the_scope():
    assert res.scope_of(
        _r("For shell and tube heat exchangers, tubes shall be tested.")
    )["types"] == ["heat exchanger"]


def test_subject_before_shall_is_the_scope():
    s = res.scope_of(
        _r("The pump casing shall withstand the maximum discharge pressure.")
    )
    assert s["types"] == ["pump"] and s["method"] == res.SUBJECT


def test_heading_gives_its_clauses_the_equipment():
    headings = {"5.2": "5.2 Heat Exchangers"}
    s = res.scope_of(
        _r("Tubes shall be seamless.", clause="5.2.1", section="5.2.1 Tubes"), headings
    )
    assert s["types"] == ["heat exchanger"] and s["method"] == res.HEADING
    assert s["quote"] == "5.2 Heat Exchangers"


def test_general_clause_is_unknown_never_a_guess():
    s = res.scope_of(
        _r(
            "Documents shall be submitted in English.",
            clause="1.1",
            section="1.1 General",
        )
    )
    assert s == {"types": [], "quote": "", "page": 3, "method": res.UNKNOWN}
    assert res.stored_fields(s) == {}


def test_several_types_named_all_are_kept():
    s = res.scope_of(_r("This section applies to pumps and compressors."))
    assert s["types"] == ["compressor", "pump"]
    assert res.stored_fields(s)["equipment_type"] == "compressor, pump"


def test_a_mid_sentence_for_does_not_set_a_scope():
    # "bolts for the pressure vessel flange" is about bolting, not a vessel-only rule
    assert (
        res.scope_of(_r("Bolts for the flange of the vessel are to be galvanised."))[
            "types"
        ]
        == []
    )


def _says(types, quote):
    def post(path, body, timeout):
        return {"response": json.dumps({"types": types, "quote": quote})}

    return post


def test_local_model_answer_is_verified_by_code():
    text = "Seals fitted on the unit of the process string shall be double."
    ok = res.ask_local_model(_r(text), post=_says(["pump"], "Seals fitted on the unit"))
    assert ok["types"] == ["pump"] and ok["method"] == res.MODEL
    assert res.ask_local_model(_r(text), post=_says(["pump"], "pump seals")) is None
    assert res.ask_local_model(_r(text), post=_says(["widget"], "Seals fitted")) is None


# ------------------------------------------------------------ extraction wiring


def _standard():
    _doc(
        "std1",
        "std.pdf",
        "COMPANY_STANDARD",
        "This clause applies to centrifugal pumps. The pump seal shall be double. "
        "Documents shall be submitted in English.",
    )
    return "std1"


def _equipment_types():
    return {
        r["requirement_text"]: r["equipment_type"]
        for r in db.connect().execute(
            "SELECT requirement_text, equipment_type FROM standard_requirements"
        )
    }


def test_extraction_writes_scope_only_when_the_switch_is_on(monkeypatch):
    std = _standard()
    monkeypatch.setattr(settings, "rule_equipment_scope_extract_enabled", False)
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    assert (
        db.connect().execute("SELECT COUNT(*) FROM standard_requirements").fetchone()[0]
        > 0
    )
    assert set(_equipment_types().values()) == {None}


def test_extraction_stores_scope_with_evidence_when_on(monkeypatch):
    std = _standard()
    monkeypatch.setattr(settings, "rule_equipment_scope_extract_enabled", True)
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    types = _equipment_types()
    assert types.get("The pump seal shall be double.") == "pump"
    assert types.get("Documents shall be submitted in English.") is None
    row = (
        db.connect()
        .execute(
            "SELECT equipment_scope_evidence FROM standard_requirements WHERE equipment_type = 'pump'"
        )
        .fetchone()
    )
    assert json.loads(row[0])["method"] in {res.WORDING, res.SUBJECT}


# ----------------------------------------------------------------- the script


def _script():
    spec = importlib.util.spec_from_file_location(
        "reextract_rule_equipment_scope", SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def copy_db(tmp_path, monkeypatch):
    std = _standard()
    monkeypatch.setattr(settings, "rule_equipment_scope_extract_enabled", False)
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    db.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.reset_connection()
    target = tmp_path / "copy" / "copy.sqlite"
    target.parent.mkdir()
    shutil.copy(settings.db_path, target)
    monkeypatch.setenv("HEAVY_JOB_LOCK", "off")
    return target


def _digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_script_refuses_a_live_shaped_path(tmp_path, copy_db, capsys):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    shutil.copy(copy_db, live)
    before = _digest(live)
    assert _script().main(["--db", str(live)]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert _digest(live) == before


def test_dry_run_leaves_the_file_byte_identical_and_counts(copy_db, tmp_path):
    before = _digest(copy_db)
    out = tmp_path / "s.json"
    assert _script().main(["--db", str(copy_db), "--dry-run", "--out", str(out)]) == 0
    assert _digest(copy_db) == before
    summary = json.loads(out.read_text())
    assert summary["dry_run"] is True and summary["rows_written"] == 0
    assert (
        summary["rules_scoped_to_type"].get("pump", 0) >= 1 and summary["unknown"] >= 1
    )


def test_write_run_changes_the_copy_only(copy_db, tmp_path):
    out = tmp_path / "s.json"
    assert _script().main(["--db", str(copy_db), "--out", str(out)]) == 0
    import sqlite3

    conn = sqlite3.connect(copy_db)
    scoped = conn.execute(
        "SELECT COUNT(*) FROM standard_requirements WHERE equipment_type = 'pump'"
    ).fetchone()[0]
    assert scoped >= 1 and json.loads(out.read_text())["rows_written"] > 0
    # the app's own database (the source of the copy) was not touched
    db.reset_connection()
    assert (
        db.connect()
        .execute(
            "SELECT COUNT(*) FROM standard_requirements WHERE equipment_type = 'pump'"
        )
        .fetchone()[0]
        == 0
    )


def test_script_takes_the_heavy_lock(copy_db, monkeypatch):
    seen = []

    def fake(kind, fn, owner=None, say=print):
        seen.append(kind)
        return heavy_lock.EXIT_BUSY

    monkeypatch.setattr(heavy_lock, "run_locked", fake)
    assert _script().main(["--db", str(copy_db), "--dry-run"]) == 75
    assert seen == ["rule-scope"]


# ------------------------------------------- negation, exclusion, deferral (rule 4)


@pytest.mark.parametrize(
    "text",
    [
        "This clause does not apply to centrifugal pumps.",
        "Not applicable to pumps.",
        "Excluding compressors, documents shall be submitted in English.",
        "This section does not cover compressors.",
        "Requirements for pumps are given elsewhere.",
        "Compressors are not covered by this clause.",
        "See clause 9 for pumps.",
    ],
)
def test_a_type_in_a_negated_excluded_or_deferred_phrase_is_never_the_scope(text):
    assert res.scope_of(_r(text))["types"] == []


def test_positive_type_stays_beside_an_excluded_one():
    s = res.scope_of(_r("This section applies to pumps, other than compressors."))
    assert s["types"] == ["pump"]


def test_contrast_keeps_only_the_positive_type():
    s = res.scope_of(
        _r("Unlike heat exchangers, vessels shall be fitted with a drain.")
    )
    assert s["types"] == ["pressure vessel"]


def test_a_negated_list_masks_every_item():
    assert res.scope_of(_r("Not applicable to pumps, compressors."))["types"] == []


def test_heading_modifier_phrase_is_not_the_scope():
    only = res.scope_of(
        _r("Piping shall be tested.", section="7 Piping connected to pumps")
    )
    assert only["types"] == []


def test_a_heading_with_a_for_scope_still_counts():
    s = res.scope_of(_r("Seals shall be fitted.", section="4 Requirements for pumps"))
    assert s["types"] == ["pump"]
    refinery = res.scope_of(
        _r("Seals shall be fitted.", section="4 Pumps in refinery service")
    )
    assert refinery["types"] == ["pump"]


def test_a_generic_valve_never_fans_out_to_specific_valve_types():
    s = res.scope_of(
        _r("Stems shall be coated.", section="6 Valves in compressor service")
    )
    assert s["types"] == []
    assert res.scope_of(_r("Valves shall be tested."))["types"] == []
    assert res.scope_of(_r("The relief valve shall be tested."))["types"] == [
        "relief valve"
    ]


def test_model_answer_inside_a_negated_phrase_is_dropped():
    text = "Pumps are not covered here; seals shall be double."
    said = _says(["pump"], "Pumps are not covered here")
    assert res.ask_local_model(_r(text), post=said) is None
    text = "Seals fitted on pumps shall be double, other than on compressors."
    assert (
        res.ask_local_model(_r(text), post=_says(["compressor"], "on compressors"))
        is None
    )
    assert res.ask_local_model(_r(text), post=_says(["pump"], "Seals fitted on pumps"))


def test_script_refuses_a_symlink_and_a_relative_path_to_a_live_shaped_file(
    tmp_path, copy_db, monkeypatch, capsys
):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    shutil.copy(copy_db, live)
    link = tmp_path / "innocent.sqlite"
    link.symlink_to(live)
    before = _digest(live)
    assert _script().main(["--db", str(link)]) == 2
    monkeypatch.chdir(live.parent)
    assert _script().main(["--db", "rag_intelligence.sqlite"]) == 2
    assert capsys.readouterr().err.count("REFUSED") == 2
    assert _digest(live) == before


def test_a_second_write_run_changes_zero_rows(copy_db, tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    assert _script().main(["--db", str(copy_db), "--out", str(first)]) == 0
    assert _script().main(["--db", str(copy_db), "--out", str(second)]) == 0
    assert json.loads(first.read_text())["rows_written"] > 0
    assert json.loads(second.read_text())["rows_written"] == 0
