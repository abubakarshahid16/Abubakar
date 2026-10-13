"""#893 (PF2): closed value families beyond the flange class. An IP rating
("IP66", "not less than IP65", "IP66, IP67 or IP68") and a valve BODY rating
("Class 300") are compared by code, as the flange rating, radiography and PWHT
already are; an answer that does not read in the family's terms is left to the
engineer. IP codes are ordered by BOTH digits. Invented sentences only."""
from __future__ import annotations

import pytest

from app import field_links as fl


def _rule(sentence):
    return fl.categorical_requirement(sentence)


@pytest.mark.parametrize("sentence, operator, value", [
    ("The enclosure rating shall be IP66.", "==", (6, 6)),
    ("The enclosure rating shall be not less than IP65.", ">=", (6, 5)),
    ("The enclosure shall be at least IP 66.", ">=", (6, 6)),
    ("The enclosure rating shall not exceed IP67.", "<=", (6, 7)),
    ("The enclosure rating shall be IP66, IP67 or IP68.", "in", ((6, 6), (6, 7), (6, 8))),
])
def test_an_ip_clause_is_read_for_what_it_says(sentence, operator, value):
    rule = _rule(sentence)
    assert rule is not None and rule["family"] == "ip_rating" and (rule["operator"], rule["value"]) == (operator, value)


@pytest.mark.parametrize("sentence", [
    "The enclosure rating shall not be IP66.",
    "The enclosure shall be IP66 or better, with 1, 20 mm entries.",      # a bare pair is a number
    "The enclosure rating shall be at least IP65 and at most IP68.",
])
def test_an_ip_shape_that_is_not_read_gives_no_rule(sentence):
    rule = _rule(sentence)
    assert rule is None or rule["operator"] in ("!=", ">="), rule


@pytest.mark.parametrize("required, provided, status", [
    ("The enclosure rating shall be not less than IP65.", "IP66", "COMPLIANT"),
    ("The enclosure rating shall be not less than IP65.", "IP 65", "COMPLIANT"),
    ("The enclosure rating shall be not less than IP65.", "IP67", "COMPLIANT"),
    ("The enclosure rating shall be not less than IP65.", "IP54", "NON_COMPLIANT"),
    ("The enclosure rating shall be not less than IP65.", "IP56", "NON_COMPLIANT"),     # digits are not summed
    ("The enclosure rating shall be IP66, IP67 or IP68.", "IP67", "COMPLIANT"),
    ("The enclosure rating shall be IP66, IP67 or IP68.", "IP65", "NON_COMPLIANT"),
])
def test_ip_codes_are_compared_digit_by_digit(required, provided, status):
    assert fl.compare_categorical(_rule(required), provided)["status"] == status


@pytest.mark.parametrize("provided", ["NEMA 4X", "weatherproof", "IPX6", "", None])
def test_an_answer_outside_the_family_is_not_guessed_into_a_code(provided):
    assert fl.compare_categorical(_rule("The enclosure rating shall be not less than IP65."), provided) is None


def test_the_ip_family_answers_to_its_own_field_names_only():
    assert fl.FAMILY_FIELDS["ip_rating"] == frozenset({"ip rating"})
    for name in ("enclosure rating", "ip class", "ingress protection", "degree of protection"):
        assert fl.field_of(name)[0] == "ip rating", name
    assert fl.field_of("flange rating")[0] == "flange rating"


def test_a_valve_body_rating_is_compared_in_asme_classes():
    rule = _rule("The body rating shall be not less than Class 300.")
    assert rule is not None and rule["family"] == "flange_rating" and (rule["operator"], rule["value"]) == (">=", 300)
    assert "body rating" in fl.FAMILY_FIELDS["flange_rating"]
    assert fl.compare_categorical(rule, "Class 600")["status"] == "COMPLIANT"
    assert fl.compare_categorical(rule, "Class 150")["status"] == "NON_COMPLIANT"
