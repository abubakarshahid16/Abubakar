"""AI applicability (#647, #677): the model proposes, code confirms.

For a clause still in a review's scope after the code gates, the model answers
whether it applies to THIS equipment and service: yes / no / unsure, a reason
category, and the words of the clause it rests on. "AI reads, code checks":

  * the quote must be in the clause;
  * a "no" counts only when CODE can confirm its reason from stated facts:
      other_equipment            the equipment vocabulary (`subject_scope`)
                                 reads the quote as about equipment this
                                 submittal is not;
      service_condition_not_met  the quote names a service condition
                                 (`service_scope`) the datasheet declares
                                 absent;
      definition                 the quote is a defining sentence
                                 (`requirement_quality`);
      informative_note           the quote is a note ("NOTE", "Informative",
                                 "Commentary") with no "shall"/"must";
  * anything else - "unsure", an unconfirmed "no", a quote not in the clause,
    a reply that could not be read - leaves the clause a CHECK. Unsure is
    never dropped (#647); the engineer sees what the model suggested.

OFF by default (`settings.ai_applicability_enabled`) and capped per run
(`ai_applicability_max_per_run`); the model is the runner's setting (#683).
Nothing here names a standard or a datasheet.
"""
from __future__ import annotations

import re

from . import ai_task_runner, requirement_quality, scope_ledger, service_scope, subject_scope

CATEGORIES = ["other_equipment", "service_condition_not_met", "informative_note",
              "definition", "none"]

SCHEMA = {
    "type": "object",
    "required": ["applies", "reason", "quote"],
    "properties": {
        "applies": {"type": "string", "enum": ["yes", "no", "unsure"]},
        "reason": {"type": "string", "enum": CATEGORIES},
        "quote": {"type": ["string", "null"]},
    },
}

INSTRUCTION = """You decide whether one clause of an engineering standard applies
to one submittal. The EQUIPMENT and SERVICE lines describe the submittal; the
CLAUSE line is the clause. Answer:
- applies: "yes", "no" or "unsure";
- reason: when "no", why - "other_equipment" (the clause is about a different
  kind of equipment), "service_condition_not_met" (it applies only in a service
  this submittal is not in), "informative_note" (a note, not a requirement), or
  "definition"; otherwise "none";
- quote: the exact words of the clause your answer rests on.
Say "unsure" whenever the clause and the submittal do not settle it."""

TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="clause_applicability", version="v1", instruction=INSTRUCTION, schema=SCHEMA,
    num_predict=300))

_NOTE = re.compile(r"^\s*(?:note|notes|informative|commentary)\b", re.IGNORECASE)
_MANDATORY = re.compile(r"\b(?:shall|must|is required|are required)\b", re.IGNORECASE)


def _squash(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def context(classification: dict | None, facts: list[dict]) -> str:
    """The EQUIPMENT and SERVICE lines: what the submittal itself states."""
    equipment = (classification or {}).get("equipment_type") or "not stated"
    service = [f"{f.get('field_label')}: {f.get('field_value') or f.get('raw_value')}"
               for f in facts if not f.get("is_blank") and re.search(
                   r"service|fluid|h2s|sour|nace|temperature|pressure",
                   str(f.get("field_label") or ""), re.IGNORECASE)][:8]
    return f"EQUIPMENT: {equipment}\nSERVICE: {'; '.join(service) or 'not stated'}"


def confirm(reason: str, quote: str, *, equipment: set[str], facts: list[dict]) -> bool:
    """Can CODE confirm the model's "does not apply" from stated facts?"""
    if reason == "other_equipment":
        subject, _ = subject_scope.requirement_subject(
            {"requirement_text": quote}, {}, subject_scope.vocabulary())
        return bool(subject) and bool(equipment) and not (subject & equipment)
    if reason == "service_condition_not_met":
        for c in service_scope.conditions():
            d = service_scope.declaration(c, facts)
            if d is not None and d["present"] is False and service_scope.specific_to(
                    c, {"requirement_text": quote}, ""):
                return True
        return False
    if reason == "definition":
        return requirement_quality.is_defining_sentence(quote)
    if reason == "informative_note":
        return bool(_NOTE.match(quote)) and not _MANDATORY.search(quote)
    return False


def gate(requirements: list[dict], *, classification: dict | None, facts: list[dict],
         provider=None, limit: int | None = None) -> dict:
    """{"kept", "decisions" (confirmed "does not apply"), "notes" {requirement
    id: what the model suggested that code did not confirm}, "asked", "not_asked"}."""
    vocab = subject_scope.vocabulary()
    equipment, _ = subject_scope.submittal_equipment(classification, facts, vocab)
    head = context(classification, facts)
    model = getattr(provider, "requested_model", None) or ai_task_runner.settings.ai_task_model
    kept: list[dict] = []
    decisions: list[dict] = []
    notes: dict = {}
    asked = 0
    for requirement in requirements:
        clause = (requirement.get("source_text") or requirement.get("requirement_text") or "").strip()
        if limit is not None and asked >= limit or not clause:
            kept.append(requirement)
            continue
        asked += 1
        result = ai_task_runner.run_task(TASK, f"{head}\nCLAUSE: {clause}", provider=provider)
        data = result.data if result.state == ai_task_runner.STATE_OK else None
        if not data or data.get("applies") == "yes":
            kept.append(requirement)
            continue
        quote = data.get("quote") or ""
        in_clause = bool(quote.strip()) and _squash(quote) in _squash(clause)
        reason = data.get("reason") or "none"
        if (data.get("applies") == "no" and in_clause and reason in scope_ledger.REASONS
                and confirm(reason, quote, equipment=equipment, facts=facts)):
            decisions.append(scope_ledger.decision(
                requirement, reason, "proposed by the model, confirmed by code",
                decided_by=f"ai:{model}+code"))
            continue
        kept.append(requirement)
        notes[requirement.get("id")] = (
            "the model was unsure whether it applies" if data.get("applies") == "unsure"
            else f"the model said it may not apply ({reason.replace('_', ' ')}); "
                 "code could not confirm it")
    return {"kept": kept, "decisions": decisions, "notes": notes, "asked": asked,
            "not_asked": len(requirements) - asked}
