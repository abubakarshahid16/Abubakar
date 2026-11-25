"""Builder C (planner 25 Nov 2026 19:15, item 2): the cross-document check by equipment tag. Code only; Questions only;
a paper the starter may not read is counted, never named or quoted. Invented tags, papers and values only."""

from __future__ import annotations

import json
import uuid

import pytest

from app import aim_review_view, db, submittal_review, tag_cross
from app.aim_review_store import shown_label
from tests.test_worker_health import temp_storage  # noqa: F401 - fixture

TAG = "99-P-901"


@pytest.fixture
def lib(temp_storage):  # noqa: F811
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    return db.connect()


def _paper(
    conn,
    doc_id: str,
    pages: dict[int, str],
    role: str = "CONTRACTOR_SUBMITTAL",
    number: str = "",
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, page_count, status, uploaded_at)"
            " VALUES (?, ?, ?, 1, ?, ?, 'ready', '2026-11-25T00:00:00Z')",
            (
                doc_id,
                f"{doc_id}.pdf",
                uuid.uuid4().hex,
                f"/nowhere/{doc_id}",
                len(pages),
            ),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, document_number, suggested_by)"
            " VALUES (?, ?, ?, 'test')",
            (doc_id, role, number or None),
        )
        for n, t in pages.items():
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, ?, ?, ?, 0)",
                (doc_id, n, t, len(t)),
            )


def _reading(
    conn,
    doc_id: str,
    name: str,
    value: str,
    unit: str,
    page: int,
    quote: str,
    blank: int = 0,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO submittal_facts (id, submittal_document_id, field_name, field_value, raw_value, raw_unit, unit,"
            " page, source_text, extraction_method, is_blank, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', ?, 'x', 'x')",
            (
                uuid.uuid4().hex,
                doc_id,
                name,
                value,
                value,
                unit,
                unit,
                page,
                quote,
                blank,
            ),
        )


def _sheet(
    conn, doc_id: str, pressure: str, unit: str, number: str = "", extra: str = ""
) -> None:
    text = f"Tag No.: {TAG}\nDesign pressure {pressure} {unit}\nMaterial Carbon steel\n{extra}"
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
    _reading(conn, doc_id, "material", "Carbon steel", "", 1, "Material Carbon steel")


def test_the_index_names_every_paper_with_the_tag_and_never_a_longer_code(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _paper(
        lib, "doc_list", {2: f"Line list\n{TAG} feed pump train\n{TAG}-X spare code"}
    )
    _paper(
        lib,
        "doc_std",
        {1: f"An invented standard naming {TAG}"},
        role="COMPANY_STANDARD",
    )
    idx = tag_cross.index(lib)
    assert idx.papers(TAG) == [
        "doc_a",
        "doc_list",
    ]  # a company standard is not read; "-X" makes another code
    assert [m.page for m in idx.tags[TAG]] == [1, 2] and idx.shared() == {
        TAG: ["doc_a", "doc_list"]
    }


def test_two_readings_that_differ_after_unit_conversion_are_one_question_naming_both_papers(
    lib,
):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    out = tag_cross.lines(lib, "doc_a", frozenset({"doc_a", "doc_b"}))
    assert len(out) == 1
    line = out[0]
    assert (
        line["label"] == "Question"
        and line["page"] == 1
        and line["quote"] == "Design pressure 10 barg"
    )
    assert (
        "INV-DS-002" in line["comment"]
        and "160 psig (page 1)" in line["comment"]
        and "page 1" in line["comment"]
    )
    assert (
        shown_label(
            line["label"],
            line["code_compare_json"],
            line["deferred"],
            line["code_note"],
        )
        == "Question"
    )
    assert json.loads(line["named_books_json"]) == [
        {"id": "doc_b", "name": "INV-DS-002"}
    ]


def test_readings_that_agree_after_conversion_give_no_line(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "145", "psig")  # 10 barg is 145.04 psig: printed rounding
    found = tag_cross.check(lib, "doc_a", frozenset({"doc_a", "doc_b"}))
    assert found["differ"] == [] and len(found["agree"]) == 2  # pressure and material
    assert tag_cross.lines(lib, "doc_a", frozenset({"doc_a", "doc_b"})) == []


def test_gauge_against_absolute_a_value_left_open_or_an_unverified_quote_is_never_compared(
    lib,
):
    _sheet(lib, "doc_a", "10", "barg")
    _paper(lib, "doc_b", {1: f"Tag No.: {TAG}\nDesign pressure 25 bara\n"})
    _reading(
        lib, "doc_b", "design pressure", "25", "bara", 1, "Design pressure 25 bara"
    )
    _paper(lib, "doc_c", {1: f"Tag No.: {TAG}\nDesign pressure TBA\n"})
    _reading(lib, "doc_c", "design pressure", "TBA", "", 1, "Design pressure TBA")
    _paper(lib, "doc_d", {1: f"Tag No.: {TAG}\nNothing else here\n"})
    _reading(
        lib, "doc_d", "design pressure", "99", "barg", 1, "Design pressure 99 barg"
    )  # forged: not on its page
    assert (
        tag_cross.lines(lib, "doc_a", frozenset({"doc_a", "doc_b", "doc_c", "doc_d"}))
        == []
    )


def test_a_paper_the_starter_may_not_read_is_counted_never_named_or_compared(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_secret", "300", "psig", number="INV-SECRET-1")
    assert (
        tag_cross.lines(lib, "doc_a", frozenset({"doc_a"})) == []
    )  # nothing readable to compare with
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    [line] = tag_cross.lines(lib, "doc_a", frozenset({"doc_a", "doc_b"}))
    assert "INV-SECRET-1" not in line["comment"] and "300" not in line["comment"]
    assert (
        "1 more held paper name this tag that you may not open; not compared."
        in line["comment"]
    )


def test_a_viewer_who_may_not_open_the_other_paper_sees_neither_its_name_nor_its_value(
    lib,
):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    [line] = tag_cross.lines(lib, "doc_a", frozenset({"doc_a", "doc_b"}))

    class Viewer:
        def may_read(self, doc_id):
            return doc_id == "doc_a"

    assert aim_review_view.book_hidden(lib, line, Viewer()) is True
    shown = aim_review_view.line_view(line, 1, hidden=True)
    assert shown["comment"] == tag_cross.HIDDEN_COMMENT
    assert "INV-DS-002" not in json.dumps(shown) and "160" not in json.dumps(shown)


def test_a_papers_own_value_lines_count_for_its_one_tag_and_a_label_stated_twice_is_never_compared(
    lib,
):
    _paper(
        lib,
        "doc_a",
        {
            1: f"Tag No.: {TAG}\nDesign temperature 120 °C\nOperating pressure 5 barg\nOperating pressure 6 barg\n"
        },
    )
    _paper(
        lib,
        "doc_b",
        {1: f"Tag No.: {TAG}\nDesign temperature 150 °C\nOperating pressure 9 barg\n"},
    )
    found = tag_cross.check(lib, "doc_a", frozenset({"doc_a", "doc_b"}))
    assert [(a.field, a.value, b.value) for a, b in found["differ"]] == [
        ("design temperature", "120", "150")
    ]
    # "operating pressure" is stated twice on doc_a with two values: no one value, never compared


def test_values_are_assigned_only_to_one_group_of_tags_never_to_a_list_of_items(lib):
    _paper(
        lib,
        "doc_list",
        {
            1: f"Tag No.: {TAG}\nDesign temperature 120 °C\nTag No.: 99-P-902\nDesign temperature 80 °C\n"
        },
    )
    _paper(lib, "doc_b", {1: f"Tag No.: {TAG}\nDesign temperature 150 °C\n"})
    assert (
        tag_cross.check(lib, "doc_b", frozenset({"doc_list", "doc_b"}))["differ"] == []
    )


def test_the_review_job_adds_the_lines_and_a_fault_of_the_check_never_stops_the_review(
    lib, monkeypatch
):
    from app import aim_review_jobs

    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig")
    assert (
        len(aim_review_jobs._cross_document(lib, "doc_a", {"doc_a", "doc_b"}, 7)) == 1
    )
    assert (
        aim_review_jobs._cross_document(lib, "doc_a", {"doc_a", "doc_b"}, 7)[0][
            "line_no"
        ]
        == 8
    )

    def boom(*a, **k):
        raise RuntimeError("an invented fault")

    monkeypatch.setattr(tag_cross, "lines", boom)
    assert aim_review_jobs._cross_document(lib, "doc_a", {"doc_a"}, 0) == []
