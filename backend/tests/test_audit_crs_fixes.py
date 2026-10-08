"""Audit 2026-09-30 (CRS and comparison engine): seven verified defects.

Synthetic data only - made-up standards, sheets and values; no client text.
Each test stands where its fix can fail it, and a positive control shows the
machinery still reaches the verdict it guards. Mutations M1430-M1449
(`scripts/mutations/audit_crs.py`), run with
`python scripts/mutation_check.py --only M1430,...`.
"""
from __future__ import annotations

import io
import uuid
import zipfile

import openpyxl
import pymupdf
from fastapi.testclient import TestClient

from app import (comparison, crs_export, crs_numbers, datasheet_checks, datasheets, db,
                 field_links, requirements_3b, standards, submittal_review)
from app.main import app
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_comparison import _chunk, _doc, _fact, _requirement, _run, _scope
from tests.test_model_matching import _signed_in
from tests.test_review_screen import _first_comment, _noise_rows, world  # noqa: F401

NOISE = ("Noise level shall not exceed 90 dB(A) at 1 m, except for pressure relief "
         "valves, which shall not exceed 115 dB(A).")


# ================================================ 1. equipment exceptions

def _noise_run(equipment_type: str | None) -> tuple[str, frozenset]:
    """A run whose one requirement carries the PSV exception, against a sheet
    stating 100 dB(A) - above the general 90, within the PSV's 115."""
    meta = {"equipment_type": equipment_type} if equipment_type else {}
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", **meta)
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    run = _run(sub)
    exceptions = requirements_3b.parse_exceptions(NOISE)
    assert exceptions and exceptions[0]["applies_to"] == "pressure relief valves"
    standards.create_requirement(
        standard_document_id=std, chunk_id=sc, requirement_text=NOISE,
        source_text=NOISE, clause="5.1", page=1,
        structured={"subject": "noise level", "operator": "<=", "raw_value": "90",
                    "raw_unit": "dB(A)", "requirement_type": "numeric_limit",
                    "exceptions": requirements_3b.encode_exceptions(exceptions)})
    datasheets.create_fact(submittal_document_id=sub, chunk_id=fc,
                           field_label="Noise level", raw_value="100 dB(A)", page=1)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,included,created_at)
            VALUES (?,?,?,'cited','referenced',1,'2026-09-30T00:00:00Z')""",
                     (str(uuid.uuid4()), run, std))
    return run, _scope(std, sub)


def _noise_status(run: str) -> str:
    return db.connect().execute(
        "SELECT compliance_status FROM review_findings WHERE review_run_id = ?"
        " AND requirement_id IS NOT NULL", (run,)).fetchone()[0]


def test_a_psv_sheet_gets_the_psv_exception_through_run_comparison():
    """M1430. The production path passed no subject, so the exception was dead
    and a PSV at 100 dB(A) was a breach. The classification's equipment type
    is the subject now."""
    run, scope = _noise_run("Pressure Safety Valve")
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert _noise_status(run) == comparison.COMPLIANT, \
        "the PSV exception (115 dB(A)) was not applied to a PSV sheet"


def test_an_unclassified_sheet_still_gets_the_general_limit():
    """The control: no equipment type -> no exception -> 100 > 90 is a breach."""
    run, scope = _noise_run(None)
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert _noise_status(run) == comparison.NON_COMPLIANT


def test_a_generic_subject_never_borrows_a_narrower_exception():
    """M1431. "valve" is not "pressure relief valve": the exception's words
    must all be in the subject, never the reverse."""
    requirement = {"exceptions": [{"applies_to": "pressure relief valves",
                                   "operator": "<=", "raw_value": "115"}]}
    assert comparison._applicable_exception(requirement, "Pressure Safety Valve")
    assert comparison._applicable_exception(requirement, "pressure relief valve")
    assert comparison._applicable_exception(requirement, "valve") is None
    assert comparison._applicable_exception(requirement, "Centrifugal Pump") is None
    assert comparison._applicable_exception(requirement, None) is None


# ================================================ 2. categorical clauses

def _cat(text: str, value: str):
    rule = field_links.categorical_requirement(text)
    return rule and field_links.compare_categorical(rule, value)


def test_alternatives_ceilings_and_prohibitions_read_what_they_say():
    """M1432, M1433, M1434. Each of these was a false NON_COMPLIANT."""
    assert _cat("Flanges shall be Class 150 or Class 300.", "CL300")["status"] == "COMPLIANT"
    assert _cat("Flange rating shall not exceed Class 600.", "Class 300")["status"] == "COMPLIANT"
    assert _cat("Class 150 flanges shall not be used.", "Class 300")["status"] == "COMPLIANT"
    # ...and each still catches the value it excludes.
    assert _cat("Flanges shall be Class 150 or Class 300.", "Class 600")["status"] == "NON_COMPLIANT"
    assert _cat("Flange rating shall not exceed Class 600.", "Class 900")["status"] == "NON_COMPLIANT"
    assert _cat("Class 150 flanges shall not be used.", "150")["status"] == "NON_COMPLIANT"
    assert _cat("Flanges shall be minimum Class 300.", "150")["status"] == "NON_COMPLIANT"


def test_not_required_is_no_requirement_at_all():
    """M1435. "not required" neither demands nor forbids: no categorical rule,
    so no verdict - the engineer reads it."""
    assert field_links.categorical_requirement(
        "Full radiography is not required for these welds.") is None
    assert field_links.categorical_requirement(
        "PWHT shall not be required for this thickness.") is None
    # "optional" states no "not", so only the not-required reading stops it
    # becoming a minimum of full radiography / an exact Class 300.
    assert field_links.categorical_requirement("Full radiography is optional.") is None
    assert field_links.categorical_requirement("Class 300 flanges are optional.") is None
    # Positive controls: the same families still read a positive clause.
    assert _cat("Full radiography shall be performed.", "spot")["status"] == "NON_COMPLIANT"
    assert _cat("PWHT shall be performed.", "No")["status"] == "NON_COMPLIANT"


def test_an_unrecognised_negation_or_class_list_gives_no_rule():
    """M1436. When unsure, no categorical requirement (engineer review)."""
    assert field_links.categorical_requirement(
        "Flanges shall not be Class 150 unless approved.") is None
    assert field_links.categorical_requirement(
        "Flanges shall be Class 150 and 300 as per table.") is None
    assert field_links.categorical_requirement(
        "Full radiography shall not be substituted by UT.") is None


def test_a_size_scoped_flange_clause_is_conditional():
    verdict = _cat("Flanges on nozzles 2 inch and larger shall be minimum Class 300.", "150")
    assert verdict["status"] == "NEEDS_ENGINEER_REVIEW"


def test_not_required_through_compare_is_not_a_breach():
    """The statement route (`compare`) reached the same false verdict."""
    for text, field, value in (
            ("Class 150 flanges shall not be used.", "Flange rating", "Class 300"),
            ("PWHT shall not be required for this thickness.", "PWHT", "Yes"),
            ("Full radiography is not required for these welds.", "Radiography", "SPOT")):
        limit = requirements_3b.parse_limit(text)
        req = dict(source_text=text, requirement_text=text,
                   requirement_type=requirements_3b.classify(text, limit), **(limit or {}))
        fact = dict(field_name=field, field_value=value, raw_value=value, raw_unit="")
        assert comparison.compare(req, fact, submittal_facts=[fact])["status"] \
            != comparison.NON_COMPLIANT, text


# ================================================ 3. common-section fields

def _f(i, name, value, tag):
    raw, _, unit = value.partition(" ")
    return dict(id=str(i), field_name=name, field_value=value, raw_value=raw,
                raw_unit=unit, page=1, equipment_tag=tag)


def test_untagged_fields_count_for_every_tag_on_the_sheet():
    """M1437. Design conditions stated once for P-101A/B are not missing."""
    facts = [_f(1, "Design pressure", "20 barg", None),
             _f(2, "Design temperature", "150 °C", None),
             _f(3, "Operating temperature", "80 °C", None),
             _f(4, "Rated flow", "100 m3/h", "P-101A"),
             _f(5, "Rated flow", "100 m3/h", "P-101B")]
    missing = [r for r in datasheet_checks.evaluate(
        facts, equipment_type="Centrifugal Pump", page_texts={1: "x"})
        if r["rule_id"] == "DS-M1"]
    assert missing == [], [(r["equipment_tag"], r["detail"]) for r in missing]


def test_a_tags_own_value_is_never_lent_to_another_tag():
    """M1438. P-101A's operating temperature does not answer for P-101B."""
    facts = [_f(1, "Design pressure", "20 barg", None),
             _f(2, "Design temperature", "150 °C", None),
             _f(3, "Operating temperature", "80 °C", "P-101A"),
             _f(4, "Rated flow", "100 m3/h", "P-101A"),
             _f(5, "Rated flow", "100 m3/h", "P-101B")]
    missing = [(r["equipment_tag"], r["field"]) for r in datasheet_checks.evaluate(
        facts, equipment_type="Centrifugal Pump", page_texts={1: "x"})
        if r["rule_id"] == "DS-M1"]
    assert ("P-101B", "Operating temperature") in missing
    assert all(tag == "P-101B" for tag, _field in missing), missing


# ================================================ 4. "Label : value" lines

LINES = ["Service : Fuel gas outlet", "Set Pressure : 12.5 barg",
         "Design Pressure : 10 barg", "Design Temperature : 120 C",
         "Wall Thickness (inlet pipe) : 2.5 mm", "Back Pressure : TBA",
         "Noise Level : *"]


def test_one_field_per_line_is_read_line_by_line(tmp_path):
    """M1439. Every line was paired with the next: 2 of 15 fields read."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 80
    for line in LINES:
        page.insert_text((60, y), line, fontsize=10)
        y += 15
    path = tmp_path / "ds.pdf"
    doc.save(str(path))
    pairs = datasheets._pairs_from_pdf_page(str(path), 1)
    assert pairs == [tuple(p.strip() for p in line.split(" : ")) for line in LINES]


def test_a_two_line_label_value_block_still_pairs():
    """The control: the pre-existing shape is unchanged."""
    assert datasheets.pairs_from_blocks([(0, 0, "Design pressure\n23.5 barg")]) == \
        [("Design pressure", "23.5 barg")]
    # A time or a ratio is not a label/value split.
    assert datasheets._self_contained_pair("Start 10:30") is None


# ================================================ 5. export safety

def _cells(data: bytes):
    book = openpyxl.load_workbook(io.BytesIO(data))
    return [c for ws in book.worksheets for row in ws.iter_rows() for c in row
            if c.value is not None]


def test_formula_text_is_written_as_text_never_a_formula():
    """M1440. Contractor reply, document name, section and reference."""
    payload = "=HYPERLINK(\"http://example.test\",\"x\")"
    rows = [{"document_name": "=1+1", "page_section": "+2+3", "comment": "-4+5",
             "comment_by": "@SUM(A1)", "crs_ref": "CRS-X-001",
             "crs_response": payload, "standard_reference": "=cmd|' /C x'!A0"}]
    data = crs_export.build_crs(rows, {"review_run_id": "r", "document_title": "=2+2"})
    cells = _cells(data)
    assert not [c.coordinate for c in cells if c.data_type == "f"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet and "<f " not in sheet
    assert payload in [c.value for c in cells], "the words received are printed unchanged"


def test_a_control_character_does_not_fail_the_export():
    """M1441. One stray byte failed the whole workbook."""
    rows = [{"document_name": "d\x00", "comment": "bad\x07char\x1f", "crs_ref": "CRS-X-001",
             "crs_response": "reply\x0b"}]
    data = crs_export.build_crs(rows, {"review_run_id": "r"})
    values = [c.value for c in _cells(data)]
    assert "bad char " in values


def test_an_unreadable_value_is_not_blamed_on_matching_units():
    """M1442. "unit 'mm' and 'mm' cannot be compared" was a false reason."""
    req = dict(raw_value="3", raw_unit="mm", operator=">=",
               requirement_type="numeric_limit", source_text="x")
    fact = dict(raw_value="see note", raw_unit="mm", field_value="see note mm", field_name="x")
    out = comparison.compare(req, fact, submittal_facts=[fact])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "could not be read as a number" in out["rationale"]
    assert "cannot be compared" not in out["rationale"]


# ================================================ low-trust values

def test_a_breach_on_an_untrusted_value_is_held_for_the_engineer():
    """M1443. OCR-fallback / needs-review / conflict / model-read values."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    sc = _chunk("sc", std); fc = _chunk("fc", sub)
    trusted = _fact(sub, fc, raw_value="95")
    assert comparison.compare(_requirement(std, sc), trusted)["status"] == comparison.NON_COMPLIANT
    for extra in ({"validation_state": datasheets.NEEDS_ENGINEER_REVIEW},
                  {"validation_state": datasheets.GEOMETRY_CONFLICT},
                  {"extraction_method": "model"}):
        held = comparison.compare(_requirement(std, sc), {**trusted, **extra})
        assert held["status"] == comparison.NEEDS_ENGINEER_REVIEW, extra
        assert held["rationale"].startswith(comparison.LOW_TRUST_VALUE)
    # An engineer's confirmation of the value makes it trusted again.
    confirmed = {**trusted, "extraction_method": "model", "confirmed_by": "eng"}
    assert comparison.compare(_requirement(std, sc), confirmed)["status"] == comparison.NON_COMPLIANT


def test_the_low_trust_spellings_are_the_datasheet_modules_own():
    assert {datasheets.NEEDS_ENGINEER_REVIEW, datasheets.GEOMETRY_CONFLICT} \
        == set(comparison._LOW_TRUST_STATES)


def test_a_low_confidence_fact_is_never_a_breach_through_run_comparison():
    """M1444. Through the pipeline: `create_fact` routes confidence below the
    threshold to needs_engineer_review, and the run holds the breach."""
    run, scope = _noise_run(None)
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET validation_state = ?",
                     (datasheets.NEEDS_ENGINEER_REVIEW,))
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert _noise_status(run) == comparison.NEEDS_ENGINEER_REVIEW


# ================================================ 6. re-runs keep decisions

def _rows(run, copy="internal"):
    response = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview?copy={copy}")
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def test_a_rejection_survives_a_re_run_and_is_not_proposed_again(world, monkeypatch):
    """M1445, M1446. The rejected finding stays, and no fresh draft of the
    same pair comes back on the sheet."""
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    assert _noise_rows(run), "positive control: the comment is on the sheet"
    client = TestClient(app)
    assert client.patch(f"/api/reviews/findings/{finding_id}",
                        json={"approval_status": "rejected"}).status_code == 200
    assert not _noise_rows(run)
    comparison.run_comparison(run, allowed_document_ids=scope)
    kept = db.connect().execute(
        "SELECT approval_status FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    assert kept is not None and kept[0] == "rejected", "the re-run deleted the rejection"
    assert not _noise_rows(run), "the rejected comment came back as a new draft"


def test_an_acceptance_survives_a_re_run(world, monkeypatch):
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    assert TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                 json={"approval_status": "accepted"}).status_code == 200
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert db.connect().execute(
        "SELECT approval_status FROM review_findings WHERE id = ?",
        (finding_id,)).fetchone()[0] == "accepted"


# ================================================ 7. rejected is never issued

def test_a_confirmed_then_rejected_comment_is_never_issued(world, monkeypatch):
    """M1447, M1448. Confirming numbered it; rejecting it before issue must
    withdraw it - not print it as "carried forward" on the issue copy."""
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    client = TestClient(app)
    client.patch(f"/api/reviews/findings/{finding_id}", json={"confirmed": True})
    [row] = _noise_rows(run)
    ref = row["crs_ref"]
    assert ref.startswith("CRS-") and ref in [r["crs_ref"] for r in _rows(run, "issue")]
    client.patch(f"/api/reviews/findings/{finding_id}", json={"approval_status": "rejected"})
    assert ref not in [r["crs_ref"] for r in _rows(run, "issue")]
    assert ref not in [r["crs_ref"] for r in _rows(run)]
    statuses = [r[0] for r in db.connect().execute("SELECT status FROM crs_comment_numbers")]
    assert statuses == [crs_numbers.WITHDRAWN]
    # Accepting it again re-opens the SAME number - never a new one.
    client.patch(f"/api/reviews/findings/{finding_id}", json={"approval_status": "accepted"})
    [row] = _noise_rows(run)
    assert row["crs_ref"] == ref and row["final_resolution"] == "Open"


def test_a_withdrawn_comment_raised_again_by_a_new_run_is_only_a_draft(world, monkeypatch):
    """M1444. A later run of the same sheet raises the same comment as a
    machine draft. Its withdrawn number must not make it "confirmed", which
    would issue the rejected comment on the new run's contractor copy."""
    sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    client = TestClient(app)
    client.patch(f"/api/reviews/findings/{finding_id}", json={"confirmed": True})
    [row] = _noise_rows(run)
    ref = row["crs_ref"]
    client.patch(f"/api/reviews/findings/{finding_id}", json={"approval_status": "rejected"})
    again = submittal_review.create_review_run(submittal_document_id=sub,
                                               allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,included,created_at)
            VALUES (?,?,'doc_std','cited','referenced',1,'2026-09-30T00:00:00Z')""",
                     (str(uuid.uuid4()), again))
    comparison.run_comparison(again, allowed_document_ids=scope)
    drafts = _noise_rows(again)
    assert drafts, "positive control: the new run raises the comment as a draft"
    assert all(r["crs_ref"] != ref for r in drafts)
    assert ref not in [r["crs_ref"] for r in _rows(again, "issue")]
    assert not [r for r in _rows(again, "issue") if "95 dB(A)" in r["comment"]]


def test_a_confirmed_comment_is_signed_with_the_engineers_name(world, monkeypatch):
    """M1449. The byline printed the raw user id ("eng-1"); `_signed_in`
    names its engineer "Engineer"."""
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    TestClient(app).patch(f"/api/reviews/findings/{finding_id}", json={"confirmed": True})
    [row] = _noise_rows(run)
    assert row["comment_by"] == "AI Review, confirmed by Engineer"
