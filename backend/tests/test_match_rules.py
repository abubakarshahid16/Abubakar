"""The three rules that decide which containment hit may be paired.

Each rule is tested on the false pairing that motivated it, from
gold/PAIRS-216400C.csv, and on the case where it must NOT refuse - because a
rule that refuses when unsure turns a correct pairing into silence, and silence
does not show up on anybody's screen.
"""

from __future__ import annotations

import pytest

from app import comparison, match_rules


def requirement(subject, text=None, **over):
    base = {"requirement_type": "numeric_limit", "value": 3.5, "unit": "bar",
            "raw_value": "3.5", "raw_unit": "bar", "subject": subject,
            "requirement_text": text or subject}
    return {**base, **over}


def fact(field_name, **over):
    base = {"id": f"fact-{field_name}", "field_name": field_name,
            "raw_value": "2.2", "raw_unit": "bar", "unit": "bar"}
    return {**base, **over}


# ------------------------------------------------------------ rule 1: units
class TestUnitDimension:
    def test_pressure_against_temperature_is_refused(self):
        assert match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="bar"), fact("y", raw_unit="°C"))

    def test_temperature_against_ohm_cm_is_refused(self):
        """SAES-X-500 6.6.3: a limit in ohm-cm filed against 30 °C."""
        assert match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="ohm-cm"), fact("y", raw_unit="°C"))

    def test_kpa_against_bar_is_allowed(self):
        assert not match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="kPa"), fact("y", raw_unit="bar (ga)"))

    def test_gauge_reference_is_split_off_first(self):
        assert not match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="bar"), fact("y", raw_unit="barg"))

    def test_two_units_without_dimension_are_left_to_compare(self):
        """dB(A) against dB: `compare` refuses these; this rule has no
        opinion, because it cannot tell them from dB(A) against dB(A)."""
        assert not match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="dB(A)"), fact("y", raw_unit="dB"))

    def test_years_against_hours_is_left_to_compare(self):
        """Both recognised, one with a dimension. `compare` already refuses
        the comparison; refusing the pairing here would hide the finding."""
        assert not match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="years"), fact("y", raw_unit="h"))

    def test_a_missing_unit_on_either_side_is_allowed(self):
        assert not match_rules.unit_dimension_conflict(
            requirement("x", raw_unit=None, unit=None), fact("y", raw_unit="°C"))
        assert not match_rules.unit_dimension_conflict(
            requirement("x", raw_unit="bar"), fact("y", raw_unit="", unit=None))

    def test_the_rule_reaches_the_matcher(self):
        result = comparison.match_by_containment(
            requirement("the operating temperature shall not exceed",
                        raw_unit="ohm-cm"),
            [fact("operating temperature", raw_unit="°C")])
        assert result["fact"] is None
        assert result["reason"] == comparison.REFUSED_BY_RULE
        assert result["refused"] == [
            {"name": "operating temperature", "reason": match_rules.UNIT_DIMENSION}]


# ------------------------------------------------------------ rule 2: domain
class TestEquipmentDomain:
    def test_battery_clause_is_refused_on_a_vessel_sheet(self):
        """SAES-P-103 5.2.5, the pairing that started all of this."""
        req = requirement("the design life of the battery shall be at least",
                          raw_unit="years", raw_value="20")
        assert match_rules.equipment_domain_conflict(req, "vessel")

    def test_a_clause_naming_no_equipment_is_never_refused(self):
        req = requirement("a minimum design life of", raw_unit="years")
        assert not match_rules.equipment_domain_conflict(req, "vessel")

    def test_an_unknown_sheet_kind_never_refuses(self):
        req = requirement("the design life of the battery shall be at least")
        assert not match_rules.equipment_domain_conflict(req, None)

    def test_a_clause_naming_this_sheets_kind_is_allowed(self):
        req = requirement("pressure vessels shall have a corrosion allowance of")
        assert not match_rules.equipment_domain_conflict(req, "vessel")

    def test_a_clause_naming_several_kinds_including_this_one_is_allowed(self):
        req = requirement("pumps, compressors and vessels shall be rated for")
        assert not match_rules.equipment_domain_conflict(req, "vessel")

    def test_the_noun_may_sit_outside_the_subject(self):
        req = requirement("the rated voltage shall be",
                          text="For cables, the rated voltage shall be 11 kV.")
        assert match_rules.equipment_domain_conflict(req, "pump")

    def test_plurals_fold_to_the_noun(self):
        assert match_rules.domains_in("batteries and exchangers") == {"battery", "exchanger"}

    def test_words_containing_a_noun_do_not_count(self):
        """"tankage" and "pumping" are not the machines."""
        assert match_rules.domains_in("tankage and pumping station") == frozenset()


class TestSheetKind:
    def test_from_the_classification_first(self):
        assert match_rules.sheet_kind([], "Pressure Vessel") == "vessel"
        assert match_rules.sheet_kind([], "Centrifugal Pump") == "pump"
        assert match_rules.sheet_kind([], "Shell and Tube") == "exchanger"

    def test_from_field_names_when_the_classification_has_none(self):
        facts = [fact("vessel support corrosion allowance"), fact("design life")]
        assert match_rules.sheet_kind(facts, None) == "vessel"

    def test_disagreeing_field_names_decide_nothing(self):
        facts = [fact("pump rated flow"), fact("motor rated power")]
        assert match_rules.sheet_kind(facts, None) is None

    def test_a_classification_naming_no_domain_falls_back_to_fields(self):
        facts = [fact("vessel support corrosion allowance")]
        assert match_rules.sheet_kind(facts, "Skid") == "vessel"

    def test_the_rule_reaches_the_matcher_by_field_names(self):
        req = requirement("the design life of the battery shall be at least",
                          raw_unit="years", raw_value="20")
        facts = [fact("design life", raw_unit="years", raw_value="25"),
                 fact("vessel support corrosion allowance", raw_unit="mm")]
        result = comparison.match_by_containment(req, facts)
        assert result["fact"] is None
        assert result["refused"] == [
            {"name": "design life", "reason": match_rules.EQUIPMENT_DOMAIN}]

    def test_the_caller_may_name_the_sheet_kind(self):
        req = requirement("the design life of the battery shall be at least",
                          raw_unit="years", raw_value="20")
        facts = [fact("design life", raw_unit="years", raw_value="25")]
        assert comparison.match_by_containment(req, facts)["fact"] is not None
        assert comparison.match_by_containment(
            req, facts, sheet_kind="vessel")["fact"] is None
        assert comparison.match_by_containment(
            req, facts, sheet_kind="battery")["fact"] is not None


# ------------------------------------------------------------ rule 3: tables
D001_6_2_3 = ("The internal design pressure shall be according to the "
              "following table: Maximum Operating Pressure (MOP) - Design "
              "Pressure. MOP up to 1.7 bar - MOP + 1.0 bar.")


class TestTableLookupInput:
    def test_the_sentence_splits_at_the_marker(self):
        before, after = match_rules.table_lookup_split(D001_6_2_3)
        assert before == "the internal design pressure"
        assert after.startswith("maximum operating pressure mop")

    def test_the_input_field_is_refused(self):
        req = requirement(D001_6_2_3, text=D001_6_2_3)
        assert match_rules.table_lookup_input_conflict(req, "maximum operating pressure")

    def test_the_constrained_field_is_allowed(self):
        req = requirement(D001_6_2_3, text=D001_6_2_3)
        assert not match_rules.table_lookup_input_conflict(req, "internal design pressure")

    def test_a_sentence_with_no_table_has_no_opinion(self):
        req = requirement("the maximum operating pressure shall not exceed")
        assert not match_rules.table_lookup_input_conflict(req, "maximum operating pressure")

    @pytest.mark.parametrize("marker", [
        "shall be according to the following table",
        "shall be in accordance with the following table",
        "shall be as given in the table below",
        "shall be per the following table",
    ])
    def test_the_marker_spellings(self, marker):
        assert match_rules.table_lookup_split(f"The design pressure {marker}: MOP") is not None

    def test_a_field_named_on_both_sides_is_the_constrained_one(self):
        text = "The design pressure shall be according to the following table: design pressure vs MOP"
        req = requirement(text, text=text)
        assert not match_rules.table_lookup_input_conflict(req, "design pressure")

    def test_the_rule_runs_before_longest_wins(self):
        """THE MEASURED CASE. Two fields are contained in the subject;
        longest-wins picked the input (26 chars) over the constrained quantity
        (24 chars). With the rule before the tie, the constrained one wins."""
        req = requirement(D001_6_2_3, text=D001_6_2_3, raw_unit="bar")
        facts = [fact("maximum operating pressure", raw_value="2.2", raw_unit="bar (ga)"),
                 fact("internal design pressure", raw_value="3.5", raw_unit="bar (ga)")]
        result = comparison.match_by_containment(req, facts)
        assert result["matched_phrase"] == "internal design pressure"
        assert result["refused"] == [
            {"name": "maximum operating pressure", "reason": match_rules.TABLE_LOOKUP_INPUT}]

    # #193, measured 2026-09-24 against the vessel regression document's
    # labelled pairing sheet (gold/PAIRS-*): SAES-E-014
    # 7.2.4 stores the SAME MOP -> design-pressure table as D-001 6.2.3, but
    # its row starts at the header - the "shall be according to the following
    # table" sentence landed in a different requirement row - so the marker
    # rule never fired and "maximum operating pressure" was paired to it: the
    # one false pairing on the sheet.
    E014_7_2_4 = ("Maximum Operating Pressure (MOP) Design Pressure Up to 6,900 "
                  "kPa (1,000 psi) Greater of MOP x 1.1")

    def test_a_header_only_table_row_refuses_its_first_column(self):
        """A lookup table's FIRST header column is its key: the input."""
        req = requirement("Maximum Operating Pressure (MOP) Design Pressure",
                          text=self.E014_7_2_4, requirement_type="table_row")
        assert match_rules.table_lookup_input_conflict(req, "maximum operating pressure")

    def test_a_header_only_table_row_allows_a_later_column(self):
        req = requirement("Maximum Operating Pressure (MOP) Design Pressure",
                          text=self.E014_7_2_4, requirement_type="table_row")
        assert not match_rules.table_lookup_input_conflict(req, "design pressure")

    def test_a_header_that_names_only_one_quantity_has_no_input_to_refuse(self):
        req = requirement("Design Pressure", text="Design Pressure 10 bar",
                          requirement_type="table_row")
        assert not match_rules.table_lookup_input_conflict(req, "design pressure")

    def test_the_header_rule_is_only_for_table_rows(self):
        """A numeric limit whose subject merely STARTS with the field is the
        ordinary case - "maximum operating pressure of the vessel" - never an
        input column."""
        req = requirement("maximum operating pressure of the vessel")
        assert not match_rules.table_lookup_input_conflict(req, "maximum operating pressure")

    def test_the_measured_false_pairing_is_now_silence(self):
        req = requirement("Maximum Operating Pressure (MOP) Design Pressure",
                          text=self.E014_7_2_4, requirement_type="table_row",
                          raw_value="6,900", raw_unit="kPa")
        facts = [fact("maximum operating pressure", raw_value="2.2", raw_unit="bar (ga)"),
                 fact("internal design pressure", raw_value="3.5", raw_unit="bar (ga)")]
        result = comparison.match_by_containment(req, facts)
        assert result["fact"] is None
        assert result["refused"] == [
            {"name": "maximum operating pressure", "reason": match_rules.TABLE_LOOKUP_INPUT}]

    def test_without_the_constrained_field_the_input_alone_is_silence(self):
        req = requirement(D001_6_2_3, text=D001_6_2_3, raw_unit="bar")
        facts = [fact("maximum operating pressure", raw_unit="bar (ga)")]
        result = comparison.match_by_containment(req, facts)
        assert result["fact"] is None
        assert result["reason"] == comparison.REFUSED_BY_RULE


# ------------------------------------------------------------ together
class TestRefusal:
    def test_the_first_refusing_rule_names_itself(self):
        req = requirement("the design life of the battery shall be",
                          raw_unit="years")
        assert match_rules.refusal(req, fact("design life", raw_unit="ohm-cm"),
                                   sheet="vessel") == match_rules.EQUIPMENT_DOMAIN
        req_bar = requirement("the design pressure of the battery shall be",
                              raw_unit="bar")
        assert match_rules.refusal(req_bar, fact("design pressure", raw_unit="°C"),
                                   sheet="vessel") == match_rules.UNIT_DIMENSION
        assert match_rules.refusal(req, fact("design life", raw_unit="years"),
                                   sheet="vessel") == match_rules.EQUIPMENT_DOMAIN
        assert match_rules.refusal(req, fact("design life", raw_unit="years"),
                                   sheet=None) is None

    def test_every_reason_is_listed(self):
        assert set(match_rules.REASONS) == {
            match_rules.UNIT_DIMENSION, match_rules.EQUIPMENT_DOMAIN,
            match_rules.TABLE_LOOKUP_INPUT}

    def test_no_rule_fires_on_the_plain_case(self):
        """The existing containment behaviour is untouched when nothing is
        wrong with the pairing."""
        result = comparison.match_by_containment(
            requirement("the internal design pressure shall be at least"),
            [fact("internal design pressure")])
        assert result["fact"]["id"] == "fact-internal design pressure"
        assert result["refused"] == []

    def test_a_tie_among_allowed_hits_is_still_ambiguous(self):
        result = comparison.match_by_containment(
            requirement("design pressure and design temperat shall be"),
            [fact("design pressure"), fact("design temperat", raw_unit="bar")])
        # both 15 chars, both allowed (same unit)
        assert result["reason"] == comparison.AMBIGUOUS_MATCH
        assert sorted(result["candidates"]) == ["design pressure", "design temperat"]
