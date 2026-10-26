"""Order 224.9: a row whose value the vendor left blank is a BLANK fact, not "not on the page".

The form reader used to be told that "TBA" / "By vendor" is "not_on_page", so the
checklist then said "on the sheet but not read: engineer to check". Now the model may
answer "left_blank" with the marker; code proves it (the marker is a blank marker,
the quote is on the page and shows the label AND the marker). Every page text is
invented; the model is a fake.
"""

from __future__ import annotations

import pytest

from app import (
    datasheet_ai,
    datasheets,
    form_reader,
    form_reader_fields,
    form_reader_run,
)
from app.config import settings
from tests.test_form_reader import (  # noqa: F401
    PUMP,
    FakeModel,
    _extract,
    _read,
    row,
    storage,
)

PAGE = "EQUIPMENT DATASHEET - CENTRIFUGAL PUMP\nRated flow: By Contractor\nDesign pressure: 23.5 barg\n"
DP_BLANK = row(
    "design_pressure",
    "By Contractor",
    "",
    "Design pressure By Contractor",
    "left_blank",
)
BLANK = row(
    "rated_flow", "By Contractor", "", "Rated flow: By Contractor", "left_blank"
)


def test_a_row_left_to_the_vendor_is_a_blank_fact_with_its_marker():
    reading, _ = _read(PAGE, [BLANK])
    (fact,) = [f for f in reading.facts if f["field_key"] == "rated_flow"]
    assert fact["form_blank"] is True and fact["value"] == "By Contractor"
    assert reading.status["rated_flow"] == form_reader.FILLED
    assert not [r for r in reading.rejected if r["field_key"] == "rated_flow"]


@pytest.mark.parametrize(
    "item, reason",
    [
        # a number is not a blank marker
        (
            row("rated_flow", "42", "", "Rated flow: By Contractor", "left_blank"),
            "blank_marker_not_proven",
        ),
        # the marker is not shown in the quote
        (
            row("rated_flow", "TBA", "", "Rated flow: By Contractor", "left_blank"),
            "blank_marker_not_proven",
        ),
        # the quote is not on the page
        (
            row(
                "rated_flow", "By Contractor", "", "Rated flow: By Vendor", "left_blank"
            ),
            "quote_not_on_page",
        ),
        # the quote is on the page but does not name the field
        (
            row("rated_flow", "By Contractor", "", "flow: By Contractor", "left_blank"),
            "label_not_in_quote",
        ),
        (row("rated_flow", "By Contractor", "", "", "left_blank"), "quote_missing"),
    ],
)
def test_a_left_blank_answer_the_code_cannot_prove_is_refused_with_its_reason(
    item, reason
):
    reading, _ = _read(PAGE, [item])
    assert not [f for f in reading.facts if f["field_key"] == "rated_flow"]
    assert [
        r["reason"] for r in reading.rejected if r["field_key"] == "rated_flow"
    ] == [reason]


def test_the_label_must_be_in_the_quote():
    text = PAGE + "Note: By Contractor\n"
    reading, _ = _read(
        text,
        [row("rated_flow", "By Contractor", "", "Note: By Contractor", "left_blank")],
    )
    assert [
        r["reason"] for r in reading.rejected if r["field_key"] == "rated_flow"
    ] == ["label_not_in_quote"]


def test_a_real_value_on_another_page_beats_a_blank_marker():
    model = FakeModel(
        {
            1: [[BLANK]],
            2: [[row("rated_flow", "42", "m3/h", "Rated flow: 42 m3/h")]],
        }
    )
    reading = form_reader.read_form(
        {1: PAGE, 2: "PUMP\nRated flow: 42 m3/h\n"}, PUMP, model
    )
    (fact,) = [f for f in reading.facts if f["field_key"] == "rated_flow"]
    assert fact["value"] == "42" and not fact["form_blank"]
    assert reading.status["rated_flow"] == form_reader.FILLED


def test_two_pages_that_both_leave_it_blank_are_one_blank_fact():
    model = FakeModel({1: [[BLANK]], 2: [[BLANK]]})
    reading = form_reader.read_form({1: PAGE, 2: PAGE}, PUMP, model)
    assert len([f for f in reading.facts if f["field_key"] == "rated_flow"]) == 1


def test_the_prompt_and_the_schema_offer_left_blank_and_the_version_moved():
    assert form_reader_fields.LEFT_BLANK in form_reader_fields.STATUSES
    assert "left_blank" in form_reader_fields.PROMPT
    assert form_reader_fields.PROMPT_VERSION != "form-reader-1"
    enum = form_reader_fields.schema_for([])["properties"]["fields"]["items"][
        "properties"
    ]["status"]["enum"]
    assert "left_blank" in enum


def test_the_ai_gate_keeps_a_proven_blank_but_still_drops_any_other_blank():
    fact = {"field": "Rated flow", "value": "By Contractor", "unit": None}
    assert datasheets._ai_gate({**fact, "form_blank": True}, set()) is None
    assert datasheets._ai_gate(fact, set()) == "blank"


def test_end_to_end_the_blank_is_stored_as_a_blank_fact_the_checklist_reads(
    storage,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    monkeypatch.setattr(settings, "datasheet_reader_mode", "form")
    from tests.test_datasheet_ai import _datasheet_pdf, _ingest

    doc = _ingest(
        _datasheet_pdf(
            storage / "d.pdf",
            [("Design pressure", "By Contractor"), ("Design temperature", "120 C")],
        )
    )
    monkeypatch.setattr(
        datasheet_ai,
        "model_call_for",
        lambda engine=None, packet_shape=None: (FakeModel({1: [[DP_BLANK]]}), None),
    )
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert result["ai_reader"]["form"]["filled"] >= 1, (
        "the form reader's blank, not only the rules'"
    )
    facts = datasheets.list_facts(doc, allowed_document_ids=frozenset({doc}))
    blanks = [f for f in facts if f["field_name"] == "design pressure"]
    assert blanks and all(f["is_blank"] for f in blanks)
    assert blanks[0]["blank_marker"].lower() == "by contractor"


def test_the_reader_summary_says_which_field_was_refused_and_why():
    reading, _ = _read(
        PAGE, [row("rated_flow", "42", "", "Rated flow: By Contractor", "left_blank")]
    )
    run = form_reader_run.as_ai_run(
        reading, [1], engine="e", model="m", unavailable=None
    )
    run["rejected_fields"] = {"rated_flow: blank_marker_not_proven": 1}
    summary = datasheets.reader_summary(
        run, {"proposals_rejected": {"x": 2}, "dropped": {"blank": 1}}, pages=[1]
    )
    assert summary["rejected_fields"] == {"rated_flow: blank_marker_not_proven": 1}
    assert summary["refused_by_reason"] == {"x": 2, "dropped: blank": 1}
    assert summary["refused_by_gate"] == 3


@pytest.mark.parametrize(
    "value, line",
    [
        ("", "Rated flow: By Contractor"),  # an empty value proves nothing
        ("-", "Rated flow: 10-12 m3/h"),  # a dash inside a range
        ("later", "Rated flow: 10 m3/h (later revision)"),  # a word inside a note
        ("later", "Rated flow: 5 m3/h later"),  # a real value comes before the marker
    ],
)
def test_a_marker_found_inside_a_real_value_never_turns_it_into_a_blank(value, line):
    reading, _ = _read(
        "DATASHEET\n" + line + "\n", [row("rated_flow", value, "", line, "left_blank")]
    )
    assert reading.facts == [], "the marker was found inside a printed value"
    assert [r["field_key"] for r in reading.rejected if r["field_key"] == "rated_flow"]


def test_a_dash_cell_after_the_label_alone_is_a_proven_blank():
    page = "DATASHEET\nRated flow -\n"
    reading, _ = _read(page, [row("rated_flow", "-", "", "Rated flow -", "left_blank")])
    assert [f["value"] for f in reading.facts if f["field_key"] == "rated_flow"] == [
        "-"
    ]


def test_the_summary_names_the_refused_field_from_a_real_read():
    model = FakeModel(
        {
            1: [
                [
                    row(
                        "rated_flow",
                        "42",
                        "",
                        "Rated flow: By Contractor",
                        "left_blank",
                    )
                ]
            ]
        }
    )
    run = form_reader_run.read_document({1: PAGE}, PUMP, model_call=model)
    assert run["rejected_fields"]["rated_flow: blank_marker_not_proven"] == 1
