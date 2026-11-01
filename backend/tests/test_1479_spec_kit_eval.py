"""#1479 evaluation fixes: a table-of-contents line, a revision-history line or a scope
sentence is not the passage that states a must-contain item. Invented text only."""

from __future__ import annotations

from app import spec_kit

DOTS = "." * 60


def _item(discipline: str, item_id: str) -> dict:
    return next(i for i in spec_kit.kits()[discipline]["items"] if i["id"] == item_id)


def _found(item_id: str, pages, discipline="pressure_vessel"):
    return spec_kit.find_item(_item(discipline, item_id), pages)


def test_a_contents_line_with_dot_leaders_is_not_a_passage():
    toc = (
        f"Contents\nScope {DOTS} 6\nCorrosion allowance {DOTS} 12\n"
        f"Wind and seismic loads {DOTS} 14\n"
    )
    for item in ("corrosion_allowance", "wind_seismic", "scope"):
        assert _found(item, [(2, toc)]) is None, item


def test_the_body_clause_is_found_after_the_contents_page():
    pages = [
        (2, f"Contents\nCorrosion allowance {DOTS} 12\n"),
        (9, "5.1 The corrosion allowance shall be 3 mm on all pressure parts."),
    ]
    got = _found("corrosion_allowance", pages)
    assert got["page"] == 9 and "3 mm" in got["quote"]


def test_a_revision_history_edition_is_not_the_referenced_editions():
    pages = [
        (1, "Revision history\nVersion 2.0 Second Edition\nVersion 1.0 First Edition")
    ]
    assert _found("referenced_editions", pages) is None
    ok = [
        (
            3,
            "Only the edition cited of a dated reference applies; "
            "the latest edition of an undated reference applies.",
        )
    ]
    assert _found("referenced_editions", ok)["page"] == 3


def test_a_scope_sentence_listing_materials_is_not_the_materials_clause():
    scope = [
        (1, "This specification covers the design, materials, fabrication and testing.")
    ]
    assert _found("materials", scope) is None
    body = [(5, "Materials of construction shall be listed on the data sheet.")]
    assert _found("materials", body)["page"] == 5


def test_a_passing_word_documentation_or_inspection_is_not_the_clause():
    stray = [
        (1, "Refer to contract documentation (e.g. the purchase order)."),
        (2, "Inspection openings shall be DN 100."),
    ]
    assert _found("documentation", stray) is None
    assert _found("inspection_testing", stray) is None
    real = [
        (3, "The supplier shall submit documentation with the data book."),
        (4, "Non-destructive examination shall be radiographic for all butt welds."),
    ]
    assert _found("documentation", real)["page"] == 3
    assert _found("inspection_testing", real)["page"] == 4


def test_a_scope_clause_needs_scope_of_this_document_not_scope_of_supply():
    assert _found("scope", [(1, "The scope of supply includes two vessels.")]) is None
    got = _found(
        "scope",
        [
            (
                1,
                "1 Scope. This specification defines the minimum requirements for vessels.",
            )
        ],
    )
    assert got["page"] == 1


def test_ordinary_wording_of_materials_documentation_and_inspection_is_found():
    assert _found("materials", [(1, "Shell material: SA-516 Gr 70.")])["page"] == 1
    assert _found("materials", [(1, "Plates shall be of ASTM A 240 material.")])
    docs = [(2, "Vendor shall submit design calculations and drawings.")]
    assert _found("documentation", docs)["page"] == 2
    nde = [
        (
            3,
            "All butt welds shall be 100% RT inspected. Inspection and testing per ASME.",
        )
    ]
    assert _found("inspection_testing", nde)["page"] == 3
    assert _found("inspection_testing", [(3, "Vessels shall be tested with water.")])


def test_a_register_or_revision_mention_is_not_the_clause():
    assert _found("documentation", [(1, "Deliverables register is attached.")]) is None
    assert (
        _found("documentation", [(1, "Documentation from the supplier is on file.")])
        is None
    )
    assert _found("scope", [(1, "The scope of this revision is editorial.")]) is None
    assert _found("inspection_testing", [(1, "The part is in the art of ut.")]) is None
