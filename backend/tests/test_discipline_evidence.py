"""Discipline values: STATED only when a sheet-title line literally states it;
otherwise INFERRED -> engineer review (owner rule 2026-09-25). Synthetic text
shaped like the two measured failures - no client document text."""
from app.model_evidence import INFERRED, REJECTED, STATED, discipline_evidence

TITLE = ["EXAMPLE OPERATING COMPANY", "MECHANICAL DATA SHEET", "CENTRIFUGAL PUMPS",
         "DATA SHEET NO.: DS-0000-DAS-M-01", "Process"]
PAGE = "\n".join(TITLE) + "\nSERVICE: RECYCLE\n"


def test_a_title_line_that_states_the_discipline_is_stated():
    r = discipline_evidence("Mechanical", "MECHANICAL DATA SHEET", title_lines=TITLE, source_text=PAGE)
    assert r["class"] == STATED and r["needs_engineer_review"] is False


def test_a_signature_cell_word_is_inferred_not_accepted():
    """THE MUTATION TARGET (M574): 'Process' alone, from a sign-off cell -
    the quote contains the word but no title line names the document kind."""
    r = discipline_evidence("Process", "Process", title_lines=TITLE, source_text=PAGE)
    assert r["class"] == INFERRED and r["needs_engineer_review"] is True


def test_a_discipline_inferred_from_a_document_number_is_inferred():
    """THE MUTATION TARGET (M575): the quote is a title-cue line but does
    not say 'Mechanical' - the model read it into the number code."""
    r = discipline_evidence("Mechanical", "DATA SHEET NO.: DS-0000-DAS-M-01",
                            title_lines=TITLE, source_text=PAGE)
    assert r["class"] == INFERRED and r["needs_engineer_review"] is True
    assert "does not state" in r["reason"]


def test_a_quote_not_on_the_page_is_rejected():
    r = discipline_evidence("Piping", "PIPING DATA SHEET", title_lines=TITLE, source_text=PAGE)
    assert r["class"] == REJECTED


def test_no_value_is_nothing():
    assert discipline_evidence(None, None, title_lines=TITLE, source_text=PAGE)["class"] is None
