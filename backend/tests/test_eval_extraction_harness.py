"""Issue #179: the extraction scoring harness scores what it claims to score.

`scripts/eval_extraction.py` is the committed, reproducible way to score a
datasheet's extraction against a gold sheet. Its headline P/R/F1 existed
before #179; what did not exist was the BREAKDOWN a reader needs to tell
"the extractor found the values" from "the extractor produced many rows":

  * filled gold slots recovered / given a wrong value / not extracted at all,
  * blank-by-design gold slots recovered as blanks,
  * extracted rows that are DUPLICATES of another extracted row, and
  * extracted rows that match no gold slot at all (SPURIOUS),

each counted separately. A duplicate is not a spurious fact and neither is a
miss - folding them together is exactly how #175's "268 facts" hid 153
duplicates and 49 bare-digit labels.

And a run with an EMPTY DENOMINATOR is a harness failure, not a score: a
gold sheet that parsed to nothing, or a document id that matched no stored
row, used to print F1 0.0000 - indistinguishable from a real zero.

Everything here is synthetic: no gold sheet and no client document is read
(CLAUDE.md rule 3; `gold/*.csv` is gitignored).

Mutations: M400-M403, `python scripts/mutation_check.py --phase 52`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "eval_extraction_under_test", REPO / "scripts" / "eval_extraction.py")
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)


def _gold(page, name, value="", unit="", marker=""):
    return {"page": page, "field_name": name, "value": value, "unit": unit,
            "blank_marker": marker, "equipment_tag": "", "note": "",
            "unsure": False, "declares_notes_page": False,
            "is_blank": not value, "index": 0}


def _got(page, name, value="", unit="", *, blank=False, marker=""):
    return {"page": page, "field_name": name, "value": "" if blank else value,
            "unit": unit, "is_blank": blank, "blank_marker": marker,
            "equipment_tag": "", "source_text": "", "index": 0}


GOLD = [
    _gold(2, "Rated flow", "120", "m3/h"),
    _gold(2, "Differential head", "85", "m"),
    _gold(2, "Seal flush plan", "", "", "*"),          # blank by design
    _gold(3, "Driver rated power", "90", "kW"),
]


def test_duplicates_and_spurious_are_counted_separately():
    got = [
        _got(2, "Rated flow", "120", "m3/h"),          # recovered
        _got(2, "Rated flow", "120", "m3/h"),          # DUPLICATE of the above
        _got(2, "Rated flow", "120", "m3/h"),          # and again
        _got(2, "Casing material", "CS"),              # SPURIOUS: no gold slot
        _got(2, "Seal flush plan", blank=True, marker="*"),   # blank recovered
        _got(3, "Driver rated power", "75", "kW"),     # WRONG VALUE
    ]
    out = ev.breakdown(GOLD, got)

    assert out["gold_filled"] == 3
    assert out["gold_blank_by_design"] == 1
    assert out["filled_recovered"] == 1
    assert out["filled_wrong_value"] == 1
    assert out["filled_not_extracted"] == 1          # Differential head
    assert out["blank_by_design_recovered"] == 1
    assert out["extracted_total"] == 6
    assert out["extracted_duplicates"] == 2
    assert out["extracted_spurious"] == 1
    # Every extracted row is accounted for exactly once.
    assert (out["extracted_matched"] + out["extracted_duplicates"]
            + out["extracted_spurious"]) == out["extracted_total"]


def test_a_repeated_row_nobody_asked_for_is_one_spurious_and_the_rest_duplicates():
    got = [_got(2, "Casing material", "CS")] * 3
    out = ev.breakdown(GOLD, got)
    assert out["extracted_spurious"] == 1
    assert out["extracted_duplicates"] == 2


# ------------------------------------------------ ranges (B4 §16.22 gap)


def _got_range(page, name, lo, hi, unit, printed):
    row = _got(page, name, printed, unit)
    row["value_min"], row["value_max"] = lo, hi
    return row


def test_a_stored_range_matches_the_gold_range():
    """THE MUTATION TARGET. Gold prints "5 - 150" M; the product stored
    value_min=5, value_max=150, unit M and a raw string "5 – 150 M" (en dash,
    unit inside). String comparison can never match these; the bounds do."""
    agree, why = ev.values_agree(_gold(2, "Elevation (MSL)", "5 - 150", "M"),
                                 _got_range(2, "Elevation (MSL)", 5.0, 150.0, "M",
                                            "5 – 150 M"))
    assert agree, why
    assert why.startswith("range:")


def test_a_range_with_a_different_bound_is_a_wrong_value():
    agree, why = ev.values_agree(_gold(2, "Elevation (MSL)", "5 - 150", "M"),
                                 _got_range(2, "Elevation (MSL)", 5.0, 120.0, "M",
                                            "5 - 120 M"))
    assert not agree
    assert why.startswith("range_mismatch:")


def test_a_scalar_is_never_credited_against_a_gold_range():
    """"150" is the top of the range, not the range - a reader who wrote only
    one end down missed the field."""
    agree, why = ev.values_agree(_gold(2, "Elevation (MSL)", "5 - 150", "M"),
                                 _got(2, "Elevation (MSL)", "150", "M"))
    assert not agree
    assert why == "range_vs_scalar:only_gold_is_a_range"


def test_a_range_is_read_off_the_printed_string_when_no_bounds_are_stored():
    """A copy made before value_min/value_max existed, or a model's raw
    output, has no stored bounds - the printed string is parsed instead."""
    agree, why = ev.values_agree(_gold(2, "Elevation (MSL)", "5 - 150", "M"),
                                 _got(2, "Elevation (MSL)", "5 to 150", "M"))
    assert agree, why


def test_a_range_in_a_different_unit_is_a_unit_mismatch():
    agree, why = ev.values_agree(_gold(2, "Elevation (MSL)", "5 - 150", "M"),
                                 _got_range(2, "Elevation (MSL)", 5.0, 150.0, "barg",
                                            "5 - 150 barg"))
    assert not agree
    assert "mismatch" in why


def test_a_negative_number_is_not_a_range():
    assert ev.parse_range("-150") is None
    assert ev.parse_range("150") is None
    assert ev.parse_range("5 - 150") == (5.0, 150.0)
    assert ev.parse_range("5 – 150 M") == (5.0, 150.0)


def test_a_right_value_on_the_wrong_page_is_not_recovered():
    """Name + value + unit + PAGE are scored together."""
    out = ev.breakdown(GOLD, [_got(3, "Rated flow", "120", "m3/h")])
    assert out["filled_recovered"] == 0
    assert out["extracted_spurious"] == 1


def test_a_right_number_in_the_wrong_unit_is_not_recovered():
    out = ev.breakdown(GOLD, [_got(2, "Rated flow", "120", "m3/min")])
    assert out["filled_recovered"] == 0
    assert out["filled_wrong_value"] == 1


def test_an_empty_gold_denominator_is_a_harness_failure():
    with pytest.raises(ev.HarnessFailure, match="gold"):
        ev.require_denominators([], [_got(2, "Rated flow", "120", "m3/h")],
                                allow_empty_extraction=False)
    # Only blanks and notes-page rows: the FILLED denominator is still zero.
    with pytest.raises(ev.HarnessFailure, match="filled"):
        ev.require_denominators([_gold(2, "Seal flush plan", "", "", "*")],
                                [_got(2, "x", "1")], allow_empty_extraction=False)


def test_zero_extracted_rows_is_a_harness_failure_unless_explicitly_allowed():
    with pytest.raises(ev.HarnessFailure, match="extracted"):
        ev.require_denominators(GOLD, [], allow_empty_extraction=False)
    # Allowed: a genuinely empty extraction is a real (bad) result.
    ev.require_denominators(GOLD, [], allow_empty_extraction=True)


def _write_gold(path: Path) -> None:
    path.write_text(
        "page,field_name,value,unit,blank_marker,equipment_tag,note\n"
        "# provenance line, never a row\n"
        "2,Rated flow,120,m3/h,,,\n"
        "2,Differential head,85,m,,,\n"
        "2,Seal flush plan,,,*,,\n"
        "3,Driver rated power,90,kW,,,\n", encoding="utf-8")


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["eval_extraction.py", *argv])
    return ev.main()


def test_main_persists_the_breakdown_to_the_chosen_out_dir(tmp_path, monkeypatch):
    gold = tmp_path / "gold.csv"
    _write_gold(gold)
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([
        {"label": "Rated flow", "value": "120", "unit": "m3/h", "page": 2},
        {"label": "Rated flow", "value": "120", "unit": "m3/h", "page": 2},
        {"label": "Casing material", "value": "CS", "page": 2},
    ]), encoding="utf-8")
    out_dir = tmp_path / "eval"

    code = _run_main(monkeypatch, ["--doc", "doc_x", "--gold", str(gold),
                                   "--rows", str(rows), "--out-dir", str(out_dir)])
    assert code == 0
    written = list(out_dir.glob("extraction-doc_x-*.json"))
    assert len(written) == 1, written
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["breakdown"]["filled_recovered"] == 1
    assert payload["breakdown"]["extracted_duplicates"] == 1
    assert payload["breakdown"]["extracted_spurious"] == 1


def test_main_exits_non_zero_and_writes_nothing_on_an_empty_denominator(tmp_path, monkeypatch):
    gold = tmp_path / "gold.csv"
    gold.write_text("page,field_name,value,unit,blank_marker,equipment_tag,note\n",
                    encoding="utf-8")
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"label": "Rated flow", "value": "1", "page": 2}]),
                    encoding="utf-8")
    out_dir = tmp_path / "eval"
    code = _run_main(monkeypatch, ["--doc", "doc_x", "--gold", str(gold),
                                   "--rows", str(rows), "--out-dir", str(out_dir)])
    assert code == 2
    assert not list(out_dir.glob("*.json")), "a failed run must not leave a score behind"
