"""Builder H (planner 25 Nov 2026 23:35 (b) item 1): the cross-document check in two lanes, each behind its own switch, OFF by default.
Lane 1 = exact facts by code (tag, number plus unit, standard plus edition); lane 2 = meaning mismatches by the local model, a
Question to the engineer only. Invented tags, papers, standards and values only."""

from __future__ import annotations

import json

import pytest

from app import aim_review, aim_review_view, cross_doc, cross_doc_meaning, tag_cross
from app.config import settings
from tests.test_u8c_tag_cross import TAG, _paper, _reading, _sheet
from tests.test_worker_health import temp_storage  # noqa: F401 - fixture

BOTH = frozenset({"doc_a", "doc_b"})


@pytest.fixture
def lib(temp_storage):  # noqa: F811
    from app import db, submittal_review

    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    return db.connect()


def _words_sheet(conn, doc_id: str, material: str, number: str = "") -> None:
    text = f"Tag No.: {TAG}\nBody material {material}\n"
    _paper(conn, doc_id, {1: text}, number=number)
    _reading(
        conn, doc_id, "body material", material, "", 1, f"Body material {material}"
    )


def _project(conn, doc_id: str, project: str) -> None:
    with conn:
        conn.execute(
            "UPDATE document_classification SET project = ? WHERE document_id = ?",
            (project, doc_id),
        )


@pytest.fixture
def lanes(monkeypatch):
    def turn(
        facts: bool = False, meaning: bool = False, model: str = "ministral-3:14b"
    ):
        monkeypatch.setattr(settings, "cross_doc_facts_enabled", facts)
        monkeypatch.setattr(settings, "cross_doc_meaning_enabled", meaning)
        monkeypatch.setattr(settings, "cross_doc_meaning_model", model)

    return turn


# ------------------------------------------------------------------ the switches


def test_both_switches_are_off_by_default():
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["cross_doc_facts_enabled"].default is False
    assert fields["cross_doc_meaning_enabled"].default is False
    assert "35b" not in fields["cross_doc_meaning_model"].default.lower()


def test_with_both_switches_off_the_review_gets_exactly_cs_check_by_tag(
    lib, lanes, monkeypatch
):
    from app import aim_review_jobs

    lanes(False, False)
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    called = []
    monkeypatch.setattr(
        cross_doc_meaning, "lines", lambda *a, **k: called.append(1) or []
    )
    monkeypatch.setattr(cross_doc, "lines", lambda *a, **k: called.append(2) or [])
    assert aim_review_jobs._cross_document(lib, "doc_a", BOTH, 7) == tag_cross.lines(
        lib, "doc_a", BOTH, 7
    )
    assert called == []  # neither lane is even asked


def test_lane_one_on_replaces_cs_lines_and_a_fault_never_stops_the_review(
    lib, lanes, monkeypatch
):
    from app import aim_review_jobs

    lanes(True, False)
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    out = aim_review_jobs._cross_document(lib, "doc_a", BOTH, 7)
    assert [x["item_id"] for x in out] == [cross_doc.ITEM_ID] and out[0]["line_no"] == 8

    def boom(*_a, **_k):
        raise RuntimeError("invented fault")

    monkeypatch.setattr(cross_doc, "lines", boom)
    assert aim_review_jobs._cross_document(lib, "doc_a", BOTH, 0) == []


# ------------------------------------------------------------------ lane 1: numbers


def test_a_number_that_differs_after_unit_conversion_is_a_finding_with_both_quotes_proven(
    lib, lanes
):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    [line] = cross_doc.lines(lib, "doc_a", BOTH)
    assert (
        line["label"] == "Question"
        and line["ask"] == "concern"
        and aim_review.sendable(line)
    )
    assert line["quote"] == "Design pressure 10 barg"
    assert (
        '"Design pressure 160 psig"' in line["comment"]
        and '"Design pressure 10 barg"' in line["comment"]
    )
    cmp = json.loads(line["code_compare_json"])
    assert (
        cmp["other_quote"] == "Design pressure 160 psig"
        and cmp["other_page"] == 1
        and cmp["unit_converted"] is True
    )
    assert line["code_note"].startswith(
        tag_cross.NOTE
    )  # the view's rule-5 hiding covers it
    assert "Pass" not in line["comment"] and "Fail" not in line["comment"]


def test_numbers_that_agree_after_conversion_give_no_line(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "145", "psig")  # 145.04 psig: printed rounding
    assert cross_doc.lines(lib, "doc_a", BOTH) == []


def test_words_that_differ_are_never_a_code_finding(lib):
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "CS")
    assert cross_doc.lines(lib, "doc_a", BOTH) == []
    assert (
        len(tag_cross.lines(lib, "doc_a", BOTH)) == 1
    )  # C's check raised it; lane 1 leaves meanings to lane 2


def test_a_quote_code_cannot_find_on_its_page_raises_nothing(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _paper(lib, "doc_b", {1: f"Tag No.: {TAG}\nAn invented page"})
    _reading(
        lib, "doc_b", "design pressure", "160", "psig", 1, "Design pressure 160 psig"
    )  # not on its page
    assert cross_doc.lines(lib, "doc_a", BOTH) == []


def test_a_paper_the_starter_may_not_read_is_never_named_or_compared(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    assert cross_doc.lines(lib, "doc_a", frozenset({"doc_a"})) == []
    assert cross_doc.package(lib, "doc_a", frozenset({"doc_a"})) == ([], 1)


def test_a_viewer_who_may_not_open_the_other_paper_sees_neither_its_name_nor_its_words(
    lib,
):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig", number="INV-DS-002")
    [line] = cross_doc.lines(lib, "doc_a", BOTH)

    class Viewer:
        def may_read(self, doc_id):
            return doc_id == "doc_a"

    assert aim_review_view.book_hidden(lib, line, Viewer()) is True
    shown = aim_review_view.line_view(line, 1, hidden=True)
    assert "INV-DS-002" not in json.dumps(shown) and "160" not in json.dumps(shown)


# ------------------------------------------------------------------ lane 1: editions


@pytest.mark.parametrize(
    ("printed", "want"),
    [
        ("API 610 11th Edition", ("edition", "11")),
        ("API 610, 12th Ed.", ("edition", "12")),
        ("API 610 (Edition 11)", ("edition", "11")),
        ("ASME B31.3-2020", ("year", "2020")),
        ("ISO 13709:2009", ("year", "2009")),
        ("API 610 (2010)", ("year", "2010")),
        ("API 610 2010 edition", ("year", "2010")),
        ("API 610 latest edition", None),
        ("API 610 2010 kW", None),
        ("API 610", None),
    ],
)
def test_the_edition_is_read_only_where_it_is_printed_beside_the_identifier(
    printed, want
):
    got = cross_doc.citations("d", {1: f"Pump to {printed} as noted"})
    assert ((got[0].sort, got[0].edition) if got else None) == want


def _cites(conn, doc_id: str, line: str, project: str = "Invented project Z") -> None:
    _paper(conn, doc_id, {2: f"An invented paper\nThe pump shall meet {line}.\n"})
    _project(conn, doc_id, project)


def test_two_papers_of_one_package_citing_different_editions_is_a_finding_with_both_quotes(
    lib,
):
    _cites(lib, "doc_a", "API 610 11th Edition")
    _cites(lib, "doc_b", "API 610 12th Edition")
    [line] = cross_doc.lines(lib, "doc_a", BOTH)
    assert (
        line["field"] == "edition of API 610"
        and line["page"] == 2
        and aim_review.sendable(line)
    )
    assert "edition 11" in line["comment"] and "edition 12" in line["comment"]
    assert (
        json.loads(line["code_compare_json"])["other_quote"]
        == "The pump shall meet API 610 12th Edition."
    )


def test_editions_are_compared_only_inside_a_package_and_only_of_the_same_sort(lib):
    _cites(lib, "doc_a", "ASME B31.3-2020")
    _cites(
        lib, "doc_b", "ASME B31.3-2016", project="Another invented project"
    )  # not the same package
    _cites(
        lib, "doc_c", "ASME B31.3 12th edition"
    )  # a year and an edition number: never compared
    assert cross_doc.lines(lib, "doc_a", frozenset({"doc_a", "doc_b", "doc_c"})) == []


def test_a_shared_tag_ties_two_papers_into_one_package(lib):
    _paper(lib, "doc_a", {1: f"Tag No.: {TAG}\nThe pump shall meet ASME B31.3-2020."})
    _paper(lib, "doc_b", {1: f"Tag No.: {TAG}\nThe pump shall meet ASME B31.3-2016."})
    _paper(
        lib, "doc_c", {1: "Tag No.: 99-P-777\nThe pump shall meet ASME B31.3-2016."}
    )  # another item: not tied
    assert cross_doc.package(lib, "doc_a", frozenset({"doc_a", "doc_b", "doc_c"})) == (
        ["doc_b"],
        0,
    )
    [line] = cross_doc.lines(lib, "doc_a", frozenset({"doc_a", "doc_b", "doc_c"}))
    assert "2016" in line["comment"] and "2020" in line["comment"]


def test_a_paper_citing_one_standard_with_two_editions_is_never_compared(lib):
    _cites(lib, "doc_a", "API 610 11th Edition and later API 610 12th Edition")
    _cites(lib, "doc_b", "API 610 12th Edition")
    assert cross_doc.lines(lib, "doc_a", BOTH) == []


def test_a_company_standard_is_never_in_the_package(lib):
    _cites(lib, "doc_a", "API 610 11th Edition")
    _cites(lib, "doc_b", "API 610 12th Edition")
    with lib:
        lib.execute(
            "UPDATE document_classification SET document_role = 'COMPANY_STANDARD' WHERE document_id = 'doc_b'"
        )
    assert cross_doc.lines(lib, "doc_a", BOTH) == []


# ------------------------------------------------------------------ lane 2


class FakeProvider:
    def __init__(
        self,
        verdict="conflict",
        why="one is a stainless grade, the other carbon steel",
        fail=None,
        cut=False,
    ):
        self.verdict, self.why, self.fail, self.cut, self.packets = (
            verdict,
            why,
            fail,
            cut,
            [],
        )

    def reason(self, packet):
        from app.reasoning_provider import ProviderRefused, Response

        self.packets.append(packet)
        if self.fail:
            raise ProviderRefused("ollama: invented refusal")
        n = packet.prompt.count("Paper 1 says")
        text = json.dumps(
            {
                "answers": [
                    {"n": i, "verdict": self.verdict, "why": self.why}
                    for i in range(1, n + 1)
                ]
            }
        )
        return Response(
            text=text,
            provider="ollama",
            model_tag="ministral-3:14b",
            digest="x",
            finish_reason="length" if self.cut else "stop",
            prompt_sha256="y",
        )


def test_a_conflict_the_model_finds_is_a_question_to_the_engineer_only_with_both_quotes_proven(
    lib,
):
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "Stainless steel 316", number="INV-DS-002")
    fake = FakeProvider()
    [line] = cross_doc_meaning.lines(lib, "doc_a", BOTH, 3, provider=fake)
    assert (
        line["label"] == "Question"
        and line["line_no"] == 4
        and line["item_id"] == cross_doc_meaning.ITEM_ID
    )
    assert not aim_review.sendable(
        line
    )  # All points only: never sent to the contractor
    assert (
        '"Body material Carbon steel"' in line["comment"]
        and '"Body material Stainless steel 316"' in line["comment"]
    )
    assert "Engineer to check" in line["comment"]
    assert (
        "AI" not in line["comment"] and fake.why not in line["comment"]
    )  # the model's words are team-only
    assert (
        aim_review.ENGINEER_QUESTION in line["code_note"]
        and "AI, to be checked (ministral-3:14b)" in line["code_note"]
    )
    assert "Pass" not in line["comment"] and "Fail" not in line["comment"]
    [packet] = fake.packets
    assert (
        packet.json_schema == cross_doc_meaning.SCHEMA
        and packet.step == cross_doc_meaning.STEP
    )


@pytest.mark.parametrize("verdict", ["same", "unclear"])
def test_same_or_unclear_is_no_line(lib, verdict):
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "CS")
    assert (
        cross_doc_meaning.lines(lib, "doc_a", BOTH, provider=FakeProvider(verdict))
        == []
    )


def test_numbers_code_compared_are_never_asked(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(lib, "doc_b", "160", "psig")
    fake = FakeProvider()
    assert (
        cross_doc_meaning.lines(lib, "doc_a", BOTH, provider=fake) == []
        and fake.packets == []
    )


def test_two_numbers_code_refused_to_compare_are_never_asked(lib):
    _sheet(lib, "doc_a", "10", "barg")
    _sheet(
        lib, "doc_b", "11", "bara"
    )  # gauge against absolute: code never compares it, and the AI is not asked to
    found, _h, _pages = cross_doc.pairs(lib, "doc_a", BOTH)
    assert any(p.verdict == "cannot" and p.numeric for p in found)
    fake = FakeProvider()
    assert (
        cross_doc_meaning.lines(lib, "doc_a", BOTH, provider=fake) == []
        and fake.packets == []
    )


def test_a_quote_code_cannot_find_is_never_asked(lib):
    _words_sheet(lib, "doc_a", "Carbon steel")
    _paper(lib, "doc_b", {1: f"Tag No.: {TAG}\nAn invented page"})
    _reading(
        lib,
        "doc_b",
        "body material",
        "Stainless steel 316",
        "",
        1,
        "Body material Stainless steel 316",
    )
    fake = FakeProvider()
    assert (
        cross_doc_meaning.lines(lib, "doc_a", BOTH, provider=fake) == []
        and fake.packets == []
    )


@pytest.mark.parametrize("fake", [FakeProvider(fail=True), FakeProvider(cut=True)])
def test_a_model_that_does_not_answer_is_one_not_run_line_never_silent(lib, fake):
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "Stainless steel 316")
    [line] = cross_doc_meaning.lines(lib, "doc_a", BOTH, provider=fake)
    assert "was not run" in line["comment"] and "1 of 1 pair" in line["comment"]
    assert aim_review.NOT_JUDGED in line["code_note"] and not aim_review.sendable(line)


def test_the_35b_model_is_refused(lib, lanes):
    lanes(False, True, model="invented-35B-model")
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "Stainless steel 316")
    [line] = cross_doc_meaning.lines(lib, "doc_a", BOTH)
    assert "35B" in line["comment"] and not aim_review.sendable(line)


def test_the_real_provider_goes_only_through_the_local_transport_with_the_forced_shape(
    lib, lanes, monkeypatch
):
    from app import model_transport

    lanes(False, True)
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "Stainless steel 316")
    sent = []

    def post(path, body, *, timeout):
        sent.append((path, body))
        return {
            "model": body["model"],
            "done_reason": "stop",
            "response": json.dumps(
                {"answers": [{"n": 1, "verdict": "conflict", "why": "invented"}]}
            ),
        }

    monkeypatch.setattr(model_transport, "post_json", post)
    [line] = cross_doc_meaning.lines(lib, "doc_a", BOTH)
    [(path, body)] = sent
    assert (
        path == "/api/generate"
        and body["model"] == "ministral-3:14b"
        and body["format"] == cross_doc_meaning.SCHEMA
    )
    assert aim_review.ENGINEER_QUESTION in line["code_note"]


def test_lane_two_on_adds_its_lines_after_lane_ones_in_the_review(
    lib, lanes, monkeypatch
):
    from app import aim_review_jobs

    lanes(True, True)
    _words_sheet(lib, "doc_a", "Carbon steel")
    _words_sheet(lib, "doc_b", "Stainless steel 316")
    monkeypatch.setattr(cross_doc_meaning, "_provider", lambda: FakeProvider())
    out = aim_review_jobs._cross_document(lib, "doc_a", BOTH, 5)
    assert [(x["item_id"], x["line_no"]) for x in out] == [
        (cross_doc_meaning.ITEM_ID, 6)
    ]
