"""Tiered automatic use of AI-compiled rules: proof, second check, labels, audit.

THE OWNER DECISION. A rule the AI compiled (a `standard_requirements` row the
model proposed and code verified, or a table rule `rule_eval` holds) may decide
a verdict WITHOUT an engineer approving it one by one - but only under these
controls, each a function here:

  1. TIERS (`tier`). A rule is SAFETY tier when its target field names one of
     the safety fields in `reference/rule_trust.json`, or its sentence carries
     a condition, exception or cross-reference (generic operator words, same
     file). Safety-tier rules are still used automatically, but every
     COMPLIANT verdict they give is flagged `show_for_engineer_tick` so the CRS
     prints the clause quote and the datasheet value for an engineer to tick.
  2. PROOF BEFORE TRUST (`prove_family`). A rule FAMILY is (standard document,
     equipment type). The family is run on an answer key through the EXISTING
     deterministic evaluators (`evaluate_case` wraps `comparison.compare` and
     `rule_eval.evaluate`; nothing is compared here). PROVEN needs at least
     `settings.rule_proof_min_cases` cases (300: the rule of three - no error
     in 300 bounds the error rate at 1% with 95% confidence) and no error.
     A proof is stored with the model id and the standard revision it was
     made under, and is INVALID when either changes (`load_proof`).
  3. SECOND CHECK (`second_check`). The rule must pass the same code checks an
     engineer's acceptance passes (`ai_requirements.verify_proposal`: quote,
     number, unit, operator and condition in its own sentence) and its
     operator must not point the opposite way to the sentence
     (`requirements_3b.contradicts_source`). Reused, never re-implemented.
  4. TRUST LABEL (`trust_label`, `check_label`, `apply_trust`). Every rule
     is labelled, one vocabulary (planner answer on #985): ENGINEER_CONFIRMED
     (a person confirmed the row, or a signed-off committed checklist item),
     AUTO_PROVEN (an AI-compiled rule, family proven, second check passed)
     or UNPROVEN (every other rule). An UNPROVEN rule never decides COMPLIANT or NON_COMPLIANT on
     its own: the verdict becomes NEEDS_ENGINEER_REVIEW with the reason.
  5. UNCOVERED FIELDS (`uncovered_fields`). Datasheet fields read with a value
     that no applicable rule targets, so the CRS can list "not checked by any
     rule" instead of missing them silently.
  6. RANDOM AUDIT (`audit_sample`, `record_audit_outcome`). A deterministic
     2-5% (at least one) of AUTO_PROVEN findings is drawn for an engineer's
     spot-check; one audit error makes the family's proof INVALID, so the
     family is UNPROVEN again until it is re-proven.

PURE WHERE IT CAN BE. Only `ensure_schema`, `save_proof`, `load_proof` and
`record_audit_outcome` touch the database. No model, no network.

WIRING (#985, BEHIND THE SWITCH). The hooks return their input unchanged
unless `settings.rule_auto_use_enabled` (OFF by default), so a review with
the switch off stores what it stored before. The call sites:
  * `comparison._run_comparison`: every verdict from `compare(...)` passes
    through `label_finding` with the family proof (`comparison._RuleTrust`,
    one per (standard_document_id, equipment_type) and compiling model);
    every datasheet check through `label_check` (`datasheet_checks.store`).
  * the same function, after all findings exist: `uncovered_fields(facts,
    applicable_requirements)` for the CRS "not checked by any rule" list, and
    `audit_sample([ids of AUTO_PROVEN findings], seed=review_run_id)`.
  * `crs_mapping` prints `trust_words` and, for `show_for_engineer_tick`, a
    safety-tick row with the clause and the datasheet value (internal copy).
No rule here names a standard, a clause or a datasheet layout.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path

from . import ai_requirements, field_links, field_naming, requirements_3b, rule_eval
from .config import settings

log = logging.getLogger(__name__)

COMPLIANT, NON_COMPLIANT = rule_eval.COMPLIANT, rule_eval.NON_COMPLIANT
NEEDS_ENGINEER_REVIEW = rule_eval.NEEDS_ENGINEER_REVIEW

SAFETY, STANDARD = "SAFETY", "STANDARD"
ENGINEER_CONFIRMED, AUTO_PROVEN, UNPROVEN = "ENGINEER_CONFIRMED", "AUTO_PROVEN", "UNPROVEN"
#: What the CRS prints for each label.
TRUST_WORDS = {ENGINEER_CONFIRMED: "engineer-approved rule", AUTO_PROVEN: "automatic (proven rule)",
               UNPROVEN: "automatic rule not yet proven"}
PROVEN, NOT_PROVEN, INVALID = "PROVEN", "NOT_PROVEN", "INVALID"
AUDIT_CORRECT, AUDIT_ERROR = "correct", "error"
AUDIT_RATE_MIN, AUDIT_RATE_MAX = 0.02, 0.05
UNPROVEN_REASON = ("the rule is not yet proven: it is neither engineer-approved nor an AI-compiled "
                   "rule whose family is proven on an answer key and passes code's second check; "
                   "an engineer decides")
#: The one mark of an AI-COMPILED rule: the row the review compares with is
#: the model's (`ai_requirements.auto_use_rules`), never confirmed by a person.
#: Only such a rule can earn AUTO_PROVEN; a family proof says nothing about a
#: rule code extracted or a checklist item.
AI_COMPILED_METHOD = "model"


# ------------------------------------------------------------ reference data

@lru_cache(maxsize=4)
def _reference(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    words = [w for w in data.get("condition_words") or [] if str(w).strip()]
    pattern = (re.compile(r"(?<![\w-])(?:" + "|".join(
        r"\s+".join(re.escape(p) for p in str(w).split()) for w in
        sorted(words, key=len, reverse=True)) + r")(?![\w-])", re.IGNORECASE) if words else None)
    return {"fields": data.get("safety_fields") or [], "condition": pattern}


def reference(path: Path | str | None = None) -> dict:
    """The safety fields and the condition-word pattern, from the reference
    file (`settings.rule_trust_reference_path`). An unreadable file RAISES:
    a missing safety list must not quietly make every rule standard tier."""
    return _reference(str(path or settings.rule_trust_reference_path))


# ------------------------------------------------------------ field names

def _words(name: str | None) -> list[str]:
    """Content words of a field name after the shared fold and synonym table
    (`field_links.canonical`), brackets dropped (`field_naming._norm`)."""
    return field_naming._content_words(field_links.canonical(field_naming._norm(name)))


def _has_words(name: str | None, needed: list[str]) -> bool:
    have = _words(name)
    return bool(needed) and all(any(field_naming._same_word(n, h) for h in have) for n in needed)


def names_field(name: str | None, term: str) -> bool:
    """`name` names `term`: every content word of `term` is in `name` (stems
    of four letters or more count). Generous by design - erring here puts a
    rule in the SAFETY tier, the cautious direction. A one-word term too
    short for a content word ("SIL") is matched as a whole word instead."""
    needed = _words(term)
    if needed:
        return _has_words(name, needed)
    return re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", (name or "").lower()) is not None


def same_field(a: str | None, b: str | None) -> bool:
    """Two names name ONE field: each names the other. Stricter than
    `names_field` on purpose: "pressure" does not cover "design pressure",
    so a datasheet field is only counted as checked by a rule about it."""
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and _has_words(a, wb) and _has_words(b, wa)


def rule_field(rule: dict) -> str | None:
    """The field a rule judges: a limit's `field` (or `subject`), a table
    rule's OUTPUT (its input is never judged - `rule_eval` 2b)."""
    return rule.get("field") or rule.get("output") or rule.get("subject")


def _sentence(rule: dict) -> str:
    return rule.get("source_text") or rule.get("requirement_text") or rule.get("quote") or ""


# ------------------------------------------------------------ 1. tiers

def tier(rule: dict, *, ref: dict | None = None) -> tuple[str, str | None]:
    """(SAFETY | STANDARD, why). Safety when the target field names a safety
    field, the sentence uses one of its `text_words`, the rule carries a
    condition or exception, or the sentence has a condition word."""
    ref = ref or reference()
    target, sentence = rule_field(rule), _sentence(rule)
    for entry in ref["fields"]:
        if any(names_field(target, term) for term in entry.get("names") or [entry["name"]]):
            return SAFETY, f"safety field: {entry['name']}"
        if any(names_field(sentence, w) for w in entry.get("text_words") or []):
            return SAFETY, f"safety field in the sentence: {entry['name']}"
    if rule.get("condition") or rule.get("exceptions"):
        return SAFETY, "the rule carries a condition or exception"
    found = ref["condition"].search(sentence) if ref["condition"] else None
    if found:
        return SAFETY, f"condition, exception or cross-reference in the sentence: {found.group(0)!r}"
    return STANDARD, None


# ------------------------------------------------------------ 2. proof

def family_key(standard_document_id: str, equipment_type: str | None) -> str:
    """One family per standard document and equipment type (folded)."""
    return f"{standard_document_id}|{' '.join(_words(equipment_type)) or '-'}"


def _status_of(verdict) -> str | None:
    return verdict.get("status") if isinstance(verdict, dict) else verdict


def _value(values: dict, name: str | None, names: list[str] | None = None):
    """The case's value for `name` (or any of `names`): {"value", "unit"}."""
    for key, got in (values or {}).items():
        if any(same_field(key, n) for n in [name, *(names or [])] if n):
            return got if isinstance(got, dict) else {"value": got, "unit": ""}
    return None


def evaluate_case(rule: dict, case: dict) -> str | None:
    """The EXISTING deterministic verdict of `rule` on one answer-key case.
    A table rule (`rows`) goes to `rule_eval.evaluate`; any other rule to
    `comparison.compare` with the case's values as datasheet facts. Nothing is
    compared here. A value the case does not give is MISSING_INFORMATION."""
    from . import comparison

    values = case.get("values") or {}
    if rule.get("rows"):
        out = _value(values, rule.get("output"))
        inp = _value(values, rule.get("input"), rule.get("input_names"))
        if out is None or inp is None:
            return rule_eval.MISSING_INFORMATION
        verdict = rule_eval.evaluate(rule, float(inp["value"]), inp.get("unit") or "",
                                     float(out["value"]), out.get("unit") or "")
        return _status_of(verdict) or NEEDS_ENGINEER_REVIEW
    facts = [{"field_name": k, "raw_value": str((v if isinstance(v, dict) else {"value": v})["value"]),
              "raw_unit": (v.get("unit") if isinstance(v, dict) else "") or ""}
             for k, v in values.items()]
    fact = next((f for f in facts if same_field(f["field_name"], rule_field(rule))), None)
    return _status_of(comparison.compare(rule, fact, submittal_facts=facts))


def prove_family(rules: list[dict], answer_key: list[dict], evaluate_fn=evaluate_case, *,
                 min_cases: int | None = None) -> dict:
    """Run every answer-key case through `evaluate_fn(rule, case)` and count.

    A case is {"rule_id", "values": {field: {"value", "unit"}}, "expected"}.
    A case whose rule is not in the family, or whose evaluation raises, is an
    ERROR - a proof never skips what it could not run. PROVEN only with at
    least `min_cases` cases and no error; anything else is NOT_PROVEN with
    the reason."""
    need = settings.rule_proof_min_cases if min_cases is None else min_cases
    by_id = {r.get("id"): r for r in rules}
    errors, correct = [], 0
    for i, case in enumerate(answer_key):
        rule, expected = by_id.get(case.get("rule_id")), case.get("expected")
        try:
            got = _status_of(evaluate_fn(rule, case)) if rule else "no such rule in the family"
        except Exception as exc:   # noqa: BLE001 - an evaluation that fails is recorded as an error, not skipped
            log.info("rule_trust: a rule evaluation failed; recorded as an error (%s)", type(exc).__name__)
            got = f"evaluation failed: {type(exc).__name__}"
        if got == expected:
            correct += 1
        else:
            errors.append({"case": i, "rule_id": case.get("rule_id"), "expected": expected, "got": got})
    cases = len(answer_key)
    if errors:
        status, reason = NOT_PROVEN, f"{len(errors)} of {cases} case(s) wrong"
    elif cases < need:
        status, reason = NOT_PROVEN, f"{cases} case(s); at least {need} are needed"
    else:
        status, reason = PROVEN, f"{cases} of {cases} cases right, none wrong"
    return {"cases": cases, "correct": correct, "errors": errors, "status": status, "reason": reason}


def proof_valid(proof: dict | None, *, model_id: str | None, standard_revision: str | None) -> bool:
    """A proof counts only for the model and the standard revision it was made
    under: a new model or a new edition needs a new proof."""
    return bool(proof) and proof.get("status") == PROVEN \
        and proof.get("model_id") == model_id and proof.get("standard_revision") == standard_revision


# ------------------------------------------------------------ 3. second check

def second_check(rule: dict) -> tuple[bool, str | None]:
    """(passed, why not). The checks an engineer's acceptance runs
    (`ai_requirements.decide_draft`), reused: `verify_proposal` against the
    rule's own sentence, then `requirements_3b.contradicts_source` with the
    RULE's operator. A table rule passes when every number in it is in its
    sentence (`rule_eval.verify_numbers`)."""
    sentence = _sentence(rule)
    if not sentence.strip():
        return False, "the rule has no source sentence"
    if rule.get("rows"):
        return (True, None) if rule_eval.verify_numbers(rule, sentence) \
            else (False, "a number of the rule is not in its sentence")
    value = rule.get("raw_value") if rule.get("raw_value") is not None else rule.get("value")
    _check, why = ai_requirements.verify_proposal(
        {"has_limit": True, "field": rule_field(rule), "operator": rule.get("operator"),
         "value": None if value is None else str(value),
         "unit": rule.get("raw_unit") if rule.get("raw_value") is not None else rule.get("unit"),
         "condition": rule.get("condition"), "quote": rule.get("quote") or sentence}, sentence)
    if why:
        return False, why
    if requirements_3b.contradicts_source(
            {"operator": rule.get("operator"), "raw_value": value}, sentence):
        return False, "the operator points the opposite way to the sentence"
    return True, None


# ------------------------------------------------------------ 4. labels

def ai_compiled(rule: dict) -> bool:
    return rule.get("extraction_method") == AI_COMPILED_METHOD


def trust_label(rule: dict, proof: dict | None) -> str:
    """EVERY RULE IS LABELLED, ONE VOCABULARY (planner answer on #985).
    ENGINEER_CONFIRMED when a person confirmed the row; AUTO_PROVEN only for
    an AI-COMPILED rule whose family proof is PROVEN (already checked current
    by `load_proof`) and which passes `second_check`; UNPROVEN for every other
    rule - a code-extracted row an engineer has not confirmed included, proof
    or not."""
    if rule.get("confirmed_by"):
        return ENGINEER_CONFIRMED
    if ai_compiled(rule) and proof and proof.get("status") == PROVEN and second_check(rule)[0]:
        return AUTO_PROVEN
    return UNPROVEN


def check_label(result: dict) -> str:
    """A datasheet check's label (`datasheet_checks` result), same vocabulary.
    ENGINEER_CONFIRMED only for an item of a COMMITTED checklist an engineer
    signed off (`sign_off.status == "signed"`: not a draft, not the local
    overlay); every other check - a draft or local item, a consistency pair,
    a mandatory field - is UNPROVEN. No family proof applies: none is AI-compiled."""
    if result.get("checklist") and not result.get("draft") and not result.get("local"):
        return ENGINEER_CONFIRMED
    return UNPROVEN


def apply_trust(verdict: dict, label: str) -> dict:
    """An UNPROVEN rule never decides COMPLIANT or NON_COMPLIANT on its own:
    either becomes NEEDS_ENGINEER_REVIEW, the rule's verdict kept as
    `rule_said`. Every verdict comes back carrying its label."""
    out = {**verdict, "trust_label": label, "trust_words": TRUST_WORDS[label]}
    if label == UNPROVEN and verdict.get("status") in (COMPLIANT, NON_COMPLIANT):
        out.update(status=NEEDS_ENGINEER_REVIEW, rule_said=verdict["status"],
                   rationale=f"{verdict.get('rationale') or ''} ({UNPROVEN_REASON})".strip())
    return out


def label_finding(finding: dict, rule: dict, proof: dict | None) -> dict:
    """THE OPT-IN HOOK. Off (`settings.rule_auto_use_enabled` False): the
    finding unchanged. On: labelled, downgraded when UNPROVEN, and a
    COMPLIANT verdict from a SAFETY-tier rule flagged for an engineer's tick."""
    if not settings.rule_auto_use_enabled:
        return finding
    out = apply_trust(finding, trust_label(rule, proof))
    level, why = tier(rule)
    out.update(tier=level, tier_reason=why,
               show_for_engineer_tick=level == SAFETY and out.get("status") == COMPLIANT)
    return out


def label_check(result: dict) -> dict:
    """The opt-in hook for a datasheet check, like `label_finding`: the result
    unchanged with the switch off; on, labelled by `check_label` and held for
    the engineer when UNPROVEN (a check's text is its `detail`). No tick: a
    signed checklist is an engineer's approval already."""
    if not settings.rule_auto_use_enabled:
        return result
    out = apply_trust(result, check_label(result))
    if out.get("rule_said"):
        out["detail"] = f"{result.get('detail') or ''} ({UNPROVEN_REASON})".strip()
    out.update(tier=None, show_for_engineer_tick=False)
    return out


# ------------------------------------------------------------ 5. uncovered

def uncovered_fields(read_fields: list[dict], rules: list[dict]) -> list[dict]:
    """The datasheet fields read WITH a value that no applicable rule
    targets (`same_field`), in reading order, once each. A blank field is not
    listed: it was not read with a value."""
    targets = [t for t in (rule_field(r) for r in rules) if t]
    out, seen = [], set()
    for fact in read_fields:
        name = fact.get("field_name") or fact.get("name")
        value = fact.get("raw_value", fact.get("value"))
        if not name or fact.get("is_blank") or value in (None, "") or name in seen:
            continue
        if not any(same_field(name, t) for t in targets):
            seen.add(name)
            out.append(fact)
    return out


# ------------------------------------------------------------ 6. audit

def audit_rate(rate: float | None = None) -> float:
    """`rate` (default `settings.rule_audit_rate`) clamped to 2-5%."""
    value = settings.rule_audit_rate if rate is None else rate
    return min(max(float(value), AUDIT_RATE_MIN), AUDIT_RATE_MAX)


def audit_sample(finding_ids: list[str], rate: float | None = None, seed: str = "") -> list[str]:
    """A deterministic draw of AUTO_PROVEN findings for an engineer's
    spot-check: ceil(rate x n), at least one when there is any. The same
    ids and seed draw the same findings (order by sha256 of seed and id);
    returned in the order given."""
    ids = list(dict.fromkeys(finding_ids))
    if not ids:
        return []
    n = max(1, math.ceil(len(ids) * audit_rate(rate) - 1e-9))
    drawn = set(sorted(ids, key=lambda i: hashlib.sha256(f"{seed}:{i}".encode()).hexdigest())[:n])
    return [i for i in ids if i in drawn]


# ------------------------------------------------------------ storage

def ensure_schema() -> None:
    from .db import connect

    conn = connect()
    with conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS rule_family_proof (
            family_key TEXT PRIMARY KEY,
            model_id TEXT,
            standard_revision TEXT,
            cases INTEGER NOT NULL,
            errors INTEGER NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            proven_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            invalidated_at TEXT,
            invalid_reason TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS rule_audit_outcome (
            finding_id TEXT NOT NULL,
            family_key TEXT NOT NULL,
            outcome TEXT NOT NULL,
            engineer TEXT,
            note TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (finding_id, family_key))""")


def save_proof(key: str, result: dict, *, model_id: str | None, standard_revision: str | None) -> dict:
    """Store `prove_family`'s result for the family, replacing the last one."""
    from .db import connect

    ensure_schema()
    conn = connect()
    with conn:
        conn.execute("INSERT OR REPLACE INTO rule_family_proof (family_key, model_id,"
                     " standard_revision, cases, errors, status, reason) VALUES (?,?,?,?,?,?,?)",
                     (key, model_id, standard_revision, result["cases"], len(result["errors"]),
                      result["status"], result.get("reason")))
    return load_proof(key, model_id=model_id, standard_revision=standard_revision)


def load_proof(key: str, *, model_id: str | None, standard_revision: str | None) -> dict | None:
    """The family's stored proof, its status INVALID (with why) when it was
    made under another model or standard revision. None: never proven."""
    from .db import connect

    ensure_schema()
    row = connect().execute("SELECT * FROM rule_family_proof WHERE family_key = ?", (key,)).fetchone()
    if row is None:
        return None
    proof = dict(row)
    if proof["status"] == PROVEN and not proof_valid(proof, model_id=model_id,
                                                     standard_revision=standard_revision):
        proof.update(status=INVALID, invalid_reason="made under another model or standard revision; "
                                                     "re-proof required")
    return proof


def record_audit_outcome(finding_id: str, key: str, *, correct: bool, engineer: str | None = None,
                         note: str | None = None) -> dict | None:
    """The engineer's spot-check result. An ERROR invalidates the family's
    proof at once: the family is UNPROVEN until it is proven again."""
    from .db import connect

    ensure_schema()
    conn = connect()
    with conn:
        conn.execute("INSERT OR REPLACE INTO rule_audit_outcome (finding_id, family_key, outcome,"
                     " engineer, note) VALUES (?,?,?,?,?)",
                     (finding_id, key, AUDIT_CORRECT if correct else AUDIT_ERROR, engineer, note))
        if not correct:
            conn.execute("UPDATE rule_family_proof SET status = ?, invalidated_at = CURRENT_TIMESTAMP,"
                         " invalid_reason = ? WHERE family_key = ?",
                         (INVALID, f"audit error on finding {finding_id}", key))
    row = conn.execute("SELECT * FROM rule_family_proof WHERE family_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def review_notes(outcome: dict, findings: list[dict]) -> list[dict]:
    """Steps 7 and 10 on the CRS Review notes sheet (internal), for crs_mapping:
    the datasheet fields no applicable rule checked, and the automatic
    findings drawn for an engineer's spot-check. Nothing on a run made with
    the switch off (it stored no `rule_trust`). Every count names its
    denominator: this run's fields read with a value; this run's findings
    decided by a proven rule."""
    trust = outcome.get("rule_trust") or {}
    if not trust:
        return []
    notes = []
    fields = [str(f) for f in (trust.get("uncovered_fields") or []) if f]
    read = trust.get("fields_read")
    notes.append({
        "note": "Not checked by any rule", "standard": "", "count": len(fields),
        "detail": (f"{len(fields)} of {read} datasheet fields read with a value that no "
                   f"applicable rule targets: {', '.join(fields)}." if fields else
                   f"Every one of the {read} datasheet fields read with a value is targeted "
                   "by an applicable rule.")})
    sample = set(trust.get("audit_sample") or [])
    if sample:
        by_id = {f.get("id"): f for f in findings}
        where = []
        for fid in trust.get("audit_sample") or []:
            f = by_id.get(fid) or {}
            page = f.get("contractor_page")
            field = f.get("contractor_section") or f.get("matched_phrase") or fid
            where.append(f"p.{page} {field}" if page else str(field))
        notes.append({
            "note": "Spot-check automatic findings", "standard": "", "count": len(sample),
            "detail": (f"{len(sample)} of {trust.get('auto_proven')} findings decided by a "
                       f"proven rule, drawn at random for an engineer's check: "
                       f"{'; '.join(where)}. One wrong one drops the family's proof.")})
    return notes


def record_engineer_decision(finding: dict, decision: str, *, actor: str, note: str) -> None:
    """Step 10, for crs_issue: an engineer's decision on a finding a PROVEN
    rule decided is that rule family's spot-check outcome. Accept = correct;
    reject = an audit error, which drops the family to UNPROVEN at once
    (`record_audit_outcome`). Nothing for a finding the run did
    not label as AUTO_PROVEN."""
    if finding.get("trust_label") != AUTO_PROVEN:
        return
    from . import classification

    stored = classification.of_document(finding["document_id"]) or {}
    key = family_key(finding.get("standard_document_id") or "", stored.get("equipment_type"))
    record_audit_outcome(finding["id"], key, correct=decision == "accept",
                         engineer=actor, note=note)
