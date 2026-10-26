"""Order 218: with REVIEW_DEBUG on, the backend console shows each review step
as it happens; with it off, nothing is printed and nothing changes.

Invented text only; a fake `prompt -> text` model; no network, no live data.
"""

from __future__ import annotations

import logging

import pytest

from app import datasheet_ai, job_progress, review_trace
from app.config import settings


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def console():
    handler = Capture()
    review_trace.log.addHandler(handler)
    old = review_trace.log.level
    review_trace.log.setLevel(logging.INFO)
    yield handler
    review_trace.log.removeHandler(handler)
    review_trace.log.setLevel(old)


def fake_model(prompt: str) -> str:
    return '{"facts": []}'


fake_model.model = "invented-model:1b"


def test_the_phases_print_a_start_and_a_done_line_in_order(console, monkeypatch):
    monkeypatch.setattr(settings, "review_debug", True)
    timings: dict = {}
    with review_trace.timed(timings, "read"):
        pass
    with review_trace.timed(timings, "standards"):
        pass
    lines = console.lines
    assert lines[0] == "[1,2,3/10 READ,CLEAN,EQUIPMENT] started"
    assert lines[1].startswith("[1,2,3/10 READ,CLEAN,EQUIPMENT] done in ") and lines[
        1
    ].endswith(" s")
    assert lines[2] == "[4/10 STANDARDS] started" and lines[3].startswith(
        "[4/10 STANDARDS] done in "
    )
    assert set(timings) == {"read", "standards"}  # the stored timings are as before


def test_each_page_prints_one_line_with_its_values_seconds_and_model(
    console, monkeypatch
):
    monkeypatch.setattr(settings, "review_debug", True)
    datasheet_ai.read_pages(
        {1: "Design pressure 9 barg", 2: "Design temperature 90 C"}, fake_model
    )
    pages = [line for line in console.lines if line.startswith("[1/10 READ] page")]
    assert len(pages) == 2
    assert pages[0].startswith("[1/10 READ] page 1")
    assert pages[1].startswith("[1/10 READ] page 2")
    for line in pages:
        assert (
            " of 2: " in line
            and " values, " in line
            and " s, model=invented-model:1b" in line
        )


def test_nothing_is_printed_with_the_switch_off(console, monkeypatch):
    monkeypatch.setattr(settings, "review_debug", False)
    with review_trace.timed({}, "read"):
        pass
    datasheet_ai.read_pages({1: "Design pressure 9 barg"}, fake_model)
    assert console.lines == []


def test_a_failing_print_never_breaks_the_review_or_the_reading(console, monkeypatch):
    monkeypatch.setattr(settings, "review_debug", True)

    def boom(*args, **kwargs):
        raise RuntimeError("console gone")

    monkeypatch.setattr(review_trace, "page_line", boom)
    ran = datasheet_ai.read_pages({1: "Design pressure 9 barg"}, fake_model)
    assert 1 in ran["pages"]  # the page was read all the same
    monkeypatch.setattr(review_trace.log, "info", boom)
    timings: dict = {}
    with review_trace.timed(timings, "compare"):
        pass
    assert "compare" in timings


def test_the_reading_is_the_same_with_the_switch_on_or_off(monkeypatch):
    monkeypatch.setattr(settings, "review_debug", False)
    off = datasheet_ai.read_pages({1: "Design pressure 9 barg"}, fake_model)
    monkeypatch.setattr(settings, "review_debug", True)
    on = datasheet_ai.read_pages({1: "Design pressure 9 barg"}, fake_model)
    assert {k: v for k, v in on.items() if k != "seconds"} == {
        k: v for k, v in off.items() if k != "seconds"
    }
    assert job_progress._where.get() is not None


def test_the_page_line_counts_values_and_names_a_failure(console, monkeypatch):
    monkeypatch.setattr(settings, "review_debug", True)
    review_trace.page_line(
        2, (2, 5), {"accepted": [{}, {}, {}]}, 12.44, fake_model, "ollama"
    )
    review_trace.page_line(
        3, (3, 5), {"error": "no text on this page"}, 0.0, None, "ollama"
    )
    assert (
        console.lines[0]
        == "[1/10 READ] page 2 of 5: 3 values, 12.4 s, model=invented-model:1b"
    )
    assert (
        console.lines[1]
        == "[1/10 READ] page 3 of 5: read failed: no text on this page, 0.0 s, model=ollama"
    )


# ------------------------------------------------ order 218.1: the live file and the stages


@pytest.fixture
def live_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "review_debug", True)
    return tmp_path / "debug" / review_trace.LIVE_FILE


def test_every_live_line_also_goes_to_the_file_with_a_time(console, live_file):
    review_trace.live("hello")
    review_trace.live("second")
    lines = live_file.read_text(encoding="utf-8").splitlines()
    assert [line[9:] for line in lines] == ["hello", "second"]
    assert lines[0][2] == ":" and lines[0][8] == " "  # HH:MM:SS then the line
    assert console.lines == ["hello", "second"]


def test_the_file_grows_during_a_read_of_a_small_invented_sheet(console, live_file):
    datasheet_ai.read_pages(
        {1: "Design pressure 9 barg", 2: "Design temperature 90 C"}, fake_model
    )
    text = live_file.read_text(encoding="utf-8")
    assert text.count("[1/10 READ] page") == 2 and "model=invented-model:1b" in text


def test_nothing_is_written_with_the_switch_off(console, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "review_debug", False)
    review_trace.live("x")
    assert not (tmp_path / "debug").exists()
    assert review_trace.install_live([("x", "f", "l")], providers=False) == 0


def test_a_wrapped_stage_passes_the_result_through_and_writes_start_and_end(
    console, live_file
):
    import types

    module = types.ModuleType("fake_stage")
    module.work = lambda items, scale=1: [i * scale for i in items]
    assert (
        review_trace.install_live([(module, "work", "do the work")], providers=False)
        == 1
    )
    assert module.work([1, 2], scale=3) == [3, 6]  # arguments in, result out, untouched
    assert (
        review_trace.install_live([(module, "work", "do the work")], providers=False)
        == 0
    )  # once only
    text = live_file.read_text(encoding="utf-8")
    assert (
        "do the work: start" in text
        and "do the work: done in " in text
        and "| 2 items" in text
    )


def test_a_failing_stage_is_reported_and_still_raises(console, live_file):
    import types

    module = types.ModuleType("fake_stage")

    def broken():
        raise ValueError("document words")

    module.broken = broken
    review_trace.install_live([(module, "broken", "stage")], providers=False)
    with pytest.raises(ValueError):
        module.broken()
    text = live_file.read_text(encoding="utf-8")
    assert "stage: failed after " in text and "(ValueError)" in text
    assert "document words" not in text  # the type only, never the message


def test_an_ai_call_and_an_ai_task_each_print_one_line(console, live_file):
    from types import SimpleNamespace as NS

    class Provider:
        def reason(self, packet):
            return NS(
                model_tag="invented-model:1b",
                tokens_in=120,
                tokens_out=30,
                wall_time_s=8.4,
                finish_reason="stop",
            )

    Provider.reason = review_trace._ai_call(Provider.reason)
    Provider().reason(NS(step="ai_task:part_scope"))
    run_task = review_trace._ai_task(
        lambda spec, text, **kw: NS(model="invented-model:1b", cached=True, state="ok")
    )
    run_task(NS(name="part_scope"), "text")
    first, second = [
        line[9:] for line in live_file.read_text(encoding="utf-8").splitlines()
    ]
    assert first.startswith(
        "AI call | task=ai_task:part_scope | model=invented-model:1b | "
    )
    assert first.endswith(" | tokens=120/30 | cache=miss")
    assert second.startswith("AI task | task=part_scope | model=invented-model:1b | ")
    assert second.endswith(" | cache=hit | state=ok")


def test_every_followed_stage_still_exists():
    """A renamed function would silently drop out of the live file."""
    import importlib

    for holder, name, _label in review_trace.STAGES:
        assert callable(
            getattr(importlib.import_module(f"app.{holder}"), name, None)
        ), (holder, name)


def test_a_bare_response_or_result_is_returned_unchanged_and_raises_nothing(
    console, live_file
):
    """The model answered; a line that cannot be built must not undo that."""
    bare_response, bare_result = object(), object()

    class Provider:
        def reason(self, packet):
            return bare_response

    Provider.reason = review_trace._ai_call(Provider.reason)
    assert Provider().reason(object()) is bare_response
    run_task = review_trace._ai_task(lambda spec, text, **kw: bare_result)
    assert run_task(object(), "text") is bare_result
