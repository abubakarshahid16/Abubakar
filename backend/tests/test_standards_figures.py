"""Figures inside rule books read as rules (owner, 26 Nov 2026, #1584 7189065710; `standards_figures`, job J2). Invented books; a
stand-in provider answers; no network."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

import pymupdf
import pytest

from app import claude_approved, standards_lane
from app.config import settings
from app.reasoning_provider import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import standards_figures


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    c.execute(
        "CREATE TABLE document_classification (document_id TEXT PRIMARY KEY, document_role TEXT, document_number TEXT)"
    )
    for d, name, role in (("std", "SAES-X-100.pdf", "COMPANY_STANDARD"), ("other_family", "ZZZ-X-100.pdf", "COMPANY_STANDARD"),
                          ("sheet", "SAES-X-100 datasheet.pdf", "CONTRACTOR_SUBMITTAL"), ("deal", "API-X-1.pdf", "CONTRACT")):  # fmt: skip
        c.execute("INSERT INTO documents VALUES (?, ?)", (d, name))
        c.execute("INSERT INTO document_classification VALUES (?, ?, NULL)", (d, role))
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture(autouse=True)
def _list_enforced(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(
        settings, "data_dir", tmp_path
    )  # an empty owner list: only the lane may let a book pass


@pytest.fixture
def book_pdf(tmp_path):
    """Pages 1-3: a drawn figure over most of the page (a picture page); page 4: text only; page 5: a captioned figure among text."""
    path = tmp_path / "book.pdf"
    pdf = pymupdf.open()
    for _ in range(3):
        pdf.new_page().draw_rect(pymupdf.Rect(60, 60, 540, 780), fill=(0.8, 0.8, 0.8))
    text = pdf.new_page()
    for k in range(30):
        text.insert_text(
            (60, 60 + 22 * k),
            f"Invented clause text line {k} of a rule book page with words only, no figure.",
        )
    cap = pdf.new_page()
    for k in range(10):
        cap.insert_text(
            (60, 60 + 14 * k),
            f"Invented clause text line {k} before the figure on this page of the book.",
        )
    cap.draw_rect(pymupdf.Rect(80, 260, 520, 600), fill=(0.8, 0.8, 0.8))
    cap.insert_text((80, 640), "Figure 3 Invented arrangement")
    pdf.save(str(path))
    return path


class _Reader:
    """Stands in for Claude: inside the call the lane must have declared exactly the book (the gate's own question)."""

    def __init__(self, answer):
        self.answer, self.packets = answer, []

    def reason(self, packet):
        assert standards_lane.allows(
            {"std"}
        ) and claude_approved.carried() == frozenset({"std"})
        self.packets.append(packet)
        return Response(text=self.answer, provider="claude", model_tag="claude-invented", digest="d", finish_reason="end_turn",
                        prompt_sha256="p", cost_usd=0.01)  # fmt: skip


ANSWER = json.dumps({"rules": [{"rule": "The invented gap shall be at least 50 mm.", "figure": "Figure 3 Invented gap",
                                "values": ["50 mm"]}]})  # fmt: skip


def test_a_held_books_figure_pages_are_read_once_each_and_every_rule_is_marked_from_a_figure_page(
    conn, book_pdf
):
    reader, out = _Reader(ANSWER), io.StringIO()
    counts = standards_figures.read_book(
        conn, "std", [2, 3], book_pdf, out, provider=reader
    )
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert (
        counts[standards_figures.READ] == 2
        and len(reader.packets) == 2
        and all(p.images for p in reader.packets)
    )
    assert [x["mark"] for x in lines] == [
        "from a figure, page 2",
        "from a figure, page 3",
    ]
    assert (
        lines[0]["rules"][0]["rule"].startswith("The invented gap")
        and lines[0]["state"] == "read"
    )


@pytest.mark.parametrize("doc", ["sheet", "deal", "other_family"])
def test_a_datasheet_a_contract_or_a_book_of_another_family_is_refused_and_nothing_is_sent(
    conn, book_pdf, doc
):
    reader, out = _Reader(ANSWER), io.StringIO()
    with pytest.raises(standards_lane.NotStandardsLane):
        standards_figures.read_book(conn, doc, [2], book_pdf, out, provider=reader)
    assert reader.packets == [] and out.getvalue() == ""


def test_never_inside_a_review_run(conn, book_pdf):
    reader = _Reader(ANSWER)
    with (
        claude_approved.reviewing("run-1"),
        pytest.raises(standards_lane.NotStandardsLane),
    ):
        standards_figures.read_book(
            conn, "std", [2], book_pdf, io.StringIO(), provider=reader
        )
    assert reader.packets == []


def test_a_refused_page_stops_the_rest_of_the_book_and_the_file_says_so(conn, book_pdf):
    class _Refusing(_Reader):
        def reason(self, packet):
            raise RuntimeError("cap")

    out = io.StringIO()
    counts = standards_figures.read_book(
        conn, "std", [1, 2, 3], book_pdf, out, provider=_Refusing(ANSWER)
    )
    assert counts[standards_figures.REFUSED] == 3
    assert {json.loads(x)["state"] for x in out.getvalue().splitlines()} == {"refused"}


def test_an_answer_with_no_rules_or_no_json_is_said_and_the_judged_sample_is_one_read_page_in_ten():
    assert (
        standards_figures.parse('{"rules": []}') == []
        and standards_figures.parse("no json here") is None
    )
    lines = [{"book": "b", "page": p, "state": "read"} for p in range(1, 31)] + [
        {"book": "b", "page": 99, "state": "no_rule"}
    ]
    assert [x["page"] for x in standards_figures.judge_sample(lines)] == [1, 11, 21]


@pytest.mark.parametrize("pages", [[4], [2, 4], [9]])
def test_a_page_that_is_not_a_figure_or_picture_page_is_refused_and_nothing_is_sent(
    conn, book_pdf, pages
):
    """Review of update 12, N2: the owner approved FIGURE pages; a text page (or a page the book does not have) is refused by the
    picture-gap counter's own test, before anything is sent."""
    reader, out = _Reader(ANSWER), io.StringIO()
    with pytest.raises(standards_figures.NotFigurePage):
        standards_figures.read_book(conn, "std", pages, book_pdf, out, provider=reader)
    assert reader.packets == [] and out.getvalue() == ""


def test_a_captioned_figure_among_text_is_a_figure_page_and_is_read(conn, book_pdf):
    reader, out = _Reader(ANSWER), io.StringIO()
    counts = standards_figures.read_book(
        conn, "std", [5], book_pdf, out, provider=reader
    )
    assert counts[standards_figures.READ] == 1 and len(reader.packets) == 1


def test_the_apps_own_gate_is_asked_first_and_a_closed_lane_sends_nothing(
    conn, book_pdf, monkeypatch
):
    """Rule 1 (the update 12 suite's script guard): with no provider given, the tool asks the app's gate before any lane opens."""
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    out = io.StringIO()
    with pytest.raises(standards_figures.ClaudeNotOpen):
        standards_figures.read_book(conn, "std", [2], book_pdf, out)
    assert out.getvalue() == ""
