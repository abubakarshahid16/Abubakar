"""#1503 owner decision, behind CRS_ONE_ROW_PER_PROBLEM_ENABLED: rows with the same
clause, problem, value and verdict are ONE row listing every tag and page, and a "did
not reference X" row goes only when nothing in the review's scope requires X.

Invented rows and findings only; no document text.
"""

from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import clause_review, crs_export, crs_issue, crs_numbers, db
from app import crs_export_quality as q
from app import crs_one_row as one
from app.config import settings
from app.crs_mapping import (
    ROW_KIND_SAFETY_TICK,
    ROW_KIND_STANDARD_NOT_CITED,
    WAITING_COMMENTS,
    row_has_no_issuable_text,
)
from app.main import _crs_content, app
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in
from tests.test_review_screen import world as _world  # noqa: F401


def finding(fid, tag="T-1", page=1, value="12 bar", status="NON_COMPLIANT", **kw):
    return {
        "id": fid,
        "equipment_tag": tag,
        "contractor_page": page,
        "contractor_evidence_text": value,
        "compliance_status": status,
        "requirement_source_text": "The set pressure shall not exceed 10 bar.",
        "crs_field_label": "Set pressure",
        "standard_clause": "4.1",
        **kw,
    }


def row(fid, kind="datasheet_check", ref="STD-1 4.1", **kw):
    return {
        "finding_id": fid,
        "finding_ids": [fid],
        "document_name": "DS-1.pdf",
        "page_section": f"p.{fid[-1:]} - Set pressure",
        "comment": f"Comment of {fid}.",
        "comment_by": "AI Review",
        "standard_reference": ref,
        "row_kind": kind,
        "engineer_confirmed": False,
        "priority": 3,
        "comment_key": f"key-{fid}",
        "member_keys": [f"key-{fid}"],
        "reasoning": f"Reasoning of {fid}.",
        **kw,
    }


TWO = [finding("f1", "T-1", 1), finding("f2", "T-2", 2)]


def merged(rows, findings, records=None):
    return one.merge_rows(rows, findings, records or {})


# Merge -------------------------------------------------------------------


def test_the_same_clause_problem_value_and_verdict_is_one_row():
    rows, notes = merged([row("f1"), row("f2")], TWO)
    assert len(rows) == 1
    assert rows[0]["finding_ids"] == ["f1", "f2"]
    assert rows[0]["member_keys"] == ["key-f1", "key-f2"]
    assert rows[0]["one_row"] is True
    assert notes and notes[0]["count"] == 2


def test_the_merged_row_lists_every_tag_and_page_with_no_cut():
    many = [finding(f"f{i}", f"T-{i}", i) for i in range(1, 31)]
    rows, _ = merged([row(f"f{i}") for i in range(1, 31)], many)
    assert len(rows) == 1
    for i in range(1, 31):
        assert f"T-{i}" in rows[0]["comment"]
    assert "more" not in rows[0]["comment"].split("Applies to")[1]
    assert rows[0]["page_section"].count("Set pressure") == 10  # the ids' last digits


def test_a_tag_only_on_one_member_still_appears():
    findings = [finding("f1", "", 1), finding("f2", "T-ONLY", 2)]
    rows, _ = merged([row("f1"), row("f2")], findings)
    assert "T-ONLY" in rows[0]["comment"]


def test_different_values_never_merge():
    findings = [finding("f1", value="12 bar"), finding("f2", value="13 bar")]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


def test_different_verdicts_never_merge():
    findings = [finding("f1"), finding("f2", status="MISSING_INFORMATION")]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


@pytest.mark.parametrize("second", ["", None, "  "])
def test_an_unknown_value_is_not_the_same_as_a_stated_one(second):
    findings = [finding("f1"), finding("f2", value=second)]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


def no_value(fid, page, sentence, **kw):
    """A finding with no field: a value is not something it could have."""
    return finding(
        fid,
        "",
        page,
        value=None,
        crs_field_label="",
        requirement_source_text=sentence,
        **kw,
    )


NO_VALUE = [no_value("f1", 1, "First sentence."), no_value("f2", 2, "Second sentence.")]


def test_two_rows_with_no_value_by_nature_are_one_row_listing_everything():
    rows, _ = merged(
        [row("f1", comment="Words of one."), row("f2", comment="Words of two.")],
        NO_VALUE,
    )
    assert len(rows) == 1
    comment = rows[0]["comment"]
    for words in (
        "First sentence.",
        "Second sentence.",
        "Words of one.",
        "Words of two.",
    ):
        assert words in comment
    assert "pages 1, 2" in comment


def test_a_subject_read_from_the_clause_is_not_a_field_of_the_document():
    # `_field_label` falls back to the clause's own subject: that names no stored field,
    # and it differs with the sentence, which is not one of the four terms.
    findings = [
        no_value("f1", None, "One.", requirement_limit={"subject": "Subject one"}),
        no_value("f2", None, "Two.", requirement_limit={"subject": "Subject two"}),
    ]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 1


def test_a_missing_value_verdict_is_a_value_that_could_not_be_read():
    findings = [
        no_value("f1", 1, "One.", status="MISSING_INFORMATION"),
        no_value("f2", 2, "Two.", status="MISSING_INFORMATION"),
    ]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


def test_no_value_by_nature_is_not_the_same_as_a_stated_one():
    findings = [
        NO_VALUE[0],
        no_value("f2", 2, "Second.") | {"contractor_evidence_text": "Quote."},
    ]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


def test_two_different_stated_quotes_with_no_field_stay_apart():
    a = no_value("f1", 1, "One.") | {"contractor_evidence_text": "Quote A."}
    b = no_value("f2", 2, "Two.") | {"contractor_evidence_text": "Quote B."}
    assert len(merged([row("f1"), row("f2")], [a, b])[0]) == 2


def test_a_value_that_could_not_be_read_stays_apart():
    # A field was there to read, by its label or its stored fact.
    labelled = [finding("f1", value=None), finding("f2", value=None)]
    assert len(merged([row("f1"), row("f2")], labelled)[0]) == 2
    stored = [
        no_value("f1", 1, "One.", matched_phrase="Phrase"),
        no_value("f2", 2, "Two.", matched_phrase="Phrase"),
    ]
    assert len(merged([row("f1"), row("f2")], stored)[0]) == 2
    section = [
        no_value("f1", 1, "One.", contractor_section="Part"),
        no_value("f2", 2, "Two.", contractor_section="Part"),
    ]
    assert len(merged([row("f1"), row("f2")], section)[0]) == 2
    with_fact = [
        no_value("f1", 1, "One.", fact_id="x"),
        no_value("f2", 2, "Two.", fact_id="y"),
    ]
    assert len(merged([row("f1"), row("f2")], with_fact)[0]) == 2
    one_of_each = [NO_VALUE[0], no_value("f2", 2, "Two.", fact_id="y")]
    assert len(merged([row("f1"), row("f2")], one_of_each)[0]) == 2


def test_a_row_holding_a_stated_and_an_unread_value_joins_nothing():
    findings = [*TWO, finding("f3", "T-3", 3, value=None)]
    wide = row("f1", finding_ids=["f1", "f3"])
    assert len(merged([wide, row("f2")], findings)[0]) == 2


def test_a_row_holding_an_unread_value_is_not_no_value_by_nature():
    findings = [*NO_VALUE, no_value("f3", 3, "Three.", fact_id="x")]
    wide = row("f1", finding_ids=["f1", "f3"])
    assert len(merged([wide, row("f2")], findings)[0]) == 2


def clause_finding(fid, outcome, sentence="A sentence."):
    text, page = clause_review._row_text(
        outcome, None, None, {"requirement_text": sentence, "clause": "4.1"}
    )
    return no_value(fid, page, sentence, origin=clause_review.ORIGIN, finding=text)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("no_evidence", "unverified"),
        ("no_evidence", "unreadable"),
        ("unverified", "unreadable"),
    ],
)
def test_a_clause_review_outcome_is_part_of_the_identity(first, second):
    # A retryable failed check and a true no-evidence row are not one decision.
    findings = [clause_finding("f1", first), clause_finding("f2", second, "Another.")]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


@pytest.mark.parametrize("outcome", ["no_evidence", "unverified", "unreadable"])
def test_the_same_clause_review_outcome_merges(outcome):
    findings = [
        clause_finding("f1", outcome),
        clause_finding("f2", outcome, "Another."),
    ]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 1


def test_a_clause_review_row_whose_outcome_cannot_be_told_stays_apart():
    bare = [
        no_value("f1", 1, "One.", origin=clause_review.ORIGIN, finding="Other words."),
        no_value("f2", 2, "Two.", origin=clause_review.ORIGIN, finding="Other words."),
    ]
    assert len(merged([row("f1"), row("f2")], bare)[0]) == 2


def test_the_outcome_is_read_for_every_outcome_the_review_writes():
    for outcome in ("no_evidence", "unverified", "unreadable"):
        text, _page = clause_review._row_text(
            outcome, 3, None, {"requirement_text": "A sentence.", "clause": "4.1"}
        )
        assert clause_review.outcome_of(text) == outcome
    text, _page = clause_review._row_text(
        "verified", 3, "Quote.", {"requirement_text": "A sentence.", "clause": "4.1"}
    )
    assert clause_review.outcome_of(text) == "verified"
    assert clause_review.outcome_of("Anything else.") == ""
    assert clause_review.outcome_of(None) == ""


def test_rows_each_holding_two_verdicts_never_merge():
    findings = [
        finding("f1"),
        finding("f3", status="MISSING_INFORMATION"),
        finding("f2"),
        finding("f4", status="MISSING_INFORMATION"),
    ]
    rows = [row("f1", finding_ids=["f1", "f3"]), row("f2", finding_ids=["f2", "f4"])]
    assert len(merged(rows, findings)[0]) == 2


def test_rows_each_holding_two_engineers_wordings_never_merge():
    findings = [
        finding("f1", engineer_comment="Words A."),
        finding("f3", engineer_comment="Words B."),
        finding("f2", engineer_comment="Words A."),
        finding("f4", engineer_comment="Words B."),
    ]
    rows = [row("f1", finding_ids=["f1", "f3"]), row("f2", finding_ids=["f2", "f4"])]
    assert len(merged(rows, findings)[0]) == 2


def test_no_value_by_nature_with_another_verdict_or_clause_stays_apart():
    other = no_value("f2", 2, "Two.", status="MISSING_INFORMATION")
    assert len(merged([row("f1"), row("f2")], [NO_VALUE[0], other])[0]) == 2
    assert len(merged([row("f1"), row("f2", ref="STD-1 4.2")], NO_VALUE)[0]) == 2


def test_a_row_whose_clause_is_not_known_stays_apart():
    # A reference naming only the standard: the clause is unknown, so not the same one.
    bare = [
        no_value("f1", 1, "One.", standard_clause=""),
        no_value("f2", 2, "Two.", standard_clause=None),
    ]
    assert len(merged([row("f1", ref="STD-1"), row("f2", ref="STD-1")], bare)[0]) == 2
    stated = [finding("f1", standard_clause=""), finding("f2", standard_clause="")]
    assert len(merged([row("f1"), row("f2")], stated)[0]) == 2


def test_every_draft_stays_and_a_waiting_row_still_reads_as_waiting():
    waiting = next(iter(WAITING_COMMENTS))
    rows, _ = merged(
        [
            row("f1", comment=waiting, ai_review_comment="Draft one."),
            row("f2", comment=waiting, ai_review_comment="Draft two."),
        ],
        NO_VALUE,
    )
    assert len(rows) == 1
    assert rows[0]["comment"] == waiting, "a waiting sentence is not text to issue"
    assert row_has_no_issuable_text(rows[0]) is True
    cell = rows[0]["ai_review_comment"]
    for words in (
        "Draft one.",
        "Draft two.",
        "First sentence.",
        "Second sentence.",
        "pages 1, 2",
    ):
        assert words in cell


def test_a_confirmed_row_with_no_value_prints_every_engineers_comment():
    rows, _ = merged(
        [
            row("f1", comment="Confirmed one.", engineer_confirmed=True),
            row("f2", comment="Confirmed two.", engineer_confirmed=True),
        ],
        NO_VALUE,
    )
    assert (
        "Confirmed one." in rows[0]["comment"]
        and "Confirmed two." in rows[0]["comment"]
    )
    assert rows[0]["engineer_confirmed"] is True


def test_the_comments_do_not_depend_on_which_member_leads():
    first = merged([row("f1", comment="A."), row("f2", comment="B.")], NO_VALUE)[0][0]
    second = merged([row("f2", comment="B."), row("f1", comment="A.")], NO_VALUE)[0][0]
    assert first["comment"] == second["comment"]


def test_two_unknown_values_are_not_the_same_either():
    findings = [finding("f1", value=""), finding("f2", value="")]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


def test_different_sentences_of_one_clause_are_one_row_listing_them_all():
    long = "Another requirement. " * 30
    findings = [TWO[0], finding("f2", "T-2", 2, requirement_source_text=long.strip())]
    rows, _ = merged([row("f1"), row("f2")], findings)
    assert len(rows) == 1
    assert "The set pressure shall not exceed 10 bar." in rows[0]["comment"]
    assert long.strip() in rows[0]["comment"], "a sentence is never cut"
    assert "T-1" in rows[0]["comment"] and "T-2" in rows[0]["comment"]


def test_one_sentence_is_not_listed_twice():
    rows, _ = merged([row("f1"), row("f2")], TWO)
    assert "shall not exceed" not in rows[0]["comment"]  # the row's own words state it


def test_the_listed_sentences_do_not_depend_on_which_member_leads():
    findings = [TWO[0], finding("f2", "T-2", 2, requirement_source_text="Another one.")]
    one_way = merged([row("f1", comment="Same."), row("f2", comment="Same.")], findings)
    other = merged([row("f2", comment="Same."), row("f1", comment="Same.")], findings)
    assert one_way[0][0]["comment"] == other[0][0]["comment"]


def test_a_row_holding_two_sentences_can_join_when_value_and_verdict_are_one():
    findings = [*TWO, finding("f3", "T-3", 3, requirement_source_text="A third.")]
    wide = row("f1", finding_ids=["f1", "f3"])
    rows, _ = merged([wide, row("f2")], findings)
    assert len(rows) == 1 and "A third." in rows[0]["comment"]


def test_an_older_row_of_two_values_stays_apart_with_a_note_naming_it():
    findings = [*TWO, finding("f3", "T-3", 3, value="99 bar")]
    wide = row("f1", finding_ids=["f1", "f3"])
    rows, _ = merged([wide, row("f2")], findings)
    assert len(rows) == 2
    assert {len(r["finding_ids"]) for r in rows} == {1, 2}


def test_another_clause_field_or_kind_never_merges():
    other_field = finding("f2", crs_field_label="Other field")
    assert len(merged([row("f1"), row("f2")], [TWO[0], other_field])[0]) == 2
    assert len(merged([row("f1"), row("f2", ref="STD-1 4.2")], TWO)[0]) == 2
    tick = row("f2", kind=ROW_KIND_SAFETY_TICK)
    assert len(merged([row("f1"), tick], TWO)[0]) == 2


def test_a_row_already_holding_two_values_is_not_merged_further():
    findings = [*TWO, finding("f3", "T-3", 3, value="99 bar")]
    wide = row("f1", finding_ids=["f1", "f3"])
    assert len(merged([wide, row("f2")], findings)[0]) == 2


def test_a_row_with_no_finding_or_no_requirement_never_merges():
    a, b = row("", finding_ids=[]), row("", finding_ids=[])
    assert len(merged([a, b], [])[0]) == 2
    bare = [
        finding("f1", requirement_source_text=""),
        finding("f2", requirement_source_text=""),
    ]
    assert len(merged([row("f1"), row("f2")], bare)[0]) == 2


def test_a_confirmed_row_never_joins_an_unconfirmed_one():
    rows = [row("f1", engineer_confirmed=True), row("f2")]
    assert len(merged(rows, TWO)[0]) == 2


def test_different_engineer_words_never_merge():
    findings = [finding("f1", engineer_comment="A."), finding("f2")]
    assert len(merged([row("f1"), row("f2")], findings)[0]) == 2


def test_safety_ticks_merge_only_when_all_the_terms_are_identical():
    kind = {"kind": ROW_KIND_SAFETY_TICK}
    assert len(merged([row("f1", **kind), row("f2", **kind)], TWO)[0]) == 1
    other = [TWO[0], finding("f2", value="13 bar")]
    assert len(merged([row("f1", **kind), row("f2", **kind)], other)[0]) == 2


def test_a_carried_forward_row_never_merges():
    kind = {"kind": "carried_forward"}
    assert len(merged([row("f1", **kind), row("f2", **kind)], TWO)[0]) == 2


# Numbers -----------------------------------------------------------------


def issued(key, comment="Other words.", ref="CRS-X-001"):
    return {key: {"ref": ref, "issued": 1, "status": "Open", "comment": comment}}


def test_two_issued_numbers_never_merge():
    records = {**issued("key-f1"), **issued("key-f2", ref="CRS-X-002")}
    assert len(merged([row("f1"), row("f2")], TWO, records)[0]) == 2


def test_two_issued_numbers_never_merge_even_when_both_hold_the_merged_words():
    words = merged([row("f1"), row("f2")], TWO)[0][0]["comment"]
    records = {**issued("key-f1", words), **issued("key-f2", words, ref="CRS-X-002")}
    assert len(merged([row("f1"), row("f2")], TWO, records)[0]) == 2


def test_an_issued_number_for_other_words_never_merges():
    assert len(merged([row("f1"), row("f2")], TWO, issued("key-f2"))[0]) == 2


def test_the_number_a_merged_row_was_issued_under_keeps_the_row_whole():
    first, _ = merged([row("f1"), row("f2")], TWO)
    words = first[0]["comment"]
    rows, _ = merged([row("f1"), row("f2")], TWO, issued("key-f1", words))
    assert len(rows) == 1
    assert rows[0]["comment_key"] == "key-f1"


def test_a_draft_number_does_not_hold_a_row_apart_and_is_named_in_the_note():
    records = {
        "key-f1": {"ref": "CRS-X-001", "issued": 0, "status": "Open", "comment": ""},
        "key-f2": {"ref": "CRS-X-002", "issued": 0, "status": "Open", "comment": ""},
    }
    rows, notes = merged([row("f1"), row("f2")], TWO, records)
    assert len(rows) == 1
    assert "CRS-X-001" in notes[0]["detail"]
    assert "CRS-X-002" in notes[0]["detail"]


# The decision on a merged row --------------------------------------------


def test_a_decision_on_any_member_of_a_merged_row_covers_every_member():
    rows, _ = merged([row("f1"), row("f2")], TWO)
    assert crs_issue.group_of(rows, "f1") == ["f1", "f2"]
    assert crs_issue.group_of(rows, "f2") == ["f2", "f1"]


def test_a_decision_on_a_later_finding_of_an_ordinary_row_stays_as_it_was():
    rows = [row("f1", finding_ids=["f1", "f2"])]
    assert crs_issue.group_of(rows, "f2") == ["f2"]


# Dropped "did not reference" rows ----------------------------------------


def scope(names=("STD-1.pdf",), counts=(5,), texts=("Set pressure to STD-1.",)):
    return one.ScopeData(list(names), list(counts), list(texts))


def not_cited(ident="API 999", key="k-not-cited"):
    return row(
        "",
        finding_ids=[],
        kind=ROW_KIND_STANDARD_NOT_CITED,
        ref=ident,
        comment=f"Contractor did not reference {ident}.",
        comment_key=key,
        member_keys=[],
    )


def check_of(ident="API 999", **kw):
    return {"required_not_cited": [{"identifier": ident, "by": "equipment type", **kw}]}


def test_requires_says_yes_no_or_unknown():
    assert one.requires("API 999", scope()) is False
    assert one.requires("API 999", scope(names=("API-999.pdf",))) is True
    assert one.requires("API 999", scope(texts=("Valves per API 999.",))) is True
    assert one.requires("API 99", scope(texts=("Valves per API 999.",))) is False
    assert one.requires("API 999", scope(names=(), counts=(), texts=())) is None
    assert one.requires("API 999", scope(counts=(5, 0))) is None
    assert one.requires("", scope()) is None
    assert one.requires("no identifier here", scope()) is None


def drop(rows, check=None, data=None, records=None, decided=frozenset()):
    return one.drop_unrequired(
        rows,
        check_of() if check is None else check,
        data or scope(),
        records or {},
        decided,
    )


def test_a_row_nothing_requires_is_dropped_counted_and_named():
    keep = row("f1")
    rows, notes = drop([keep, not_cited()])
    assert rows == [keep]
    assert len(notes) == 1
    assert notes[0]["standard"] == "API 999"
    assert notes[0]["count"] == 1
    assert "complies" in notes[0]["detail"]  # "not mentioned" is never "compliant"
    assert "does not say" in notes[0]["detail"]


def test_requires_unknown_keeps_the_row():
    data = scope(names=(), counts=(), texts=())
    rows, notes = drop([not_cited()], data=data)
    assert len(rows) == 1 and not notes


def test_a_required_standard_keeps_its_row():
    data = scope(texts=("Valves per API 999.",))
    rows, notes = drop([not_cited()], data=data)
    assert len(rows) == 1 and not notes


def test_an_unsure_type_or_a_declared_service_keeps_the_row():
    assert len(drop([not_cited()], check=check_of(unsure=True))[0]) == 1
    assert len(drop([not_cited()], check=check_of(by="service"))[0]) == 1
    assert len(drop([not_cited()], check={"required_not_cited": []})[0]) == 1


def test_a_numbered_or_decided_row_is_never_dropped():
    assert len(drop([not_cited()], records=issued("k-not-cited"))[0]) == 1
    assert len(drop([not_cited()], decided=frozenset({"k-not-cited"}))[0]) == 1


def test_a_draft_number_does_not_keep_the_row():
    records = {
        "k-not-cited": {"ref": "R", "issued": 0, "status": "Open", "comment": ""}
    }
    assert drop([not_cited()], records=records)[0] == []


def test_a_row_of_another_kind_is_never_dropped():
    other = row("", finding_ids=[], kind="standard_not_applicable", ref="API 999")
    assert drop([other])[0] == [other]


# The switch and the export -----------------------------------------------


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "crs_one_row_per_problem_enabled", True)


def test_the_switch_is_off_by_default_and_off_changes_nothing():
    assert settings.crs_one_row_per_problem_enabled is False
    rows = [row("f1"), row("f2"), not_cited()]
    out, notes = one.apply(rows, ["n"], TWO, check_of(), "run", "scope", frozenset())
    assert out is rows and notes == ["n"]


def test_with_the_switch_the_export_does_not_merge_rows_of_different_values(on):
    # Both rows on one page and clause: #1509's view merge would join them.
    a = row("f1", page_section="p.1 - X")
    b = row("f2", page_section="p.1 - X", comment="Another comment.")
    meta = {"review_run_id": "r", "export_quality": True, "copy": "internal"}
    view = crs_export.build_crs_view([a, b], meta)
    assert len(view["rows"]) == 2
    assert view["rows_merged"] == 0


def test_without_the_switch_the_earlier_export_merge_stays():
    a = row("f1", page_section="p.1 - X")
    b = row("f2", page_section="p.1 - X", comment="Another comment.")
    meta = {"review_run_id": "r", "export_quality": True, "copy": "internal"}
    assert len(crs_export.build_crs_view([a, b], meta)["rows"]) == 1
    assert q.one_row_enabled() is False


def test_the_long_list_wraps_in_the_cell(on):
    many = [finding(f"f{i}", f"T-{i}", i % 9 + 1) for i in range(1, 31)]
    rows, _ = merged([row(f"f{i}") for i in range(1, 31)], many)
    meta = {"review_run_id": "r", "export_quality": False, "copy": "internal"}
    ws = openpyxl.load_workbook(io.BytesIO(crs_export.build_crs(rows, meta)))["CRS"]
    r = crs_export.FIRST_DATA_ROW
    assert ws.cell(row=r, column=3).alignment.wrap_text is True
    assert ws.cell(row=r, column=4).alignment.wrap_text is True
    assert "T-30" in ws.cell(row=r, column=4).value


def test_the_contractor_copy_gets_the_one_row_and_no_internal_text():
    confirmed = [row("f1", engineer_confirmed=True), row("f2", engineer_confirmed=True)]
    rows, _ = merged(confirmed, TWO)
    meta = {"review_run_id": "r", "export_quality": False, "copy": "issue"}
    data = crs_export.build_crs(rows, meta)
    book = openpyxl.load_workbook(io.BytesIO(data))
    text = " ".join(
        str(c)
        for s in book.worksheets
        for r in s.iter_rows(values_only=True)
        for c in r
        if c
    )
    assert "T-1" in text and "T-2" in text
    assert "Reasoning of" not in text
    assert "One row per problem" not in text
    assert len(crs_export.build_crs_view(rows, meta)["rows"]) == 1


def test_an_unconfirmed_merged_row_never_reaches_the_contractor_copy():
    rows, _ = merged([row("f1"), row("f2")], TWO)
    meta = {"review_run_id": "r", "export_quality": False, "copy": "issue"}
    assert crs_export.build_crs_view(rows, meta)["rows"] == []


# One row followed from the findings to the cell --------------------------


def _clone_noise_finding(run):
    """Two safety ticks, the one kind `crs_mapping` builds a row per finding for: a second
    tag on another page, the same clause, problem, value and verdict."""
    conn = db.connect()
    source = dict(
        conn.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ?"
            " AND compliance_status = 'NON_COMPLIANT' LIMIT 1",
            (run,),
        ).fetchone()
    )
    source.update(compliance_status="COMPLIANT", show_for_engineer_tick=1)
    with conn:
        conn.execute(
            "UPDATE review_findings SET compliance_status = 'COMPLIANT',"
            " show_for_engineer_tick = 1 WHERE id = ?",
            (source["id"],),
        )
    clone = {**source, "id": source["id"] + "-b", "equipment_tag": "TAG-SECOND"}
    clone["contractor_page"] = (source["contractor_page"] or 1) + 1
    marks = ",".join("?" for _ in clone)
    with conn:
        conn.execute(
            f"INSERT INTO review_findings ({','.join(clone)}) VALUES ({marks})",
            tuple(clone.values()),
        )
    return source["id"], clone["id"]


def _about(run, scope_ids, copy):
    from app import access

    reader = access.AccessScope(user_id=None, allowed_document_ids=scope_ids)
    rows, meta, _n, _s = _crs_content(run, reader, copy)
    return [
        r
        for r in rows
        if {r.get("finding_id"), *(r.get("finding_ids") or [])} & _about.ids
    ], meta


def test_confirming_a_merged_row_acts_on_every_member_and_it_stays_one_row(
    _world,  # noqa: F811
    monkeypatch,
    on,
):
    _sub, run, scope_ids = _world
    first, second = _clone_noise_finding(run)
    _about.ids = {first, second}
    rows, _meta = _about(run, scope_ids, "internal")
    assert len(rows) == 1 and set(rows[0]["finding_ids"]) == {first, second}
    assert "TAG-SECOND" in rows[0]["comment"]

    _signed_in(monkeypatch, scope_ids)
    # The screen may send either member.
    response = TestClient(app).post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{second}/decision",
        json={"decision": "accept", "reason": "checked on the page"},
    )
    assert response.status_code == 200, response.text
    confirmed = (
        db.connect()
        .execute(
            "SELECT id, confirmed_by FROM review_findings WHERE id IN (?, ?)",
            (first, second),
        )
        .fetchall()
    )
    assert all(r["confirmed_by"] for r in confirmed), "every member is confirmed"
    events = (
        db.connect()
        .execute(
            "SELECT finding_id FROM review_finding_events WHERE finding_id IN (?, ?)",
            (first, second),
        )
        .fetchall()
    )
    assert {r["finding_id"] for r in events} == {first, second}, (
        "each has its audit trail"
    )

    rows, _meta = _about(run, scope_ids, "internal")
    assert len(rows) == 1, "one row after the confirmation"
    assert rows[0]["row_kind"] == ROW_KIND_SAFETY_TICK
    assert rows[0]["engineer_confirmed"] is True
    assert rows[0]["crs_status"] == crs_numbers.OPEN
    assert "TAG-SECOND" in rows[0]["comment"]
    numbers = (
        db.connect()
        .execute("SELECT COUNT(*) FROM crs_comment_numbers WHERE issued = 1")
        .fetchone()[0]
    )
    assert numbers == 1, "one number issued for the one row"


def test_confirming_one_member_alone_never_makes_the_other_look_confirmed(
    _world,  # noqa: F811
    monkeypatch,
    on,
):
    _sub, run, scope_ids = _world
    first, second = _clone_noise_finding(run)
    _about.ids = {first, second}
    _signed_in(monkeypatch, scope_ids)
    response = TestClient(app).patch(
        f"/api/reviews/findings/{first}", json={"engineer_comment": "Engineer words."}
    )
    assert response.status_code == 200, response.text
    rows, _meta = _about(run, scope_ids, "internal")
    by_id = {r["finding_id"]: r for r in rows}
    assert by_id[first]["engineer_confirmed"] is True
    assert by_id[second]["engineer_confirmed"] is False
    assert second not in (by_id[first].get("finding_ids") or [])
