"""The clause locator of a technical query's evidence passage (lead-4, 26 Nov 2026, goal G6: a clause number on every passage). Invented
page text only."""

from __future__ import annotations

from app.technical_query_match import heading_above, last_heading, locator_for

from .test_technical_queries import temp_storage  # noqa: F401 - the fixture is used by name


def test_a_clause_number_alone_on_its_line_takes_its_title_from_the_next_line():
    page = "Invented Contract Part\n4.2.1\nInvented Cooling Water\nThe invented header shall be designed for 12 bar."
    assert (
        heading_above(page, "The invented header shall be designed for 12 bar.")
        == "4.2.1 Invented Cooling Water"
    )
    page2 = "1.\nScope Of Invented Work\nThe invented contractor shall supply the invented pumps."
    assert (
        heading_above(page2, "The invented contractor shall supply the invented pumps.")
        == "1 Scope Of Invented Work"
    )


def test_a_passage_that_opens_with_its_own_clause_is_located_at_that_clause_not_the_one_before():
    page = "7.13 Invented Earlier Clause\nInvented earlier words.\n8.1 Invented Own Clause\nThe invented own clause words."
    assert (
        heading_above(page, "8.1 Invented Own Clause The invented own clause words.")
        == "8.1 Invented Own Clause"
    )


def test_a_heading_inside_the_start_of_the_passage_is_used_when_none_stands_above_it():
    page = "Invented page header\nSome invented lead-in text.\n3.4 Invented Clause\nThe invented clause words."
    assert (
        heading_above(
            page,
            "Some invented lead-in text. 3.4 Invented Clause The invented clause words.",
        )
        == "3.4 Invented Clause"
    )


def test_a_table_of_numbers_is_not_a_heading():
    table = "1.2.3\n4.5\n% of invented total\nA\n( A $ )"
    assert last_heading(table) is None


def test_the_last_heading_of_the_page_before_still_serves_a_passage_with_none_on_its_page():
    earlier = "5.6\nInvented Testing\nInvented words."
    assert (
        locator_for(
            "Invented words without any heading.",
            earlier,
            "Invented words without any heading.",
        )
        == "5.6 Invented Testing"
    )


def test_a_passage_spanning_two_clauses_is_located_at_the_clause_holding_the_matched_words():
    from app import db
    from app.technical_queries import _locator_of
    from app.technical_query_match import best_sentence, key_terms

    page = ("3.1 Invented Painting\nThe invented steel shall be painted in invented grey.\n"
            "3.2 Invented Insulation\nThe invented insulation thickness shall be 50 mm on invented pipes.")  # fmt: skip
    passage_text = (
        "The invented steel shall be painted in invented grey.\n3.2 Invented Insulation\n"
        "The invented insulation thickness shall be 50 mm on invented pipes."
    )
    terms = key_terms("What insulation thickness applies?")
    assert best_sentence(terms, passage_text).startswith(
        "The invented insulation thickness"
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('c9','c.pdf',?,1,'c.pdf','ready','2026-01-01')",
            ("9" * 64,),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('c9',1,?,?,0,1)",
            (page, len(page)),
        )
        passage = {"document_id": "c9", "page_start": 1, "page_end": 1}
        assert (
            _locator_of(conn, passage, passage_text, terms) == "3.2 Invented Insulation"
        )
        assert (
            _locator_of(conn, passage, passage_text, key_terms("Which paint colour?"))
            == "3.1 Invented Painting"
        )


def test_a_numbered_list_item_is_an_item_with_the_clause_it_refers_to():
    page = "Invented Schedule\n7.\nThe invented spare parts listed in the invented annex (Ref. Invented Contract, Sub-Clause 3.2.1)\n8.\nInvented next item text."
    assert (
        heading_above(page, "The invented spare parts listed in the invented annex")
        == "Item 7 (refers to 3.2.1)"
    )
    title = "4.2.1\nInvented Cooling Water\nThe invented header words."
    assert (
        heading_above(title, "The invented header words.")
        == "4.2.1 Invented Cooling Water"
    )  # a title is still a clause heading


def test_a_dotted_number_before_a_long_sentence_is_a_wrapped_reference_not_a_heading():
    page = (
        "3.4.1.2\nInvented Seal Flush\nThe invented flush plan applies.\n3.4.1\n"
        "And the invented requirements of the invented annex (42) shall also apply to every invented seal of the package\n"
        "The invented seal answer sits here."
    )
    assert (
        heading_above(page, "The invented seal answer sits here.")
        == "3.4.1.2 Invented Seal Flush"
    )


def test_the_clause_holding_the_matched_words_wins_over_the_label_the_search_gave_the_passage_start(
    monkeypatch,
):
    from app import db
    from app import technical_queries as TQ
    from app.technical_query_match import key_terms

    page = "9.10.6 Invented Sub Clause\nInvented words of the sub clause.\n10 INVENTED NEW CLAUSE\nThe invented warranty period is invented months."
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('c8','c.pdf',?,1,'c.pdf','ready','2026-01-01')",
            ("8" * 64,),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('c8',1,?,?,0,1)",
            (page, len(page)),
        )
        passage = {
            "document_id": "c8",
            "page_start": 1,
            "page_end": 1,
            "locator": "9.10 Invented > 9.10.6 Invented Sub Clause",
        }
        quote = "Invented words of the sub clause.\n10 INVENTED NEW CLAUSE\nThe invented warranty period is invented months."
        got = TQ._matched_clause(
            conn, passage, quote, key_terms("What warranty period applies?")
        )
    assert got == "10 INVENTED NEW CLAUSE"
