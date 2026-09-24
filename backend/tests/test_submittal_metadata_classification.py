"""#176: evidence-based title-block fields for CONTRACTOR_SUBMITTAL documents.

`document_number`, `revision`, `project`, `service`, `equipment_tags` and
`discipline` were written only by `classification.confirm()` (admin PUT) and
were NULL for every real submittal. This file proves the automated writer
that now fills them from the document's OWN title-block text - and, just as
much, proves where it refuses to.

TWO LAYERS, deliberately:

  * `suggest_submittal_metadata` over page text directly, for the near-miss
    cases. Each near-miss is a line SHAPE measured on the three real
    regression datasheets (a pump datasheet, a PSV datasheet, a vessel
    datasheet): "SERVICE ORDER NO.", "Sour service :", "SUBCONTRACTOR DOC NO:
    NA", "CONTRACT NO:", a revision-table header "Rev." with a row number on
    the next line, a "SERVICE: ___CONTINUOUS" duty field, a nozzle-table
    "Service" column header. Every one of them is text a looser pattern would
    have turned into a confident wrong value.
  * The REAL ingestion path (`POST /api/documents` -> set role -> worker to
    READY), for the wiring, the storage, the audit trail and the guards -
    the same reason `test_equipment_type_classification.py` gives: calling
    the classifier directly proves it works, not that ingestion runs it.

ANONYMISED. The fixtures reproduce the real title blocks' LAYOUT (labels,
line breaks, underscore-filled form cells, parenthetical remarks) with
invented numbers, names and tags. No real project number, document number,
tag or company name appears here.
"""

from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import classification, db, states
from app import submittal_review
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


# ================================================================= fixtures
#
# Shapes copied from the real regression datasheets' page text as PyMuPDF
# extracts it; every identifier invented.

PUMP_P1 = """Sheet 1 of 7
SOME OPERATOR COMPANY (X.Y.Z.)
Project: RFP - 1234567
Installation of New Units at AREA-01, AREA-02
RECYCLE WATER PUMPS DATA SHEET
Item No.: 01-G-101 A/B, 02-G-101 A/B &
03-G-201 A/B
Doc. No.: ABC-DAS-M-01
This document is subject to detail design verification.
Revised and Issued with
Supplementary Letter No. 6
Rev.
Revision
By
Date
"""

PUMP_P2 = """SOME OPERATOR COMPANY
CENTRIFUGAL PUMP DATA SHEET
RECYCLE WATER PUMPS
DATA SHEET NO.: ABC-DAS-M-01
PROJECT NO.: RFP - 1234567
Sheet 2 of 7
Rev. No.: 4
Rev.
2
Item No. 01-G-101 A/B, 02-G-101 A/B & 03-G-201 A/B
SERVICE
______________RECYCLE WATER PUMPS______________
MANUFACTURER
*___
LIQUID CHARACTERISTICS
SERVICE:
_________CONTINUOUS
MECHANICAL SEAL (6.8.1)
"""

PSV_P1 = """Page 1 of 5
SOME OPERATOR COMPANY
DATA SHEET FOR
PRESSURE SAFETY VALVES (PSVs)
DOCUMENT NO. ABC-DAS-I-02
PROJECT NO. AB/1234
Sheet 1 of 6
Rev. 1
MAKE / MFR. MODEL NO.
Design Standard: API RP 520 Pt-1&2
Tag No. PSV-1001 A/B (for AREA-9, 10 & 19) & PSV-2001 A/B (for AREA-21)
Location
1st Stage Separator
Fluid
Crude Oil/Gas (Dual Service)
Mfr. drawing no.
"""

PSV_P2 = """SOME OPERATOR COMPANY
DATA SHEET FOR
PRESSURE SAFETY VALVES (PSVs)
DOCUMENT NO. ABC-DAS-I-02
PROJECT NO. AB/1234
Sheet 2 of 6
Rev. 1
Tag No. PSV-1003 A/B (for AREA-9, 10 & 19) & PSV-2003 A/B (for AREA-21)
"""

VESSEL_P1 = """SOME FIELD DEVELOPMENT PROGRAM (SFDP)
SOME JOINT OPERATIONS
OFFSHORE & ONSHORE FACILITIES PROJECT (COMMON)
CONTRACT NO: XY001AB23
SERVICE ORDER NO. 001-SFDP-2023
Rev. 00
Uncontrolled When Printed
MECHANICAL DATASHEET
SOME ONSHORE FACILITY
SOUR WATER DRUMS
(1234-47-V-0001A/B)
CONTRACTOR DOC NO: 9999X-1234-SP-0810-0003
SUBCONTRACTOR DOC NO: NA
LICENSOR DOC NO: NA
00
Issued for Final
Rev.
Date
"""

VESSEL_P2 = """MECHANICAL DATASHEET SOUR WATER DRUMS
DWG TYPE
TAG No. : 1234-47-V-0001A/B
REV NO
00
Tag number :
1234-47-V-0001A/B
Tag description :
Sour Water Drums
Project country :
Some Country
Sour service :
NACE MR0175/ISO 15156
Amine service :
no
Service
2003
"""

NO_EVIDENCE = """TRANSMITTAL COVER SHEET
Project Correspondence
Subject: Response to comments received on the previous submission
Reference: Letter 4521 dated earlier this month regarding scheduling
Nothing on this page carries a labelled title-block field.
"""


def _pages(*texts: str) -> list[dict]:
    return [{"page_no": i, "text": t} for i, t in enumerate(texts, start=1)]


def _suggest(*texts: str):
    return classification.suggest_submittal_metadata(_pages(*texts))


# ======================================== the classifier, over page text


def test_the_pump_title_block_yields_each_labelled_field_with_its_page():
    found = _suggest(PUMP_P1, PUMP_P2).found

    assert found["document_number"].value == "ABC-DAS-M-01"
    assert found["document_number"].page == 1
    assert found["document_number"].quote == "Doc. No.: ABC-DAS-M-01"

    # Page 1 carries only the revision TABLE; the labelled value is page 2's.
    assert found["revision"].value == "4"
    assert found["revision"].page == 2
    assert found["revision"].quote == "Rev. No.: 4"

    assert found["project"].value == "RFP - 1234567"
    assert found["project"].page == 1

    assert found["service"].value == "RECYCLE WATER PUMPS"
    assert found["service"].page == 2

    # A wrapped "&" continuation on page 1 and the full list on page 2 agree.
    assert found["equipment_tags"].value == [
        "01-G-101 A/B", "02-G-101 A/B", "03-G-201 A/B"]

    # "CENTRIFUGAL PUMP DATA SHEET" names equipment, not a discipline.
    assert "discipline" not in found

    for evidence in found.values():
        assert evidence.confidence < 0.9, "confidence is never 'high'"
        assert evidence.classifier_version == \
            classification.SUBMITTAL_METADATA_CLASSIFIER_VERSION


def test_the_psv_title_block_yields_tags_without_the_parenthetical_remarks():
    found = _suggest(PSV_P1, PSV_P2).found

    assert found["document_number"].value == "ABC-DAS-I-02"
    assert found["revision"].value == "1"
    assert found["project"].value == "AB/1234"
    # Union across pages, in reading order. "AREA-9" lives only inside a
    # "(for AREA-9, 10 & 19)" remark and is a location, never a tag.
    assert found["equipment_tags"].value == [
        "PSV-1001 A/B", "PSV-2001 A/B", "PSV-1003 A/B", "PSV-2003 A/B"]
    assert found["equipment_tags"].pages == [1, 2]
    # "Fluid ... (Dual Service)" is not a SERVICE label.
    assert "service" not in found
    assert "discipline" not in found


def test_the_vessel_title_block_yields_contractor_number_and_discipline():
    found = _suggest(VESSEL_P1, VESSEL_P2).found

    assert found["document_number"].value == "9999X-1234-SP-0810-0003"
    assert found["document_number"].quote == \
        "CONTRACTOR DOC NO: 9999X-1234-SP-0810-0003"
    assert found["revision"].value == "00", "'00' is the sheet's own spelling"
    assert found["discipline"].value == "Mechanical"
    assert found["discipline"].page == 1
    assert found["discipline"].quote == "MECHANICAL DATASHEET"
    assert found["equipment_tags"].value == ["1234-47-V-0001A/B"]
    # No labelled project number: "FACILITIES PROJECT (COMMON)" is a name,
    # "CONTRACT NO" is a contract and "Project country" is a country.
    assert "project" not in found
    # "SERVICE ORDER NO.", "Sour service :", "Amine service :" and a nozzle
    # table's "Service" header are none of them the equipment's service.
    assert "service" not in found


def test_a_page_with_no_labelled_fields_yields_nothing():
    result = _suggest(NO_EVIDENCE)
    assert result.found == {}
    assert result.conflicts == {}


# ------------------------------------------------------------- near misses
#
# ONE SNIPPET PER CASE, never several in one page: two near-misses that both
# (wrongly) matched with different values would be a CONFLICT, the field
# would stay NULL, and the test would pass while the pattern was broken.


@pytest.mark.parametrize("snippet", [
    "CONTRACT NO: XY001AB23\n",
    "SUBCONTRACTOR DOC NO: 1234-AB-0001\n",
    "LICENSOR DOC NO: 1234-AB-0002\n",
    "DOCUMENT NO.: NA\n",
    "Doc. No.: ____________\n",
    "Mfr. drawing no. 12-34-56\n",
    "SPECIFICATION NO. ____SPEC-P-001____\n",
])
def test_document_number_near_misses_stay_unknown(snippet):
    assert "document_number" not in _suggest(snippet).found


@pytest.mark.parametrize("snippet", [
    # The real pump sheet's page-2 layout: a "Rev." column header with the
    # form's ROW NUMBER on the next line. Only a value on the label's own
    # line is a revision.
    "Rev.\n2\n",
    "Rev \n3\n",
    "REV NO\n00\n",
    "Revision\nA\n",
    "Revised and Issued with\n",
])
def test_a_revision_table_row_number_is_not_a_revision(snippet):
    assert "revision" not in _suggest(snippet).found


def test_disagreeing_revisions_are_a_conflict_not_a_pick():
    result = _suggest("Rev. 1\n", "Rev. 2\n")
    assert "revision" not in result.found
    assert sorted(result.conflicts["revision"]) == ["1", "2"]


def test_disagreeing_document_numbers_are_a_conflict_not_a_pick():
    result = _suggest("Doc. No.: ABC-DAS-M-01\n", "Doc. No.: ABC-DAS-M-02\n")
    assert "document_number" not in result.found
    assert "document_number" in result.conflicts


@pytest.mark.parametrize("snippet", [
    "Project: A Refinery Debottlenecking Project\n",
    "Project country : Some Country 2\n",
    "Project region : Region 7\n",
    "OFFSHORE & ONSHORE FACILITIES PROJECT (COMMON)\n",
    "SOME STANDARD FOR PROJECT QA/QC REQUIREMENTS\n",
])
def test_a_project_name_without_an_identifier_is_not_recorded(snippet):
    assert "project" not in _suggest(snippet).found


@pytest.mark.parametrize("snippet", [
    "SERVICE ORDER NO. 001-SFDP-2023\n",
    "Sour service :\nNACE MR0175/ISO 15156\n",
    "Sour service : NACE MR0175/ISO 15156\n",
    "Amine service : no\n",
    "SERVICE FACTOR ________________\n",
    "Crude Oil/Gas (Dual Service)\n",
    "Service\n2003\n",
    "Service\nInlet\n",
])
def test_service_near_misses_stay_unknown(snippet):
    assert "service" not in _suggest(snippet).found


def test_a_duty_field_labelled_service_is_not_the_equipment_service():
    # API 610's "LIQUID CHARACTERISTICS / SERVICE: CONTINUOUS" names the duty
    # cycle, not what the pump is for.
    found = _suggest("LIQUID CHARACTERISTICS\nSERVICE:\n_________CONTINUOUS\n").found
    assert "service" not in found


@pytest.mark.parametrize("snippet", [
    "TAG ALL ORIFICES (7.5.2.4) __________\n",
    "Tag description : Sour Water Drums\n",
    "ITEM No\nPUMP DRIVER GEAR BASE TOTAL\n",
    "Tag number :\n1234-47-V-0001A/B\n",
    "Item No.: (for AREA-9 & AREA-10)\n",
])
def test_tag_near_misses_stay_unknown(snippet):
    assert "equipment_tags" not in _suggest(snippet).found


@pytest.mark.parametrize("snippet", [
    "This document is based on the Process Datasheet ABC-PDS-0001\n",
    "MECHANICAL SEAL (6.8.1)\n",
    "ABC-DAS-E-   MOTOR DATA SHEET\n",
    "Vendor shall submit complete API 682 Seal Data Sheet\n",
])
def test_discipline_near_misses_on_the_title_page_stay_unknown(snippet):
    assert "discipline" not in _suggest(snippet).found


def test_discipline_is_read_from_the_title_block_page_only():
    # The same title phrase on a BODY page names a section, not this
    # document's discipline.
    found = _suggest("SOME CLIENT\nTITLE PAGE WITHOUT A DISCIPLINE\n",
                     "MECHANICAL DATASHEET SOUR WATER DRUMS\n").found
    assert "discipline" not in found


# ================================================= the real ingestion path


def _pdf(path, pages: list[str]) -> str:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=612, height=792)
        y = 40
        for line in text.splitlines():
            page.insert_text((40, y), line, fontsize=9)
            y += 13
    doc.save(str(path))
    doc.close()
    return str(path)


def _upload(client, tmp_path, name, pages) -> str:
    path = _pdf(tmp_path / name, pages)
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")})
    assert resp.status_code == 200, resp.text
    return resp.json()["document"]["id"]


def _run_to_settled(doc_id: str) -> str:
    worker = IngestionWorker()
    status = None
    for _ in range(10):
        worker.process(doc_id)
        status = db.connect().execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()["status"]
        if status in (states.READY, states.FAILED, states.NO_SEARCHABLE_CONTENT):
            break
    return status


def _submittal(client, tmp_path, name, pages) -> str:
    doc_id = _upload(client, tmp_path, name, pages)
    assert classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    assert _run_to_settled(doc_id) == states.READY
    return doc_id


def _row(doc_id: str) -> dict:
    row = db.connect().execute(
        "SELECT * FROM document_classification WHERE document_id = ?",
        (doc_id,)).fetchone()
    return dict(row) if row else {}


def _evidence(doc_id: str) -> dict:
    return json.loads(_row(doc_id)["field_evidence"] or "{}")


def _audits(doc_id: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM audit_events WHERE action = ? AND resource_id = ?",
        (classification.FIELD_RECLASSIFIED_ACTION, doc_id))]


def test_ingestion_writes_the_vessel_fields_with_evidence(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "vessel.pdf",
                        [VESSEL_P1, VESSEL_P2])
    row = _row(doc_id)
    assert row["document_number"] == "9999X-1234-SP-0810-0003"
    assert row["revision"] == "00"
    assert row["discipline"] == "Mechanical"
    # Rule 8: the canonical column is derived at the same write.
    assert row["discipline_canonical"] == "Mechanical"
    assert json.loads(row["equipment_tags"]) == ["1234-47-V-0001A/B"]
    assert row["project"] is None
    assert row["service"] is None
    assert row["contractor_vendor"] is None, "out of scope - never written"

    evidence = _evidence(doc_id)
    assert set(evidence) == {
        "document_number", "revision", "discipline", "equipment_tags"}
    number = evidence["document_number"]
    assert number["page"] == 1
    assert number["quote"] == "CONTRACTOR DOC NO: 9999X-1234-SP-0810-0003"
    assert number["method"] == "title_block_label"
    assert number["confidence"] < 0.9
    assert number["classifier_version"] == \
        classification.SUBMITTAL_METADATA_CLASSIFIER_VERSION
    # First classification: nothing to supersede, nothing audited.
    assert _audits(doc_id) == []


def test_ingestion_writes_the_pump_service_and_project(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "pump.pdf",
                        [PUMP_P1, PUMP_P2])
    row = _row(doc_id)
    assert row["service"] == "RECYCLE WATER PUMPS"
    assert row["project"] == "RFP - 1234567"
    assert row["revision"] == "4"
    assert row["discipline"] is None


# ============================================ the generalization proof
#
# THE 3 REAL REGRESSION DATASHEETS ARE REGRESSION CHECKS, NOT THE TARGET
# (owner instruction, 2026-09-25). This SYNTHETIC document - a different
# company, a different project-number style, a letter revision instead of
# a number, a different discipline word (Piping, not Mechanical), a
# different label wording throughout - proves the classifier reads LABEL
# SHAPES from the document's own text, not the three real documents'
# specific wording. Invented numbers and names throughout; the word
# SYNTHETIC in every fixture name so nobody mistakes it for a real sheet.

SYNTHETIC_PIPING_P1 = (
    "GLOBAL ENERGY CONTRACTING LLC\n"
    "PROJECT NO. GEC-55521\n"
    "DOC. NO.: SYN-0007-PP-0099\n"
    "Rev. No.: B\n"
    "\n"
    "PIPING DATA SHEET\n"
    "CENTRIFUGAL PUMPS\n"
    "\n"
    "SERVICE:  DESALTED CRUDE TRANSFER\n"
    "TAG NO.: P-7701A/B\n"
)

SYNTHETIC_NEGATIVE_P1 = (
    "GLOBAL ENERGY CONTRACTING LLC\n"
    "This datasheet supports the piping package for the new transfer pumps.\n"
    "Document identifiers and revision history are maintained in the\n"
    "vendor's own document control system and are not printed on this sheet.\n"
    "SERVICE ORDER NO.: 4471\n"
    "CONTRACT NO.: GEC-9000\n"
)


def test_synthetic_datasheet_with_a_different_layout_classifies_correctly(tmp_path):
    """THE GENERALIZATION PROOF. Every label here is worded, ordered and
    punctuated differently from all three real regression fixtures (a
    letter revision "B" instead of a number; "PIPING DATA SHEET" instead
    of "MECHANICAL DATASHEET"/blank; "DOC. NO.:" instead of "CONTRACTOR
    DOC NO:"/"DATA SHEET NO.:"; a different project-number shape). If this
    passes, the classifier is reading label SHAPES, not memorised text."""
    doc_id = _submittal(TestClient(app), tmp_path, "synthetic-piping.pdf",
                        [SYNTHETIC_PIPING_P1])
    row = _row(doc_id)
    assert row["document_number"] == "SYN-0007-PP-0099"
    assert row["revision"] == "B"
    assert row["project"] == "GEC-55521"
    assert row["service"] == "DESALTED CRUDE TRANSFER"
    assert row["discipline"] == "Piping"
    assert json.loads(row["equipment_tags"]) == ["P-7701A/B"]
    assert row["equipment_type"] == "Centrifugal Pump"

    evidence = _evidence(doc_id)
    for field in ("document_number", "revision", "project", "service",
                 "discipline", "equipment_tags"):
        assert evidence[field]["page"] == 1
        assert evidence[field]["quote"], f"{field} has no quote"


def test_synthetic_datasheet_with_no_real_labels_stays_entirely_unknown(tmp_path):
    """THE NEGATIVE CASE THE GENERALIZATION PROOF REQUIRES. Plausible
    prose mentions "pumps" and a project in passing, and two near-miss
    labels ("SERVICE ORDER NO.", "CONTRACT NO.") that are shaped like the
    real fields but are not them - none of it is a label this classifier
    recognises, so every field must stay NULL. A novel layout is not
    license to guess."""
    doc_id = _submittal(TestClient(app), tmp_path, "synthetic-negative.pdf",
                        [SYNTHETIC_NEGATIVE_P1])
    row = _row(doc_id)
    for name in ("document_number", "revision", "project", "service",
                 "discipline"):
        assert row[name] is None, name
    assert row["equipment_type"] is None
    assert row["equipment_tags"] is None
    assert row["field_evidence"] is None


def test_a_document_without_evidence_keeps_every_field_null(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "cover.pdf", [NO_EVIDENCE])
    row = _row(doc_id)
    for name in ("document_number", "revision", "project", "service",
                 "discipline", "contractor_vendor"):
        assert row[name] is None, name
    assert row["equipment_tags"] is None
    assert row["field_evidence"] is None
    # Direct call too: the ingest hook swallows exceptions, so a crash would
    # look exactly like "nothing matched" from the stored row alone.
    assert classification.classify_metadata_for_submittal(doc_id) == {}


def test_a_company_standard_is_never_given_submittal_fields(tmp_path):
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "standard.pdf", [VESSEL_P1])
    classification.set_role(doc_id, "COMPANY_STANDARD")
    assert _run_to_settled(doc_id) == states.READY
    row = _row(doc_id)
    assert row["document_number"] is None
    assert row["field_evidence"] is None


def test_a_value_the_classifier_did_not_write_is_never_overwritten(tmp_path):
    """A discipline set by someone else (the standards backfill's
    `set_discipline`, or the register tier) is not the classifier's to
    replace - it has no evidence entry of the classifier's own."""
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "vessel.pdf", [VESSEL_P1, VESSEL_P2])
    classification.set_role(doc_id, "CONTRACTOR_SUBMITTAL")
    classification.set_discipline(doc_id, "Process (Licensor)")
    assert _run_to_settled(doc_id) == states.READY

    row = _row(doc_id)
    assert row["discipline"] == "Process (Licensor)"
    assert "discipline" not in _evidence(doc_id)
    # The other fields were NULL and are still filled.
    assert row["document_number"] == "9999X-1234-SP-0810-0003"


def test_a_confirmed_classification_is_left_alone(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "vessel.pdf",
                        [VESSEL_P1, VESSEL_P2])
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('admin1','admin@example.test','Admin','h',"
            "'2026-09-07T00:00:00Z')")
    classification.confirm(
        doc_id, doc_type=None, discipline=None, doc_class=None, subject_ids=[],
        confirmed_by="admin1",
        metadata={"document_role": "CONTRACTOR_SUBMITTAL",
                  "document_number": "TYPED-BY-ADMIN-1"})
    row = _row(doc_id)
    assert row["document_number"] == "TYPED-BY-ADMIN-1"
    # confirm() REPLACED discipline and every metadata field, so the
    # classifier's page/quote for them would now misdescribe the row.
    evidence = _evidence(doc_id)
    assert "document_number" not in evidence
    assert "discipline" not in evidence
    # Tags were not part of this PUT, so their evidence still describes them.
    assert "equipment_tags" in evidence

    assert classification.classify_metadata_for_submittal(doc_id) == {}
    assert _row(doc_id)["document_number"] == "TYPED-BY-ADMIN-1"


def _rewrite_page(doc_id: str, page_no: int, text: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE pages SET text = ? WHERE document_id = ?"
                     " AND page_no = ?", (text, doc_id, page_no))


def test_reclassification_is_audited_and_the_old_value_kept(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "vessel.pdf",
                        [VESSEL_P1, VESSEL_P2])
    assert _row(doc_id)["revision"] == "00"

    _rewrite_page(doc_id, 1, VESSEL_P1.replace("Rev. 00", "Rev. 01"))
    from app import ingest as ingest_mod
    ingest_mod._classify_metadata_if_contractor_submittal(doc_id)

    assert _row(doc_id)["revision"] == "01"
    audits = _audits(doc_id)
    assert len(audits) == 1, audits
    detail = json.loads(audits[0]["detail"])
    assert detail["field"] == "revision"
    assert detail["classifier_version"] == \
        classification.SUBMITTAL_METADATA_CLASSIFIER_VERSION
    # PRIVACY: a free-text field's values are document text and never enter
    # the audit log (db.py: "Response-safe detail only").
    assert "00" not in json.dumps(detail) and "01" not in json.dumps(detail)
    # ...so the superseded value is kept beside the field, in the row.
    superseded = _evidence(doc_id)["revision"]["superseded"]
    assert [s["value"] for s in superseded] == ["00"]


def test_a_controlled_vocabulary_reclassification_names_old_and_new(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "vessel.pdf",
                        [VESSEL_P1, VESSEL_P2])
    _rewrite_page(doc_id, 1, VESSEL_P1.replace(
        "MECHANICAL DATASHEET", "PROCESS DATASHEET"))
    classification.classify_metadata_for_submittal(doc_id)

    assert _row(doc_id)["discipline"] == "Process"
    detail = json.loads(_audits(doc_id)[0]["detail"])
    assert (detail["field"], detail["old"], detail["new"]) == (
        "discipline", "Mechanical", "Process")


def test_rerunning_over_unchanged_text_does_not_audit(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "vessel.pdf",
                        [VESSEL_P1, VESSEL_P2])
    classification.classify_metadata_for_submittal(doc_id)
    classification.classify_metadata_for_submittal(doc_id)
    assert _audits(doc_id) == []


def test_of_document_decodes_the_field_evidence(tmp_path):
    doc_id = _submittal(TestClient(app), tmp_path, "vessel.pdf",
                        [VESSEL_P1, VESSEL_P2])
    record = classification.of_document(doc_id)
    assert record["field_evidence"]["revision"]["page"] == 1
