"""Owner order 2026-10-11, item 1 (s1): the datasheet AI reader is ON by
default - "AI understands, code checks, engineer decides".

The reader already existed (`datasheet_ai`, "AI reads, code checks": a value is
kept only when its quote is on that page and two runs agree). What this adds:

  * DATASHEET_AI_READER defaults to "ollama" (local; nothing leaves the
    machine). Tests pin it off (`tests/env_isolation.py` TEST_PINS).
  * The local model is slow: every call has its own timeout
    (DATASHEET_AI_TIMEOUT_SECONDS, not the provider's 15 minutes), and a
    document has a time budget (DATASHEET_AI_MAX_SECONDS). A page past either
    keeps the code readers' reading, with the reason.
  * The review SAYS which reader read the sheet: the engine and model, the
    pages the AI read, and each page left to the code readers and why.

Invented data only.
"""
from __future__ import annotations

import httpx

from app import absence, datasheet_ai, datasheets, model_transport
from app.config import Settings, settings
from tests.test_datasheet_ai import (AGREE, ROWS, FakeModel, _datasheet_pdf, _ingest,  # noqa: F401
                                     _use, temp_storage)


# ---------------------------------------------------------------- the default

def test_the_ai_reader_is_on_by_default_with_the_local_engine_and_off_in_tests():
    assert Settings.model_fields["datasheet_ai_reader"].default == "ollama"
    assert settings.datasheet_ai_reader == "off"       # pinned for the suite


def test_the_time_limits_must_be_positive():
    for field in ("datasheet_ai_timeout_seconds", "datasheet_ai_max_seconds"):
        try:
            Settings(_env_file=None, **{field: 0})
        except ValueError as exc:
            assert "must be positive" in str(exc)
        else:
            raise AssertionError(f"{field}=0 was accepted")


# ---------------------------------------------------------------- timeouts

def test_the_local_engine_uses_its_own_timeout_and_records_its_model(monkeypatch):
    seen = []

    def post_json(path, body, *, timeout):
        seen.append(timeout)
        return {"response": '{"facts": []}', "model": body["model"], "done_reason": "stop"}
    monkeypatch.setattr(model_transport, "post_json", post_json)
    monkeypatch.setattr(settings, "datasheet_ai_timeout_seconds", 42.0)
    monkeypatch.setattr(settings, "datasheet_ai_ollama_model", "local-0001")
    call, why = datasheet_ai.model_call_for("ollama")
    assert why is None and call.model == "local-0001"
    datasheet_ai.read_page_text_with_ai("1 Design pressure 23.5 barg", 1, call)
    assert seen and set(seen) == {42.0}


class SlowOnPage:
    """Times out on the pages named; answers nothing elsewhere."""
    engine = "fake-engine"
    model = "fake-model"

    def __init__(self, exc):
        self.exc, self.calls = exc, []

    def __call__(self, prompt):
        self.calls.append(prompt)
        if "page two" in prompt:
            raise self.exc
        return '{"facts": []}'


def test_a_call_that_times_out_leaves_the_page_to_the_code_readers_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_timeout_seconds", 30.0)
    for exc in (TimeoutError(), httpx.ReadTimeout("slow")):
        model = SlowOnPage(exc)
        out = datasheet_ai.read_pages({1: "page one text", 2: "page two text", 3: "page three"}, model)
        assert out["timed_out"] == [2]
        assert out["reasons"] == {2: datasheet_ai.TIMED_OUT.format(seconds="30")}
        assert "timed out after 30 s" in out["reasons"][2]
        assert set(out["pages"]) == {1, 2, 3}                    # pages 1 and 3 still read


def test_another_failure_is_not_called_a_timeout():
    out = datasheet_ai.read_pages({1: "page two text"}, SlowOnPage(RuntimeError("down")))
    assert out["timed_out"] == [] and out["reasons"] == {1: "engine failed (RuntimeError)"}


def test_the_document_time_budget_stops_the_calls_and_names_every_page_left(monkeypatch):
    clock = iter([0.0, 10.0, 20.0, 1000.0, 1000.0, 1000.0])
    monkeypatch.setattr(datasheet_ai.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(settings, "datasheet_ai_max_seconds", 100.0)
    model = FakeModel()
    out = datasheet_ai.read_pages({1: "a", 2: "b", 3: "c", 4: "d"}, model)
    assert set(out["pages"]) == {1, 2}
    assert out["stopped"] == "time_budget"
    left = datasheet_ai.OUT_OF_TIME.format(seconds="100")
    assert out["reasons"] == {3: left, 4: left}
    assert model.calls == 4                                       # two runs per page, pages 1-2 only


# ---------------------------------------------------------------- the run says it

def test_the_extraction_keeps_what_read_the_sheet(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel([AGREE]))
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    got = datasheets.latest_reader_summary(doc)
    assert got["engine"] == "fake-engine" and got["pages"] == 1 and got["pages_read"] == 1
    assert got["code_only"] == {} and got["agreed"] >= 1


def test_with_the_reader_off_the_summary_says_code_readers_only(tmp_path):
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    assert datasheets.latest_reader_summary(doc) is None          # never read yet
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert datasheets.latest_reader_summary(doc) == {"engine": "off", "pages": 1}


def test_a_page_left_to_the_code_readers_is_in_the_summary(tmp_path, monkeypatch):
    _use(monkeypatch, FakeModel(raises=TimeoutError()))
    monkeypatch.setattr(settings, "datasheet_ai_timeout_seconds", 30.0)
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    got = datasheets.latest_reader_summary(doc)
    assert got["pages_read"] == 0 and got["timed_out"] == [1]
    assert got["code_only"] == {"1": datasheet_ai.TIMED_OUT.format(seconds="30")}


def test_the_review_line_names_the_reader_and_the_code_only_pages():
    line = absence.reader_summary_line
    assert line(None) is None
    assert line({"engine": "off", "pages": 5}) == (
        "Datasheet read by the code readers only (AI reader off; 5 page(s)).")
    assert line({"engine": "ollama", "model": "m1", "pages": 5, "unavailable": "ollama engine unavailable (X)"}) == (
        "AI reader ollama (m1) was not available (ollama engine unavailable (X)); "
        "the datasheet was read by the code readers only (5 page(s)).")
    slow = datasheet_ai.TIMED_OUT.format(seconds="180")
    assert line({"engine": "ollama", "model": "m1", "pages": 5, "pages_read": 3,
                 "code_only": {"2": slow, "4": slow}}) == (
        f"AI reader ollama (m1) read 3 of 5 page(s); code readers only on page(s) 2, 4: {slow}.")
    assert absence.split_lines({"reader": {"engine": "off", "pages": 2}})[0].startswith(
        "Datasheet read by the code readers only")
