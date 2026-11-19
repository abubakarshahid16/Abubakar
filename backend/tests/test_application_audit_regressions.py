"""Regression examples use fictional papers and standard identifiers."""
import pytest
from app import standard_ids
from app.aim_review import steps
from app.aim_review.paper import Paper
from app.aim_review.verify import paper_relation


@pytest.mark.parametrize("design,expected", [(94, "pass"), (48, "fail")])
def test_paper_pair_uses_its_own_relationship_not_a_different_clause_limit(design, expected):
    design_quote = f"Internal maximum design temperature: {design} degC"
    operating_quote = "Maximum operating temperature: 58 degC"
    paper = Paper("fictional", {1: design_quote, 2: operating_quote})
    nums = {
        "paper_value": str(design), "paper_unit": "degC", "operator": "<=",
        "rule_value": "58", "rule_unit": "degC",
        "limit_quote": operating_quote, "limit_page": 2,
    }
    label, result = steps._numbers(
        nums, design_quote,
        "External-pressure design temperature shall not exceed the chart limit.",
        [], paper,
        "Design temperature is not below the maximum operating temperature. "
        "Under external pressure, check the chart limit.",
    )
    assert label == "AI opinion"
    assert result["op"] == ">="
    assert result["result"] == expected
    assert result["read_from"] == "verified paper quotes"


def test_relation_is_reversed_when_the_quoted_fields_are_in_the_other_order():
    assert paper_relation(
        "Design pressure shall not be less than operating pressure.",
        "Operating pressure: 8 bar", "Design pressure: 12 bar",
    ) == "<="


def test_unrelated_field_names_do_not_supply_an_operator():
    assert paper_relation(
        "Test pressure shall not be less than operating pressure.",
        "Design pressure: 12 bar", "Relieving pressure: 8 bar",
    ) is None


@pytest.mark.parametrize("identifier", ["XY-MECH-STD-104", "XY MECH STD 104"])
def test_an_unregistered_company_standard_is_read_from_the_paper(identifier):
    assert standard_ids.cited_standards(f"Relief design per {identifier}.") == [identifier]


def test_company_standard_shape_does_not_accept_equipment_tags():
    assert standard_ids.cited_standards("Tags 21-PV-1234 and 21-XY-STD-104-X.") == []
