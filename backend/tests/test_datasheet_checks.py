"""Owner order 2c: datasheet self-checks (kind B) - the sheet against itself.

Every rule, positive and negative, on made-up values (mutations M1056-M1064):
  * consistency (design >= operating, test > design, rated flow within min/max)
    by arithmetic ONLY on one scale - gauge against absolute, different units
    and two values under one name are skipped, never guessed;
  * mandatory fields present and not "TBA"/"by vendor";
  * units present and of the field's kind;
  * a revision block;
and end to end: with NO standard held, the review still gives Datasheet check
comments, cited to page and field, on the CRS.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import comparison, datasheet_checks as dc, db
from app.main import app

VESSEL = "Pressure Vessel"
PAGES = {1: "Rev Description Prepared Checked\n0 Issued for review"}


def fact(name, value, unit=None, *, page=1, normalized=None, norm_unit=None, blank=None, tag=None):
    return {"id": f"f-{name}-{value}-{tag}", "field_name": name, "field_label": name.capitalize(),
            "field_value": f"{value} {unit}".strip() if unit else value,
            "raw_value": value if blank is None else None, "raw_unit": unit,
            "normalized_value": normalized, "normalized_unit": norm_unit,
            "is_blank": 1 if blank else 0, "blank_marker": blank, "page": page,
            "equipment_tag": tag}


def run(facts, equipment_type=VESSEL, pages=PAGES):
    return {r["rule_id"]: r for r in dc.evaluate(facts, equipment_type=equipment_type, page_texts=pages)}


def P(name, value, unit="barg"):
    return fact(name, value, unit, normalized=float(value) / 10, norm_unit="MPa")


def full_vessel(**over):
    base = {"design pressure": P("design pressure", "23.5"),
            "operating pressure": P("operating pressure", "20"),
            "hydrotest pressure": P("hydrotest pressure", "30.6"),
            "design temperature": fact("design temperature", "120", "C", normalized=120.0, norm_unit="C"),
            "operating temperature": fact("operating temperature", "90", "C", normalized=90.0, norm_unit="C"),
            "corrosion allowance": fact("corrosion allowance", "3", "mm")}
    base.update(over)
    return [f for f in base.values() if f is not None]


def test_a_consistent_full_vessel_sheet_raises_nothing():
    results = run(full_vessel())
    assert {r["status"] for r in results.values()} == {"COMPLIANT"}, results


def test_design_pressure_below_operating_is_a_comment_with_the_calculation():
    """M1056."""
    r = run(full_vessel(**{"design pressure": P("design pressure", "18")}))["DS-C1"]
    assert r["status"] == "NON_COMPLIANT"
    assert r["detail"] == ("Design pressure 18 barg (page 1) is not at least operating "
                           "pressure 20 barg (page 1).")


def test_test_pressure_must_exceed_design_pressure():
    assert run(full_vessel(**{"hydrotest pressure": P("hydrotest pressure", "23.5")}))["DS-C3"]["status"] \
        == "NON_COMPLIANT"


def test_design_temperature_below_operating_is_a_comment():
    low = fact("design temperature", "80", "C", normalized=80.0, norm_unit="C")
    assert run(full_vessel(**{"design temperature": low}))["DS-C2"]["status"] == "NON_COMPLIANT"


@pytest.mark.parametrize("rated, rule", [("5", "DS-C4"), ("500", "DS-C5")])
def test_rated_flow_outside_min_max_is_a_comment(rated, rule):
    facts = [fact("rated flow", rated, "m3/h"), fact("minimum continuous flow", "10", "m3/h"),
             fact("maximum flow", "200", "m3/h")]
    results = run(facts, equipment_type="Centrifugal Pump")
    assert results[rule]["status"] == "NON_COMPLIANT"
    ok = run([fact("rated flow", "120", "m3/h"), fact("minimum continuous flow", "10", "m3/h"),
              fact("maximum flow", "200", "m3/h")], equipment_type="Centrifugal Pump")
    assert ok["DS-C4"]["status"] == ok["DS-C5"]["status"] == "COMPLIANT"


def test_gauge_against_absolute_is_skipped_not_guessed():
    """M1057: 18 bara against 20 barg cannot be compared without the site's
    atmospheric pressure - no result at all, rather than a wrong one."""
    absolute = fact("design pressure", "18", "bara", normalized=1.8, norm_unit="MPa")
    assert "DS-C1" not in run(full_vessel(**{"design pressure": absolute}))


def test_two_different_values_under_one_name_are_not_chosen_between():
    """M1058."""
    facts = full_vessel() + [P("design pressure", "15")]
    assert "DS-C1" not in run(facts)


def test_a_mandatory_field_absent_or_tba_is_a_missing_value():
    """M1059, M1060."""
    results = run(full_vessel(**{"corrosion allowance": None,
                                 "hydrotest pressure": fact("hydrotest pressure", "TBA", blank="TBA")}))
    assert results["DS-M1"]["status"] == "MISSING_INFORMATION"
    assert "Corrosion allowance was not found" in results["DS-M1"]["detail"]
    assert results["DS-M2"]["detail"].startswith("Hydrotest pressure is marked 'TBA' on page 1")


def test_no_mandatory_list_for_an_unknown_equipment_type():
    assert not [k for k in run(full_vessel(**{"corrosion allowance": None}), equipment_type=None)
                if k.startswith("DS-M")]


def test_a_value_without_its_unit_or_in_the_wrong_kind_of_unit():
    """M1061, M1062."""
    results = run(full_vessel(**{
        "corrosion allowance": fact("corrosion allowance", "3"),
        "operating pressure": fact("operating pressure", "20", "C")}))
    assert results["DS-U1"]["detail"] == "Corrosion allowance is stated as '3' on page 1 without a unit."
    assert results["DS-U2"]["status"] == "NON_COMPLIANT"
    assert "which is a temperature unit, not a pressure unit" in results["DS-U2"]["detail"]


def test_a_revision_block_is_looked_for():
    """M1063."""
    assert run(full_vessel())["DS-R1"]["status"] == "COMPLIANT"
    assert run(full_vessel(), pages={1: "DESIGN DATA\nDesign pressure 23.5 barg"})["DS-R1"]["status"] \
        == "MISSING_INFORMATION"


# ----------------------------------------------------------- end to end

@pytest.fixture
def vessel_run(tmp_path, monkeypatch):
    """A synthetic vessel sheet, reviewed with NO standard held."""
    import tests.test_b3_page_ledger as ledger_tests
    from app import datasheets, submittal_review
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "dc.sqlite")
    db.reset_connection(); db.init_db()
    submittal_review.ensure_schema(); submittal_review.migrate_facts_to_per_document()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ledger_tests, "ROWS", [
        ("Design pressure", "18 barg"), ("Operating pressure", "20 barg"),
        ("Hydrotest pressure", "TBA"), ("Design temperature", "120 C"),
        ("Operating temperature", "90 C"), ("Corrosion allowance", "3 mm")])
    sub = ledger_tests._sheet(tmp_path, notes_page=False)
    with db.connect() as conn:
        conn.execute("INSERT INTO document_classification (document_id,document_role,"
                     "equipment_type,suggested_by) VALUES (?,'CONTRACTOR_SUBMITTAL','Pressure Vessel','test')",
                     (sub,))
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    run_id = submittal_review.create_review_run(submittal_document_id=sub,
                                                allowed_document_ids=frozenset({sub}))
    comparison.run_comparison(run_id, allowed_document_ids=frozenset({sub}))
    yield sub, run_id
    db.reset_connection()


def test_with_no_standard_held_the_review_still_gives_datasheet_check_comments(vessel_run):
    """M1064: the owner's pump run gave 0 findings with 0 standards; kind B
    does not need one."""
    sub, run_id = vessel_run
    rows = [dict(r) for r in db.connect().execute(
        "SELECT compliance_status, origin, contractor_page, contractor_section, finding"
        " FROM review_findings WHERE review_run_id = ? AND origin = 'datasheet_check'", (run_id,))]
    by_text = {r["finding"]: r for r in rows}
    c1 = by_text["Datasheet check: Design pressure 18 barg (page 1) is not at least "
                 "operating pressure 20 barg (page 1)."]
    assert (c1["compliance_status"], c1["contractor_page"]) == ("NON_COMPLIANT", 1)
    assert any(r["finding"].startswith("Datasheet check: Hydrotest pressure is marked 'TBA'")
               for r in rows)

    view = TestClient(app).get(f"/api/reviews/runs/{run_id}/crs/preview").json()
    comments = [r for r in view["rows"] if "Datasheet check:" in r["comment"]]
    assert len(comments) >= 2
    # Every field check cites its page and field; the revision-block check is
    # about the whole sheet and cites no single page.
    field_rows = [r for r in comments if "revision block" not in r["comment"]]
    assert field_rows and all(r["page_section"].startswith("submittal p1 / ") for r in field_rows)
    assert all(r["comment_by"] == "AI Review" for r in comments)
