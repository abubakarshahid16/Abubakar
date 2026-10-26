"""Order 210 FIX 1: a clause that only asks for a value to be stated on the
datasheet, where the sheet has no matching field, is the contractor's
omission (MISSING_INFORMATION), not "another document's question".

The six PF1 items it should catch (clause text is the invented standard's):
pump D2 seal plan, compressor D3 vibration alarm setpoint, relief valve D2
orifice designation, tank D2 corrosion allowance, transmitter D2 ingress
protection, motor D2 starting method. Invented clauses only; no model.

It is never a pass, and only when every page was read (`qualify_by_pages`
still downgrades an unread page to the engineer).
"""

from __future__ import annotations

import pytest

from app import comparison, field_links

PF1_CLAUSES = [
    "The mechanical seal plan shall be stated on the datasheet.",
    "The vibration alarm setpoint shall be stated on the datasheet.",
    "The orifice designation shall be stated on the datasheet.",
    "The corrosion allowance shall be stated on the datasheet.",
    "The ingress protection rating shall be stated on the datasheet.",
    "The starting method shall be stated on the datasheet.",
]


def _req(text, rtype="statement"):
    return {
        "id": "req-1",
        "standard_document_id": "std",
        "clause": "9.1",
        "requirement_type": rtype,
        "requirement_text": text,
        "source_text": text,
        "subject": "x",
    }


@pytest.mark.parametrize("text", PF1_CLAUSES)
def test_a_stated_clause_with_no_field_is_missing_information(text):
    verdict = comparison._compare(_req(text), None, submittal_facts=[])
    assert verdict["status"] == comparison.MISSING_INFORMATION
    assert verdict["status"] not in (comparison.COMPLIANT, comparison.NOT_APPLICABLE)


def test_a_statement_that_does_not_ask_to_be_stated_stays_another_documents_question():
    text = "The pump shall comply with the manufacturer's quality manual."
    assert not field_links.asks_only_to_be_stated(text)
    verdict = comparison._compare(_req(text), None, submittal_facts=[])
    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def test_a_conditional_stated_clause_is_not_turned_into_an_omission():
    text = "Impact test results shall be stated on the datasheet if the design metal temperature is below -10 C."
    verdict = comparison._compare(_req(text), None, submittal_facts=[])
    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def test_an_unread_page_still_sends_it_to_the_engineer():
    verdict = comparison._compare(_req(PF1_CLAUSES[0]), None, submittal_facts=[])
    qualified = comparison.qualify_by_pages(
        verdict,
        {"pages_total": 3, "fact_pages": [1, 2], "pages_not_read_into_fields": [3]},
    )
    assert qualified["status"] == comparison.NEEDS_ENGINEER_REVIEW
