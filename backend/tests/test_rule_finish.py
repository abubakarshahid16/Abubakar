"""The rule finishing line (Lane 1): steps a, b, c, d, g, may_decide, finish_status, persistence, the runner's guards.

Every text here is INVENTED. No standard text, no document text.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import rule_finish as rf

ROOT = Path(__file__).resolve().parents[2]


def rule(**kw) -> dict:
    base = {
        "rule_id": "r1",
        "rule_key": "k" * 64,
        "version_id": "v1",
        "standard": "X-1.pdf",
        "kind": "no_figure",
        "field": "widget thing",
        "comparator": None,
        "value": None,
        "value_low": None,
        "value_high": None,
        "unit": None,
        "quote": "Widgets shall be painted.",
        "page": 2,
        "standard_document_id": "doc_x",
        "applicability": [("subject", "pumps")],
    }
    base.update(kw)
    return base


# ------------------------------------------------------------------------------------------------ step a


def test_a_figure_in_the_quote_with_nothing_filled_fails_and_proposes_without_applying():
    r = rule(quote="The pump casing shall have a wall of at least 6 mm.")
    result, reason, ev = rf.limit_and_unit(r)
    assert (result, reason) == (rf.FAIL, "figure_not_filled")
    (p,) = ev["proposed"]
    assert (p["value"], p["unit"], p["comparator"], p["applied"]) == (
        6.0,
        "mm",
        ">=",
        False,
    )
    assert r["value"] is None and r["unit"] is None  # never applied silently


def test_a_filled_value_and_unit_that_stand_in_the_quote_pass():
    r = rule(
        kind="limit",
        value=6,
        unit="mm",
        comparator=">=",
        quote="The wall shall be at least 6 mm thick.",
    )
    assert rf.limit_and_unit(r)[:2] == (rf.PASS, "value_and_unit_stand_in_quote")


@pytest.mark.parametrize(
    "value, unit, reason",
    [
        (7, "mm", "value_not_in_quote"),
        (6, "kPa", "unit_not_in_quote"),
        (6, None, "unit_not_filled"),
    ],
)
def test_a_value_or_unit_not_in_the_quote_fails(value, unit, reason):
    r = rule(
        kind="limit",
        value=value,
        unit=unit,
        comparator=">=",
        quote="The wall shall be at least 6 mm thick.",
    )
    assert rf.limit_and_unit(r)[:2] == (rf.FAIL, reason)


def test_a_range_needs_both_ends_in_the_quote():
    q = "Ambient temperature shall be between 10 and 40 C."
    ok = rule(kind="range", value_low=10, value_high=40, unit="C", quote=q)
    bad = rule(kind="range", value_low=10, value_high=45, unit="C", quote=q)
    assert rf.limit_and_unit(ok)[0] == rf.PASS
    assert rf.limit_and_unit(bad)[:2] == (rf.FAIL, "value_not_in_quote")


@pytest.mark.parametrize(
    "quote",
    [
        "Widgets shall be painted.",  # no number
        "Issued 12 March 2025 under clause 4.3.2 for part PN-16.",  # a date, a clause and a part number
        "See table 7 and item 5 of the list.",  # bare numbers
    ],
)
def test_a_quote_with_no_figure_with_a_unit_is_not_applicable(quote):
    assert rf.limit_and_unit(rule(quote=quote))[:2] == (
        rf.NOT_APPLICABLE,
        "no_figure_in_quote",
    )


def test_a_number_the_unit_table_does_not_know_is_not_a_figure():
    assert (
        rf.limit_and_unit(rule(quote="Provide 5 widgets per bay."))[0]
        == rf.NOT_APPLICABLE
    )


def test_a_number_read_by_numparse_with_a_thousands_comma_stands():
    r = rule(
        kind="limit",
        value=1000,
        unit="kPa",
        comparator="<=",
        quote="The pressure shall not exceed 1,000 kPa.",
    )
    assert rf.limit_and_unit(r)[0] == rf.PASS


# ------------------------------------------------------------------------------------------------ step b


@pytest.mark.parametrize(
    "quote, kw, source",
    [
        (
            "The set pressure shall be shown on the data sheet.",
            {"value": 3, "unit": "bar"},
            rf.DATASHEET_PRESENCE,
        ),
        ("Piping shall be indicated on the layout drawing.", {}, rf.DRAWING),
        ("Relief load calculations shall be made.", {}, rf.CALCULATION),
        ("Valves shall be hydrostatically tested.", {}, rf.TEST),
        ("The welding procedure shall be approved.", {}, rf.PROCEDURE),
        ("The contractor shall supply spare parts.", {}, rf.OWNER_DUTY),
        (
            "The wall thickness shall be 6 mm.",
            {"value": 6, "unit": "mm"},
            rf.DATASHEET_VALUE,
        ),
        ("Things shall be good.", {}, rf.SOURCE_INCOMPLETE),
    ],
)
def test_the_evidence_source_is_one_value_of_the_closed_list(quote, kw, source):
    result, reason, ev = rf.evidence_source(rule(quote=quote, field="thing", **kw))
    assert reason == ev["source"] == source and source in rf.EVIDENCE_SOURCES
    assert result == (rf.INCOMPLETE if source == rf.SOURCE_INCOMPLETE else rf.PASS)
    assert quote not in json.dumps(ev)  # the cue words, never the quote


def test_a_limit_with_data_sheet_wording_is_a_presence_check_not_a_value_check():
    r = rule(
        quote="The design pressure shall be shown on the data sheet.",
        field="design pressure",
        value=5,
        unit="bar",
    )
    assert rf.evidence_source(r)[1] == rf.DATASHEET_PRESENCE


# ------------------------------------------------------------------------------------------------ step c

PAGE2 = "Intro line.\nThe vendor shall state the following\n(a) the tag number;\n(b) the service;\n(c) the date.\nNext paragraph here."
LAST = "Closing text on this page. The vendor shall report the following"
NEXT = "(a) first item\n(b) second item\n1.2.3 Next clause heading text"


def test_a_fragment_is_rejoined_with_its_list_and_verified_contiguous():
    r = rule(quote="The vendor shall state the following")
    result, reason, ev = rf.fragments(r, {2: PAGE2})
    assert (
        (result, reason) == (rf.PASS, "rejoined_with_list")
        and ev["items"] == 3
        and ev["pages"] == [2]
    )
    joined, _ = rf.rejoin(r, {2: PAGE2})
    assert (
        joined.startswith("The vendor shall state the following")
        and "(c) the date." in joined
    )
    assert "Next paragraph" not in joined


def test_a_list_that_opens_the_next_page_is_rejoined_across_the_page_break():
    r = rule(quote="The vendor shall report the following", page=5)
    result, reason, ev = rf.fragments(r, {5: LAST, 6: NEXT})
    assert (
        (result, reason) == (rf.PASS, "rejoined_with_list")
        and ev["pages"] == [5, 6]
        and ev["items"] == 2
    )


def test_a_fragment_without_a_list_in_the_page_text_is_incomplete():
    r = rule(quote="The vendor shall state the following")
    assert rf.fragments(
        r,
        {
            2: "The vendor shall state the following\nSome other paragraph that is no list."
        },
    )[:2] == (
        rf.INCOMPLETE,
        "list_not_found",
    )
    assert rf.fragments(r, {})[:2] == (rf.INCOMPLETE, "page_text_missing")
    assert rf.fragments(r, {2: "Nothing relevant."})[:2] == (
        rf.INCOMPLETE,
        "quote_not_located",
    )


def test_a_quote_that_holds_its_list_is_not_a_fragment():
    r = rule(
        quote="The vendor shall state the following: (a) the tag; (b) the service; (c) the date."
    )
    assert rf.fragments(r, {})[:2] == (rf.PASS, "list_in_quote")


def test_below_and_listed_are_pointers_only_where_they_point():
    assert (
        rf.fragments(rule(quote="Temperature below 0 degrees is not allowed."), {})[0]
        == rf.NOT_APPLICABLE
    )
    assert (
        rf.fragments(rule(quote="Widgets shall be painted."), {})[0]
        == rf.NOT_APPLICABLE
    )
    assert (
        rf.fragments(rule(quote="The data are as listed below."), {})[0]
        == rf.INCOMPLETE
    )


# ------------------------------------------------------------------------------------------------ step d


def test_a_subject_in_the_vocabulary_and_a_readable_condition_are_testable():
    r = rule(
        applicability=[
            ("subject", "centrifugal pumps"),
            ("condition", "operating pressure exceeding 100 kPa"),
        ]
    )
    result, reason, ev = rf.conditions_of(r)
    assert (result, reason) == (rf.PASS, "conditions_testable")
    assert ev["equipment_types"] == ["pump"] and ev["tests"][0]["kind"] == "pressure"


def test_a_subject_outside_the_vocabulary_or_an_unreadable_condition_is_incomplete():
    assert rf.conditions_of(rule(applicability=[("subject", "gizmos")]))[:2] == (
        rf.INCOMPLETE,
        "subject_not_in_equipment_vocabulary",
    )
    r = rule(
        applicability=[("subject", "pumps"), ("condition", "when the moon is full")]
    )
    assert rf.conditions_of(r)[0] == rf.INCOMPLETE
    assert rf.conditions_of(rule(applicability=[]))[:2] == (
        rf.INCOMPLETE,
        "no_applicability_rows",
    )


def test_in_all_cases_is_unconditional():
    r = rule(applicability=[("subject", "vessels"), ("condition", "in all cases")])
    assert rf.conditions_of(r)[0] == rf.PASS


# ------------------------------------------------------------------------------------------------ step g

PAGES = {2: "Some text.  Widgets shall be\npainted. More text."}


def test_a_quote_on_its_cited_page_is_found():
    assert rf.quote_found(rule(), PAGES)[:2] == (rf.PASS, "quote_found")


def test_a_quote_not_on_its_cited_page_fails_quote_not_found():
    assert rf.quote_found(rule(quote="Widgets shall be varnished."), PAGES)[:2] == (
        rf.FAIL,
        "quote_not_found",
    )
    assert rf.quote_found(rule(page=3), PAGES)[:2] == (
        rf.FAIL,
        "page_text_missing",
    )  # on another page only
    assert rf.quote_found(rule(), None)[:2] == (rf.FAIL, "page_text_missing")


# ------------------------------------------------------------------------------------------------ may_decide, finished

GOOD = {
    "a": "pass",
    "b": "pass",
    "c": "not_applicable",
    "d": "pass",
    "e": "pass",
    "f": "pass",
    "g": "pass",
}


def test_a_rule_that_passed_everything_decides():
    assert rf.may_decide(GOOD) is True
    assert rf.finish_status(GOOD) == (rf.FINISHED, None, None)


@pytest.mark.parametrize("g", ["fail", "incomplete", "not_applicable", None])
def test_a_rule_whose_quote_is_not_found_never_decides(g):
    steps = dict(GOOD, g=g)
    if g is None:
        del steps["g"]
    assert rf.may_decide(steps) is False
    assert rf.finish_status(steps).blocking == "g"


@pytest.mark.parametrize("step", ["a", "b", "c", "d"])
@pytest.mark.parametrize("bad", ["fail", "incomplete"])
def test_a_failed_or_incomplete_step_a_b_c_d_blocks(step, bad):
    steps = dict(GOOD, **{step: bad})
    assert rf.may_decide(steps) is False
    assert rf.finish_status(steps) == (rf.NOT_FINISHED, step, bad)


@pytest.mark.parametrize("step", ["e", "f"])
def test_a_missing_engineer_check_or_owner_sample_blocks(step):
    steps = {k: v for k, v in GOOD.items() if k != step}
    assert rf.may_decide(steps) is False
    assert rf.finish_status(steps) == (rf.NOT_FINISHED, step, "missing")
    assert rf.may_decide(dict(GOOD, **{step: "fail"})) is False


def test_the_results_may_be_dicts_or_tuples():
    steps = {k: (v, "r", {}) for k, v in GOOD.items()}
    assert rf.may_decide(steps) is True
    steps["g"] = {"result": "fail", "reason": "quote_not_found"}
    assert rf.may_decide(steps) is False


def test_run_steps_alone_never_finishes_a_rule():
    steps = rf.run_steps(rule(), PAGES)
    assert set(steps) == set(rf.CODE_STEPS)
    assert (
        rf.may_decide({k: v[0] for k, v in steps.items()}) is False
    )  # e and f are missing


# ------------------------------------------------------------------------------------------------ the runner


def _tiny_rulebook(path: Path) -> None:
    from app import rulebook_v2_schema as s

    conn = sqlite3.connect(path)
    for sql in s._TABLE_SQL[:5]:
        conn.execute(sql)
    conn.execute(
        "INSERT INTO rulebook_rule VALUES ('r1','abcdef0123456789','X-1.pdf','t','now')"
    )
    conn.commit()
    conn.close()


def test_the_runner_makes_a_marked_copy_and_refuses_every_protected_or_stranger_database(
    tmp_path,
):
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_finish_run as run

    source = tmp_path / "orig.sqlite"
    _tiny_rulebook(source)
    pages = tmp_path / "pages.sqlite"
    sqlite3.connect(pages).close()
    for bad in (
        source,
        pages,
    ):  # the source and the pages database, even renamed by case or a link
        with pytest.raises(SystemExit) as exc:
            run.prepare_work_db(source, pages, bad)
        assert "refused" in str(exc.value)
    link = tmp_path / "link.sqlite"
    link.symlink_to(source)
    with pytest.raises(SystemExit):
        run.prepare_work_db(source, pages, link)
    copy = run.prepare_work_db(source, pages, tmp_path / "work.sqlite")
    assert copy.exists() and copy != source
    assert run.prepare_work_db(source, pages, copy) == copy  # a marked copy is reused
    stranger = tmp_path / "stranger.sqlite"
    sqlite3.connect(stranger).close()
    with pytest.raises(
        SystemExit
    ):  # an existing file that is not a copy of the source is refused
        run.prepare_work_db(source, pages, stranger)


def test_the_runner_pkt_time_is_asia_karachi():
    sys.path.insert(0, str(ROOT / "scripts"))
    import rule_finish_run as run

    assert str(run.PKT) == "Asia/Karachi" and run.pkt_now().endswith(" PKT")


def test_a_lone_letter_unit_after_a_space_is_read_as_the_figure_it_is():
    q = "The vent shall be at least 15 m from any ignition source."
    ok = rule(kind="limit", value=15, unit="m", comparator=">=", quote=q)
    assert rf.limit_and_unit(ok)[:2] == (rf.PASS, "value_and_unit_stand_in_quote")
    assert rf.limit_and_unit(rule(quote=q))[:2] == (rf.FAIL, "figure_not_filled")
    # "a" is the word, not an ampere: no figure
    assert (
        rf.limit_and_unit(rule(quote="Give it 3 a coat of paint."))[0]
        == rf.NOT_APPLICABLE
    )
