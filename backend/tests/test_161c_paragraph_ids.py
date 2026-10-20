"""Order 161 C: a CRS row cites the paragraph the standard's own text puts the
requirement under, whatever numbering style the standard uses; "paragraph not
identified" only when the text has none (or does not say). Invented standards
only: no real standard, client or document text.
"""

from __future__ import annotations

import pytest

from app import comparison, crs_mapping, db, paragraph_ids, standards
from tests.test_b3_page_ledger import (
    temp_storage,  # noqa: F401 - the fixture, used by name
)

NOW = "2026-10-20T00:00:00Z"


def _pad(prefix: str, n: int) -> str:
    """Enough other headings of one style that a standard has a numbering."""
    return "\n".join(f"{prefix}{i} Filler heading\nSome text {i}." for i in range(n))


# A: letters-hyphen-number paragraph ids with lettered sub-paragraphs.
STYLE_PREFIXED = (
    _pad("XQ-", 9)
    + "\nXQ-20 DESIGN CONDITIONS\n(a) General words about design.\n"
    + "(b) The maximum design pressure shall not exceed 12 bar at 80 degrees.\n(1) A detail under it that matters for the design.\n"
)
# B: dotted numbers.
STYLE_DOTTED = (
    "\n".join(f"{i}.{i} Section\nText {i}." for i in range(1, 10))
    + "\n5.3.2 Wall thickness\nThe wall thickness shall be at least 6 mm.\n"
)
# C (held out): a number, a hyphen, a number.
STYLE_HELD_OUT = (
    "\n".join(f"{i}-{i} Part\nText {i}." for i in range(1, 10))
    + "\n12-4.1 Test pressure\nThe test pressure shall be 1.5 times the design pressure.\n"
)


@pytest.mark.parametrize(
    "text, source, expected",
    [
        (
            STYLE_PREFIXED,
            "The maximum design pressure shall not exceed 12 bar",
            "XQ-20(b)",
        ),
        (
            STYLE_PREFIXED,
            "A detail under it that matters for the design.",
            "XQ-20(b)(1)",
        ),
        (STYLE_DOTTED, "The wall thickness shall be at least 6 mm.", "5.3.2"),
        (
            STYLE_HELD_OUT,
            "The test pressure shall be 1.5 times the design pressure.",
            "12-4.1",
        ),
    ],
)
def test_the_paragraph_is_read_from_each_standards_own_numbering(
    text, source, expected
):
    shape = paragraph_ids.dominant_shape([text])
    assert shape is not None
    assert paragraph_ids.paragraph_for([text], 0, source, shape) == expected


def test_a_table_row_in_another_shape_is_never_taken_for_the_heading():
    # a prefixed standard that also has a table row "0.3 Carbon steel" in the same chunk
    text = STYLE_PREFIXED.replace(
        "(b) The maximum", "0.3 Carbon steel 7.2\n(b) The maximum"
    )
    assert paragraph_ids.dominant_shape([text]) == "prefixed"
    got = paragraph_ids.paragraph_for(
        [text], 0, "The maximum design pressure shall not exceed 12 bar", "prefixed"
    )
    assert got == "XQ-20(b)"


def test_unsure_is_none_never_a_guess():
    few = "XQ-1 One\nText.\nXQ-2 Two\nText."
    assert (
        paragraph_ids.dominant_shape([few]) is None
    )  # too few headings to be a numbering
    mixed = _pad("XQ-", 5) + "\n" + "\n".join(f"{i}.{i} Title\nT" for i in range(1, 6))
    assert paragraph_ids.dominant_shape([mixed]) is None  # no shape holds half
    assert (
        paragraph_ids.paragraph_for(
            [STYLE_PREFIXED],
            0,
            "A sentence that is not in the chunk at all",
            "prefixed",
        )
        is None
    )
    assert (
        paragraph_ids.paragraph_for(
            ["no headings here\njust text with a sentence."],
            0,
            "just text with a sentence.",
            "prefixed",
        )
        is None
    )


def test_the_heading_may_be_in_an_earlier_chunk():
    first = _pad("XQ-", 9) + "\nXQ-30 LATER RULES\nIntro."
    second = "The continuing sentence of that paragraph says something specific."
    assert (
        paragraph_ids.paragraph_for([first, second], 1, second, "prefixed") == "XQ-30"
    )


def _standard_with(chunks_text: list[str]) -> tuple[str, list[str]]:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('std','std.pdf','s',1,'std.pdf','ready',1,?)",
            (NOW,),
        )
        ids = []
        for i, text in enumerate(chunks_text):
            cid = f"c{i}"
            ids.append(cid)
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
                "token_count,content_hash,retrievable) VALUES (?,?,?,?,1,1,NULL,'prose',?,1,?,1)",
                (cid, "std", "std.pdf", i, text, f"h{i}"),
            )
    return "std", ids


def _requirement(chunk_id: str, source: str, clause: str | None = "0.3") -> str:
    return standards.create_requirement(
        standard_document_id="std",
        chunk_id=chunk_id,
        clause=clause,
        page=1,
        requirement_text=source,
        source_text=source,
        structured={"requirement_type": "statement"},
    )["id"]


@pytest.mark.usefixtures("temp_storage")
def test_attach_sets_the_paragraph_of_a_finding_whose_clause_is_a_table_number():
    _std, ids = _standard_with([STYLE_PREFIXED])
    req = _requirement(
        ids[0], "The maximum design pressure shall not exceed 12 bar at 80 degrees."
    )
    findings = [
        {
            "requirement_id": req,
            "standard_document_id": "std",
            "standard_clause": "0.3",
            "clause_identified": False,
        }
    ]
    paragraph_ids.attach(findings)
    assert findings[0]["paragraph_id"] == "XQ-20(b)"
    assert (
        findings[0]["standard_clause"] == "0.3"
    )  # the stored clause is left exactly as it was


@pytest.mark.usefixtures("temp_storage")
def test_attach_leaves_a_finding_with_a_real_clause_alone():
    _std, ids = _standard_with([STYLE_PREFIXED])
    req = _requirement(
        ids[0],
        "The maximum design pressure shall not exceed 12 bar at 80 degrees.",
        "4.3",
    )
    findings = [
        {
            "requirement_id": req,
            "standard_document_id": "std",
            "standard_clause": "4.3",
            "clause_identified": True,
        }
    ]
    paragraph_ids.attach(findings)
    assert "paragraph_id" not in findings[0]


@pytest.mark.usefixtures("temp_storage")
def test_attach_is_wired_into_the_crs_context():
    _std, ids = _standard_with([STYLE_PREFIXED])
    req = _requirement(
        ids[0],
        "The maximum design pressure shall not exceed 12 bar at 80 degrees.",
        None,
    )
    findings = [
        {"requirement_id": req, "standard_document_id": "std", "standard_clause": None}
    ]
    comparison.attach_crs_context(findings)
    assert findings[0].get("paragraph_id") == "XQ-20(b)"


def test_the_crs_cites_the_paragraph_instead_of_saying_it_is_not_identified():
    base = {
        "standard_name": "Some-Code.pdf",
        "standard_clause": "0.3",
        "standard_page": 12,
        "clause_identified": False,
    }
    assert "paragraph not identified" in crs_mapping._standard_reference(base)
    got = crs_mapping._standard_reference({**base, "paragraph_id": "XQ-20(b)"})
    assert (
        "cl. XQ-20(b)" in got
        and "paragraph not identified" not in got
        and "(p.12)" in got
    )
    # a finding with no clause at all gets the paragraph too
    none = {
        "standard_name": "Some-Code.pdf",
        "standard_page": 3,
        "paragraph_id": "XQ-20",
    }
    assert "cl. XQ-20" in crs_mapping._standard_reference(none)
    # an identified clause is printed as before
    ok = {
        "standard_name": "Some-Code.pdf",
        "standard_clause": "5.3",
        "clause_identified": True,
        "paragraph_id": "ignored",
    }
    assert "cl. 5.3" in crs_mapping._standard_reference(ok)


# ----------------------------- what the independent review found: never a wrong paragraph

BODY = _pad("XQ-", 9) + "\nXQ-21 Scope\n(a) intro\n"


@pytest.mark.parametrize(
    "line",
    [
        "XQ-20 shall apply to the vessel when hot.",
        "XQ-20 shall apply to the vessel when hot and tested",  # no closing full stop
    ],
)
def test_a_cross_reference_line_is_not_a_heading(line):
    text = BODY + line + "\nThe vessel shall be tested at 5 bar.\n"
    got = paragraph_ids.paragraph_for(
        [text], 0, "The vessel shall be tested at 5 bar.", "prefixed"
    )
    assert got == "XQ-21(a)"  # not XQ-20


@pytest.mark.parametrize(
    "row", ["XQ-99 Hot 5 bar", "XQ-99 Design pressure is exceeded."]
)
def test_a_table_row_or_a_sentence_is_not_a_heading(row):
    text = BODY + row + "\nThe vessel shall be tested at 5 bar.\n"
    got = paragraph_ids.paragraph_for(
        [text], 0, "The vessel shall be tested at 5 bar.", "prefixed"
    )
    assert got == "XQ-21(a)"


def test_a_running_header_in_many_chunks_is_not_a_heading():
    chunks = [f"XQ-500 Welded Tanks\nBody text {i} of this page.\n" for i in range(4)]
    chunks[3] = BODY + "XQ-500 Welded Tanks\nThe vessel shall be tested at 5 bar.\n"
    skip = paragraph_ids.running_headers(chunks)
    assert "XQ-500" in skip
    got = paragraph_ids.paragraph_for(
        chunks, 3, "The vessel shall be tested at 5 bar.", "prefixed", skip
    )
    assert got == "XQ-21(a)"


def test_a_sentence_that_occurs_twice_cannot_be_placed():
    text = (
        _pad("XQ-", 9)
        + "\nXQ-21 First\nThe pump shall be sealed against leakage.\nXQ-22 Second\n"
        + "The pump shall be sealed against leakage.\n"
    )
    assert (
        paragraph_ids.paragraph_for(
            [text], 0, "The pump shall be sealed against leakage.", "prefixed"
        )
        is None
    )


def test_a_sentence_too_short_to_place_is_none():
    assert paragraph_ids.paragraph_for([STYLE_PREFIXED], 0, "Yes.", "prefixed") is None


def test_two_shapes_with_the_same_number_of_headings_are_not_a_numbering():
    tied = _pad("XQ-", 10) + "\n" + "\n".join(f"{i}.{i} Title\nT" for i in range(1, 11))
    assert paragraph_ids.dominant_shape([tied]) is None


def test_the_sub_paragraph_survives_a_heading_in_an_earlier_chunk():
    first = _pad("XQ-", 9) + "\nXQ-30 LATER RULES\n(b) The first part of the rule.\n"
    second = "The continuing sentence of that paragraph says something specific."
    assert (
        paragraph_ids.paragraph_for([first, second], 1, second, "prefixed")
        == "XQ-30(b)"
    )
