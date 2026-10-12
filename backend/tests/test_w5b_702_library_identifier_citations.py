"""#702: a datasheet that cites a standard by the library's own document number
(any numbering scheme, not only API/ASME/ISO/SAES...) selects that standard.
INVENTED identifiers. Mutations: M5401-M5412, `python scripts/mutation_check.py --phase 5401`.
"""
from __future__ import annotations

from app import applicability, standard_ids
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401 - autouse


def _select(sub, *ids):
    result = applicability.select(sub, allowed_document_ids=_scope(sub, *ids), persist=False)
    return {s["standard_document_id"]: s for s in result["selected"]}, result


def test_the_built_in_reader_cannot_see_a_company_number_which_is_the_gap():
    assert standard_ids.parse_all("per STD-Q-555 Ed 2024") == ()
    assert len(standard_ids.parse_all("per API 610")) == 1


def test_a_datasheet_citing_the_librarys_document_number_selects_that_standard():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="XYZ-PR-0042")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL",
               text="Relief valves shall comply with XYZ-PR-0042 and the data below.")
    chosen, _ = _select(sub, std)
    assert std in chosen
    row = chosen[std]
    assert row["method"] == applicability.METHOD_REFERENCED and row["included"] is True
    assert "XYZ-PR-0042" in row["reason"]
    assert row["evidence_page"] == 1 and "XYZ-PR-0042" in row["evidence_quote"]


def test_the_number_may_be_written_with_other_separators_and_an_edition():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Design per STD Q 210 Ed 2024.")
    chosen, _ = _select(sub, std)
    assert chosen[std]["included"] is True


def test_a_longer_number_is_not_the_library_standard():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Design per STD-Q-2100 only.")
    chosen, _ = _select(sub, std)
    assert std not in chosen


def test_a_number_that_is_only_a_prefix_of_the_cited_one_does_not_match_either():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="ABC-ENG-PRC-0042")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Use XABC-ENG-PRC-0042 rules.")
    chosen, _ = _select(sub, std)
    assert std not in chosen


def test_a_standard_whose_number_is_only_in_its_file_name_is_a_possible_match_not_included():
    std = _doc("std_f", "ABC-ENG-PRC-0042 Rev 3.pdf", "COMPANY_STANDARD")   # no document_number
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Fabrication per ABC-ENG-PRC-0042 Rev 3.")
    chosen, _ = _select(sub, std)
    row = chosen[std]
    assert row["method"] == applicability.METHOD_POSSIBLE and row["included"] is False
    assert row["reason"].startswith("possible match, engineer to confirm")
    assert row["evidence_page"] == 1 and row["identifier"] == "ABC-ENG-PRC-0042"


def test_an_edition_group_in_the_file_name_is_not_part_of_the_number():
    std = _doc("std_f", "STD-Q-210_Ed2024.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Per STD-Q-210.")
    chosen, _ = _select(sub, std)
    assert chosen[std]["method"] == applicability.METHOD_POSSIBLE


def test_a_standard_named_by_its_title_is_a_possible_match():
    std = _doc("std_t", "x.pdf", "COMPANY_STANDARD", title="Piping Fabrication Requirements")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL",
               text="Welding follows the Piping Fabrication Requirements of the owner.")
    chosen, _ = _select(sub, std)
    assert chosen[std]["method"] == applicability.METHOD_POSSIBLE and chosen[std]["included"] is False


def test_a_title_of_fewer_than_three_words_is_not_matched():
    std = _doc("std_t", "x.pdf", "COMPANY_STANDARD", title="Piping Standard")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Follow the Piping Standard here.")
    chosen, _ = _select(sub, std)
    assert std not in chosen


def test_a_possible_match_is_shown_to_the_engineer_in_the_reasons_view():
    std = _doc("std_f", "ABC-ENG-PRC-0042 Rev 3.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Per ABC-ENG-PRC-0042.")
    rows = applicability.applicability_with_reasons(sub, allowed_document_ids=_scope(sub, std))
    [row] = [r for r in rows if r["standard_document_id"] == std]
    assert row["status"] == applicability.STATUS_UNKNOWN
    assert "possible match, engineer to confirm" in row["reason"]


def test_a_built_in_family_citation_still_selects_as_before():
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD", document_number="API 610")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Pump per API 610 and STD-Q-210.")
    q = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210")
    chosen, _ = _select(sub, std, q)
    assert chosen[std]["method"] == applicability.METHOD_REFERENCED
    assert chosen[q]["method"] == applicability.METHOD_REFERENCED


def test_a_submittal_that_names_nothing_the_library_holds_selects_nothing_by_citation():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Nothing relevant is cited here.")
    chosen, _ = _select(sub, std)
    assert std not in chosen


def test_the_caller_only_matches_standards_it_may_read():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Per STD-Q-210.")
    result = applicability.select(sub, allowed_document_ids=_scope(sub), persist=False)   # std not granted
    assert not any(s["standard_document_id"] == std for s in result["selected"])


def test_a_superseded_standard_is_not_selected_by_its_number():
    std = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210",
               superseded_by="newer")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", text="Per STD-Q-210.")
    chosen, _ = _select(sub, std)
    assert std not in chosen


# ------------------------------------------------ the chat tool reads it too

def test_the_chat_tool_lists_a_company_number_as_held_and_a_file_name_match_as_possible():
    from app import chat_tools
    held = _doc("std_q", "company-q.pdf", "COMPANY_STANDARD", document_number="STD-Q-210")
    maybe = _doc("std_f", "ABC-ENG-PRC-0042 Rev 3.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL",
               text="Per STD-Q-210 and ABC-ENG-PRC-0042 Rev 3.")
    run = chat_tools.run_list_cited_standards(
        {"document_id": sub}, allowed_document_ids=_scope(sub, held, maybe))
    assert "STD-Q-210: held (company-q.pdf)" in run.note
    assert "ABC-ENG-PRC-0042: possible match, engineer to confirm (ABC-ENG-PRC-0042 Rev 3.pdf)" in run.note
