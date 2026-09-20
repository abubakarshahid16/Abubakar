"""GATE 4 - when evidence is removed, the engine must abstain, not decide.

Four ways to remove evidence from one valid packet. None of them may produce
COMPLIANT or NON_COMPLIANT, each must say what is missing, and none may quote
text that was not in its input.

The packet is the Phase 0.5 pairing, so these cases exercise the same shapes the
slice will: SAES-A-133 clause 7.1.2.1 (>= 1.6 mm minimum corrosion allowance)
against 216400C page 4 "Design corrosion allowance for welded internals" = 0 mm.

MUTATION-SENSITIVE BY CONSTRUCTION. Each case names the branch of
`comparison.compare` (or `match_rules.refusal`) it depends on, and
`test_abstention_gate4_mutation.py`'s harness disables those branches one at a
time and requires the matching case to fail. A case that survives its own branch
being removed is vacuous and this project has already shipped one of those - see
`docs/status-honesty-audit.md`, B14.

NOT an accuracy test. It asserts that the engine declines; it says nothing about
whether any verdict it does reach is engineering-correct.
"""

from __future__ import annotations

import pytest

from app import comparison, match_rules

# ------------------------------------------------------------------ the packet

CLAUSE_TEXT = ('For carbon steel, low-alloy steel and alloy steel systems, a '
               'minimum C.A. of at least 1.6 mm (1/16") shall be used.')

#: Unrelated text, from a different standard, used to replace the clause.
FOREIGN_TEXT = ("Purge gas oxygen content shall not exceed 0.5 percent by "
                "volume before welding begins.")


def requirement(**over) -> dict:
    base = {
        "id": "78a0d3de-3eb7-42ce-b91c-b7403dab5959",
        "standard_document_id": "doc_saes_a_133",
        "clause": "7.1.2.1",
        "page": 48,
        "subject": "minimum C.A",
        "operator": ">=",
        "raw_value": "1.6",
        "raw_unit": "mm",
        "requirement_text": CLAUSE_TEXT,
        "source_text": CLAUSE_TEXT,
        "requirement_type": "numeric_limit",
        "condition": "carbon steel",
        "exceptions": None,
    }
    base.update(over)
    return base


def fact(**over) -> dict:
    base = {
        "id": "fact-216400c-ca-welded-internals",
        "submittal_document_id": "doc_2ec2934f8d3f",
        "field_name": "Design corrosion allowance for welded internals",
        "field_value": "0 mm",
        "raw_value": "0",
        "raw_unit": "mm",
        "page": 4,
        "is_blank": False,
        "blank_marker": None,
    }
    base.update(over)
    return base


DECIDED = {comparison.COMPLIANT, comparison.NON_COMPLIANT}


def assert_no_invented_quote(result: dict, *allowed_sources: str) -> None:
    """Nothing in double quotes in the rationale may be absent from the input.

    The rationale is allowed to quote the clause or the submitted field. It is
    not allowed to introduce a sentence from anywhere else, which is the failure
    a model in this position actually commits.
    """
    import re
    haystack = " ".join(" ".join(s.split()) for s in allowed_sources)
    for quoted in re.findall(r'"([^"]{8,})"', result.get("rationale") or ""):
        flat = " ".join(quoted.split())
        assert flat in haystack, (
            f"rationale quotes text absent from the input: {flat!r}")


# ------------------------------------------------------------------ control

def test_the_control_packet_does_reach_a_verdict():
    """The baseline must DECIDE, or the four cases below prove nothing.

    A test whose control also abstains cannot distinguish "abstained because
    evidence was removed" from "abstains always".
    """
    out = comparison.compare(requirement(), fact())
    assert out["status"] in DECIDED, (
        f"control must reach a verdict, got {out['status']}: {out['rationale']}")
    assert out["status"] == comparison.NON_COMPLIANT, (
        "0 mm against a >= 1.6 mm limit is the arithmetic this engine does")


# ------------------------------------------------- case 1: value blanked

def test_case_1_a_blanked_datasheet_value_never_becomes_a_verdict():
    """Branch: `compare`'s `fact.get("is_blank")`.

    Returns MISSING_INFORMATION rather than NEEDS_ENGINEER_REVIEW, deliberately
    and with a comment saying so: a field the sheet defers is not equipment
    failing anything. Both are safe non-approval outcomes under NORTH-STAR 2.2,
    which names MISSING_INFORMATION as its own finding type. What this asserts is
    the part that matters: no verdict, and the reason is named.
    """
    out = comparison.compare(requirement(),
                             fact(raw_value=None, field_value="BY VENDOR",
                                  is_blank=True, blank_marker="BY VENDOR"))
    assert out["status"] not in DECIDED
    assert out["status"] == comparison.MISSING_INFORMATION
    assert "BY VENDOR" in out["rationale"]
    assert out["observed"] is None
    assert_no_invented_quote(out, CLAUSE_TEXT, "BY VENDOR")


# ------------------------------------- case 2: clause replaced by foreign text

def test_case_2_a_clause_carrying_no_limit_is_not_compared():
    """Branch: `compare`'s `limit is None`.

    The clause text is replaced with a sentence from another standard, and the
    parsed limit goes with it - which is what re-extracting that sentence would
    actually yield, since it states no corrosion-allowance minimum.
    """
    out = comparison.compare(
        requirement(requirement_text=FOREIGN_TEXT, source_text=FOREIGN_TEXT,
                    operator=None, raw_value=None, raw_unit=None),
        fact())
    assert out["status"] not in DECIDED
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "no numeric limit" in out["rationale"]
    assert out["limit"] is None
    assert_no_invented_quote(out, FOREIGN_TEXT, "0 mm")


@pytest.mark.xfail(
    strict=True,
    reason="NO VALIDATOR CHECKS THAT THE CLAUSE TEXT SUPPORTS THE STORED LIMIT. "
           "Swap the clause text for an unrelated sentence but leave the parsed "
           "operator/value/unit in place and the engine still decides, quoting a "
           "limit its own evidence no longer contains. Recorded as a gap, not "
           "silently tolerated - see the Gate 4 finding in "
           "CURRENT_STATE_AND_BLOCKERS section 13.")
def test_case_2b_a_limit_its_clause_text_does_not_support_is_refused():
    out = comparison.compare(
        requirement(requirement_text=FOREIGN_TEXT, source_text=FOREIGN_TEXT),
        fact())
    assert out["status"] not in DECIDED


# --------------------------- case 3: clause present but does not govern

def test_case_3_a_requirement_from_another_equipment_domain_is_refused():
    """Branch: `match_rules.equipment_domain_conflict`, via `refusal`.

    This pairing is refused BEFORE `compare` ever sees it, which is the correct
    place: a pump clause against a vessel sheet is not a comparison that should
    be attempted and then abstained from.
    """
    pump_clause = requirement(
        requirement_text="The pump casing shall have a minimum thickness of "
                         "6 mm.",
        source_text="The pump casing shall have a minimum thickness of 6 mm.",
        subject="pump casing thickness", raw_value="6", raw_unit="mm")
    reason = match_rules.refusal(pump_clause, fact(), sheet="vessel")
    assert reason == match_rules.EQUIPMENT_DOMAIN, (
        f"a pump clause against a vessel sheet must be refused, got {reason!r}")


def test_case_3b_the_control_pairing_is_not_refused():
    """The refusal rules must not reject the valid packet, or case 3 is vacuous."""
    assert match_rules.refusal(requirement(), fact(), sheet="vessel") is None


# ------------------------------------------------ case 4: incompatible units

def test_case_4_incompatible_units_are_never_converted_by_guess():
    """Branch: `compare`'s `claims._compatible(...) is None`."""
    out = comparison.compare(requirement(),
                             fact(raw_value="60", raw_unit="degC",
                                  field_value="60 degC"))
    assert out["status"] not in DECIDED
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "cannot be compared" in out["rationale"]
    assert "no conversion is guessed" in out["rationale"]
    assert_no_invented_quote(out, CLAUSE_TEXT, "60 degC")


# ------------------------------------------------------------ the whole gate

def test_no_removal_of_evidence_produces_a_verdict():
    """All four at once, as one statement: remove evidence, get no verdict."""
    removals = {
        "value blanked": comparison.compare(
            requirement(), fact(raw_value=None, is_blank=True,
                                blank_marker="BY VENDOR")),
        "clause carries no limit": comparison.compare(
            requirement(requirement_text=FOREIGN_TEXT, source_text=FOREIGN_TEXT,
                        operator=None, raw_value=None, raw_unit=None), fact()),
        "incompatible units": comparison.compare(
            requirement(), fact(raw_value="60", raw_unit="degC")),
    }
    for label, out in removals.items():
        assert out["status"] not in DECIDED, f"{label} produced {out['status']}"
        assert out["rationale"], f"{label} abstained without saying why"
    assert match_rules.refusal(
        requirement(requirement_text="The pump casing shall have a minimum "
                                     "thickness of 6 mm.",
                    subject="pump casing thickness"),
        fact(), sheet="vessel") is not None
