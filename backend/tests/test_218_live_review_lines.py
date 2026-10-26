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
