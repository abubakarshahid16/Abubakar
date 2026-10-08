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
#
# THE FIX'S OWN BUG, caught next (by Claude Code, verifying the first version
# of this fix against real cached data): the first version backfilled the
# quote INSIDE `decide_by_reasoning`, whose result is exactly what
# `applicability._cached_scope_decision` stores in the B5 cache table. That
# freezes the backfill into a row at write time - fine for a standard read
# fresh, but every one of the ~828 rows already cached before the fix shipped
# would keep coming back with quote=None forever, since a cache HIT never
# calls `decide_by_reasoning` again. The real fix is `with_covered_evidence`,
# a separate function the CALLER applies to every decision it reads back -
# cache hit or miss - never baked into what gets written. `decide_by_
# reasoning` itself must therefore return the RAW model quote (None, for a
# normal APPLICABLE), and `with_covered_evidence` is what backs it - proven
# below on both.

def test_decide_by_reasoning_returns_the_raw_quote_unbacked():
    """`decide_by_reasoning`'s own result must stay exactly what the model
    said - None for a normal APPLICABLE - because that result is what gets
    written into the cache table. If this function backfilled the quote
    itself, every already-cached row would be stuck with whatever quote
    existed at the moment it was cached, forever."""
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE, basis="covered equipment matches")])
    out = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    assert out["quote"] is None
    assert out["page"] is None


def test_with_covered_evidence_backs_an_applicable_decision():
    """The actual fix: reading a decision back through `with_covered_evidence`
    fills in the record's own verified quote when the decision has none.
    Deleting `_covered_evidence` / its call here makes this fail with
    quote=None, page=None - and unlike a fix inside `decide_by_reasoning`,
    this same call also repairs a decision that came from the cache."""
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE, basis="covered equipment matches")])
    raw = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    out = ar.with_covered_evidence(raw, RECORD)
    assert out["quote"] == "covers centrifugal pumps"
    assert out["page"] == 2


def test_with_covered_evidence_backs_an_applicable_candidate_too():
    prov = FakeProvider([_answer(applicability_v2.APPLICABLE_CANDIDATE, basis="plausibly covered")])
    raw = ar.decide_by_reasoning(RECORD, "Centrifugal Pump", prov, step="t")
    out = ar.with_covered_evidence(raw, RECORD)
    assert out["quote"] == "covers centrifugal pumps"
    assert out["page"] == 2


def test_with_covered_evidence_repairs_a_decision_that_came_from_the_cache():
    """THE MUTATION TARGET for the fix's own bug fix. A decision shaped
    exactly like a row already sitting in `applicability_scope_decision_
    cache` from before this fix existed - quote=None, no model call involved
    at all - must still come out backed. This is what a fix living only
    inside `decide_by_reasoning` could never do."""
    stale_cached_row = {"decision": applicability_v2.APPLICABLE, "basis": "old answer",
                        "quote": None, "page": None, "term": "Centrifugal Pump"}
    out = ar.with_covered_evidence(stale_cached_row, RECORD)
    assert out["quote"] == "covers centrifugal pumps"
    assert out["page"] == 2


def test_with_covered_evidence_keeps_a_model_supplied_quote():
    """If the model DOES supply a quote (not required by the prompt, but not
    forbidden either), that quote is trusted as-is - the record is only a
    fallback for what the prompt told the model to leave out."""
    decision = {"decision": applicability_v2.APPLICABLE, "basis": "because",
               "quote": "its own quote", "page": 9, "term": "Centrifugal Pump"}
    out = ar.with_covered_evidence(decision, RECORD)
    assert out["quote"] == "its own quote"
    assert out["page"] == 9


def test_with_covered_evidence_on_a_generic_scope_record_has_no_quote_not_an_empty_one():
    """A record with no covered_equipment/covered_activities items (a
    `generic_scope` one) has no evidence to fall back to. The result says so
    with None, never with an empty string standing in for a citation."""
    generic_record = {"covered_equipment": [], "covered_activities": [],
                      "explicit_exclusions": [], "explicit_limits": [],
                      "generic_scope": True}
    decision = {"decision": applicability_v2.APPLICABLE, "basis": "generic scope covers everything",
               "quote": None, "page": None, "term": "Centrifugal Pump"}
    out = ar.with_covered_evidence(decision, generic_record)
    assert out["quote"] is None
    assert out["page"] is None


def test_with_covered_evidence_leaves_not_applicable_and_unknown_alone():
    """Only APPLICABLE/APPLICABLE_CANDIDATE are backfilled. NOT_APPLICABLE
    already has its own citation requirement (`_cites_a_verified_item`); a
    quote does not belong on UNKNOWN at all."""
    not_applicable = {"decision": applicability_v2.NOT_APPLICABLE, "basis": "excluded",
                      "quote": "does not apply to pumps in domestic water service",
                      "page": 2, "term": "Centrifugal Pump"}
    assert ar.with_covered_evidence(not_applicable, RECORD) == not_applicable
    unknown = {"decision": applicability_v2.UNKNOWN, "basis": "no idea",
              "quote": None, "page": None, "term": "Centrifugal Pump"}
    assert ar.with_covered_evidence(unknown, RECORD) == unknown


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
