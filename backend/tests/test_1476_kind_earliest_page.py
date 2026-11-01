"""#1476 proof finding: a 64-page hydrotest plan was called a datasheet because
an attachment on page 51 ("Material Safety Data Sheet") was read before the
cover. A document names itself on its first page; a test plan is a procedure.
Invented documents only."""

from __future__ import annotations

import pytest

from app import document_kind


def _filler(tag, n=12):
    return "\n".join(f"{tag} line {i}" for i in range(n))


COVER = (
    "Line 9 River Crossing\nHydrostatic Pressure Test Plan\nVersion\nREV-2\n"
    + _filler("Cover")
)
ATTACHMENT = "ACME GASES\nMaterial Safety Data Sheet\nProduct: nitrogen\n" + _filler(
    "MSDS"
)


def _pages(*texts):
    return [{"page_no": i + 1, "text": t} for i, t in enumerate(texts)]


def test_an_attachment_late_in_the_document_does_not_decide_its_kind():
    pages = _pages(COVER, *[_filler(f"Body {i}") for i in range(3)], ATTACHMENT)
    e = document_kind.decide_document_kind(pages, document_role="CONTRACTOR_SUBMITTAL")
    assert (e.kind, e.page) == ("procedure", 1)


def test_the_earliest_page_naming_the_document_wins():
    later = "WELDING PROCEDURE\n" + _filler("Appendix")
    pages = _pages("PIPING SPECIFICATION\n" + _filler("Cover"), _filler("Body"), later)
    e = document_kind.decide_document_kind(pages, document_role="CONTRACTOR_SUBMITTAL")
    assert (e.kind, e.page) == ("specification", 1)


@pytest.mark.parametrize(
    "title",
    [
        "Hydrostatic Pressure Test Plan",
        "PNEUMATIC TESTING PLAN",
        "Inspection and Test Plan",
    ],
)
def test_a_test_plan_is_a_procedure(title):
    e = document_kind.decide_document_kind(_pages(title + "\n" + _filler("Cover")))
    assert e.kind == "procedure"


def test_a_plot_plan_is_not_made_a_procedure():
    e = document_kind.decide_document_kind(_pages("PLOT PLAN\n" + _filler("Cover")))
    assert e.kind != "procedure"
