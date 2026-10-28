"""Planner 2026-10-10 (F-a): a checklist field not read as a fact is searched
for in the text of every page before anyone is blamed.

Live, every unread checklist field on the PSV sheet became "value not found by
the page reader - engineer to check": one page was read only by the page
reader, so every absence on the sheet was excused. Now:
  * the label is in a page's text -> on the sheet, not read: an engineer
    checks that page (a READER GAP, never the contractor's omission);
  * the label is in no page's text, and every page has text -> MISSING, the
    contractor's, with the pages searched;
  * a page with no text (a scan) -> the search decides nothing (as before).
Invented values only.
"""
from __future__ import annotations

from app import absence, datasheet_checks as dc

PSV = "Pressure Safety Valve"


def fact(name, value, unit=None, page=1):
    return {"id": f"f-{name}", "field_name": name, "field_label": name.capitalize(),
            "field_value": f"{value} {unit}".strip() if unit else value, "raw_value": value,
            "raw_unit": unit, "normalized_value": None, "normalized_unit": None, "is_blank": 0,
            "blank_marker": None, "value_note": None, "page": page, "equipment_tag": None}


SHEET = [fact("set pressure", "10", "barg"), fact("max allow working pressure", "12", "barg")]
PAGES = {1: "1 Set pressure 10 barg\n2 Max. allow. working pressure 12 barg\n30 Orifice\ndesignation  J\n"
            "31 Effective\narea  1.287 in2",
         2: "NOTES\n1. Relieving capacity based on blocked discharge."}


def results(pages=PAGES, facts=SHEET):
    return {r["rule_id"]: r for r in dc.evaluate(facts, equipment_type=PSV, page_texts=pages)
            if r.get("checklist")}


def test_a_label_on_the_sheet_that_was_not_read_is_a_reader_gap_with_its_page():
    r = results()
    for item in ("PSV-13", "PSV-12"):      # orifice designation (wrapped label), orifice area ("Effective area")
        assert r[item]["status"] == "NEEDS_ENGINEER_REVIEW"
        assert r[item]["reader_gap"] is True and r[item]["pages"] == [1]
        assert (
            "wording for it appears on page 1" in r[item]["detail"]
            and "engineer to check" in r[item]["detail"]
        )


def test_a_label_in_no_pages_text_is_missing_for_the_contractor():
    r = results()["PSV-09"]                 # cold differential test pressure: printed nowhere
    assert r["status"] == "MISSING_INFORMATION" and r.get("text_searched") is True
    assert "in the text of pages 1-2" in r["detail"] and "contractor is to provide" in r["detail"]


def test_a_label_search_that_finds_nothing_says_what_it_searched_not_that_the_value_is_absent():
    # CRS-008 (I-06 hand check, 29 Oct): a note stated the rating in other words, so "was not found in
    # the text" was false. The search is by the field's NAME; the row says so and leaves the door open.
    detail = results()["PSV-09"]["detail"]
    assert "no label for it was found" in detail and "searched by its name" in detail
    assert "may state it in other words" in detail
    assert "was not found" not in detail


def test_a_page_with_no_text_decides_nothing():
    r = results(pages={1: PAGES[1], 2: ""})["PSV-09"]
    assert r["status"] == "MISSING_INFORMATION" and not r.get("text_searched")   # left to the page rule
    assert "not found in the fields read from the datasheet" in r["detail"]


def test_other_wordings_come_from_the_data():
    rules = dc.load_rules()
    assert dc.label_search("relief_case", rules, PAGES) == [2]        # "blocked discharge" (printed_as)
    assert dc.label_search("cdtp", rules, PAGES) == []
    assert dc.label_search("cdtp", rules, {}) is None


def test_a_text_searched_absence_is_not_re_excused_by_the_page_reader_rule(monkeypatch):
    from app import comparison
    seen = []
    monkeypatch.setattr(comparison, "qualify_by_pages", lambda v, p: seen.append(v) or v)
    from app import review as review_mod
    monkeypatch.setattr(review_mod, "rejected_in_run", lambda *a, **k: [])
    monkeypatch.setattr(review_mod, "create", lambda row, created_by=None: {"id": "x"})

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): return self

    import app.db as db_mod
    monkeypatch.setattr(db_mod, "connect", lambda: _Conn())
    searched = [results()["PSV-09"]]
    dc.store("run", "sub", searched, pages_read={"pages_read_only_by_page_reader": [2]})
    assert seen == []                                                  # not handed to the page rule


def test_the_review_states_its_reader_coverage():
    cov = dc.coverage(dc.evaluate(SHEET, equipment_type=PSV, page_texts=PAGES))
    assert cov["read"] == 2 and cov["fields"] > cov["read"]
    assert cov["on_sheet_not_read"] >= 2 and 1 in cov["gap_pages"]
    line = [
        ln
        for ln in absence.split_lines({"checklist_coverage": cov})
        if ln.startswith("Checklist fields")
    ][0]
    assert (
        f"read 2 of {cov['fields']}" in line
        and "wording on the sheet, not read" in line
    )


# ---- order 228.9: the labels a relief-valve sheet prints for these fields

PRINTED_AS = {
    "rated_capacity": "rated relieving capacity",
    "orifice_area": "actual discharge area",
}


def test_the_reader_is_asked_with_the_labels_a_relief_valve_sheet_prints():
    from app import form_reader_fields as ff

    fields = {f.key: f for f in ff.field_list_for(PSV)}
    for key, spelling in PRINTED_AS.items():
        assert spelling in fields[key].synonyms[: ff.MAX_SYNONYMS_SHOWN]
        assert spelling in ff.build_prompt([fields[key]], "x", 1)


def test_a_printed_label_the_data_did_not_know_is_a_reader_gap_not_the_contractors_omission():
    pages = {
        1: "1 Set pressure 10 barg\n2 Max. allow. working pressure 12 barg\n"
        "32 Actual discharge area 1.2 in2"
    }
    r = dc.evaluate(SHEET, equipment_type=PSV, page_texts=pages)
    (area,) = [x for x in r if x["rule_id"] == "PSV-12"]
    assert area["status"] == "NEEDS_ENGINEER_REVIEW" and area.get("reader_gap") is True


def test_the_wording_claims_only_that_wording_for_the_field_appears():
    detail = results()["PSV-12"]["detail"]
    assert "on the sheet" not in detail
    assert "wording for it appears on page 1" in detail


def test_no_spelling_is_listed_for_two_roles():
    """"Calculated area" is the area the sizing REQUIRES; listed for the orifice
    area too, the reader could store it as the valve's own area and "area at
    least required" would compare the number with itself."""
    seen = {}
    for role, body in dc.load_rules()["roles"].items():
        for spelling in body.get("printed_as", []):
            assert seen.setdefault(spelling.lower(), role) == role, spelling


def test_the_required_area_is_never_offered_as_the_orifice_area():
    from app import form_reader_fields as ff

    fields = {f.key: f for f in ff.field_list_for(PSV)}
    assert "calculated area" not in fields["orifice_area"].synonyms
    assert "calculated area" in fields["required_area"].synonyms
