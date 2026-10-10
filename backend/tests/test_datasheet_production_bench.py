"""The datasheet benchmark measures THE PRODUCTION PATH, with each switch.

`datasheet_offline.read_file` runs what a real upload runs for a datasheet
(upload validation, extract, chunk, OCR when the engine is here, then
`datasheets.extract_facts`) in a throwaway database, with
DATASHEET_OFFICE_INPUT and DATASHEET_AI_READER set for the run and restored
afterwards. `scripts/datasheet_bench.py` scores the readers built on it:
rules, rules+office, hybrid:<engine>, ai-only:<engine>.

Every model here is a FAKE callable: no network, no Ollama, no Claude. The
files are the made-up benchmark datasheets. Proved here:

  * hybrid on the .xlsx and on a PDF gives facts through the real extract
    path, written by the AI reader (`extraction_method='model'`);
  * an AI-only fact whose quote is not on the page is not stored;
  * a disagreement is stored as a conflict for an engineer and counted;
  * the flags (and the paths) are restored after a run, even on an exception;
  * a scan whose pages need OCR where the engine is missing is reported as
    `ocr_unavailable`, never as a reader that read it and found nothing;
  * `--reader all-local` never builds a Claude call;
  * `hybrid:claude` is production's engine, metered by `claude_spend`.

Mutations: M1720-M1739 (`scripts/mutations/datasheet_production_bench.py`).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

from app import datasheet_ai, datasheets
from tools import datasheet_offline
from app.config import settings

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load("datasheet_bench_production_under_test", "datasheet_bench.py")
BENCH = bench.BENCH
XLSX = BENCH / "ds12_pump.xlsx"
FREE_TEXT = BENCH / "ds07_gate_valve_free_text.pdf"
PSV = BENCH / "ds02_psv_unruled.pdf"
RULED = BENCH / "ds01_pump_ruled.pdf"
SCAN = BENCH / "ds11_flowmeter_scanned.pdf"


@pytest.fixture(scope="module")
def key() -> dict:
    return bench.load_key()


@pytest.fixture(autouse=True)
def switches_off(monkeypatch, tmp_path):
    """Both switches OFF going in, as production defaults them, and a private
    spend ledger - so a leak of a run's flags is visible to every test."""
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")


def _model(extra=None):
    """A FAKE model: proposes the facts `extra(page_text)` returns."""
    def call(prompt: str) -> str:
        page = bench._prompt_page_text(prompt)
        return json.dumps({"facts": extra(page) if extra else []})
    call.engine = "fake"
    return call


# ============================================= hybrid through the real path

@pytest.mark.slow
def test_hybrid_reads_the_xlsx_through_the_real_extract_path(key):
    entry = key["files"]["ds12_pump.xlsx"]
    out = datasheet_offline.read_file(XLSX, office_input=True, ai_engine="ollama",
                                      model_call=bench.oracle_model_call(entry))
    assert out["status"] == "read"
    assert out["stages"][:3] == ["upload", "extract", "chunk"]
    assert out["flags"]["datasheet_office_input"] is True
    assert out["flags"]["datasheet_ai_reader"] == "ollama"
    ai = out["summary"]["ai_reader"]
    # Every answer on the sheet is the AI's: written as its own where the
    # rules read nothing (free text), agreed where the rules read the same
    # value - since the unit-cell fix the rules read "Capacity | m3/h | 42".
    assert ai["engine"] == "oracle" and ai["pages_read"] == 1
    assert ai["facts_written"] + ai["agreed"] >= 8
    model_facts = [f for f in out["facts"] if f["extraction_method"] == datasheet_ai.EXTRACTION_METHOD]
    assert {f["field_label"] for f in model_facts} >= {"Pumped fluid", "Casing material"}
    [capacity] = [f for f in out["facts"] if f["field_label"] == "Capacity"]
    assert capacity["extraction_method"] == "xlsx" and capacity["raw_unit"] == "m3/h"
    assert capacity["confidence"] == datasheet_ai.AGREED_CONFIDENCE
    assert all(f["section"] == "model:offered" for f in model_facts)
    # Scored as the owner will see it: every answer, nothing wrong.
    reading = bench.read_file_with("hybrid:oracle", XLSX, model_call=bench.oracle_model_call(entry))
    s = bench.score_file(entry, reading["facts"])
    assert (s["found"], s["wrong_value"], s["forbidden"]) == (8, 0, 0)
    # ...and more than the rules alone read from the same workbook.
    rules = bench.score_file(entry, bench.read_file_with("rules+office", XLSX)["facts"])
    assert rules["found"] < s["found"]


@pytest.mark.slow
def test_hybrid_reads_a_pdf_through_the_real_extract_path(key):
    entry = key["files"]["ds07_gate_valve_free_text.pdf"]
    reading = bench.read_file_with("hybrid:oracle", FREE_TEXT,
                                   model_call=bench.oracle_model_call(entry))
    assert reading["status"] == "read" and reading["calls"] == 2   # two runs of one page
    assert "extract" in reading["stages"] and "chunk" in reading["stages"]
    assert reading["ai_reader"]["ai_only"] >= 5
    assert any(f["method"] == datasheet_ai.EXTRACTION_METHOD for f in reading["facts"])
    s = bench.score_file(entry, reading["facts"])
    alone = bench.score_file(entry, bench.read_file_with("rules", FREE_TEXT)["facts"])
    assert s["found"] >= 5 > alone["found"]


@pytest.mark.slow
def test_the_oracle_run_is_labelled_an_upper_bound_not_an_ai(key):
    report = bench.run_reader(bench.ORACLE, key, files=["ds02_psv_unruled.pdf"])
    assert report["label"] == bench.ORACLE_LABEL and "not an AI" in report["label"]
    assert bench.summary_rows([report])[0]["label"] == bench.ORACLE_LABEL


# ========================================================== the gate holds

@pytest.mark.slow
def test_an_ai_only_fact_whose_quote_is_not_on_the_page_is_not_stored():
    def invented(page):
        return [{"field": "Spring material", "value": "Inconel X-750", "unit": None,
                 "quote": "Spring material : Inconel X-750", "kind": "offered"}]
    out = datasheet_offline.read_file(PSV, office_input=True, ai_engine="ollama",
                                      model_call=_model(invented))
    assert out["status"] == "read"
    ai = out["summary"]["ai_reader"]
    assert ai["pages_read"] == 1
    assert ai["proposals_rejected"].get("quote_not_on_page") == 1
    assert ai["facts_written"] == 0
    assert not any("Inconel" in str(f["field_value"]) or f["field_label"] == "Spring material"
                   for f in out["facts"])


@pytest.mark.slow
def test_a_disagreement_is_stored_as_a_conflict_and_counted(key):
    """The AI reads field A with row B's value (a quote from A's label to B's
    value is on the page): both readings kept, both flagged for an engineer."""
    first, second = key["files"]["ds01_pump_ruled.pdf"]["expected"][:2]

    def cross(page):
        found_a = bench._oracle_quote(first, page)
        found_b = bench._oracle_quote(second, page)
        if not (found_a and found_b):
            return []
        start = page.index(found_a[1])
        end = page.index(found_b[1]) + len(found_b[1])
        # The quote runs to the end of row B's VALUE and its UNIT: since W2
        # (audit M2) a unit must be in the quote or its column header, so a
        # quote that stopped at "85" and reported unit "m" would be refused
        # for that, not for the disagreement this test is about.
        unit = second.get("unit")
        if unit:
            tail = re.match(r"\s*" + re.escape(unit), page[end:])
            if tail:
                end += tail.end()
        return [{"field": found_a[0], "value": second["value"], "unit": second.get("unit"),
                 "quote": page[start:end], "kind": "offered"}]
    reading = bench.read_file_with("hybrid:ollama", RULED, model_call=_model(cross))
    assert reading["status"] == "read"
    assert reading["ai_reader"]["conflicts"] >= 1
    states = [f for f in reading["facts"] if f["state"] == datasheets.GEOMETRY_CONFLICT]
    assert len(states) >= 2 and reading["conflicts"] == len(states)
    assert {f["method"] for f in states} >= {datasheet_ai.EXTRACTION_METHOD}


# ================================================ the switches come back off

def test_the_flags_and_paths_are_restored_after_a_run_even_on_an_exception(monkeypatch):
    before = (settings.data_dir, settings.db_path, settings.upload_dir)
    env_before = {n: os.environ.get(n) for n in ("DATA_DIR", "DB_PATH", "UPLOAD_DIR")}
    seen = {}

    def boom(path, *, run_ocr):
        seen.update(office=settings.datasheet_office_input, ai=settings.datasheet_ai_reader,
                    env=os.environ.get("DATA_DIR"), data=settings.data_dir)
        raise RuntimeError("a stage blew up")
    monkeypatch.setattr(datasheet_offline, "_ingest", boom)
    with pytest.raises(RuntimeError):
        datasheet_offline.read_file(PSV, office_input=True, ai_engine="claude",
                                    model_call=_model())
    # During the run: the switches the reader asked for, the throwaway paths.
    assert seen["office"] is True and seen["ai"] == "claude"
    assert seen["env"] == str(seen["data"]) and seen["data"] != before[0]
    # After it, even though it raised: exactly what production had.
    assert settings.datasheet_office_input is False
    assert settings.datasheet_ai_reader == "off"
    assert (settings.data_dir, settings.db_path, settings.upload_dir) == before
    assert {n: os.environ.get(n) for n in env_before} == env_before
    assert datasheet_ai._CALL_OVERRIDE.get() is None


@pytest.mark.slow
def test_a_normal_run_restores_the_flags_too():
    datasheet_offline.read_file(PSV, office_input=True, ai_engine="ollama", model_call=_model())
    assert settings.datasheet_office_input is False and settings.datasheet_ai_reader == "off"


def test_the_model_call_override_never_switches_the_reader_on():
    with datasheet_ai.using_model_call(_model()):
        assert datasheet_ai.model_call_for("off") == (None, "DATASHEET_AI_READER is off")
        call, why = datasheet_ai.model_call_for("ollama")
        assert why is None and call.engine == "fake"
    assert datasheet_ai._CALL_OVERRIDE.get() is None


def test_rules_mode_is_todays_production_for_office_files():
    xlsx = bench.read_file_with("rules", XLSX)
    docx = bench.read_file_with("rules", BENCH / "ds13_heater.docx")
    assert xlsx["status"] == "stored_not_indexed" and xlsx["facts"] == []
    # W5b-01 (#525): a Word file is no longer refused at upload by default (it
    # is indexed and searchable), but with DATASHEET_OFFICE_INPUT off its
    # datasheet FIELDS are not read - so today's production still yields no facts.
    assert docx["status"] == "read" and docx["facts"] == []
    assert bench.read_file_with("rules+office", XLSX)["status"] == "read"


# ==================================================== OCR is never a silent 0

@pytest.mark.slow
def test_a_scan_with_no_ocr_engine_is_reported_as_ocr_unavailable(monkeypatch, tmp_path, key):
    monkeypatch.setattr(settings, "ocr_model_dir", tmp_path / "no-models-here")
    ok, why = datasheet_offline.ocr_available()
    assert ok is False and "missing" in why
    out = datasheet_offline.read_file(SCAN, office_input=False, ai_engine=None)
    assert out["status"] == datasheet_offline.OCR_UNAVAILABLE
    assert out["ocr"]["pages_needing_ocr"] == 1 and "ocr unavailable" in out["reason"]
    report = bench.run_reader("rules", key, files=["ds11_flowmeter_scanned.pdf"])
    row = report["files"]["ds11_flowmeter_scanned.pdf"]
    assert row["status"] == "ocr_unavailable" and report["total"]["files_unsupported"] == 1


# ===================================================== which engines are built

@pytest.mark.slow
def test_all_local_never_builds_a_claude_call(monkeypatch, tmp_path):
    assert bench.readers_for("all-local") == (
        "rules", "rules+office", "hybrid:ollama", "ai-only:ollama")
    built = []

    def fake_build(reader):
        built.append(reader)
        return _model(), None

    def no_claude(*_a, **_k):
        raise AssertionError("a Claude call was built under all-local")
    from app import reader_transport
    monkeypatch.setattr(bench, "build_model_call", fake_build)
    monkeypatch.setattr(datasheet_ai, "_claude_call", no_claude)
    monkeypatch.setattr(reader_transport, "transport", no_claude)
    out = tmp_path / "local.json"
    assert bench.main(["--reader", "all-local", "--files", "ds02_psv_unruled.pdf",
                       "--out", str(out)]) == 0
    assert built == ["hybrid:ollama", "ai-only:ollama"]
    report = json.loads(out.read_text())
    assert [r["reader"] for r in report["reports"]] == list(bench.ALL_LOCAL)
    assert [r["reader"] for r in report["summary"]] == list(bench.ALL_LOCAL)


@pytest.mark.slow
def test_hybrid_claude_is_productions_engine_metered_by_claude_spend(monkeypatch):
    """Against a FAKE transport: nothing leaves the machine."""
    from app import claude_budget, claude_spend, reader_transport
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
    monkeypatch.delenv("STANDARDS_READER_MODEL", raising=False)
    sent = []

    def transport(url, *, headers, body, timeout):
        sent.append(body)
        return {"content": [{"type": "text", "text": '{"facts": []}'}],
                "usage": {"input_tokens": 1000, "output_tokens": 100},
                "model": "claude-sonnet-4-5", "stop_reason": "end_turn"}
    transport.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    monkeypatch.setattr(reader_transport, "transport", lambda: transport)
    call, usage_fn = bench.build_model_call("hybrid:claude")
    assert isinstance(call, claude_budget.Budget) and call.step == datasheet_ai.STEP
    reading = bench.read_file_with("hybrid:claude", PSV, model_call=call)
    assert reading["status"] == "read" and reading["calls"] == 2 and len(sent) == 2
    assert claude_spend.spent(datasheet_ai.STEP) > 0      # production's step, the one ledger
    assert usage_fn()["estimated_usd"] > 0


def test_hybrid_claude_is_unavailable_without_reasoning_provider_claude(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    with pytest.raises(bench.ReaderUnavailable):
        bench.build_model_call("hybrid:claude")
