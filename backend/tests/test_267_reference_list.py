"""Order 267.1: a list of cited documents is not a requirement. Invented standards only.

M-03 row 352 was a sentence that began with a references title, listed two standard identifiers and
paired with the sheet field "Other (see below)" as if it were a requirement. The chunker marks only a
BACK-matter references page; a list near the front reached the extractor as ordinary text."""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, requirement_quality, standards
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.main import app
from tests.test_w6_640_requirements_supersede import temp_storage  # noqa: F401

LINES = [
    "2.1 References",
    "The documents listed here shall be read with this standard: SAEP-20 and SAMSS-007 and API 610.",
    "3.1 Design",
    "Company References SAEP-31 and SAMSS-044 shall be applied by the vendor where listed.",
    "Reference conditions per API 610 and ASME B31.3 shall apply to every pump covered here.",
    "References API 610 shall govern the design of every pump covered by this standard.",
    "The vessel shall comply with API 610 and ASME B31.3 for piping within the battery limit.",
    "4.1 Materials",
    "Casing material shall be carbon steel for every service in the scope of this standard.",
]


def _texts(std):
    return [
        r["requirement_text"]
        for r in db.connect().execute(
            "SELECT requirement_text FROM standard_requirements WHERE standard_document_id = ?"
            " AND superseded_at IS NULL",
            (std,),
        )
    ]


def _standard_on_page_two(lines: list[str]) -> str:
    """A ten-page invented standard whose page 2 carries `lines` (page 2 is front matter, not back matter)."""
    path = settings.data_dir / "ref.pdf"
    pdf = pymupdf.open()
    for n in range(10):
        page = pdf.new_page()
        text = (
            lines
            if n == 1
            else [
                f"9.{n} Filler clause {n}",
                f"Filler text number {n} about nothing in particular here.",
            ]
        )
        for i, line in enumerate(text):
            page.insert_text((72, 100 + i * 16), line)
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = (
            TestClient(app)
            .post("/api/documents", files={"file": ("ref.pdf", fh, "application/pdf")})
            .json()["document"]["id"]
        )
    extract_document(doc_id)
    chunk_document(doc_id)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_classification"
            " (document_id, suggested_by, document_role) VALUES (?, 'test', 'COMPANY_STANDARD')",
            (doc_id,),
        )
    return doc_id


@pytest.fixture
def extracted(temp_storage):  # noqa: F811
    std = _standard_on_page_two(LINES)
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    return " | ".join(_texts(std))


def test_a_sentence_under_a_references_heading_is_not_a_requirement(extracted):
    assert "documents listed here" not in extracted


def test_a_references_list_run_into_one_line_is_not_a_requirement(extracted):
    assert "SAEP-31" not in extracted


def test_a_sentence_that_merely_starts_with_reference_is_kept(extracted):
    assert "Reference conditions per API 610" in extracted


def test_a_sentence_that_names_one_standard_after_a_references_title_is_kept(extracted):
    assert "References API 610 shall govern" in extracted


def test_a_clause_that_cites_two_standards_is_kept(extracted):
    assert "The vessel shall comply with API 610" in extracted


def test_the_section_after_the_references_is_read_as_usual(extracted):
    assert "Casing material shall be carbon steel" in extracted


@pytest.mark.parametrize(
    "title,expected",
    [
        ("2.1 References", True),
        ("Normative references", True),
        ("Saudi Aramco References", True),
        ("4.1 Bibliography", True),
        ("Normative reference", True),
        ("Reference", True),
        ("Design Reference", False),
        ("Standard Reference", False),
        ("Pressure Relief Valve Reference", False),
        ("Reference pressure", False),
        ("References to piping codes in the design of vents", False),
        (None, False),
    ],
)
def test_which_titles_open_a_references_section(title, expected):
    assert requirement_quality.is_references_heading(title) is expected
