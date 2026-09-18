"""Phase 5B: does this submittal meet the requirements that govern it.

SECTION 14 IS THE SHAPE OF THIS FILE. Python decides; the model describes.

    DETERMINISTIC, HERE, NEVER THE MODEL
        numeric comparison, unit conversion, required-field presence,
        threshold evaluation, review-code policy, citation existence.

    THE MODEL, AND ONLY THIS
        interpreting technical wording, matching a field label to a
        requirement, reading a condition in prose, drafting the
        contractor-facing comment, explaining its reasoning.

When the two disagree, THE DETERMINISTIC RESULT WINS and the disagreement is
recorded on the finding. `_reconcile` is the one place that happens, written as
its own function so removing it is visible rather than an edited condition.

THE THREE THINGS THIS ENGINE REFUSES TO DO

1. TURN AN ABSENCE INTO A FAILURE. A blank "By Contractor" field means the
   vendor has not been asked yet. It is MISSING_INFORMATION. Manufacturing a
   finding against a vendor who was never asked is the worst output this
   product could produce, and phase 4 already detects those blanks correctly -
   this file's job is not to undo that.

2. STATE A FINDING WITHOUT BOTH CITATIONS. The contractor side and the
   standard side must each resolve to a real chunk and page. Anything that
   fails becomes NEEDS_ENGINEER_REVIEW - never dropped, never guessed into a
   status.

3. LET A GENERAL LIMIT OVERRIDE ITS OWN EXCEPTION. A standard capping
   equipment at 90 dB(A) with an exception allowing relief valves 115 dB(A)
   does not make a 108 dB(A) valve non-compliant. 3B stored the exceptions;
   `_applicable_exception` applies them, and an engine that skipped it would
   report a false breach against a compliant valve.

COMPLETENESS GATES THE CODE. A review that examined nine fields and returns
"Approved with Comments" is making a claim about the two hundred and forty
nobody looked at. Below the threshold the recommendation is Manual Review
Required regardless of how few breaches were found, and the figure is always
reported with its denominator.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import claims, datasheets, submittal_review
from .db import connect

# ----------------------------------------------------------------- statuses

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
MISSING_INFORMATION = "MISSING_INFORMATION"
CONDITIONAL = "CONDITIONAL"
NOT_APPLICABLE = "NOT_APPLICABLE"
NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"

#: Statuses that block approval. `MISSING_INFORMATION` is deliberately NOT
#: here: a field nobody filled in is a question, not a failure, and it steers
#: the code through completeness rather than by masquerading as a breach.
BLOCKING = frozenset({NON_COMPLIANT})

# -------------------------------------------------------------- review codes
#
# CONFIGURABLE, because the client may use different names or numbers
# (section 15). The DEFAULT set is here and the policy that maps findings to a
# code is `recommend_code`, which is deterministic and never the model's.

CODE_APPROVED = "Approved"
CODE_APPROVED_WITH_COMMENTS = "Approved with Comments"
CODE_REJECTED = "Rejected / Revise and Resubmit"
CODE_MANUAL = "Manual Review Required"

DEFAULT_CODES = (
    CODE_APPROVED, CODE_APPROVED_WITH_COMMENTS, CODE_REJECTED, CODE_MANUAL)

#: Below this, the recommendation is Manual Review Required whatever else was
#: found. Section 15 scopes that code to "insufficient confidence"; insufficient
#: EXTRACTION belongs in the same bucket, because a review that could not read
#: the submittal has not established anything about it.
#:
#: 0.6 is a threshold on a heuristic and is named here so it has one home. It
#: is deliberately above phase 4's measured 0.43 on the real pump datasheet:
#: that review would be gated, and it should be.
COMPLETENESS_THRESHOLD = 0.6

#: Confidence ceilings. NEVER "high" (CLAUDE.md rule 4). A deterministic
#: numeric comparison is the strongest thing here and still stops at 0.9,
#: because the comparison is only as good as the extraction that fed it.
CONFIDENCE_DETERMINISTIC = 0.9
CONFIDENCE_MODEL_ASSISTED = 0.5
CONFIDENCE_UNRESOLVED = 0.3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _scope_clause(allowed_document_ids: frozenset[str], column: str) -> tuple[str, list[str]]:
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE {column} IN ({marks})", sorted(allowed_document_ids)


class ComparisonError(ValueError):
    """A finding could not be created. Carries a reason, never a row."""


# ------------------------------------------------------- deterministic core

def _measurement_from_requirement(requirement: dict) -> claims.Measurement | None:
    """The requirement's limit as a `claims.Measurement`, or None.

    None means there is no numeric limit to compare against - a `statement`
    requirement, or one whose value never parsed. That is not a failure of the
    submittal and must not be reported as one.
    """
    raw_value = requirement.get("raw_value")
    if raw_value is None:
        return None
    return claims.normalise(
        str(raw_value), requirement.get("raw_unit") or "",
        requirement.get("operator"))


def _measurement_from_fact(fact: dict) -> claims.Measurement | None:
    """The submitted value as a `claims.Measurement`, or None.

    A BLANK FACT YIELDS NONE AND IS HANDLED BEFORE THIS IS REACHED. Phase 4
    records a blank with `raw_value` NULL and `is_blank` 1, so a blank cannot
    accidentally arrive here as a zero.
    """
    if fact.get("is_blank"):
        return None
    raw_value = fact.get("raw_value")
    if raw_value is None:
        return None
    return claims.normalise(str(raw_value), fact.get("raw_unit") or "")


def _applicable_exception(requirement: dict, subject: str | None) -> dict | None:
    """The exception that governs this subject instead of the general limit.

    THE WORKED CASE. A standard caps equipment at 90 dB(A) "except for pressure
    relief valves, which shall not exceed 115 dB(A)". For a PSV the exception's
    115 is the limit, and the general 90 does not apply. An engine that skipped
    this reports a false breach against a compliant valve - the exact failure
    3B stored exceptions to prevent.

    Matched on the SUBJECT the submittal is about (its equipment type), against
    the exception's `applies_to` text, both folded to lowercase words. A
    conservative containment match: "pressure relief valve" matches "pressure
    relief valves", and nothing matches when the subject is unknown. An
    exception applied too eagerly EXCUSES a real breach, which is the more
    dangerous direction, so an unknown subject gets the general limit.
    """
    if not subject:
        return None
    exceptions = requirement.get("exceptions")
    if isinstance(exceptions, str):
        try:
            exceptions = json.loads(exceptions or "[]")
        except (TypeError, ValueError):
            exceptions = []
    if not exceptions:
        return None
    wanted = " ".join(str(subject).lower().split())
    for exception in exceptions:
        applies_to = " ".join(str(exception.get("applies_to") or "").lower().split())
        if not applies_to:
            continue
        # Singular/plural tolerance without a stemmer: compare on the stem of
        # each word, which is enough for "valve"/"valves" and refuses to be
        # clever beyond that.
        a = {w.rstrip("s") for w in wanted.split()}
        b = {w.rstrip("s") for w in applies_to.split()}
        if a and (a <= b or b <= a):
            return exception
    return None


def compare(requirement: dict, fact: dict | None, *,
            subject: str | None = None) -> dict:
    """The DETERMINISTIC verdict for one requirement against one fact.

    Returns `{status, rationale, limit, observed, exception_applied}`. No model
    is called and none can be: this function is the reason a numeric breach is
    reproducible.

    The order of the checks is the policy, and each one refuses to fall through
    into a stronger claim than the evidence supports:

      1. no fact at all           -> MISSING_INFORMATION (never a failure)
      2. the fact is blank        -> MISSING_INFORMATION (never a failure)
      3. no numeric limit         -> NEEDS_ENGINEER_REVIEW (a human reads it)
      4. units cannot be compared -> NEEDS_ENGINEER_REVIEW (never a guess)
      5. the numbers compare      -> COMPLIANT or NON_COMPLIANT
    """
    if fact is None:
        return {
            "status": MISSING_INFORMATION,
            "rationale": "the submittal states no value for this requirement",
            "limit": None, "observed": None, "exception_applied": None,
        }
    if fact.get("is_blank"):
        marker = fact.get("blank_marker") or "blank"
        return {
            # NOT NON_COMPLIANT. The sheet says whose job it is, not that the
            # equipment fails anything.
            "status": MISSING_INFORMATION,
            "rationale": f"the submittal leaves this field to be provided ({marker})",
            "limit": None, "observed": None, "exception_applied": None,
        }

    exception = _applicable_exception(requirement, subject)
    governing = dict(requirement)
    if exception is not None:
        # The exception REPLACES the limit for this subject.
        governing.update({
            "operator": exception.get("operator") or requirement.get("operator"),
            "raw_value": exception.get("raw_value"),
            "raw_unit": exception.get("raw_unit") or requirement.get("raw_unit"),
        })

    limit = _measurement_from_requirement(governing)
    observed = _measurement_from_fact(fact)

    if limit is None:
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": "the requirement states no numeric limit this engine "
                         "can evaluate; it needs a human reading",
            "limit": None, "observed": _describe(observed, fact),
            "exception_applied": exception,
        }
    if observed is None:
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": "the submitted value could not be read as a quantity",
            "limit": _describe(limit, governing), "observed": None,
            "exception_applied": exception,
        }

    # UNITS MUST BE COMPARABLE, AND AN UNKNOWN UNIT IS NOT A GUESS. `claims`
    # owns this: it converts within a dimension, compares directly when both
    # sides carry the identical spelling, and returns None when it cannot do
    # either. None means NO COMPARISON WAS MADE, which is a result.
    verdict = claims._compatible(observed, limit)
    if verdict is None:
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": (
                f"the submitted unit {fact.get('raw_unit')!r} and the required "
                f"unit {governing.get('raw_unit')!r} cannot be compared by this "
                "system; no conversion is guessed"),
            "limit": _describe(limit, governing),
            "observed": _describe(observed, fact),
            "exception_applied": exception,
        }

    status = COMPLIANT if verdict else NON_COMPLIANT
    within = "within" if verdict else "outside"
    note = ""
    if exception is not None:
        note = (f"; the exception for {exception.get('applies_to')!r} governs "
                f"instead of the general limit")
    return {
        "status": status,
        "rationale": (
            f"the submitted value {fact.get('raw_value')} "
            f"{fact.get('raw_unit') or ''}".rstrip() +
            f" is {within} the required "
            f"{governing.get('operator') or ''} {governing.get('raw_value')} "
            f"{governing.get('raw_unit') or ''}".rstrip() + note),
        "limit": _describe(limit, governing),
        "observed": _describe(observed, fact),
        "exception_applied": exception,
    }


def _describe(measurement: claims.Measurement | None, source: dict) -> dict | None:
    """A measurement as stored: raw exactly as written, normalised or None.

    The raw pair is always present so a reader sees the document's own words;
    the normalised pair is None when the unit is unknown, NEVER 0.
    """
    if measurement is None:
        return None
    return {
        "raw_value": source.get("raw_value"),
        "raw_unit": source.get("raw_unit"),
        "normalized_value": measurement.normalized_value,
        "normalized_unit": measurement.normalized_unit,
    }


def _reconcile(deterministic: str, model_opinion: str | None) -> tuple[str, str | None]:
    """`(status, disagreement)`. THE DETERMINISTIC RESULT ALWAYS WINS.

    Section 14's hard line, in one function so that removing it is a visible
    act. The model may be better at reading a clause; it is not better at
    deciding whether 108 is under 115, and a system that let it overrule
    arithmetic would be unable to say why any number came out as it did.

    A disagreement is RECORDED rather than discarded: it is the signal that
    either the extraction or the clause reading is wrong, and a reviewer wants
    to see it.
    """
    if not model_opinion or model_opinion == deterministic:
        return deterministic, None
    return deterministic, (
        f"the model proposed {model_opinion} and the deterministic comparison "
        f"returned {deterministic}; the deterministic result stands")


# -------------------------------------------------------- citation validation

def _citation_resolves(chunk_id: str | None, document_id: str | None,
                       page: int | None) -> bool:
    """True when this citation opens a real passage of the right document.

    The same three checks `standards.create_requirement` and
    `datasheets.create_fact` make. A citation that opens the WRONG document is
    worse than one that opens nothing, because a reader who follows it sees
    something real and believes it.
    """
    if not chunk_id:
        return False
    row = connect().execute(
        "SELECT document_id, page_start, page_end FROM chunks WHERE id = ?",
        (chunk_id,)).fetchone()
    if row is None:
        return False
    if document_id and row["document_id"] != document_id:
        return False
    if page is not None and not (row["page_start"] <= page <= row["page_end"]):
        return False
    return True


def create_finding(
    *, review_run_id: str, submittal_document_id: str, requirement: dict,
    fact: dict | None, verdict: dict, comment: str | None = None,
    model_opinion: str | None = None, severity: str = "major",
    category: str = "requirement_deviation",
) -> dict:
    """Write one finding. REFUSES anything it cannot support.

    A finding is a claim about a contractor's work. It is not written unless
    BOTH citations resolve - the contractor's page and the standard's clause -
    and a finding that fails that is DOWNGRADED to NEEDS_ENGINEER_REVIEW with
    the reason recorded, never dropped and never guessed into a status
    (section 12).

    `ai_rationale` is stored SEPARATELY from `finding`, so a reader can see why
    the system said what it said rather than only what it concluded.
    """
    submittal_review.ensure_schema()
    status, disagreement = _reconcile(verdict["status"], model_opinion)

    standard_ok = _citation_resolves(
        requirement.get("chunk_id"), requirement.get("standard_document_id"),
        requirement.get("page"))
    contractor_ok = fact is None or _citation_resolves(
        fact.get("chunk_id"), submittal_document_id, fact.get("page"))

    unresolved: list[str] = []
    if not standard_ok:
        unresolved.append("the standard citation does not resolve")
    if not contractor_ok:
        unresolved.append("the contractor citation does not resolve")

    # A MISSING_INFORMATION finding has no contractor value by definition, so
    # the absence of a contractor citation is not a defect there - what must
    # still resolve is the requirement being asked about.
    if status == MISSING_INFORMATION and standard_ok and fact is None:
        unresolved = [u for u in unresolved
                      if "contractor citation" not in u]

    if unresolved:
        status = NEEDS_ENGINEER_REVIEW
        confidence = CONFIDENCE_UNRESOLVED
    elif model_opinion:
        confidence = CONFIDENCE_MODEL_ASSISTED
    else:
        confidence = CONFIDENCE_DETERMINISTIC

    now = _now()
    finding_id = str(uuid.uuid4())
    rationale = verdict.get("rationale") or ""
    if disagreement:
        rationale = f"{rationale}. {disagreement}"
    if unresolved:
        rationale = f"{rationale}. " + "; ".join(unresolved)

    row = {
        "id": finding_id,
        "document_id": submittal_document_id,
        "review_run_id": review_run_id,
        "compliance_status": status,
        "category": category,
        "severity": severity,
        "requirement": requirement.get("requirement_text") or "",
        "finding": comment or rationale,
        "required_action": _required_action(status),
        "confidence": _confidence_label(confidence),
        "contractor_page": (fact or {}).get("page"),
        "contractor_section": (fact or {}).get("section"),
        "contractor_evidence_text": (fact or {}).get("field_value"),
        "standard_document_id": requirement.get("standard_document_id"),
        "standard_clause": requirement.get("clause"),
        "standard_page": requirement.get("page"),
        "requirement_source_text": requirement.get("source_text"),
        "ai_rationale": rationale,
        "unresolved_evidence": json.dumps(unresolved),
        "created_at": now,
        "updated_at": now,
    }
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO review_findings
               (id, document_id, review_run_id, compliance_status, category,
                severity, requirement, finding, required_action, confidence,
                contractor_page, contractor_section, contractor_evidence_text,
                standard_document_id, standard_clause, standard_page,
                requirement_source_text, ai_rationale, unresolved_evidence,
                governing_sources, citation_ids, status, approval_status,
                created_at, updated_at)
               VALUES (:id, :document_id, :review_run_id, :compliance_status,
                       :category, :severity, :requirement, :finding,
                       :required_action, :confidence, :contractor_page,
                       :contractor_section, :contractor_evidence_text,
                       :standard_document_id, :standard_clause, :standard_page,
                       :requirement_source_text, :ai_rationale,
                       :unresolved_evidence, '[]', '[]', 'open', 'pending',
                       :created_at, :updated_at)""", row)
    return {**row, "unresolved_evidence": unresolved,
            "citation_resolves": not unresolved}


def _required_action(status: str) -> str:
    return {
        COMPLIANT: "None. The requirement is met.",
        NON_COMPLIANT: "Revise the submittal to meet the stated requirement.",
        MISSING_INFORMATION: "Provide the missing value.",
        CONDITIONAL: "Confirm the condition under which this requirement holds.",
        NOT_APPLICABLE: "None. The requirement does not govern this submittal.",
        NEEDS_ENGINEER_REVIEW: "An engineer must review this manually.",
    }.get(status, "An engineer must review this manually.")


def _confidence_label(value: float) -> str:
    """CLAUDE.md rule 4: confidence is NEVER "high".

    The vocabulary stops at medium on purpose. A system that says "high
    confidence" invites a reader to stop checking, and nothing this engine
    does - extraction, clause reading, unit handling - earns that.
    """
    return "medium" if value >= CONFIDENCE_MODEL_ASSISTED else "low"


# ---------------------------------------------------- completeness and codes


def completeness_for_run(
    submittal_document_id: str, *, allowed_document_ids: frozenset[str],
    reference_coverage: float | None = None,
) -> dict:
    """How much of this submittal the review actually examined.

    REPORTED WITH ITS DENOMINATOR, ALWAYS. "checked 9 of ~250 fields" is a
    statement a reader can act on; "extraction coverage 0.43" invites them to
    read it as a score. Both are returned and the caller is expected to show
    the counts.

    `fields_total` is an ESTIMATE and is labelled one: it is the number of
    label-value slots phase 4's pairing could see, which is itself a lower
    bound on what the sheet contains. An estimate is the honest shape here -
    nobody has counted the real total, and pretending to would be worse than
    saying approximately.
    """
    facts = datasheets.list_facts(
        submittal_document_id, allowed_document_ids=allowed_document_ids)
    row = connect().execute(
        "SELECT page_count FROM documents WHERE id = ?",
        (submittal_document_id,)).fetchone()
    pages = (row["page_count"] if row else None) or 0

    fields_read = len(facts)
    # A datasheet page carries on the order of this many label-value slots.
    # Measured roughly against the real KOC sheets rather than assumed, and
    # used ONLY to give the reader a denominator - never to compute a pass.
    fields_estimated = pages * 35 if pages else None
    extraction = (
        round(min(fields_read / fields_estimated, 1.0), 3)
        if fields_estimated else None)

    parts = [p for p in (extraction, reference_coverage) if p is not None]
    overall = round(min(parts), 3) if parts else None
    return {
        "fields_read": fields_read,
        "fields_estimated": fields_estimated,
        "pages": pages,
        "extraction_coverage": extraction,
        "reference_coverage": reference_coverage,
        # THE WEAKEST LINK, not the average. A review with every standard
        # present but a tenth of the datasheet read is a tenth of a review, and
        # an average would let the good number carry the bad one.
        "completeness": overall,
        "sufficient": bool(overall is not None and overall >= COMPLETENESS_THRESHOLD),
    }


def recommend_code(findings: list[dict], completeness: dict, *,
                   codes: tuple[str, ...] = DEFAULT_CODES) -> dict:
    """The AI-RECOMMENDED review code. Deterministic policy, never the model.

    THE COMPLETENESS GATE COMES FIRST AND OVERRIDES EVERYTHING. A review that
    examined nine fields and returns "Approved with Comments" is making a claim
    about the two hundred and forty nobody looked at - and the code is exactly
    what a reader takes as that claim. Section 15 scopes Manual Review Required
    to "insufficient confidence"; insufficient extraction is the same thing
    wearing different clothes.

    `codes` is a parameter because the client may use different names or
    numbers (section 15). The POLICY is fixed; the labels are not.
    """
    approved, with_comments, rejected, manual = codes
    statuses = [f.get("compliance_status") for f in findings]

    blocking = [s for s in statuses if s in BLOCKING]
    unresolved = [s for s in statuses if s == NEEDS_ENGINEER_REVIEW]
    missing = [s for s in statuses if s == MISSING_INFORMATION]

    if not completeness.get("sufficient"):
        return {
            "code": manual,
            "reason": _insufficient_reason(completeness),
            "blocking": len(blocking), "unresolved": len(unresolved),
            "missing_information": len(missing),
        }
    if unresolved:
        return {
            "code": manual,
            "reason": f"{len(unresolved)} requirement(s) could not be evaluated "
                      "and need an engineer",
            "blocking": len(blocking), "unresolved": len(unresolved),
            "missing_information": len(missing),
        }
    if blocking:
        return {
            "code": rejected,
            "reason": f"{len(blocking)} requirement(s) are not met",
            "blocking": len(blocking), "unresolved": 0,
            "missing_information": len(missing),
        }
    if missing:
        return {
            # MISSING INFORMATION IS NOT A FAILURE, so it does not reject. It
            # is also not nothing, so it does not approve silently.
            "code": with_comments,
            "reason": f"{len(missing)} field(s) are left for the contractor to "
                      "provide; no requirement was found unmet",
            "blocking": 0, "unresolved": 0, "missing_information": len(missing),
        }
    return {
        "code": approved,
        "reason": "every evaluated requirement is met",
        "blocking": 0, "unresolved": 0, "missing_information": 0,
    }


def _insufficient_reason(completeness: dict) -> str:
    """Why the review was gated, WITH THE COUNTS."""
    read = completeness.get("fields_read")
    total = completeness.get("fields_estimated")
    if total:
        return (f"the review examined {read} of approximately {total} fields; "
                "that is not enough of the submittal to recommend a code")
    return ("the submittal could not be read well enough to recommend a code")


def run_comparison(
    review_run_id: str, *, allowed_document_ids: frozenset[str],
    subject: str | None = None, reference_coverage: float | None = None,
    model_opinions: dict | None = None, replace: bool = True,
) -> dict:
    """Evaluate every applicable requirement against the submittal's facts.

    One finding per requirement. The verdict is deterministic; `model_opinions`
    - if a caller supplies any - may only DESCRIBE, and `_reconcile` discards
    any that disagree with the arithmetic while recording that they did.

    Scoped throughout: the run's submittal must be readable, and requirements
    come only from standards the caller may read.
    """
    submittal_review.ensure_schema()
    run = submittal_review.get_review_run(
        review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        raise ComparisonError("no review run with that id")
    submittal_id = run["submittal_document_id"]

    if replace:
        conn = connect()
        with conn:
            conn.execute(
                "DELETE FROM review_findings WHERE review_run_id = ?",
                (review_run_id,))

    applicable = submittal_review.list_applicable_standards(
        review_run_id, allowed_document_ids=allowed_document_ids,
        include_excluded=False)
    standard_ids = [a["standard_document_id"] for a in applicable]

    requirements: list[dict] = []
    for standard_id in standard_ids:
        from . import standards as standards_mod
        requirements.extend(standards_mod.list_requirements(
            standard_id, allowed_document_ids=allowed_document_ids))

    facts = datasheets.list_facts(
        submittal_id, allowed_document_ids=allowed_document_ids)
    by_field = {}
    for fact in facts:
        by_field.setdefault(fact.get("field_name") or "", fact)

    findings: list[dict] = []
    for requirement in requirements:
        fact = _match_fact(requirement, by_field)
        verdict = compare(requirement, fact, subject=subject)
        opinion = (model_opinions or {}).get(requirement.get("id"))
        findings.append(create_finding(
            review_run_id=review_run_id, submittal_document_id=submittal_id,
            requirement=requirement, fact=fact, verdict=verdict,
            model_opinion=opinion))

    coverage = completeness_for_run(
        submittal_id, allowed_document_ids=allowed_document_ids,
        reference_coverage=reference_coverage)
    recommendation = recommend_code(findings, coverage)
    _store_run_outcome(review_run_id, recommendation, coverage)

    return {
        "review_run_id": review_run_id,
        "submittal_document_id": submittal_id,
        "requirements_evaluated": len(requirements),
        "findings": findings,
        "by_status": {
            status: sum(1 for f in findings if f["compliance_status"] == status)
            for status in (COMPLIANT, NON_COMPLIANT, MISSING_INFORMATION,
                           CONDITIONAL, NOT_APPLICABLE, NEEDS_ENGINEER_REVIEW)
        },
        "completeness": coverage,
        "recommended_code": recommendation,
    }


def _match_fact(requirement: dict, by_field: dict) -> dict | None:
    """The submitted fact this requirement is about, or None.

    Matched on the NORMALISED field name, which `datasheets` already computes.
    An unmatched requirement yields None and becomes MISSING_INFORMATION -
    never a failure, because "this system could not find the field" and "the
    contractor got it wrong" are different statements.

    THIS IS WHERE THE MODEL WOULD EARN ITS PLACE. Matching a free-text
    requirement to a datasheet label is exactly the interpretive work section
    14 assigns to it. This phase does the deterministic half - exact normalised
    match - and reports the rest as unmatched rather than guessing, which is
    why the missing-information count is high on a real sheet.
    """
    field = (requirement.get("field") or "").strip().lower()
    if field and field in by_field:
        return by_field[field]
    return None


def _store_run_outcome(review_run_id: str, recommendation: dict,
                       coverage: dict) -> None:
    """Persist the AI recommendation and the completeness it was gated on.

    The FINAL code is not written here. The AI recommends; the engineer
    decides, and `record_engineer_code` is where that happens - section 15's
    "the engineer's final action is governance, not the initial review".
    """
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE review_runs SET status = ?, refusal_reason = ?,"
            " updated_at = ? WHERE id = ?",
            ("completed", json.dumps({
                "recommended_code": recommendation["code"],
                "reason": recommendation["reason"],
                "completeness": coverage,
            }), _now(), review_run_id))


def record_engineer_code(
    review_run_id: str, *, code: str, reviewer: str | None,
    override_reason: str | None = None,
    allowed_document_ids: frozenset[str], actor: dict | None = None,
) -> dict:
    """The engineer's FINAL code. Audited, and a reason is required to override.

    Section 15: store the AI-recommended code, the final engineer code, the
    override reason, the reviewer and the timestamp. The AI recommends and the
    engineer decides - so a final code that DIFFERS from the recommendation
    needs a reason, and one that agrees does not.
    """
    submittal_review.ensure_schema()
    run = submittal_review.get_review_run(
        review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        raise ComparisonError("no review run with that id")
    try:
        stored = json.loads(run.get("refusal_reason") or "{}")
    except (TypeError, ValueError):
        stored = {}
    recommended = stored.get("recommended_code")
    if recommended and code != recommended and not (override_reason or "").strip():
        raise ComparisonError(
            "overriding the recommended code requires a reason")

    outcome = {
        **stored,
        "final_code": code,
        "reviewer": reviewer,
        "override_reason": (override_reason or "").strip() or None,
        "decided_at": _now(),
    }
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE review_runs SET refusal_reason = ?, updated_at = ?"
            " WHERE id = ?", (json.dumps(outcome), _now(), review_run_id))
    _audit("review.code_recorded", actor, review_run_id,
           detail=f"recommended={recommended} final={code} "
                  f"overridden={bool(outcome['override_reason'])}")
    return outcome


def run_outcome(review_run_id: str, *,
                allowed_document_ids: frozenset[str]) -> dict | None:
    """The stored recommendation and decision for a run, under the caller's
    grants."""
    run = submittal_review.get_review_run(
        review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        return None
    try:
        return json.loads(run.get("refusal_reason") or "{}")
    except (TypeError, ValueError):
        return {}


def list_findings(review_run_id: str, *,
                  allowed_document_ids: frozenset[str]) -> list[dict]:
    """This run's findings, under the caller's grants.

    Delegates to `submittal_review.list_run_findings`, which already checks the
    run's submittal is readable before returning anything.
    """
    return submittal_review.list_run_findings(
        review_run_id, allowed_document_ids=allowed_document_ids)


def _audit(action: str, actor: dict | None, resource_id: str | None,
           detail: str | None = None) -> None:
    """Durable record of a review decision. Ids and codes only."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO audit_events
                       (at, actor_user_id, actor_username, action,
                        resource_type, resource_id, outcome, detail)
                   VALUES (?, ?, ?, ?, 'review', ?, 'ok', ?)""",
                (_now(), (actor or {}).get("id"),
                 ((actor or {}).get("email") or "unauthenticated")[:200],
                 action, resource_id, detail))
    except Exception:  # noqa: BLE001 - an unwritable audit must not block it
        pass
