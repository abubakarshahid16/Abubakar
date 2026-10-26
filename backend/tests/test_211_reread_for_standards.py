"""Order 211, audit R2: the sheet is read again for the standards a review chose.

A first review reads the sheet before any standard is chosen, so the fields the
standards ask about were never asked. These tests hold the decision (which
fields the last read did not ask), the one extra read, the order inside the
review job and the record of what a read asked. No model, no real document.
"""

from __future__ import annotations

import pytest

from app import (
    datasheets,
    form_reader,
    form_reader_run,
    reread_for_standards,
    review_jobs,
)
from app.config import settings
from app.form_reader_fields import field_list_for
from tests.test_p3_review_jobs import (  # noqa: F401
    W,
    _enqueue,
    temp_storage,
    world,
)

SUBJECTS = ["set pressure", "outlet size"]


@pytest.fixture
def summary(monkeypatch):
    """The last read's stored summary, and the standards' fields, by hand."""
    state = {"summary": {"engine": "ollama", "asked_subjects": []}}
    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda d: state["summary"])
    monkeypatch.setattr(
        form_reader_run,
        "requirement_subjects",
        lambda ids: list(SUBJECTS) if ids else [],
    )
    monkeypatch.setattr(form_reader_run, "equipment_type_of", lambda d, c: None)
    monkeypatch.setattr(reread_for_standards, "_chunks", lambda d: [])
    return state


def test_a_field_the_last_read_never_asked_is_missing(summary):
    assert reread_for_standards.missing_subjects("d", ["std"]) == [
        "Set pressure",
        "Outlet size",
    ]


def test_a_field_the_last_read_asked_is_not_missing(summary):
    summary["summary"]["asked_subjects"] = ["Set pressure"]
    assert reread_for_standards.missing_subjects("d", ["std"]) == ["Outlet size"]
    summary["summary"]["asked_subjects"] = ["Set pressure", "Outlet size"]
    assert reread_for_standards.missing_subjects("d", ["std"]) == []


def test_a_field_the_types_own_form_already_has_is_not_missing(summary, monkeypatch):
    own = field_list_for(None)[0]
    monkeypatch.setattr(
        form_reader_run,
        "requirement_subjects",
        lambda ids: [own.name.lower(), "outlet size"],
    )
    assert reread_for_standards.missing_subjects("d", ["std"]) == ["Outlet size"]


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        {"engine": "off"},
        {"engine": "ollama", "unavailable": "ollama engine unavailable"},
    ],
)
def test_a_last_read_that_was_not_a_model_read_is_not_read_again(summary, stored):
    summary["summary"] = stored
    assert reread_for_standards.missing_subjects("d", ["std"]) == []


def test_no_chosen_standard_asks_for_nothing(summary):
    assert reread_for_standards.missing_subjects("d", []) == []


@pytest.fixture
def reads(monkeypatch):
    """`extract_facts` as a spy: which standards the reader would ask for."""
    calls = []

    def spy(document_id, **kw):
        calls.append({"standards": form_reader_run.standards_of(document_id), **kw})

    monkeypatch.setattr(datasheets, "extract_facts", spy)
    monkeypatch.setattr(
        reread_for_standards, "chosen_standards", lambda run_id: ["s1", "s2"]
    )
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(settings, "datasheet_reader_mode", "form")
    return calls


def test_the_sheet_is_read_once_more_for_the_chosen_standards(reads, monkeypatch):
    monkeypatch.setattr(
        reread_for_standards, "missing_subjects", lambda d, ids: ["Set pressure"]
    )
    out = reread_for_standards.for_review("d", frozenset({"d"}), "run-1")
    assert out == {"subjects": 1}
    assert len(reads) == 1
    assert reads[0]["standards"] == ["s1", "s2"], (
        "the reader asks for THESE standards' fields"
    )
    assert reads[0]["replace"] is True and reads[0]["review_run_id"] == "run-1"
    assert form_reader_run.standards_of("d") == [], "the override ends with the read"


def test_the_extra_read_is_timed_in_the_jobs_trace_and_only_when_it_happens(
    reads, monkeypatch
):
    timings = {}
    monkeypatch.setattr(reread_for_standards, "missing_subjects", lambda d, ids: [])
    reread_for_standards.for_review("d", frozenset({"d"}), "run-1", timings)
    assert timings == {}
    monkeypatch.setattr(
        reread_for_standards, "missing_subjects", lambda d, ids: ["Set pressure"]
    )
    reread_for_standards.for_review("d", frozenset({"d"}), "run-1", timings)
    assert list(timings) == ["read_again"]


def test_nothing_missing_is_no_second_read(reads, monkeypatch):
    monkeypatch.setattr(reread_for_standards, "missing_subjects", lambda d, ids: [])
    assert reread_for_standards.for_review("d", frozenset({"d"}), "run-1") is None
    assert reads == []


@pytest.mark.parametrize(
    ("name", "value"),
    [("datasheet_ai_reader", "off"), ("datasheet_reader_mode", "rules")],
)
def test_with_the_model_reader_or_the_form_off_there_is_no_second_read(
    reads, monkeypatch, name, value
):
    monkeypatch.setattr(
        reread_for_standards, "missing_subjects", lambda d, ids: ["Set pressure"]
    )
    monkeypatch.setattr(settings, name, value)
    assert reread_for_standards.for_review("d", frozenset({"d"}), "run-1") is None
    assert reads == []


def test_a_failed_second_read_leaves_the_first_in_place_and_the_review_going(
    monkeypatch,
):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(settings, "datasheet_reader_mode", "form")
    monkeypatch.setattr(reread_for_standards, "chosen_standards", lambda run_id: ["s1"])
    monkeypatch.setattr(
        reread_for_standards, "missing_subjects", lambda d, ids: ["Set pressure"]
    )

    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(datasheets, "extract_facts", boom)
    assert reread_for_standards.for_review("d", frozenset({"d"}), "run-1") is None


def test_reading_for_overrides_the_latest_runs_standards_only_inside_the_block():
    with form_reader_run.reading_for(["a", "", "b", "a"]):
        assert form_reader_run.standards_of("nothing") == ["a", "b"]
        with form_reader_run.reading_for([]):
            assert form_reader_run.standards_of("nothing") == []
        assert form_reader_run.standards_of("nothing") == ["a", "b"]
    assert form_reader_run.standards_of("nothing") == []


def test_a_read_records_the_requirement_fields_it_asked_and_the_summary_keeps_them(
    monkeypatch,
):
    def empty(page_texts, equipment_type, model_call, *, fields, **kw):
        return form_reader.FormReading(
            fields=fields, status={f.key: "missing" for f in fields}
        )

    monkeypatch.setattr(form_reader_run, "read_form", empty)
    run = form_reader_run.read_document(
        {1: "x"}, None, model_call=lambda *a, **k: {}, extra_subjects=SUBJECTS
    )
    assert run["asked_subjects"] == ["Set pressure", "Outlet size"]
    summary = datasheets.reader_summary(run, {}, pages=[1])
    assert summary["asked_subjects"] == ["Set pressure", "Outlet size"]
    plain = form_reader_run.read_document({1: "x"}, None, model_call=lambda *a, **k: {})
    assert plain["asked_subjects"] == []


def test_the_job_reads_again_after_the_standards_are_chosen_and_before_the_comparison(
    world,  # noqa: F811
    monkeypatch,
):
    from app import applicability, comparison

    order = []
    real_select = applicability.select

    def select(*a, **k):
        order.append("select")
        return real_select(*a, **k)

    real_compare = comparison.run_comparison

    def compare(*a, **k):
        order.append("compare")
        return real_compare(*a, **k)

    monkeypatch.setattr(applicability, "select", select)
    monkeypatch.setattr(comparison, "run_comparison", compare)
    monkeypatch.setattr(
        reread_for_standards,
        "for_review",
        lambda doc, scope, run, timings: order.append(("reread", doc, run)),
    )
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    assert order == ["select", ("reread", world["sub"], run_id), "compare"]
