"""The made-up datasheet benchmark: its answer key, its scorer, its readers.

`scripts/make_datasheet_bench.py` writes 14 invented datasheets (PDF, XLSX,
DOCX) and `answer_key.json`; `scripts/datasheet_bench.py` scores a reader
against them. These tests prove, each against the code that would break it:

  * the committed files ARE the generator's output (key and files in step);
  * the key is HONEST - every expected value is in its file - and the honesty
    check catches a key that is not;
  * the scorer's arithmetic on a hand example: recall, precision, forbidden,
    wrong value, duplicates, blanks, unit normalisation;
  * an AI reader runs through `read_file_with` with a FAKE model (no network),
    the gate still throws away an invented row, a file the reader cannot read
    is "unsupported" (a miss, never a crash), and the Claude model call is
    wired through the USD caps;
  * the rules reader runs on a PDF with no project database.

Mutations: M1650-M1663, `python scripts/mutation_check.py --only M1650,...`.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load("datasheet_bench_under_test", "datasheet_bench.py")
BENCH = bench.BENCH


@pytest.fixture(scope="module")
def key() -> dict:
    return bench.load_key()


# ============================================================ the answer key

def test_the_key_is_well_formed_and_covers_every_format(key):
    from app import claude_datasheet
    files = key["files"]
    assert len(files) == 14
    assert {Path(n).suffix for n in files} == {".pdf", ".xlsx", ".docx"}
    assert [n for n, e in files.items() if not e["text_layer"]] == ["ds11_flowmeter_scanned.pdf"]
    for name, entry in files.items():
        assert (BENCH / name).is_file(), name
        assert entry["expected"], name
        for item in entry["expected"]:
            assert item["field"] and item["value"], (name, item)
            assert item["kind"] in claude_datasheet.KINDS, (name, item)
    # Required and offered values of one field are both in the key.
    kinds = {i["kind"] for i in files["ds04_control_valve_req_off.pdf"]["expected"]}
    assert kinds == {"required", "offered"}
    assert len(files["ds14_blanks_by_vendor.pdf"]["forbidden"]) >= 5
    assert sum(p.stat().st_size for p in BENCH.iterdir()) < 1_500_000


def test_the_key_is_honest(key):
    """Every expected value, expected field and forbidden field is in its
    file's text; the scanned file has no text layer. Asserted POSITIVELY
    first: the check read real text for the text-layer files."""
    assert "12.5 barg" in bench.file_text(BENCH / "ds02_psv_unruled.pdf")
    assert "Mechanical seal" in bench.file_text(BENCH / "ds12_pump.xlsx")
    assert "Incoloy 800" in bench.file_text(BENCH / "ds13_heater.docx")
    assert bench.key_problems(key) == []


def _doctored(key: dict, name: str, change) -> dict:
    copy = json.loads(json.dumps(key))
    change(copy["files"][name])
    return copy


def test_the_honesty_check_catches_a_value_not_in_the_file(key):
    bad = _doctored(key, "ds01_pump_ruled.pdf",
                    lambda e: e["expected"][0].update(value="1234.5"))
    problems = bench.key_problems(bad)
    assert problems == ["ds01_pump_ruled.pdf: expected value 'Rated capacity' not in the file"]
    # The same slip in a workbook, where the unit sits in its own cell.
    bad = _doctored(key, "ds12_pump.xlsx", lambda e: e["expected"][0].update(value="43"))
    assert bench.key_problems(bad) == ["ds12_pump.xlsx: expected value 'Capacity' not in the file"]


def test_the_honesty_check_catches_a_field_or_forbidden_field_not_in_the_file(key):
    bad = _doctored(key, "ds14_blanks_by_vendor.pdf",
                    lambda e: e["forbidden"].append("Shaft diameter"))
    assert bench.key_problems(bad) == [
        "ds14_blanks_by_vendor.pdf: forbidden field 'Shaft diameter' not in the file"]
    bad = _doctored(key, "ds05_motor_units_grid.pdf",
                    lambda e: e["expected"][0].update(field="Output rating"))
    assert bench.key_problems(bad) == [
        "ds05_motor_units_grid.pdf: expected field 'Output rating' not in the file"]


def test_the_honesty_check_catches_a_scanned_claim_on_a_text_file(key):
    bad = _doctored(key, "ds09_rotated_page.pdf", lambda e: e.update(text_layer=False))
    assert bench.key_problems(bad) == ["ds09_rotated_page.pdf: marked scanned but has a text layer"]


def test_the_committed_files_are_the_generators_output(tmp_path, monkeypatch):
    gen = _load("make_datasheet_bench_under_test", "make_datasheet_bench.py")
    monkeypatch.setattr(gen, "OUT", tmp_path)
    monkeypatch.setattr(gen, "REPO", tmp_path.parent)
    assert gen.main() == 0
    made = sorted(p.name for p in tmp_path.iterdir())
    assert made == sorted(p.name for p in BENCH.iterdir())
    for name in made:
        assert (tmp_path / name).read_bytes() == (BENCH / name).read_bytes(), name


# ============================================================ scorer maths

HAND_ENTRY = {
    "expected": [
        {"field": "Design pressure", "value": "10", "unit": "bar", "kind": "offered"},
        {"field": "Impeller diameter", "value": "5", "unit": "mm", "kind": "offered"},
        {"field": "Casing material", "value": "Carbon steel", "unit": None, "kind": "offered"},
    ],
    "forbidden": ["Motor power"],
    "ignore": ["Tag No"],
}


def _fact(field, value, unit=None, *, blank=False):
    return {"field": field, "value": value, "unit": unit, "blank": blank}


HAND_FACTS = [
    _fact("DESIGN PRESS.", "1 MPa", "MPa"),         # correct: 1 MPa == 10 bar
    _fact("Impeller dia", "6", "mm"),               # wrong value
    _fact("Motor power", "7", "kW"),                # forbidden
    _fact("Nozzle load", "3", "kN"),                # extra
    _fact("Tag No", "SYN-P-0001"),                  # ignored
    _fact("Design pressure", "10 bar", "bar"),      # duplicate of the correct answer
    _fact("Casing material", "By Vendor", blank=True),  # a blank: no value claimed
]


def test_scorer_arithmetic_on_a_hand_example():
    s = bench.score_file(HAND_ENTRY, HAND_FACTS)
    assert (s["expected"], s["found"], s["correct"]) == (3, 1, 1)
    assert (s["wrong_value"], s["forbidden"], s["extra"]) == (1, 1, 1)
    assert (s["duplicate"], s["ignored"], s["blanks_recorded"]) == (1, 1, 1)
    assert s["reported"] == 4
    assert s["recall"] == pytest.approx(0.333)
    assert s["precision"] == 0.25
    assert s["missed"] == ["Impeller diameter = 5 mm", "Casing material = Carbon steel"]


def test_a_blank_reported_as_a_value_is_forbidden_and_a_blank_as_blank_is_not():
    entry = {"expected": [], "forbidden": ["Motor power"], "ignore": []}
    as_blank = bench.score_file(entry, [_fact("Motor power", "By Vendor", blank=True)])
    assert (as_blank["forbidden"], as_blank["reported"], as_blank["precision"]) == (0, 0, None)
    as_value = bench.score_file(entry, [_fact("Motor power", "55", "kW")])
    assert (as_value["forbidden"], as_value["reported"], as_value["precision"]) == (1, 1, 0.0)


def test_value_matching_normalises_units_and_refuses_a_lost_unit():
    item = {"field": "Set pressure", "value": "12.5", "unit": "barg"}
    assert bench.value_matches(item, {"value": "12.5 barg", "unit": "barg"})
    assert bench.value_matches(item, {"value": "12.5"}) is False          # unit lost
    assert bench.value_matches(item, {"value": "12.5 bara", "unit": "bara"}) is False  # gauge vs absolute
    length = {"field": "Tube OD", "value": "19.05", "unit": "mm"}
    assert bench.value_matches(length, {"value": "0.75 in", "unit": "in"})
    assert bench.value_matches(length, {"value": "0.8 in", "unit": "in"}) is False
    unitless = {"field": "Power factor", "value": "0.87", "unit": None}
    assert bench.value_matches(unitless, {"value": "0.87", "unit": None})
    text = {"field": "Casing material", "value": "Carbon steel", "unit": None}
    assert bench.value_matches(text, {"value": "CARBON  STEEL."})
    assert bench.value_matches(text, {"value": "Stainless steel"}) is False


def test_field_matching_folds_abbreviations_and_table_column_labels():
    item = {"field": "Number of passes", "value": "2"}
    assert bench.field_matches(item, "No. of passes")
    assert bench.field_matches(item, "Number of passes - Offered")
    assert not bench.field_matches(item, "Number of tubes")
    merged = {"field": "Design pressure", "value": "0.05", "aliases": ["Pressure"]}
    assert bench.field_matches(merged, "Pressure")


def test_totals_are_ratios_of_sums_with_no_percentage_of_nothing():
    per_file = {
        "a.pdf": {"status": "read", "score": bench.score_file(HAND_ENTRY, HAND_FACTS)},
        "b.xlsx": {"status": "unsupported", "score": bench.score_file(HAND_ENTRY, [])},
    }
    t = bench.totals(per_file)
    assert (t["expected"], t["found"], t["reported"]) == (6, 1, 4)
    assert t["recall"] == pytest.approx(0.167)
    assert t["files_unsupported"] == 1
    assert bench.score_file(HAND_ENTRY, [])["precision"] is None


# ============================================================ the readers

def _fake_model(*, invent: bool = False, pipes: bool = False):
    """A stand-in model: reads "Label : value unit" lines off the page in the
    prompt and answers the page reader's JSON. `invent` adds a row that is
    not on the page, which the gate must throw away. `pipes` also reads a
    rendered table row "Label | value" (a workbook's or Word table's)."""
    def call(prompt: str) -> str:
        page = prompt.split("PAGE ", 1)[1].split("\n", 1)[1]
        facts = []
        for line in page.splitlines():
            if pipes and line.count(" | ") == 1:
                label, value = line.strip().split(" | ")
                if value and not value.lower().startswith("by vendor"):
                    facts.append({"field": label, "value": value, "unit": None,
                                  "quote": line.strip(), "kind": "offered"})
                continue
            m = re.match(r"^(?P<label>[A-Za-z][^:]+?) : (?P<value>\S.*)$", line.strip())
            if not m:
                continue
            value, _, unit = m["value"].partition(" ")
            facts.append({"field": m["label"], "value": m["value"] if not re.match(r"^\d", value) else value,
                          "unit": (unit or None) if re.match(r"^\d", value) else None,
                          "quote": line.strip(), "kind": "offered"})
        if invent:
            facts.append({"field": "Spring material", "value": "Inconel X-750", "unit": None,
                          "quote": "Spring material : Inconel X-750", "kind": "offered"})
        return json.dumps({"facts": facts})
    return call


def test_a_fake_model_reads_a_pdf_through_read_file_with(key):
    reading = bench.read_file_with("ai-only:claude", BENCH / "ds02_psv_unruled.pdf",
                                   model_call=_fake_model(invent=True))
    assert reading["status"] == "read"
    assert reading["calls"] == 2                  # two runs of the one page (the gate's rule 6)
    fields = {f["field"] for f in reading["facts"]}
    assert "Set pressure" in fields
    assert "Spring material" not in fields        # invented: not on the page, gate refused it
    assert reading["rejected"].get("quote_not_on_page") == 1
    s = bench.score_file(key["files"]["ds02_psv_unruled.pdf"], reading["facts"])
    assert s["found"] >= 8 and s["forbidden"] == 0 and s["wrong_value"] == 0


@pytest.fixture
def no_ocr(monkeypatch, tmp_path):
    """The project's OCR engine is not here: its model folder is empty."""
    from app.config import settings
    monkeypatch.setattr(settings, "ocr_model_dir", tmp_path / "no-ocr-models")


def test_a_file_the_ai_reader_cannot_read_is_unsupported_not_a_crash(no_ocr):
    calls = []
    reading = bench.read_file_with("ai-only:ollama", BENCH / "ds11_flowmeter_scanned.pdf",
                                   model_call=lambda p: calls.append(p) or "{}")
    assert reading["status"] == "ocr_unavailable"
    assert reading["facts"] == [] and calls == [] and reading["calls"] == 0
    assert "ocr unavailable" in reading["reason"]


@pytest.mark.parametrize("name", ["ds12_pump.xlsx", "ds13_heater.docx"])
def test_the_ai_only_reader_reads_office_files_through_their_page_texts(name, key):
    reading = bench.read_file_with("ai-only:ollama", BENCH / name,
                                   model_call=_fake_model(pipes=True))
    assert reading["status"] == "read" and reading["calls"] >= 2
    s = bench.score_file(key["files"][name], reading["facts"])
    assert s["found"] >= 3 and s["forbidden"] == 0


def test_a_whole_run_with_a_fake_model_counts_unsupported_files_as_misses(key, no_ocr):
    report = bench.run_reader("ai-only:claude", key, model_call=_fake_model())
    t = report["total"]
    assert t["files"] == 14 and t["files_unsupported"] == 1
    assert report["files"]["ds11_flowmeter_scanned.pdf"]["status"] == "ocr_unavailable"
    assert report["files"]["ds11_flowmeter_scanned.pdf"]["score"]["found"] == 0
    assert t["expected"] == sum(len(e["expected"]) for e in key["files"].values())
    assert report["calls"] == sum(r["calls"] for r in report["files"].values()) > 0


def test_the_claude_model_call_is_off_without_the_egress_flags(monkeypatch):
    from app import reader_transport
    monkeypatch.setattr(reader_transport, "transport", lambda: None)
    with pytest.raises(bench.ReaderUnavailable):
        bench.build_model_call("ai-only:claude")


@pytest.fixture
def claude_lane(tmp_path, monkeypatch):
    """The reader lane switched on against a FAKE transport: nothing leaves."""
    from app import reader_transport
    from app.config import settings
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    monkeypatch.delenv("STANDARDS_READER_MODEL", raising=False)
    sent = []

    def transport(url, *, headers, body, timeout):
        sent.append(body)
        transport.usage["calls"] += 1
        transport.usage["input_tokens"] += 1000
        transport.usage["output_tokens"] += 100
        return {"content": [{"type": "text", "text": '{"facts": []}'}],
                "usage": {"input_tokens": 1000, "output_tokens": 100},
                "model": "claude-sonnet-4-5", "stop_reason": "end_turn"}
    transport.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(reader_transport, "transport", lambda: transport)
    return sent


def test_the_claude_model_call_is_metered_and_charged_to_its_own_step(claude_lane):
    from app import claude_budget, claude_spend
    call, usage_fn = bench.build_model_call("ai-only:claude")
    assert isinstance(call, claude_budget.Budget)
    reading = bench.read_file_with("ai-only:claude", BENCH / "ds02_psv_unruled.pdf", model_call=call)
    assert reading["status"] == "read" and reading["calls"] == 2 and len(claude_lane) == 2
    assert claude_spend.spent(bench.STEP) > 0            # the one ledger saw both calls
    usage = usage_fn()
    assert usage["input_tokens"] == 2000 and usage["estimated_usd"] > 0


def test_a_usd_cap_stops_the_claude_reader_before_anything_is_sent(claude_lane, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.000001)
    call, _usage = bench.build_model_call("ai-only:claude")
    reading = bench.read_file_with("ai-only:claude", BENCH / "ds02_psv_unruled.pdf", model_call=call)
    assert reading["status"] == "stopped" and reading["stopped"] == "usd_cap_reached"
    assert claude_lane == []


def test_the_rules_reader_runs_on_a_pdf_without_the_project_database(key):
    from app import db
    from app.config import settings
    before = settings.db_path
    reading = bench.read_file_with("rules", BENCH / "ds01_pump_ruled.pdf")
    assert settings.db_path == before            # restored
    db.connect().execute("SELECT 1")             # the suite's own database still opens
    assert reading["status"] == "read"
    s = bench.score_file(key["files"]["ds01_pump_ruled.pdf"], reading["facts"])
    assert (s["found"], s["expected"]) == (10, 10)
    # "Coupling type: By Vendor" is recorded as a blank, never as a value.
    assert s["forbidden"] == 0 and s["blanks_recorded"] >= 1
    # Today's production refuses a Word file at upload; with office input on
    # the same file is read.
    assert bench.read_file_with("rules", BENCH / "ds13_heater.docx")["status"] == "refused_at_upload"
    assert bench.read_file_with("rules+office", BENCH / "ds13_heater.docx")["status"] == "read"
