"""W5b-07 (#531): internal consistency of numeric tables. INVENTED tables.

Mutations: M5201-M5212,
`python scripts/mutation_check.py --phase 5201`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import table_consistency as tc
from app.main import app
from tests.test_standards_3b import _chunk, _doc, _ruled_table_pdf, _scope, temp_storage  # noqa: F401


def kinds(rows):
    return sorted(f["kind"] for f in tc.check_table(rows, page=3, chunk_id="c1")["findings"])


BANDS_OK = [["Class", "From", "To"], ["A", "0", "10"], ["B", "11", "20"], ["C", "21", "30"]]


# ------------------------------------------------------------------ numbers

def test_a_plain_number_keeps_the_precision_it_was_printed_to():
    n = tc.read_number("1,250.50")
    assert (n.value, n.decimals) == (1250.5, 2)
    assert tc.read_number("12 mm") is None and tc.read_number("10-20") is None
    assert tc.read_number("") is None and tc.read_number(None) is None


# -------------------------------------------------------------------- bands

def test_two_bands_that_overlap_are_a_cited_finding():
    rows = [["Class", "From", "To"], ["A", "0", "10"], ["B", "8", "20"]]
    result = tc.check_table(rows, page=7, chunk_id="chunk-9")
    [finding] = result["findings"]
    assert finding["kind"] == "band_overlap"
    assert finding["rows"] == [1, 2] and finding["page"] == 7 and finding["chunk_id"] == "chunk-9"
    assert finding["cells"] == ["0", "10", "8", "20"]
    assert finding["status"] == "needs_engineer_review"


def test_bands_that_meet_without_overlap_or_gap_raise_nothing():
    assert kinds(BANDS_OK) == []        # 10 then 11 on whole numbers is contiguous


def test_a_gap_between_bands_is_reported():
    rows = [["Class", "From", "To"], ["A", "0", "10"], ["B", "15", "20"]]
    assert kinds(rows) == ["band_gap"]


def test_a_boundary_that_belongs_to_two_bands_is_reported():
    rows = [["Class", "From", "To"], ["A", "0", "10"], ["B", "10", "20"]]
    assert kinds(rows) == ["band_shared_boundary"]


def test_a_band_whose_low_end_is_above_its_high_end_is_reported():
    rows = [["Class", "Min", "Max"], ["A", "20", "10"], ["B", "30", "40"]]
    assert "band_inverted" in kinds(rows)


def test_bands_written_as_ranges_in_one_column_are_checked():
    rows = [["Size", "Limit"], ["10-20", "1"], ["15-30", "2"]]
    assert kinds(rows) == ["band_overlap"]
    assert kinds([["Size", "Limit"], ["10-20", "1"], ["21-30", "2"]]) == []


def test_bands_given_out_of_order_are_still_compared():
    rows = [["Class", "From", "To"], ["B", "8", "20"], ["A", "0", "10"]]
    assert kinds(rows) == ["band_overlap"]


def test_valid_bands_listed_out_of_order_raise_nothing():
    rows = [["Class", "From", "To"], ["B", "11", "20"], ["A", "0", "10"]]
    assert kinds(rows) == []


# ------------------------------------------------------------------- totals

def test_a_total_column_that_is_not_the_sum_is_reported():
    rows = [["Item", "Q1", "Q2", "Total"], ["x", "10.0", "5.0", "15.0"], ["y", "10.0", "5.0", "19.0"]]
    [f] = tc.check_table(rows)["findings"]
    assert f["kind"] == "total_column_mismatch" and f["rows"] == [2]


def test_a_printed_total_within_rounding_of_its_terms_is_not_an_error():
    rows = [["Item", "Q1", "Q2", "Total"], ["x", "10.2", "5.3", "15.5"], ["y", "3.4", "1.2", "4.6"]]
    assert kinds(rows) == []
    # one unit in the last printed digit is rounding when the terms are rounded
    assert kinds([["Item", "Q1", "Q2", "Total"], ["x", "10.24", "5.33", "15.6"],
                  ["y", "1.00", "1.00", "2.00"]]) == []


def test_a_total_row_that_is_not_the_column_sum_is_reported():
    rows = [["Item", "Cost"], ["a", "100.0"], ["b", "250.0"], ["Total", "400.0"]]
    [f] = tc.check_table(rows)["findings"]
    assert f["kind"] == "total_row_mismatch" and f["columns"] == ["Cost"]
    assert kinds([["Item", "Cost"], ["a", "100.0"], ["b", "250.0"], ["Total", "350.0"]]) == []


def test_a_total_over_cells_that_are_not_all_numbers_is_not_checked():
    rows = [["Item", "Grade", "Q1", "Q2", "Total"],
            ["x", "B", "5.0", "6.0", "9.0"], ["y", "B", "6.0", "6.0", "9.0"]]
    result = tc.check_table(rows)
    assert result["findings"] == [] and result["checks_run"]["totals"] == 0


# ----------------------------------------------------------------- formulas

def test_a_column_that_is_not_its_stated_formula_is_reported():
    rows = [["Item", "Width", "Height", "Area = Width x Height"],
            ["a", "2.0", "3.0", "6.0"], ["b", "2.0", "3.0", "7.0"]]
    [f] = tc.check_table(rows)["findings"]
    assert f["kind"] == "formula_mismatch" and f["rows"] == [2]
    assert f["cells"] == ["2.0", "3.0", "7.0"]


def test_a_formula_column_that_holds_passes_and_counts_as_checked():
    rows = [["Item", "Width (m)", "Height (m)", "Area (m2) = Width x Height"],
            ["a", "2.0", "3.0", "6.0"], ["b", "1.5", "4.0", "6.0"]]
    result = tc.check_table(rows)
    assert result["findings"] == [] and result["checks_run"]["formulas"] == 1


def test_a_formula_naming_a_column_the_table_does_not_have_is_not_checked():
    rows = [["Item", "Width", "Area = Width x Depth"], ["a", "2.0", "6.0"], ["b", "2.0", "7.0"]]
    result = tc.check_table(rows)
    assert result["findings"] == [] and result["checks_run"]["formulas"] == 0


def test_a_sum_and_a_difference_formula_work_too():
    rows = [["Item", "A", "B", "Net = A - B"], ["a", "9.0", "4.0", "5.0"], ["b", "9.0", "4.0", "6.0"]]
    assert kinds(rows) == ["formula_mismatch"]
    rows = [["Item", "A", "B", "S = A + B"], ["a", "9.0", "4.0", "13.0"], ["b", "9.0", "4.0", "14.0"]]
    assert kinds(rows) == ["formula_mismatch"]


# --------------------------------------------------------- nothing to check

def test_a_table_with_nothing_to_check_ran_no_check_and_says_so():
    rows = [["Material", "Density"], ["Steel", "7850.0"], ["Water", "1000.0"]]
    result = tc.check_table(rows)
    assert result["findings"] == [] and sum(result["checks_run"].values()) == 0


def test_a_table_too_small_to_have_bands_or_totals_is_not_checked():
    assert tc.check_table([["A", "B"], ["1", "2"]])["checks_run"] == {"bands": 0, "totals": 0, "formulas": 0}


# ------------------------------------------------- a real parsed table, by id

def _doc_with(tmp_path, header, rows, doc_id="d1"):
    pdf = _ruled_table_pdf(tmp_path / f"{doc_id}.pdf", header, rows)
    doc = _doc(doc_id, pdf)
    _chunk(f"c-{doc_id}", doc, "table text", kind="table", page=1)
    return doc


def test_a_ruled_table_in_a_document_yields_a_cited_finding(tmp_path):
    doc = _doc_with(tmp_path, ["Class", "From", "To"],
                    [["Class A", "0.0", "10.0"], ["Class B", "8.0", "20.0"]])
    report = tc.check_document(doc, allowed_document_ids=_scope(doc))
    assert report["state"] == "ok" and report["tables_checked"] == 1
    [f] = report["findings"]
    assert f["kind"] == "band_overlap" and f["page"] == 1 and f["chunk_id"] == f"c-{doc}"


def test_a_document_whose_tables_hold_nothing_to_check_is_not_called_consistent(tmp_path):
    doc = _doc_with(tmp_path, ["Material", "Density"], [["Steel", "7850.0"], ["Water", "1000.0"]])
    report = tc.check_document(doc, allowed_document_ids=_scope(doc))
    assert report["state"] == "nothing_checked" and report["findings"] == []
    assert report["tables_with_nothing_to_check"] == 1


def test_a_document_with_no_tables_says_so(tmp_path):
    doc = _doc("d2", str(tmp_path / "none.pdf"))
    assert tc.check_document(doc, allowed_document_ids=_scope(doc))["state"] == "no_tables"


def test_an_unparsed_table_is_counted_never_clean(tmp_path):
    doc = _doc_with(tmp_path, ["D", "E", "F", "I"], [["N", "I", "T", "I"]])
    report = tc.check_document(doc, allowed_document_ids=_scope(doc))
    assert report["tables_unparsed"] == 1 and report["state"] == "nothing_checked"


def test_a_document_the_caller_may_not_read_has_no_tables_for_that_caller(tmp_path):
    doc = _doc_with(tmp_path, ["Class", "From", "To"],
                    [["Class A", "0.0", "10.0"], ["Class B", "8.0", "20.0"]])
    other = _doc("d9", str(tmp_path / "none.pdf"))
    report = tc.check_document(doc, allowed_document_ids=_scope(other))
    assert report["tables_total"] == 0 and report["findings"] == []


def test_the_route_returns_the_report(tmp_path):
    doc = _doc_with(tmp_path, ["Class", "From", "To"],
                    [["Class A", "0.0", "10.0"], ["Class B", "8.0", "20.0"]])
    r = TestClient(app).get(f"/api/documents/{doc}/table-consistency")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["findings"][0]["kind"] == "band_overlap" and body["state"] == "ok"
    assert TestClient(app).get("/api/documents/no-such/table-consistency").status_code == 404
