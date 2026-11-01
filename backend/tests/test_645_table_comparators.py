"""#645 slice 2: a standard's TABLE row that states no comparator in words. The
comparator comes from the column HEADER (or the caption), read by code; the
stored quote carries the header line and the row line, both taken from the
chunk by code. A header that states none leaves the row unknown and refused.
A fake model stands in for the local one. Invented tables only."""

from __future__ import annotations

import pytest

from app import ai_requirement_chunks as arc
from app import ai_requirement_tables as art
from app import ai_requirements as air
from app.config import settings
from app.db import connect
from tests.test_645_chunk_extraction import drafts, item, reply
from tests.test_645_chunk_extraction import run as run_chunk
from tests.test_645_clause_checks import Fake
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixture
    _doc,
    review_run,
    temp_storage,
)


@pytest.fixture
def standard(monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    _doc("std", "STD-1.pdf", "COMPANY_STANDARD")
    return "std"


MIN_MAX = (
    "| Parameter | Min | Max | Unit |\n"
    "| --- | --- | --- | --- |\n"
    "| Design pressure | 1 | 10 | barg |\n"
    "| Design temperature | -20 | 120 | degC |"
)
ROW = "Design pressure | 1 | 10 | barg"


def row_item(**over) -> dict:
    base = {
        "quote": ROW,
        "subject": "design pressure",
        "operator": "<=",
        "value": "10",
        "unit": "barg",
    }
    return item(**{**base, **over})


def limits() -> set[tuple]:
    return {(d["operator"], d["value"], d["unit"]) for d in drafts()}


def raw_page(text: str) -> str:
    """The page as the raw extraction holds it: one cell per line."""
    out = []
    for line in text.splitlines():
        if "|" not in line:
            out.append(line)
        elif set(line) - set(" |-:"):
            out.extend(c.strip() for c in line.strip().strip("|").split("|"))
    return "\n".join(out)


def run(model_reply, text, *, page_text=None, **kw):
    """`run` of the chunk tests, with the chunk's page stored the raw way."""
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pages (document_id, page_no, text, char_count,"
            " batch_no) VALUES ('std', 1, ?, 1, 0)",
            (raw_page(text) if page_text is None else page_text,),
        )
    return run_chunk(model_reply, text, **kw)


def test_min_and_max_columns_give_two_limits_with_the_header_unit_column(standard):
    report = run(reply(row_item()), MIN_MAX)
    assert report["proposed"] == 2 and report["refused"] == {}
    assert limits() == {(">=", "1", "barg"), ("<=", "10", "barg")}
    page = raw_page(MIN_MAX)
    for draft in drafts():
        # the quote is the PAGE's own words (one cell per line), not the markdown
        assert draft["quote"].split("\n") == [
            "Parameter", "Min", "Max", "Unit",
            "Design pressure", "1", "10", "barg",
        ]  # fmt: skip
        assert "|" not in draft["quote"] and draft["quote"].split("\n")[0] in page
    held = (
        connect()
        .execute("SELECT superseded_at, requirement_type FROM standard_requirements")
        .fetchall()
    )
    assert {r["superseded_at"] for r in held} == {arc.HELD}
    assert {r["requirement_type"] for r in held} == {"statement"}


def test_unit_from_a_bracket_in_the_column_header(standard):
    table = "| Parameter | Min (barg) | Max (barg) |\n| Design pressure | 1 | 10 |"
    report = run(reply(row_item(quote="Design pressure | 1 | 10")), table)
    assert report["proposed"] == 2
    assert limits() == {(">=", "1", "barg"), ("<=", "10", "barg")}


def test_unit_in_the_row_cell_and_a_maximum_allowable_header(standard):
    table = "| Item | Maximum allowable working pressure |\n| Vessel A | 19 barg |"
    report = run(
        reply(row_item(quote="Vessel A | 19 barg", subject="vessel A", value="19")),
        table,
    )
    assert report["proposed"] == 1
    assert limits() == {("<=", "19", "barg")}


def test_a_limit_column_without_direction_stays_unknown_and_is_refused(standard):
    table = "| Parameter | Limit |\n| Design pressure | 10 barg |"
    report = run(reply(row_item(quote="Design pressure | 10 barg")), table)
    assert report["proposed"] == 0 and drafts() == []
    assert report["refused"] == {arc.COMPARATOR_NOT_STATED: 1}


def test_a_header_with_both_directions_in_one_cell_is_unknown(standard):
    table = "| Parameter | Min/Max (barg) |\n| Design pressure | 10 |"
    report = run(reply(row_item(quote="Design pressure | 10")), table)
    assert report["proposed"] == 0 and drafts() == []
    assert report["refused"] == {arc.COMPARATOR_NOT_STATED: 1}


def test_a_table_with_no_header_row_gives_no_comparator(standard):
    table = "Design pressure | 10 | barg\nDesign temperature | 120 | degC"
    report = run(reply(row_item(quote="Design pressure | 10 | barg")), table)
    assert report["proposed"] == 0 and drafts() == []
    assert sum(report["refused"].values()) == 1


def test_a_header_cell_absent_from_the_page_is_refused(standard):
    page = raw_page(MIN_MAX).replace("Max\n", "")
    report = run(reply(row_item()), MIN_MAX, page_text=page)
    assert report["proposed"] == 0 and drafts() == []
    assert report["refused"] == {art.CELLS_NOT_ON_PAGE: 1}


def test_cells_out_of_reading_order_on_the_page_are_refused(standard):
    page = "Design pressure\n1\n10\nbarg\nParameter\nMin\nMax\nUnit"
    report = run(reply(row_item()), MIN_MAX, page_text=page)
    assert report["proposed"] == 0 and drafts() == []


def test_a_missing_page_text_refuses(standard):
    report = run(reply(row_item()), MIN_MAX, page_text="")
    assert report["proposed"] == 0 and drafts() == []


def test_accept_checks_the_quote_on_the_page_again(standard):
    run(reply(row_item()), MIN_MAX)
    [maximum] = [d for d in drafts() if d["operator"] == "<="]
    with connect() as conn:
        conn.execute("UPDATE pages SET text = 'a different page' WHERE page_no = 1")
    with pytest.raises(air.DraftError, match="not on the page"):
        air.decide_draft(
            maximum["id"],
            decision="accept",
            allowed_document_ids=frozenset({"std"}),
            actor={"id": None},
        )


def test_a_prose_header_is_not_a_direction(standard):
    for cell in (
        "Remarks: minimum thickness shall be verified",
        "Minimum thickness shall be verified",
        "Notes on the maximum value",
    ):
        assert art.header_operator(cell) is None
    table = (
        "| Parameter | Remarks: minimum thickness shall be verified |\n| Wall | 6 mm |"
    )
    report = run(reply(row_item(quote="Wall | 6 mm", value="6", unit="mm")), table)
    assert report["proposed"] == 0 and drafts() == []
    assert art.header_operator("Minimum wall thickness") == ">="


def test_a_value_not_in_the_row_cells_is_refused(standard):
    report = run(reply(row_item(value="15")), MIN_MAX)
    assert report["proposed"] == 0 and drafts() == []
    assert sum(report["refused"].values()) == 1


def test_a_value_only_in_the_label_column_is_not_a_limit(standard):
    table = "| Parameter | Max (barg) |\n| Class 150 | 10 |"
    report = run(reply(row_item(quote="Class 150 | 10", value="150")), table)
    assert report["proposed"] == 0 and drafts() == []


def test_a_model_direction_the_header_contradicts_is_refused(standard):
    report = run(reply(row_item(operator=">=", value="10")), MIN_MAX)
    assert report["proposed"] == 0 and drafts() == []
    assert air.OPERATOR_DISAGREED in report["refused"]


def test_a_model_unit_the_table_does_not_hold_is_refused(standard):
    report = run(reply(row_item(unit="psi")), MIN_MAX)
    assert report["proposed"] == 0 and drafts() == []


def test_a_range_cell_is_not_a_single_limit(standard):
    table = "| Parameter | Max (barg) |\n| Design pressure | 5-10 |"
    report = run(reply(row_item(quote="Design pressure | 5-10", value="10")), table)
    assert report["proposed"] == 0 and drafts() == []


def test_a_caption_gives_the_direction_when_no_header_cell_does(standard):
    table = (
        "Maximum allowable working pressure\n"
        "| Flange class | Value (barg) |\n"
        "| Class 150 | 19 |"
    )
    report = run(
        reply(row_item(quote="Class 150 | 19", subject="class 150", value="19")),
        table,
    )
    assert report["proposed"] == 1
    assert limits() == {("<=", "19", "barg")}
    assert drafts()[0]["quote"].splitlines()[0] == "Maximum allowable working pressure"


def test_a_caption_does_not_override_a_header_that_states_a_direction(standard):
    table = (
        "Maximum allowable working pressure\n"
        "| Parameter | Min (barg) | Typical (barg) |\n"
        "| Design pressure | 1 | 5 |"
    )
    report = run(reply(row_item(quote="Design pressure | 1 | 5", value="5")), table)
    assert ("<=", "5", "barg") not in limits()
    assert report["proposed"] <= 1


def test_a_conditional_row_without_its_condition_is_refused(standard):
    table = "| Parameter | Max (barg) |\n| Design pressure when sour | 10 |"
    report = run(reply(row_item(quote="Design pressure when sour | 10")), table)
    assert report["proposed"] == 0 and drafts() == []


def test_the_same_row_is_not_proposed_twice(standard):
    run(reply(row_item()), MIN_MAX)
    again = arc.extract_standard(
        "std",
        allowed_document_ids=frozenset({"std"}),
        max_chunks=5,
        provider=Fake(*([reply(row_item())] * 3)),
        unload=lambda provider: None,
    )
    assert again["proposed"] == 0 and len(drafts()) == 2
    assert again["refused"] == {arc.ALREADY_HELD: 2}


def test_switch_off_reads_and_writes_nothing(standard, monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", False)
    report = run(reply(row_item()), MIN_MAX)
    assert report["chunks"] == 0 and report["proposed"] == 0 and drafts() == []


def test_a_chunk_across_pages_is_refused(standard):
    report = run(reply(row_item()), MIN_MAX, page_end=2)
    assert report["proposed"] == 0 and drafts() == []
    assert arc.PAGE_UNCERTAIN in report["refused"]


def test_an_accepted_table_draft_becomes_a_confirmed_limit_with_its_direction(standard):
    run(reply(row_item()), MIN_MAX)
    [maximum] = [d for d in drafts() if d["operator"] == "<="]
    done = air.decide_draft(
        maximum["id"],
        decision="accept",
        allowed_document_ids=frozenset({"std"}),
        actor={"id": None},
    )
    assert done["status"] == air.ACCEPTED
    new = (
        connect()
        .execute(
            "SELECT * FROM standard_requirements WHERE id = ?",
            (done["new_requirement_id"],),
        )
        .fetchone()
    )
    assert new["requirement_type"] == "numeric_limit"
    # the other column's draft is its own statement row: still waiting
    [minimum] = [d for d in drafts() if d["operator"] == ">="]
    assert minimum["status"] == air.DRAFT


@pytest.mark.parametrize(
    "cell, want",
    [
        ("Max", "<="),
        ("Maximum allowable working pressure (barg)", "<="),
        ("Min.", ">="),
        ("not less than", ">="),
        ("Min/Max", None),
        ("Limit", None),
        ("Pressure up to 50 bar", None),
        ("Maximum 10", None),
        ("Administer", None),
        ("", None),
    ],
)
def test_header_comparator_reading(cell, want):
    assert art.header_operator(cell) == want


def test_header_unit_reading():
    assert art.header_unit("Pressure (barg)") == "barg"
    assert art.header_unit("Temperature [degC]") == "degC"
    assert art.header_unit("Pressure (ask the vendor)") is None
    assert art.header_unit("Pressure") is None
