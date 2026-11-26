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


def test_a_matched_sentence_across_a_heading_and_a_blank_line_is_located_at_that_heading():
    page = "9.10.6 Invented Seals\nThe invented seal text ends here.\n\n10 INVENTED NEW CLAUSE\n \nThe invented answer words (1) follow."
    sentence = "10 INVENTED NEW CLAUSE The invented answer words (1) follow."
    assert heading_above(page, sentence) == "10 INVENTED NEW CLAUSE"


def test_a_list_item_whose_reference_stands_on_the_line_after_its_text_is_an_item():
    page = "24.\nInvented earlier item text (Ref. Invented, Sub-Clause 7.5.4)\n25.\nInvented spare parts for the invented start\n(Ref. Invented, Sub-Clause 7.1.15)\n26.\nNext."
    assert (
        heading_above(page, "Invented spare parts for the invented start")
        == "Item 25 (refers to 7.1.15)"
    )


def test_a_table_value_alone_on_its_line_is_not_a_clause_heading():
    page = "6.2 Invented Design Data\nInvented pressure\n1.5\nBar g\n2.0\nBar g\nThe invented answer words."
    assert (
        heading_above(page, "The invented answer words.") == "6.2 Invented Design Data"
    )
    clause = "10.1\nInvented General\nThe invented text.\n10.1.1\nInvented Scope\nThe invented answer words."
    assert (
        heading_above(clause, "The invented answer words.") == "10.1.1 Invented Scope"
    )


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


def test_a_short_quote_without_the_matched_words_is_located_by_the_whole_passage():
    # run 9, Q7: the quote kept from the passage held none of the question's words; the answer's item stands earlier in the passage
    from app import db
    from app import technical_queries as TQ
    from app.technical_query_match import key_terms

    page = (
        "Invented Schedule\n23.\nInvented grout curing record (Ref. Invented, Sub-Clause 2.8.4)\n"
        "24.\nInvented painting record (Ref. Invented, Sub-Clause 7.5.4)\n25.\nInvented spare parts list for the invented start\n"
        "(Ref. Invented, Sub-Clause 7.1.15)"
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
        passage = {"document_id": "c9", "page_start": 1, "page_end": 1, "text": page}
        quote = "Invented spare parts list for the invented start"
        got = TQ._matched_clause(
            conn, passage, quote, key_terms("Which grout curing record is due?")
        )
    assert got == "Item 23 (refers to 2.8.4)"


def test_a_numbered_table_passage_is_located_at_the_row_holding_the_matched_words():
    from app.technical_query_match import key_terms, table_item

    passage = (
        "| Item | Invented record | Days |\n| 19. | Invented grout curing record (Ref. Invented, Sub-Clause 2.8.4) | 60 |\n"
        "| 20. | Invented painting record (Ref. Invented, Sub-Clause 7.5.4) | 90 |\n| 21. | Invented spare parts list | 180 |"
    )
    terms = key_terms("Which grout curing record is due?")
    assert table_item(terms, passage) == "Item 19 (refers to 2.8.4)"
    assert (
        table_item(terms, "| 19. | Invented grout curing record |") is None
    )  # one row is not a list
    article = "| 19. | Invented grout curing record (Ref. Invented, Art 30) | 60 |\n| 20. | Invented other | 90 |"
    assert table_item(terms, article) == "Item 19 (refers to Art 30)"
    assert table_item(key_terms("What colour is the roof?"), passage) is None


def test_a_bare_clause_number_takes_its_title_from_the_page():
    from app.technical_query_match import titled

    page = "7.4 Invented Painting\nInvented words.\n7.5 Invented Coating\nThe invented coating words."
    assert titled("7.5", page) == "7.5 Invented Coating"
    assert titled("9.9", page) is None


def test_several_lone_decimal_values_between_text_rows_are_not_headings():
    page = "4.1 Invented Data\nInvented pressure\n1.5\nBar Gauge Reading\nInvented temperature\n2.0\nDegrees Reading\nThe invented answer."
    assert heading_above(page, "The invented answer.") == "4.1 Invented Data"


def test_consecutive_two_line_clause_headings_stay_headings():
    page = "4.1\nInvented General\nInvented words.\n4.2\nInvented Scope\nThe invented answer."
    assert heading_above(page, "The invented answer.") == "4.2 Invented Scope"
