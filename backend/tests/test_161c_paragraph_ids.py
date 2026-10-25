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


# ------------------------ the real shape found on the owner's data: run-in headings

RUN_IN = "\n".join(
    f"XQ-{i} GENERAL RULES NUMBER (a) Some words of the first paragraph number {i}."
    for i in range(30, 40)
) + (
    "\nXQ-20 DESIGN TEMPERATURE (a) Maximum. Except as required in the note below, the maximum"
    " temperature used in design shall be the mean metal temperature across the thickness."
    "\n(b) Minimum. The minimum metal temperature used in design shall be the lowest expected."
    "\n(1) A detail of the minimum that carries its own limit for the design of the part.\n"
)


@pytest.mark.parametrize(
    "source, expected",
    [
        (
            "Except as required in the note below, the maximum temperature used in design",
            "XQ-20(a)",
        ),
        (
            "The minimum metal temperature used in design shall be the lowest expected.",
            "XQ-20(b)",
        ),
        (
            "A detail of the minimum that carries its own limit for the design of the part.",
            "XQ-20(b)(1)",
        ),
    ],
)
def test_a_run_in_heading_names_the_paragraph_and_its_sub_paragraph(source, expected):
    shape = paragraph_ids.dominant_shape([RUN_IN])
    assert shape == "prefixed"
    assert paragraph_ids.paragraph_for([RUN_IN], 0, source, shape) == expected


@pytest.mark.parametrize(
    "line",
    [
        "XQ-77 DESIGN TEMPERATURE . . . . . . . . . 25",  # a contents entry with a dot leader
        "XQ-77 DESIGN TEMPERATURE 25",  # a page number follows the title
        "XQ-77 HOT 5 bar",  # a table row
    ],
)
def test_a_contents_entry_or_a_table_row_is_not_a_run_in_heading(line):
    text = RUN_IN + line + "\nThe vessel shall be tested at 5 bar in full.\n"
    got = paragraph_ids.paragraph_for(
        [text], 0, "The vessel shall be tested at 5 bar in full.", "prefixed"
    )
    assert got == "XQ-20(b)(1)"  # the last real heading, not XQ-77


@pytest.fixture(autouse=True)
def _empty_memo():
    paragraph_ids._CACHE.clear()
    yield
    paragraph_ids._CACHE.clear()


def _finding(req: str) -> dict:
    return {
        "requirement_id": req,
        "standard_document_id": "std",
        "standard_clause": "0.3",
        "clause_identified": False,
    }


@pytest.mark.usefixtures("temp_storage")
def test_the_standard_is_loaded_once_across_calls_and_again_when_its_chunks_change(
    monkeypatch,
):
    _std, ids = _standard_with([RUN_IN])
    req = _requirement(
        ids[0],
        "The minimum metal temperature used in design shall be the lowest expected.",
    )
    loads = []
    real = paragraph_ids._load
    monkeypatch.setattr(
        paragraph_ids, "_load", lambda std: loads.append(std) or real(std)
    )
    first, second = [_finding(req)], [_finding(req)]
    paragraph_ids.attach(first)
    paragraph_ids.attach(second)
    assert first[0]["paragraph_id"] == second[0]["paragraph_id"] == "XQ-20(b)"
    assert loads == ["std"]  # two calls, one load
    new_source = "A brand new paragraph that follows all the others in the standard."
    with db.connect() as conn:  # a chunk is added: the memo must not hide it
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
            "token_count,content_hash,retrievable) VALUES ('c9','std','std.pdf',9,1,1,NULL,'prose',?,1,'h9',1)",
            (f"XQ-50 NEW RULE (a) {new_source}",),
        )
    added = [_finding(_requirement("c9", new_source))]
    paragraph_ids.attach(added)
    assert added[0]["paragraph_id"] == "XQ-50(a)"
    assert loads == ["std", "std"]  # the changed standard was read again


@pytest.mark.parametrize(
    "text, shape, source, expected",
    [
        (
            RUN_IN,
            "prefixed",
            "XQ-31 GENERAL RULES NUMBER (a) Some words of the first paragraph number 31.",
            "XQ-31(a)",
        ),
        (
            STYLE_PREFIXED,
            "prefixed",
            "XQ-20 DESIGN CONDITIONS\n(a) General words about design.",
            "XQ-20",
        ),
    ],
)
def test_a_sentence_that_opens_with_its_own_heading_is_under_that_heading(
    text, shape, source, expected
):
    # The heading line that starts the sentence is the sentence's heading, not
    # the paragraph before it (a wrong citation, shown with no sign of a guess).
    assert paragraph_ids.paragraph_for([text], 0, source, shape) == expected


@pytest.mark.usefixtures("temp_storage")
def test_a_standard_is_read_once_per_attach_however_many_findings_it_has(monkeypatch):
    _std, ids = _standard_with([RUN_IN])
    sources = [
        "The minimum metal temperature used in design shall be the lowest expected.",
        "Except as required in the note below, the maximum temperature used in design",
        "A detail of the minimum that carries its own limit for the design of the part.",
    ]
    findings = [
        {
            "requirement_id": _requirement(ids[0], source),
            "standard_document_id": "std",
            "standard_clause": "0.3",
            "clause_identified": False,
        }
        for source in sources
    ]
    reads = []
    real = paragraph_ids._read
    monkeypatch.setattr(
        paragraph_ids, "_read", lambda std: reads.append(std) or real(std)
    )
    paragraph_ids.attach(findings)
    assert reads == ["std"]
    assert [f["paragraph_id"] for f in findings] == [
        "XQ-20(b)",
        "XQ-20(a)",
        "XQ-20(b)(1)",
    ]


# A heading the numbering does not recognise (its CAPITALS title is longer than
# a title may be) between a recognised heading and the sentence.
LONG_HEADING = (
    "Q-3 MATERIAL BASIS FOR THE PLATE AND ITS WELDED ATTACHMENTS AND THE LIMITS ON "
    "THE FORMING OF BOTH IN THIS PART (a) General words about it."
)
UNRECOGNISED = (
    RUN_IN
    + LONG_HEADING
    + "\n"
    + "The plate shall be of the stated grade and of no other grade.\n"
)


@pytest.mark.parametrize(
    "source",
    [
        # the sentence is under the unrecognised heading, not under XQ-20
        "The plate shall be of the stated grade and of no other grade.",
        # the sentence opens with the unrecognised heading itself
        LONG_HEADING,
    ],
)
def test_an_unrecognised_heading_before_the_sentence_gives_no_paragraph(source):
    shape = paragraph_ids.dominant_shape([UNRECOGNISED])
    assert shape == "prefixed"
    got = paragraph_ids.paragraph_for([UNRECOGNISED], 0, source, shape)
    assert got is None  # unsure is "not identified", never the paragraph before


def test_a_recognised_paragraph_before_the_unrecognised_one_is_still_read():
    shape = paragraph_ids.dominant_shape([UNRECOGNISED])
    got = paragraph_ids.paragraph_for(
        [UNRECOGNISED],
        0,
        "The minimum metal temperature used in design shall be the lowest expected.",
        shape,
    )
    assert got == "XQ-20(b)"


TITLE_CASE_DOTTED = (
    "\n".join(f"{i}.{i} Title Number A\nText {i}." for i in range(1, 10))
    + "\n3.4 Another Title Here\n"
)


@pytest.mark.parametrize(
    "heading",
    [
        "A.1 General Requirements For Welds",  # own line, Title Case
        "B-7 General Requirements",  # another shape, own line
        "A.1 General Requirements (a) Welds apply.",  # Title Case run-in
        "B-7 Appendix Mixed Case Title (a) text.",
    ],
)
def test_a_title_case_heading_of_another_shape_before_the_sentence_gives_no_paragraph(
    heading,
):
    sentence = "The weld shall be inspected by a qualified engineer yearly."
    text = TITLE_CASE_DOTTED + heading + "\n" + sentence + "\n"
    shape = paragraph_ids.dominant_shape([text])
    assert shape == "dotted"
    assert paragraph_ids.paragraph_for([text], 0, sentence, shape) is None


def test_the_title_case_guard_leaves_a_sentence_under_its_own_recognised_heading():
    sentence = "The weld shall be inspected by a qualified engineer yearly."
    text = TITLE_CASE_DOTTED + sentence + "\n"
    shape = paragraph_ids.dominant_shape([text])
    assert paragraph_ids.paragraph_for([text], 0, sentence, shape) == "3.4"


def test_documented_limit_a_title_case_heading_with_its_sentence_on_the_same_line():
    # NOT the wanted behaviour, pinned so a later change is deliberate: a Title
    # Case run followed by a lowercase word cannot be told from prose without a
    # word list, so the paragraph before is returned.
    # The general fail-safe (return None, never the paragraph before) is #1267.
    sentence = "The weld shall be inspected by a qualified engineer yearly."
    text = TITLE_CASE_DOTTED + "A.1 General Requirements " + sentence + "\n"
    shape = paragraph_ids.dominant_shape([text])
    assert paragraph_ids.paragraph_for([text], 0, sentence, shape) == "3.4"


@pytest.mark.parametrize(
    "line",
    [
        "A.1 Welds shall be examined",
        "B-7 Welds shall be examined",
        "12-4 Section Eight",
    ],
)
def test_the_guard_fails_safe_on_a_capital_initial_line_that_starts_with_an_identifier(
    line,
):
    # Cost of the guard, pinned: an unmarked list item or a footer of another shape between the
    # heading and the sentence gives "not identified", never a paragraph.
    sentence = "The weld shall be inspected by a qualified engineer yearly."
    text = TITLE_CASE_DOTTED + line + "\n" + sentence + "\n"
    shape = paragraph_ids.dominant_shape([text])
    assert paragraph_ids.paragraph_for([text], 0, sentence, shape) is None


def test_documented_limit_a_list_item_of_the_standards_own_shape_reads_as_a_heading():
    # NOT the wanted behaviour, pinned so a later change is deliberate: in a
    # dotted standard "2 Welds shall be examined" has the shape of a heading, so
    # it is one; shape alone cannot tell a list item from a heading.
    # The general fail-safe (return None, never the paragraph before) is #1267.
    sentence = "The weld shall be inspected by a qualified engineer yearly."
    text = TITLE_CASE_DOTTED + "2 Welds shall be examined\n" + sentence + "\n"
    shape = paragraph_ids.dominant_shape([text])
    assert paragraph_ids.paragraph_for([text], 0, sentence, shape) == "2"
