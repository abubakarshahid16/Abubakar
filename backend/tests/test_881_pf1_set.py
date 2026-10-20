"""PF1 (#881): the builder of the unfamiliar-datasheet test set.

The set's CONTENT is local and never in git; this tests the builder on a tiny
invented spec. A wrong key proves nothing, so the builder's three rules are
what is tested: the key is written from the rows that are drawn, every keyed
clause is in the standard the sheet cites, and the set never lands in a git
repository.
"""
from __future__ import annotations

import copy
import json

import pymupdf
import pytest

from tools import pf1_set, review_score


def _doc(doc_id="pf1-t-pump", layout="ruled_units", held_out=False):
    return {
        "id": doc_id, "equipment_type": "Centrifugal Pump", "held_out": held_out, "layout": layout,
        "sheet": {"document_number": "DS-0001-P", "tag": "SYN-P-0001", "title": "PUMP DATASHEET", "pages": [
            {"rows": [
                {"field": "Design pressure", "value": "9", "unit": "barg", "group": "Design",
                 "key": {"id": "D1", "kind": "defect", "clause": "4.2", "note": "invented: below 12 barg"}},
                {"field": "Rated flow", "value": "120", "unit": "m3/h", "required": "100", "group": "Design",
                 "key": {"id": "M1", "kind": "met", "clause": "6.3"}},
                {"field": "Casing material", "value": "Carbon steel", "group": "Materials"}]},
            {"rows": [
                {"field": "Differential head", "value": "4.5", "unit": "bar", "group": "Performance",
                 "key": {"id": "T1", "kind": "trap", "clause": "7.1", "note": "invented: 45 m of water"}}]}]},
        "standard": {"number": "STD-PUMP-0001", "title": "Pumps (invented)", "sections": [
            {"clause": "1", "title": "Scope", "text": "This invented standard covers pumps."},
            {"clause": "4.2", "title": "Design pressure", "text": "The design pressure shall be at least 12 barg."},
            {"clause": "6.3", "title": "Flow", "text": "The rated flow shall be at least the required flow.",
             "table": [["Service", "Minimum flow"], ["General", "100 m3/h"]]},
            {"clause": "7.1", "title": "Head", "text": "The differential head shall be at least 40 m."},
            {"clause": "9.4", "title": "Steam turbines", "text": "A steam turbine driver shall have a trip valve."}]},
        "unprinted": [{"id": "D2", "kind": "defect", "clause": "5.1", "field": "seal plan",
                       "note": "invented: the sheet does not state it"},
                      {"id": "N1", "kind": "not_applicable", "clause": "9.4"}],
    }


def _spec(*docs):
    return {"format": "pf1-spec/1", "documents": list(docs) or [_doc()]}


def _with_clause_5_1(doc):
    doc["standard"]["sections"].append({"clause": "5.1", "title": "Seal", "text": "The seal plan shall be stated."})
    return doc


def test_a_set_is_built_a_sheet_a_standard_a_key_and_an_index(tmp_path):
    index = pf1_set.build(_spec(_with_clause_5_1(_doc())), tmp_path / "set")
    (entry,) = index["documents"]
    assert entry["items"] == {"defect": 2, "met": 1, "trap": 1, "not_applicable": 1}
    assert entry["held_out"] is False and entry["pages"] == 2 and entry["text_layer"] is True
    for name in ("datasheet", "standard", "key"):
        assert (tmp_path / "set" / entry[name]).is_file()
    assert json.loads((tmp_path / "set" / "index.json").read_text(encoding="utf-8")) == index
    sheet = pymupdf.open(tmp_path / "set" / entry["datasheet"])
    assert len(sheet) == 2 and "Applicable standard: STD-PUMP-0001" in sheet[0].get_text()
    standard = pymupdf.open(tmp_path / "set" / entry["standard"])
    text = "".join(page.get_text() for page in standard)
    assert "4.2  Design pressure" in text and "at least 12 barg" in text and "100 m3/h" in text


def test_the_key_is_one_the_scorer_reads_and_is_written_from_the_drawn_rows(tmp_path):
    index = pf1_set.build(_spec(_with_clause_5_1(_doc())), tmp_path / "set")
    key = review_score.load_key(tmp_path / "set" / index["documents"][0]["key"])
    assert key["source"] == "invented" and key["complete_for_flags"] is True and key["name"] == "pf1-t-pump"
    by_id = {item["id"]: item for item in key["items"]}
    assert by_id["D1"] == {"id": "D1", "kind": "defect", "standard": "STD-PUMP-0001", "clause": "4.2",
                           "field": "Design pressure", "submittal_page": 1, "note": "invented: below 12 barg"}
    assert by_id["T1"]["submittal_page"] == 2                       # the page it is drawn on
    assert "submittal_page" not in by_id["D2"] and by_id["D2"]["field"] == "seal plan"   # left out of the sheet
    assert by_id["N1"]["kind"] == "not_applicable"
    assert "Casing material" not in json.dumps(key)                 # an unkeyed row is not an answer


@pytest.mark.parametrize("layout", sorted(pf1_set.LAYOUTS))
def test_every_layout_prints_each_keyed_value_on_its_page(layout, tmp_path):
    doc = _with_clause_5_1(_doc(layout=layout))
    index = pf1_set.build(_spec(doc), tmp_path / "set")
    entry = index["documents"][0]
    sheet = pymupdf.open(tmp_path / "set" / entry["datasheet"])
    words = "".join(page.get_text() for page in sheet)
    if layout == "scanned":
        assert entry["text_layer"] is False and not words.strip() and sheet[0].get_images()
    else:
        assert pf1_set.unprinted_keyed_rows(doc, (tmp_path / "set" / entry["datasheet"]).read_bytes()) == []
        assert "9 barg" in " ".join(words.split()) or "9\nbarg" in words
    assert sheet[0].rotation == (90 if layout == "landscape" else 0)


def test_a_keyed_value_that_is_not_on_its_page_stops_the_build(tmp_path, monkeypatch):
    """RULE 1. The drawing drops a row; the key must not be written."""
    drawn = pf1_set.LAYOUTS["ruled_units"]
    monkeypatch.setitem(pf1_set.LAYOUTS, "ruled_units", (lambda page, rows: drawn[0](page, rows[1:]), True, False))
    with pytest.raises(pf1_set.SpecError, match="not on their page: D1"):
        pf1_set.build(_spec(_with_clause_5_1(_doc())), tmp_path / "set")
    assert not (tmp_path / "set").exists()                          # nothing half-written


def test_a_keyed_clause_that_is_not_in_the_standard_is_refused(tmp_path):
    """RULE 2. `_doc()` keys clause 5.1 and its standard has no 5.1."""
    with pytest.raises(pf1_set.SpecError, match="D2: clause '5.1' is not in the standard"):
        pf1_set.build(_spec(_doc()), tmp_path / "set")
    doc = _with_clause_5_1(_doc())
    doc["unprinted"][0]["clause"] = "5.1.3"                         # under a clause that is there
    pf1_set.validate(_spec(doc))
    doc["unprinted"][0]["clause"] = "4.20"                          # not under 4.2
    with pytest.raises(pf1_set.SpecError, match="4.20"):
        pf1_set.validate(_spec(doc))


def test_a_sheet_that_does_not_cite_its_standard_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(pf1_set, "_notes", lambda page, y, lines: None)
    with pytest.raises(pf1_set.SpecError, match="does not print its standard's number"):
        pf1_set.build(_spec(_with_clause_5_1(_doc())), tmp_path / "set")


def test_the_set_is_refused_inside_a_git_repository(tmp_path):
    """RULE 3. Held-out answers in a repository are not held out."""
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(pf1_set.SpecError, match="inside a git repository"):
        pf1_set.build(_spec(_with_clause_5_1(_doc())), tmp_path / "repo" / "eval" / "pf1")
    assert not (tmp_path / "repo" / "eval").exists()
    assert pf1_set.inside_a_git_repository(pf1_set.Path(__file__)) is True


@pytest.mark.parametrize("change, message", [
    (lambda d: d.pop("held_out"), "held_out must be true or false"),
    (lambda d: d.update(held_out="no"), "held_out must be true or false"),
    (lambda d: d.update(layout="hologram"), "layout must be one of"),
    (lambda d: d.update(id="PF1 Pump"), "document id"),
    (lambda d: d.update(equipment_type=" "), "equipment_type is required"),
    (lambda d: d["sheet"]["pages"][0]["rows"][1]["key"].update(id="D1"), "unique in its document"),
    (lambda d: d["sheet"]["pages"][0]["rows"][0]["key"].update(kind="wrong"), "kind must be one of"),
    (lambda d: d["sheet"].update(pages=[]), "needs pages"),
    (lambda d: d["standard"].update(number=""), "needs a number and sections"),
])
def test_a_spec_that_cannot_give_trusted_answers_is_refused(change, message):
    doc = _with_clause_5_1(_doc())
    change(doc)
    with pytest.raises(pf1_set.SpecError, match=message):
        pf1_set.validate(_spec(doc))


def test_a_document_of_defects_only_is_refused():
    """A set with no correct item cannot show a false flag."""
    doc = _with_clause_5_1(_doc())
    for page in doc["sheet"]["pages"]:
        for row in page["rows"]:
            if row.get("key", {}).get("kind") in ("met", "trap"):
                del row["key"]
    with pytest.raises(pf1_set.SpecError, match="at least one planted defect and one correct item"):
        pf1_set.validate(_spec(doc))


def test_two_documents_one_held_out_and_the_summary_holds_counts_only(tmp_path):
    held = _with_clause_5_1(_doc("pf1-t-tank", layout="scanned", held_out=True))
    held["equipment_type"] = "Storage Tank"
    index = pf1_set.build(_spec(_with_clause_5_1(_doc()), held), tmp_path / "set")
    assert pf1_set.summary(index) == {
        "documents": 2, "against_library_standards": 0, "equipment_types": 2, "layouts": 2, "held_out": 1,
        "without_a_text_layer": 1,
        "items": {"defect": 4, "met": 2, "trap": 2, "not_applicable": 2}}
    text = json.dumps(pf1_set.summary(index))
    assert "D1" not in text and "4.2" not in text and "pf1-t" not in text
    with pytest.raises(pf1_set.SpecError, match="unique"):
        pf1_set.validate(_spec(_with_clause_5_1(_doc()), _with_clause_5_1(_doc())))


def test_the_same_spec_gives_the_same_bytes(tmp_path):
    spec = _spec(_with_clause_5_1(_doc()))
    pf1_set.build(copy.deepcopy(spec), tmp_path / "a")
    pf1_set.build(copy.deepcopy(spec), tmp_path / "b")
    for path in sorted((tmp_path / "a").iterdir()):
        assert path.read_bytes() == (tmp_path / "b" / path.name).read_bytes(), path.name


def test_one_printed_value_may_answer_the_invented_standard_and_a_held_checklist(tmp_path):
    """A PSV sheet: the product already holds a checklist for the type, so
    the same planted value is also a defect under that checklist's rule. The
    second item names its own standard; its clause is not looked up in the
    invented standard. A key that does not list every defect says so."""
    doc = _with_clause_5_1(_doc())
    row = doc["sheet"]["pages"][0]["rows"][0]
    row["key"] = [row["key"], {"id": "D1x", "kind": "defect", "standard": "API 520-I", "clause": "5.4.2.1"}]
    doc["complete_for_flags"] = False
    index = pf1_set.build(_spec(doc), tmp_path / "set")
    key = review_score.load_key(tmp_path / "set" / index["documents"][0]["key"])
    by_id = {item["id"]: item for item in key["items"]}
    assert by_id["D1"]["standard"] == "STD-PUMP-0001" and by_id["D1x"]["standard"] == "API 520-I"
    assert by_id["D1x"]["submittal_page"] == 1 and by_id["D1x"]["field"] == "Design pressure"
    assert key["complete_for_flags"] is False and index["documents"][0]["complete_for_flags"] is False
    assert index["documents"][0]["items"]["defect"] == 3
    row["key"][1].pop("standard")                                  # now it is about the invented standard
    with pytest.raises(pf1_set.SpecError, match="D1x: clause '5.4.2.1' is not in the standard"):
        pf1_set.validate(_spec(doc))


def test_a_label_that_would_print_over_its_neighbour_stops_the_build(tmp_path):
    """Seen on the first real set: a long label ran into the value beside it.
    An unreadable sheet nobody planted would be blamed on the review."""
    doc = _with_clause_5_1(_doc(layout="two_column_form"))
    doc["sheet"]["pages"][0]["rows"][0]["field"] = "Design pressure of the casing at the maximum temperature"
    with pytest.raises(pf1_set.SpecError, match="does not fit its 160-point cell"):
        pf1_set.build(_spec(doc), tmp_path / "set")
    assert not (tmp_path / "set").exists()


def _library_doc():
    """A sheet planted against requirements STORED in the library: it cites
    two held standards by number and has no invented standard."""
    doc = _doc("pf1r-t-pump")
    del doc["standard"], doc["unprinted"]
    doc["library_standards"] = ["LIB-STD-0001", "LIB-STD-0002"]
    rows = doc["sheet"]["pages"][0]["rows"] + doc["sheet"]["pages"][1]["rows"]
    for row, standard in zip([r for r in rows if "key" in r], ("LIB-STD-0001", "LIB-STD-0002", "LIB-STD-0001")):
        row["key"]["standard"] = standard
    return doc


def test_a_sheet_against_library_standards_cites_them_and_writes_no_standard_file(tmp_path):
    index = pf1_set.build(_spec(_library_doc(), _with_clause_5_1(_doc())), tmp_path / "set")
    entry = index["documents"][0]
    assert entry["group"] == "library" and entry["library_standards"] == 2
    assert entry["standard"] is None and entry["standard_number"] is None
    assert not (tmp_path / "set" / "pf1r-t-pump.standard.pdf").exists()
    text = pymupdf.open(tmp_path / "set" / entry["datasheet"])[0].get_text()
    assert "Applicable standard: LIB-STD-0001" in text and "Applicable standard: LIB-STD-0002" in text
    key = review_score.load_key(tmp_path / "set" / entry["key"])
    assert {item["standard"] for item in key["items"]} == {"LIB-STD-0001", "LIB-STD-0002"}
    # a real library may rightly apply requirements nobody judged: the key never claims to be complete
    assert key["complete_for_flags"] is False and entry["complete_for_flags"] is False
    assert index["documents"][1]["group"] == "invented"
    assert pf1_set.summary(index)["against_library_standards"] == 1


@pytest.mark.parametrize("change, message", [
    (lambda d: d["sheet"]["pages"][0]["rows"][0]["key"].update(standard="LIB-STD-0009"), "not one the sheet cites"),
    (lambda d: d["sheet"]["pages"][0]["rows"][0]["key"].pop("standard"), "not one the sheet cites"),
    (lambda d: d.update(library_standards=[]), "one or the other"),
    (lambda d: d.update(standard=_doc()["standard"]), "one or the other"),
])
def test_a_library_sheet_whose_answers_cannot_be_traced_is_refused(change, message):
    doc = _library_doc()
    change(doc)
    with pytest.raises(pf1_set.SpecError, match=message):
        pf1_set.validate(_spec(doc))


# --------------------------------------- the one exception: invented tuning sheets in git


def _repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path / "tests" / "data" / "pf1"


def test_inside_a_repository_the_build_is_still_refused_without_the_flag(tmp_path):
    out = _repo(tmp_path)
    with pytest.raises(pf1_set.SpecError, match="inside a git repository"):
        pf1_set.build(_spec(_with_clause_5_1(_doc())), out)
    assert not out.exists()


def test_the_flag_lets_invented_tuning_sheets_into_tests_data_pf1(tmp_path):
    out = _repo(tmp_path)
    index = pf1_set.build(_spec(_with_clause_5_1(_doc())), out, allow_in_git=True)
    assert [d["id"] for d in index["documents"]] == ["pf1-t-pump"]
    assert (out / "index.json").is_file() and (out / "pf1-t-pump.key.json").is_file()


def test_a_held_out_sheet_is_never_written_into_a_repository_even_with_the_flag(
    tmp_path,
):
    out = _repo(tmp_path)
    spec = _spec(
        _with_clause_5_1(_doc("pf1-open")),
        _with_clause_5_1(_doc("pf1-held", held_out=True)),
    )
    with pytest.raises(pf1_set.SpecError, match="1 held-out") as caught:
        pf1_set.build(spec, out, allow_in_git=True)
    assert "pf1-held" not in str(
        caught.value
    )  # counts only, never the id of a held-out sheet
    assert not out.exists()  # nothing written, not even the open sheet


def test_a_library_group_sheet_is_never_written_into_a_repository_even_with_the_flag(
    tmp_path,
):
    out = _repo(tmp_path)
    with pytest.raises(pf1_set.SpecError, match="1 library-group"):
        pf1_set.build(_spec(_library_doc()), out, allow_in_git=True)
    assert not out.exists()


def test_the_flag_writes_only_into_a_folder_named_tests_data_pf1(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(pf1_set.SpecError, match="tests/data/pf1"):
        pf1_set.build(
            _spec(_with_clause_5_1(_doc())), tmp_path / "elsewhere", allow_in_git=True
        )
    assert not (tmp_path / "elsewhere").exists()


def test_the_flag_changes_nothing_outside_a_repository(tmp_path):
    index = pf1_set.build(
        _spec(_with_clause_5_1(_doc("pf1-held", held_out=True))),
        tmp_path / "set",
        allow_in_git=True,
    )
    assert (
        index["documents"][0]["held_out"] is True
    )  # outside git, the flag is not consulted
