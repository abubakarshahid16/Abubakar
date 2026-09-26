"""B6 finding: a number inside a sentence is part of the sentence.

`quality.longest_clause` decides whether a chunk is retrievable (the quality
gate) and whether a short early page is front matter (`classify_page`). It
counted only runs of letter-words, so every number ended the "sentence". The
requirement clauses densest in figures - exactly what engineers ask about -
then read as debris and were never indexed for search: on the B6 synthetic
corpus 3 of 15 clauses were unreachable ("50 to 75 micrometres", "AISI 4140",
"epoxy primer 75 micrometres, ... 150 micrometres").

The fix is narrow: a plain number BETWEEN two words keeps the run going
without counting in it. A number next to a number, or at the end, still breaks
the run - so tables, contents columns and symbol debris stay out.
"""
from __future__ import annotations

from app.chunker import classify_page
from app.quality import assess, longest_clause


def test_a_measurement_inside_a_sentence_does_not_end_it():
    assert longest_clause("a surface profile of 50 to 75 micrometres before the first coat") == 9


def test_a_clause_dense_in_figures_passes_the_quality_gate():
    for text in [
        "The casing shall be ASTM A216 WCB, the impeller CA6NM and the shaft "
        "AISI 4140 for all centrifugal pumps.",
        "Abrasive blast cleaning to Sa 2.5 with a surface profile of 50 to 75 "
        "micrometres before the first coat.",
    ]:
        assert assess(text)["ok"], text


def test_a_short_first_page_with_a_figured_clause_is_content_not_front_matter():
    page = ("3.4 Coating System\nEpoxy primer 75 micrometres, epoxy intermediate 150 "
            "micrometres and\npolyurethane topcoat 50 micrometres dry film thickness.")
    assert classify_page(page, 2, 4) == "prose"


def test_numbers_that_are_not_inside_a_sentence_still_break_the_run():
    # contents lines: a number next to a number, or at the end
    assert longest_clause("5.3.1 Identity Theft 257 5.3.2 Fraud Losses 260") == 2
    # a table row
    assert longest_clause("Flow 120 150 180 m3/h") == 1
    # a number cannot START a run: only the words after it count
    assert longest_clause("12 14 pumps") == 1
    # and a number never counts as a word itself
    assert longest_clause("of 50 to") == 2


def test_a_wall_of_numbers_has_no_clause_at_all():
    assert longest_clause("10 20 30 40 50 60 70 80 90 100 110 120 130 140") == 0


def test_table_rows_are_not_read_as_one_sentence():
    """A label/value table extracted one cell per line: each row number is
    followed by a capitalised label, so rows do not bridge into a 'sentence'."""
    table = "1\nDesign pressure\n23.5 barg\n2\nSet pressure\n340 psig\n3\nCompressibility factor\n0.892\n"
    assert longest_clause(table) == 3
    # the same words laid out as a sentence on one line do bridge
    assert longest_clause("Design pressure 23.5 barg and set pressure 340 psig") == 7


def test_a_table_joined_onto_one_line_still_reads_as_rows():
    """The chunker joins a table's cells with spaces, so the line rule alone
    cannot see the rows there. A row number is followed by a capitalised
    label; a measurement by its lower-case unit or the rest of the sentence."""
    flat = "1 Design pressure 23.5 barg 2 Set pressure 340 psig 3 Compressibility factor 0.892"
    assert longest_clause(flat) == 3
    assert not assess(flat)["ok"]
