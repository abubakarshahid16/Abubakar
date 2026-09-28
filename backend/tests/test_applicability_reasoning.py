"""AI-reasoning applicability (owner request 2026-09-28: no manual taxonomy).
Fake provider, no DB, no network. Mirrors the FakeProvider pattern used in
test_scope_records.py."""
import json

from app import applicability_reasoning as ar
from app import applicability_v2
from app import reasoning_provider as rp

RECORD = {
    "covered_equipment": [{"term": "centrifugal pumps", "quote": "covers centrifugal pumps", "page": 2}],
    "covered_activities": [],
    "explicit_exclusions": [{"term": "domestic water pumps",
                             "quote": "does not apply to pumps in domestic water service", "page": 2}],
    "explicit_limits": [{"kind": "service", "term": "process service", "quote": "for process service",
                         "page": 2}],
    "generic_scope": False,
}


class FakeProvider:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def reason(self, packet):
        text = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return rp.Response(text=text, provider="claude", model_tag="fake", digest="d", finish_reason="stop",
                           prompt_sha256=packet.sha256, schema_errors=rp.schema_errors(text, packet.json_schema))


def _answer(decision, quote=None, page=None, basis="because"):
    return json.dumps({"decision": decision, "basis": basis, "quote": quote, "page": page})


def test_missing_equipment_type_is_unknown_without_calling_the_model():
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE)])
    out = ar.decide_by_reasoning(RECORD, None, prov, step="t")
    assert out["decision"] == applicability_v2.UNKNOWN
    assert prov.calls == 0


def test_missing_record_is_unknown_without_calling_the_model():
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE)])
    out = ar.decide_by_reasoning(None, "Centrifugal Pump", prov, step="t")
    assert out["decision"] == applicability_v2.UNKNOWN
    assert prov.calls == 0


def test_applicable_passes_through():
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE, basis="covered equipment matches")])
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    assert out["decision"] == applicability_v2.APPLICABLE
    assert out["term"] == "Centrifugal Pump"


# --------------------------------- bug fix, 2026-09-28: APPLICABLE evidence
#
# THE BUG (found reviewing a real review of EF1975-DAS-M-03). The INSTRUCTIONS
# prompt tells the model quote/page are null unless it cites an exclusion or
# limit, so an APPLICABLE/APPLICABLE_CANDIDATE decision always arrived with
# quote=None - a claim rendered with no citation behind it, on a standard
# whose scope record actually holds a verified quote for the covered
# equipment. `test_applicable_passes_through` above never asserted on
# `quote`/`page` at all, so this shipped and stayed green.

def test_an_applicable_decision_is_backed_by_the_records_own_covered_quote():
    """The fix: when the model gives no quote for APPLICABLE (the normal
    case, per the prompt's own instructions), the record's own verified
    `covered_equipment` quote backs the decision instead of an empty one.
    Deleting `_covered_evidence` / its call in `decide_by_reasoning` makes
    this fail with quote=None, page=None."""
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE, basis="covered equipment matches")])
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    assert out["quote"] == "covers centrifugal pumps"
    assert out["page"] == 2


def test_an_applicable_candidate_decision_is_also_backed_by_record_evidence():
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE_CANDIDATE, basis="plausibly covered")])
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    assert out["quote"] == "covers centrifugal pumps"
    assert out["page"] == 2


def test_a_model_supplied_applicable_quote_is_kept_not_overwritten():
    """If the model DOES supply a quote (not required by the prompt, but not
    forbidden either), that quote is trusted as-is - the record is only a
    fallback for what the prompt told the model to leave out."""
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE, quote="its own quote", page=9,
                                 basis="because")])
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    assert out["quote"] == "its own quote"
    assert out["page"] == 9


def test_applicable_on_a_generic_scope_record_has_no_quote_not_an_empty_one():
    """A record with no covered_equipment/covered_activities items (a
    `generic_scope` one) has no evidence to fall back to. The result says so
    with None, never with an empty string standing in for a citation."""
    generic_record = {"covered_equipment": [], "covered_activities": [],
                      "explicit_exclusions": [], "explicit_limits": [],
                      "generic_scope": True}
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE, basis="generic scope covers everything")])
    out = ar.decide_by_reasoning(generic_record, "Centrifugal Pump", prov, step="t")
    assert out["quote"] is None
    assert out["page"] is None


def test_not_applicable_with_a_fabricated_quote_is_rejected_to_unknown():
    """THE SAFETY ANCHOR: the model claims NOT_APPLICABLE but the quote it
    gives does not match any of the record's own verified exclusion/limit
    quotes character for character - this must never be trusted."""
    fabricated = _answer(applicability_v2.NOT_APPLICABLE,
                         quote="this equipment is definitely not covered", page=2)
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", FakeProvider([fabricated]), step="t")
    assert out["decision"] == applicability_v2.UNKNOWN
    assert "did not cite" in out["basis"]


def test_not_applicable_citing_a_real_verified_item_is_accepted_at_the_single_call_level():
    real = _answer(applicability_v2.NOT_APPLICABLE,
                   quote="does not apply to pumps in domestic water service", page=2)
    out = ar.decide_by_reasoning(RECORD, "Domestic Water Pump", FakeProvider([real]), step="t")
    assert out["decision"] == applicability_v2.NOT_APPLICABLE
    assert out["quote"] == "does not apply to pumps in domestic water service"


def test_not_applicable_stands_only_when_three_rereads_agree():
    """THE MUTATION TARGET, same shape as test_scope_records' equivalent: the
    confirmation step must not be skippable."""
    na = _answer(applicability_v2.NOT_APPLICABLE,
                quote="does not apply to pumps in domestic water service", page=2)
    ok = _answer(applicability_v2.APPLICABLE, basis="covered after all")
    kept = ar.decide_with_confirmation_by_reasoning(
        RECORD, "Domestic Water Pump", FakeProvider([na, na, na, na]), step="t")
    held = ar.decide_with_confirmation_by_reasoning(
        RECORD, "Domestic Water Pump", FakeProvider([na, na, ok, na]), step="t")
    assert kept["decision"] == applicability_v2.NOT_APPLICABLE and kept["confirmations"] == 3
    assert held["decision"] == applicability_v2.UNKNOWN and held["confirmations"] == 2


def test_invalid_json_is_unknown():
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", FakeProvider(["not json"]), step="t")
    assert out["decision"] == applicability_v2.UNKNOWN
    assert "invalid or unavailable" in out["basis"]


def test_unknown_decision_never_requires_confirmation_rereads():
    prov = FakeProvider([_answer(applicability_v2.UNKNOWN, basis="cannot tell")])
    out = ar.decide_with_confirmation_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    assert out["decision"] == applicability_v2.UNKNOWN
    assert prov.calls == 1
