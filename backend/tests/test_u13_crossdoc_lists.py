"""Update 13 (lead-4, 26 Nov 2026 16:03, item 3): the cross-document check (lane 1, exact facts by code) on a LINE LIST and a PIPING
CLASS paper of one package, the two planted list kinds. A line both papers name (its tag on each paper's own tag line) ties them; a
number that differs after unit conversion is a Question with both quotes found on their pages; numbers that agree say nothing; a
standard cited with two editions is a Question; words are never a code finding. Lane 1 off: builder C's check by tag, exactly.
Invented line tags, values and standards only."""

from __future__ import annotations

import json

import pytest

from app import aim_review, cross_doc, tag_cross
from app.config import settings
from tests.test_u8c_tag_cross import _paper, _reading
from tests.test_worker_health import temp_storage  # noqa: F401 - fixture

LINE = "99-L-901"
LL, PC = "doc_linelist", "doc_pipingclass"
BOTH = frozenset({LL, PC})


@pytest.fixture
def lib(temp_storage):  # noqa: F811
    from app import db, submittal_review

    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    return db.connect()


@pytest.fixture
def lane1(monkeypatch):
    monkeypatch.setattr(settings, "cross_doc_facts_enabled", True)


def _list_paper(conn, doc_id, pressure, unit, *, cites="", material="", number=""):
    text = (
        f"Tag No.: {LINE}\nDesign pressure {pressure} {unit}\n"
        + (f"Piping material {material}\n" if material else "")
        + (f"Design to {cites}.\n" if cites else "")
    )
    _paper(conn, doc_id, {1: text}, number=number)
    _reading(
        conn,
        doc_id,
        "design pressure",
        pressure,
        unit,
        1,
        f"Design pressure {pressure} {unit}",
    )
    if material:
        _reading(
            conn,
            doc_id,
            "piping material",
            material,
            "",
            1,
            f"Piping material {material}",
        )


def test_a_line_list_and_a_piping_class_paper_naming_one_line_are_one_package(lib):
    _list_paper(lib, LL, "19", "barg")
    _list_paper(lib, PC, "20", "barg", number="INV-PC-001")
    assert cross_doc.package(lib, LL, BOTH) == ([PC], 0)


def test_a_line_pressure_that_differs_between_the_two_lists_is_a_question_with_both_quotes(
    lib, lane1
):
    _list_paper(lib, LL, "19", "barg")
    _list_paper(lib, PC, "20", "barg", number="INV-PC-001")
    [line] = [
        x for x in cross_doc.lines(lib, LL, BOTH) if x["field"] == "design pressure"
    ]
    assert (
        line["label"] == "Question"
        and line["ask"] == "concern"
        and aim_review.sendable(line)
    )
    assert (
        '"Design pressure 19 barg"' in line["comment"]
        and '"Design pressure 20 barg"' in line["comment"]
    )
    cmp = json.loads(line["code_compare_json"])
    assert (
        cmp["result"] == "differs"
        and cmp["other_quote"] == "Design pressure 20 barg"
        and cmp["other_page"] == 1
    )
    assert "Pass" not in line["comment"] and "Fail" not in line["comment"]


def test_pressures_that_agree_after_unit_conversion_say_nothing(lib, lane1):
    _list_paper(lib, LL, "290", "psig")  # 20 barg is 290.08 psig
    _list_paper(lib, PC, "20", "barg", number="INV-PC-001")
    assert [
        x for x in cross_doc.lines(lib, LL, BOTH) if x["field"] == "design pressure"
    ] == []


def test_the_two_lists_citing_two_editions_of_one_standard_is_a_question(lib, lane1):
    _list_paper(lib, LL, "20", "barg", cites="ASME B31.3-2020")
    _list_paper(lib, PC, "20", "barg", cites="ASME B31.3-2016", number="INV-PC-001")
    [line] = [
        x for x in cross_doc.lines(lib, LL, BOTH) if x["field"].startswith("edition of")
    ]
    assert (
        "2016" in line["comment"]
        and "2020" in line["comment"]
        and line["label"] == "Question"
    )


def test_a_material_word_that_differs_is_never_a_code_finding(lib, lane1):
    _list_paper(lib, LL, "20", "barg", material="Carbon steel")
    _list_paper(lib, PC, "20", "barg", material="Stainless steel", number="INV-PC-001")
    assert [
        x for x in cross_doc.lines(lib, LL, BOTH) if x["field"] == "piping material"
    ] == []


def test_with_lane_one_off_the_review_keeps_cs_check_by_tag_exactly(lib, monkeypatch):
    from app import aim_review_jobs

    monkeypatch.setattr(settings, "cross_doc_facts_enabled", False)
    monkeypatch.setattr(settings, "cross_doc_meaning_enabled", False)
    _list_paper(lib, LL, "19", "barg")
    _list_paper(lib, PC, "20", "barg", number="INV-PC-001")
    assert aim_review_jobs._cross_document(lib, LL, BOTH, 0) == tag_cross.lines(
        lib, LL, BOTH, 0
    )
