"""Applicability by AI reasoning, not a taxonomy - built at the owner's
request 2026-09-28: no manual equipment lexicon (it would need thousands of
entries to cover real-world naming and was never built beyond a proposal
that does not exist as a file). Instead the model compares a standard's
already-verified scope record directly against the submittal's own
classified equipment type, in plain text.

WHAT STAYS THE SAME AS applicability_v2.decide, on purpose. Every exclusion
and limit item in `record` already passed `scope_records.verify` - its quote
is confirmed to sit on the page it names, before this module ever sees it.
The model here cannot invent a quote: a NOT_APPLICABLE is accepted only when
the model's quote matches one of these already-verified items character for
character (`_cites_a_verified_item`). Same asymmetric safety rule as
applicability_v2 - a wrong NOT_APPLICABLE hides a standard from the engineer,
the worst error - enforced by the same `applicability_v2.confirm_not_applicable`
gate: NOT_APPLICABLE needs 3 independent re-reads to agree, each with a
verified quote, or it falls back to UNKNOWN.

LIVE as of PR #310 (2026-09-28), behind `APPLICABILITY_REASONING_ENABLED` (on by
default since #736):
`applicability.select` calls `scope_decisions_by_reasoning`, which calls
`decide_with_confirmation_by_reasoning` below, through a per-(standard,
equipment type) cache. Not a proposal any more - correct this docstring
again if that ever stops being true, per this project's own rule that a
stale claim in a comment is a defect, not a nitpick.
"""

from __future__ import annotations

import json

from . import applicability_v2
from .reasoning_provider import Packet

PROMPT_VERSION = "scope-reasoning-v1"

#: Output cap. A decision is a few sentences at most; generous headroom
#: against a rambling answer costs little and a truncated one is unusable.
NUM_PREDICT = 400

SCHEMA = {"type": "object", "properties": {
    "decision": {"type": "string", "enum": [applicability_v2.APPLICABLE, applicability_v2.NOT_APPLICABLE,
                                            applicability_v2.APPLICABLE_CANDIDATE, applicability_v2.UNKNOWN]},
    "basis": {"type": "string"},
    "quote": {"type": ["string", "null"]},
    "page": {"type": ["integer", "null"]}},
    "required": ["decision", "basis", "quote", "page"]}

INSTRUCTIONS = (
    "You are told what one engineering standard's scope covers, excludes and limits - already read and "
    "quote-verified against the standard's own pages - and what kind of equipment a real submittal is. "
    "Decide whether the standard applies to that equipment.\n"
    "Rules:\n"
    f"- Say {applicability_v2.NOT_APPLICABLE} ONLY when one of the EXCLUSIONS or LIMITS below explicitly "
    "names or clearly covers this exact equipment type. Copy that item's quote EXACTLY, character for "
    "character, into \"quote\", and its page into \"page\". Never write a quote that is not one of "
    "the items given to you below.\n"
    f"- If the scope is generic (covers \"equipment\", \"facilities\" or similar with nothing "
    f"specific), or only lists OTHER equipment without an exclusion naming this one, say {applicability_v2.UNKNOWN} "
    f"or {applicability_v2.APPLICABLE_CANDIDATE} - never {applicability_v2.NOT_APPLICABLE}.\n"
    f"- Say {applicability_v2.APPLICABLE} when covered equipment or activities clearly include this "
    "equipment type, with no excluding limit.\n"
    f"- Say {applicability_v2.APPLICABLE_CANDIDATE} when the scope plausibly covers this equipment but "
    "an engineer should confirm (e.g. an activity/stage limit like in-service vs new).\n"
    f"- Say {applicability_v2.UNKNOWN} when you cannot tell from what is given.\n"
    "\"basis\" is one short plain-English sentence for the engineer reading this. "
    "\"quote\"/\"page\" are null unless your decision cites a specific exclusion or limit item. "
    "JSON only.\n")


def _record_summary(record: dict) -> str:
    """The scope record's verified items, laid out for the prompt. Only the
    fields the model needs to decide - never re-sent the raw source pages,
    which the record's own verification has already reduced to short quotes."""
    lines = []
    for label, key in (("Covered equipment", "covered_equipment"),
                       ("Covered activities", "covered_activities"),
                       ("Excluded (does not apply to)", "explicit_exclusions"),
                       ("Limited to", "explicit_limits")):
        items = record.get(key) or []
        if not items:
            lines.append(f"{label}: none")
            continue
        lines.append(f"{label}:")
        for it in items:
            term = it.get("term") or it.get("activity") or it.get("kind") or ""
            quote = it.get("quote") or ""
            page = it.get("page")
            lines.append(f"  - {term!r}: \"{quote}\" (page {page})")
    generic = bool(record.get("generic_scope"))
    lines.append(f"Generic scope (names no specific equipment): {generic}")
    return "\n".join(lines)


def packet(record: dict, equipment_type: str, *, step: str, seed: int | None = None) -> Packet:
    """The one request comparing a standard's verified scope to one
    submittal's equipment type. Deterministic except for `seed`, which
    distinguishes the independent re-reads of a NOT_APPLICABLE confirmation."""
    prompt = (f"STANDARD SCOPE (already verified):\n{_record_summary(record)}\n\n"
             f"SUBMITTAL EQUIPMENT TYPE: {equipment_type!r}\n\nANSWER:\n")
    return Packet(prompt=prompt, system=INSTRUCTIONS, num_ctx=4096, num_predict=NUM_PREDICT,
                 json_schema=SCHEMA, step=step, seed=seed, prompt_version=PROMPT_VERSION)


def _usable(response) -> dict | None:
    """The parsed answer, or None when it is invalid (schema errors, truncated, not JSON)."""
    if response is None or response.schema_errors or response.truncated:
        return None
    try:
        parsed = json.loads(response.text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or parsed.get("decision") not in (
            applicability_v2.APPLICABLE, applicability_v2.NOT_APPLICABLE,
            applicability_v2.APPLICABLE_CANDIDATE, applicability_v2.UNKNOWN):
        return None
    return parsed


def _cites_a_verified_item(quote: str | None, record: dict) -> bool:
    """The safety anchor: a NOT_APPLICABLE is accepted only when the model's
    quote is character-for-character one of the record's OWN already-verified
    exclusion/limit quotes - never a quote the model wrote itself. This is
    what stops the model from inventing evidence for a wrong exclusion,
    exactly as `scope_records.verify` stops it for the scope reading itself."""
    if not quote or not quote.strip():
        return False
    verified = {it.get("quote") for k in ("explicit_exclusions", "explicit_limits")
               for it in (record.get(k) or [])}
    return quote in verified


def _covered_evidence(record: dict) -> tuple[str | None, int | None]:
    """The (quote, page) that backs an APPLICABLE/APPLICABLE_CANDIDATE
    decision, taken from the record's own verified `covered_equipment` or
    `covered_activities` items - never from the model.

    THE BUG THIS FIXES (found reviewing EF1975-DAS-M-03, 2026-09-28): the
    INSTRUCTIONS prompt above tells the model "quote"/"page" are null UNLESS
    it cites a specific exclusion or limit, so an APPLICABLE decision comes
    back with quote=None, page=None by design - the model was never asked to
    cite what makes it applicable. `applicability.select` then rendered that
    as `covers this equipment: "" (page None)`, a claim with no citation
    behind it, on a standard whose record actually holds a verified quote
    naming the equipment. This reads that quote from the record instead,
    which `scope_records.verify` already confirmed sits on the page it
    names - the same evidence bar `_cites_a_verified_item` holds NOT_APPLICABLE
    to, applied to the other side of the same decision.

    Returns (None, None) when the record names no specific covered item (a
    `generic_scope` record, say) - that is reported as no quote, never as an
    empty string standing in for one."""
    for key in ("covered_equipment", "covered_activities"):
        for item in record.get(key) or []:
            quote = item.get("quote")
            if quote and quote.strip():
                return quote, item.get("page")
    return None, None


def decide_by_reasoning(record: dict | None, equipment_type: str | None, provider, *, step: str,
                        seed: int | None = None) -> dict:
    """One AI-reasoning decision. Same return shape as `applicability_v2.decide`:
    {decision, basis, quote, page, term}."""
    empty = lambda basis: {"decision": applicability_v2.UNKNOWN, "basis": basis,
                           "quote": None, "page": None, "term": equipment_type}
    if not equipment_type:
        return empty("no equipment type classified for this submittal")
    if not record:
        return empty("no verified scope record for this standard")
    response = provider.reason(packet(record, equipment_type, step=step, seed=seed))
    parsed = _usable(response)
    if parsed is None:
        return empty("model comparison invalid or unavailable")
    decision = parsed["decision"]
    quote, page = parsed.get("quote"), parsed.get("page")
    if decision == applicability_v2.NOT_APPLICABLE and not _cites_a_verified_item(quote, record):
        return empty("model's NOT_APPLICABLE did not cite one of the standard's own "
                     "verified exclusion/limit quotes - held back rather than trusted")
    # NOT backfilled from the record here - see `with_covered_evidence` below.
    # This function's return value is exactly what
    # `applicability._cached_scope_decision` stores in
    # `applicability_scope_decision_cache`. Filling the quote in HERE would
    # freeze it into the row at the moment it is written: a standard read
    # fresh today would get it, but the ~828 rows already cached before this
    # fix shipped would keep returning quote=None forever, because a cache
    # HIT never calls this function again. The backfill has to happen on
    # every READ of a decision, not on write - hence it lives in the caller.
    return {"decision": decision, "basis": parsed.get("basis"), "quote": quote, "page": page,
           "term": equipment_type}


def with_covered_evidence(decision: dict, record: dict | None) -> dict:
    """`decision`, with its quote/page backed by the record's own verified
    covered-item evidence when it has none (see `_covered_evidence`).

    BUG FIX, 2026-09-28 (caught by Claude Code verifying the first version of
    this fix against real cached data): the evidence backfill must be applied
    by the CALLER after every read of a scope decision - cache hit or fresh
    compute - never baked into `decide_by_reasoning`'s own return value,
    which is what gets written into `applicability_scope_decision_cache`. A
    fix inside `decide_by_reasoning` only reaches decisions computed AFTER
    the fix shipped; the ~828 already-cached rows from before it existed
    would keep coming back with quote=None on every cache hit, since a hit
    never calls that function again. Applying it here instead costs nothing
    (`record` is already in memory - no model call) and fixes every
    already-cached row the moment this ships, not only new ones.

    `applicability._cached_scope_decision` is the one caller: it calls this
    on the decision it is about to return, whether that decision came from
    the cache table or was just computed and is about to be stored. A model-
    supplied quote is trusted as-is; this only fills in what the reasoning
    prompt told the model to leave out for APPLICABLE/APPLICABLE_CANDIDATE.
    """
    if decision.get("decision") not in (applicability_v2.APPLICABLE, applicability_v2.APPLICABLE_CANDIDATE):
        return decision
    quote = decision.get("quote")
    if quote and quote.strip():
        return decision
    if not record:
        return decision
    covered_quote, covered_page = _covered_evidence(record)
    if not covered_quote:
        return decision
    return {**decision, "quote": covered_quote, "page": covered_page}


def decide_with_confirmation_by_reasoning(record: dict | None, equipment_type: str | None, provider, *,
                                          step: str) -> dict:
    """`decide_by_reasoning`, and a NOT_APPLICABLE stands only if 3 independent
    re-reads of the SAME record all agree (owner order 4.5.4's rule, applied
    to the reasoning path the same way `scope_records.decide_with_confirmation`
    applies it to the taxonomy path)."""
    first = decide_by_reasoning(record, equipment_type, provider, step=step)
    if first["decision"] != applicability_v2.NOT_APPLICABLE:
        return {**first, "confirmations": None}
    rereads = [decide_by_reasoning(record, equipment_type, provider, step=step, seed=s) for s in (1, 2, 3)]
    if applicability_v2.confirm_not_applicable(rereads):
        return {**first, "confirmations": 3}
    agreeing = sum(1 for r in rereads if r["decision"] == applicability_v2.NOT_APPLICABLE)
    return {"decision": applicability_v2.UNKNOWN,
           "basis": f"NOT_APPLICABLE held back: {agreeing}/3 re-reads agreed",
           "quote": None, "page": None, "term": equipment_type, "confirmations": agreeing}
