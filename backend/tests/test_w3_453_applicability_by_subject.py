"""#453: a requirement about a different kind of equipment is not a check.
Synthetic data only. Mutations M3101-M3112."""
from __future__ import annotations

import json
import os
import uuid

import pytest

from app import comparison, datasheets, db, standards, submittal_review, subject_scope
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t453.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, role, name=None, equipment=None, title=None):
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',3,'2026-09-18T00:00:00Z')""",
            (doc_id, name or f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf"))
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,document_role,equipment_type,title)
            VALUES (?,?,?,?,?)""", (doc_id, "test", role, equipment, title))
    return doc_id


def _chunk(chunk_id, doc_id, section=None, page=1, ordinal=0):
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,?,?,?,?,'prose','t',1,?,1)""",
            (chunk_id, doc_id, "f.pdf", ordinal, page, page, section, f"h-{chunk_id}"))


def _req(std, chunk, text, clause, field="relief capacity"):
    return standards.create_requirement(
        standard_document_id=std, chunk_id=chunk, clause=clause, page=1,
        requirement_text=text, source_text=text, confidence=0.9,
        structured={"requirement_type": "numeric_limit", "operator": "<=",
                    "value": 10, "unit": "bar", "raw_value": "10", "raw_unit": "bar",
                    "field": field, "subject": field})["id"]


def _review(requirements, *, equipment="Pressure Safety Valve", title=None, headings=()):
    """requirements: [(key, text, clause)] written into one standard."""
    sub = _doc("sub", "CONTRACTOR_SUBMITTAL", equipment=equipment, title=title)
    _chunk("fc", sub)
    std = _doc("std", "COMPANY_STANDARD", "SAES-X.pdf")
    _chunk("c-std", std, section=None)
    for number, (clause, heading) in enumerate(headings):
        _chunk(f"h{number}", std, section=f"{clause} {heading}", ordinal=number + 1)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run, sub))
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,included,
             created_at) VALUES (?,?,?,'rule',1,?)""",
            (str(uuid.uuid4()), run, std, "2026-09-18T00:00:00Z"))
    ids = {key: _req(std, "c-std", text, clause) for key, text, clause in requirements}
    datasheets.create_fact(submittal_document_id=sub, chunk_id="fc",
                           field_label="Set pressure", raw_value="9 bar", page=1)
    result = comparison.run_comparison(run, allowed_document_ids=frozenset({sub, std}))
    cited = {f["requirement_id"] for f in result["findings"] if f.get("requirement_id")}
    return ids, cited, result


TURBINE = "The steam turbine casing relief device shall be sized for the maximum steam flow."
GENERAL = "The relief capacity shall be stated on the datasheet."


def test_a_turbine_casing_requirement_is_not_applied_to_a_relief_valve_submittal():
    """Test 1. With a general control that IS applied."""
    ids, cited, result = _review([("turbine", TURBINE, "8.7"), ("general", GENERAL, "5.1")])
    assert ids["general"] in cited                      # positive first
    assert ids["turbine"] not in cited
    [line] = result["requirements_not_applied"]
    assert line["line"] == ("1 requirement not applied: they are about steam turbine, "
                            "this submittal is relief valve")
    assert line["standards"][0]["standard_name"] == "SAES-X.pdf"
    assert line["standards"][0]["clauses"] == ["8.7"]
    assert result["applicability"]["not_applied"] == 1


def test_a_general_requirement_is_still_applied_and_a_component_never_excludes():
    ids, cited, result = _review([
        ("general", GENERAL, "5.1"),
        ("flange", "Flange faces shall be machined to the stated finish.", "6.2"),
        ("piping", "Inlet piping shall be sloped back to the vessel.", "6.3")])
    assert set(ids.values()) <= cited
    assert result["requirements_not_applied"] == []
    assert result["applicability"]["checked_general"] == 3


def test_a_clause_with_a_silent_sentence_takes_its_subject_from_its_heading_path():
    """The sentence names no equipment; the clause 8 heading does."""
    ids, cited, result = _review(
        [("heading", "Relief shall be sized for the maximum flow.", "8.7.2"),
         ("other", "Relief shall be sized for the stated flow.", "5.1")],
        headings=[("8", "Steam turbines")])
    assert ids["other"] in cited
    assert ids["heading"] not in cited
    assert result["requirements_not_applied"][0]["subject"] == "steam turbine"


def test_what_a_sentence_only_mentions_is_not_its_subject():
    """Piping 'back to the vessel' is a piping clause, not a vessel clause."""
    ids, cited, _ = _review([
        ("piping", "Inlet piping shall be sloped back to the vessel.", "6.3"),
        ("vessel", "The vessel shall be fitted with a relief valve.", "6.4")])
    assert ids["piping"] in cited
    assert ids["vessel"] not in cited


def test_the_requirements_own_wording_wins_over_its_heading():
    ids, cited, _ = _review(
        [("own", "The relief valve seat shall be tight at 90 percent of set pressure.", "8.7.2")],
        headings=[("8", "Steam turbines")])
    assert ids["own"] in cited


def test_a_requirement_with_an_unclear_subject_is_kept():
    """An ambiguous spelling ('valve') matches several types and is kept."""
    ids, cited, result = _review([("valve", "The valve body shall be marked with the tag.", "4.1")])
    assert ids["valve"] in cited
    assert result["requirements_not_applied"] == []


def test_an_unknown_submittal_equipment_keeps_everything_and_says_so():
    ids, cited, result = _review([("turbine", TURBINE, "8.7")], equipment=None)
    assert ids["turbine"] in cited
    assert result["requirements_not_applied"] == []
    assert result["applicability"]["kept_equipment_unknown"] == 1
    assert result["applicability"]["submittal_equipment"] == []


def test_the_submittals_title_names_its_equipment_when_the_classification_does_not():
    ids, cited, result = _review([("turbine", TURBINE, "8.7")],
                                 equipment=None, title="Pressure relief valve data sheet")
    assert ids["turbine"] not in cited
    assert result["applicability"]["equipment_source"] == "title"


def test_a_synonym_added_to_the_vocabulary_file_changes_the_result_without_code(
        tmp_path, monkeypatch):
    path = tmp_path / "vocab.json"
    data = json.loads(subject_scope.VOCABULARY_PATH.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(subject_scope, "VOCABULARY_PATH", path)
    requirement = {"id": "r", "standard_document_id": "s", "clause": "9.1",
                   "requirement_text": "The THX-9 casing shall be hydrotested."}
    facts, classification = [], {"equipment_type": "Pressure Safety Valve"}
    before = subject_scope.gate([requirement], classification=classification, facts=facts)
    assert before["kept"] == [requirement]          # the word means nothing yet
    assert before["not_applied"] == []

    data["types"]["steam turbine"]["synonyms"].append("thx-9")
    path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    after = subject_scope.gate([requirement], classification=classification, facts=facts)
    assert after["kept"] == []
    assert after["not_applied"][0]["subject"] == "steam turbine"


def test_a_spelling_listed_under_two_types_matches_both():
    vocab = subject_scope.vocabulary()
    assert {"relief valve", "control valve"} <= vocab.types_in("the valve")
    assert vocab.equipment_in("a steam turbine casing") == {"steam turbine"}
    assert vocab.equipment_in("the turbine") == {"steam turbine", "gas turbine"}


RELIEF_SPELLINGS = ["PZV", "PZVs", "PSV", "PSVs", "PRV", "PRVs", "pressure relief valve",
                    "pressure relief valves", "pressure safety valves", "safety valve",
                    "safety valves", "safety relief valves", "pilot-operated relief valve",
                    "pilot-operated relief valves", "rupture disk", "rupture disks",
                    "rupture disc", "rupture discs", "bursting disc", "bursting discs"]


@pytest.mark.parametrize("spelling", RELIEF_SPELLINGS)
def test_every_relief_valve_spelling_means_a_relief_valve(spelling):
    vocab = subject_scope.vocabulary()
    requirement = {"requirement_text": f"The {spelling} shall be sealed and tested."}
    assert subject_scope.requirement_subject(requirement, {}, vocab) == ({"relief valve"}, "wording")


def test_a_requirement_about_pzvs_is_not_applied_to_a_pump_submittal():
    requirement = {"id": "r", "standard_document_id": "s", "clause": "9.1",
                   "requirement_text": "PZVs shall be set at the stated pressure."}
    result = subject_scope.gate([requirement], classification={"equipment_type": "Pump"}, facts=[])
    assert result["kept"] == []
    assert result["not_applied"][0]["subject"] == "relief valve"


def test_a_plural_needs_no_listing_of_its_own(tmp_path, monkeypatch):
    path = tmp_path / "vocab.json"
    path.write_text(json.dumps({"types": {"widget": {"kind": "equipment", "synonyms": ["thx"]}}}),
                    encoding="utf-8")
    vocab = subject_scope.vocabulary(path)
    assert vocab.equipment_in("The thxs shall be tested") == {"widget"}
    assert vocab.equipment_in("The widgets shall be tested") == {"widget"}
