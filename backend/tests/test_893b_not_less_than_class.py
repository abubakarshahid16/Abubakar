"""#893 (PF2): "The flange rating of nozzles shall be not less than Class 300."
is a FLOOR on the class. `_flange_rule` read the "not" of "not less than" as a
negation it has no rule for and returned nothing, so the clause went to an
engineer on a sheet that states the class. Invented sentences only."""
from __future__ import annotations

import pytest

from app import field_links


@pytest.mark.parametrize("sentence, operator, value", [
    ("The flange rating of nozzles shall be not less than Class 300.", ">=", 300),
    ("Flanges shall be rated not less than Class 150.", ">=", 150),
    ("The flange rating of nozzles shall be at least Class 300.", ">=", 300),
    ("The flange rating shall not exceed Class 600.", "<=", 600),
    ("The flange rating shall be Class 300.", "==", 300),
])
def test_a_comparative_with_not_in_it_is_read_as_what_it_says(sentence, operator, value):
    rule = field_links.categorical_requirement(sentence)
    assert rule is not None and (rule["operator"], rule["value"]) == (operator, value), rule


@pytest.mark.parametrize("sentence", [
    "The flange rating of nozzles shall not be Class 300.",             # another negation: still a question
    "Class 150 flanges shall not be used.",                              # forbidden: has its own reading
    "The flange rating shall not be less than Class 300 unless the line is not pressurised.",
])
def test_another_negation_is_still_left_to_the_engineer_or_its_own_reading(sentence):
    rule = field_links.categorical_requirement(sentence)
    assert rule is None or rule["operator"] == "!=", rule


def test_the_floor_is_then_compared_with_the_sheet():
    rule = field_links.categorical_requirement("The flange rating of nozzles shall be not less than Class 300.")
    assert field_links.compare_categorical(rule, "Class 600")["status"] == "COMPLIANT"
    assert field_links.compare_categorical(rule, "Class 150")["status"] == "NON_COMPLIANT"
