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

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from . import claims, datasheets, requirements_3b, schemas, submittal_review
from .config import settings
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

#: Label-value slots a datasheet page is ASSUMED to carry.
#:
#: A NOMINAL FIGURE, NOT A MEASUREMENT OF ANY PARTICULAR DOCUMENT. It came from
#: eyeballing other datasheets, and every denominator built on it - "42 of 385"
#: - is therefore an estimate of an estimate. It exists so a coverage figure is
#: never shown without SOMETHING to divide by, because a bare percentage with
#: no denominator is the thing this project refuses to print.
#:
#: It must never be used to compute a pass, and `_insufficient_reason` states
#: in words that the denominator is nominal so a reader cannot mistake it for a
#: count of the sheet in front of them.
FIELDS_PER_PAGE_NOMINAL = 35

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


def fact_has_number(fact: dict) -> bool:
    """Does this fact carry a number a matcher could pair a limit with?

    A RANGE COUNTS. Its `raw_value` is NULL - there is no single value - and
    a matcher testing that column alone skipped every range, so the ambient
    band and the design/operating pair could never be paired and `compare`
    could never reach the code that reads them.
    """
    return (fact.get("raw_value") not in (None, "")
            or fact_range(fact) is not None)


def fact_range(fact: dict) -> tuple[float, float] | None:
    """`(min, max)` when the submitted value is a range, else None."""
    low, high = fact.get("value_min"), fact.get("value_max")
    if low is None or high is None:
        return None
    return float(low), float(high)


def _range_side(operator: str | None) -> str | None:
    """Which end of a range the rule is asking about.

    DETERMINISTIC AND CONSERVATIVE, AND IT NEVER AVERAGES. A range is two
    numbers the document actually states; the mean of them is a number it
    does not, and comparing that mean would answer a question nobody asked
    with a figure nobody wrote.

    An upper limit - "shall not exceed 55 C" - is about the TOP of the band,
    because that is where the range would breach it. A lower limit - "shall be
    at least -10 C" - is about the BOTTOM, for the same reason. Each is the
    worst case for the rule at hand, which is the only safe reading of a
    value that spans.

    An EXACT-EQUALITY rule has no such side. "shall be 50 C" against "-3 to
    55 C" is a question for a person: the band contains the value and is not
    equal to it, and neither COMPLIANT nor NON_COMPLIANT is true.
    """
    if operator in ("<=", "<"):
        return "max"
    if operator in (">=", ">"):
        return "min"
    return None


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
    # BEFORE ANY OTHER BRANCH, INCLUDING THE ABSENT-FACT ONE. A table row is
    # not a limit whether or not a value was submitted against it, and a
    # reviewer needs to see the row rather than a verdict about it.
    # ONLY WHEN A VALUE WAS ACTUALLY MATCHED AGAINST IT. A table row nobody
    # submitted anything against is an unmatched requirement like any other,
    # and MISSING_INFORMATION is the true description of it. Raising every one
    # to NEEDS_ENGINEER_REVIEW would fill a reviewer's queue with rows carrying
    # nothing to act on, and bury the few that do.
    #
    # The one an engineer CAN act on is a table row with a submitted value
    # beside it: the pairing is real, the comparison is not safe to make, and
    # the row is what they need to see.
    if requirement.get("requirement_type") == requirements_3b.TABLE_ROW \
            and fact is not None and not fact.get("is_blank"):
        fragment = " ".join(
            (requirement.get("source_text")
             or requirement.get("requirement_text") or "").split())
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": (
                f"{TABLE_ROW_REASON}: this requirement's number belongs to a "
                f"lookup table, not to a limit, so no comparison was made. "
                f"The row reads: {fragment}"),
            "limit": None, "observed": _describe(_measurement_from_fact(fact), fact)
            if fact else None,
            "exception_applied": None,
        }
    # A MARGIN IS NOT A VALUE, and the thing it is a margin from is not on the
    # datasheet. "at least 28°C warmer than the calculated dew point" compared
    # against an internal design temperature of 95°C returned COMPLIANT in the
    # model tier's evaluation - arithmetic on a number that is not a
    # temperature at all. Same placement as the table row, and for the same
    # reason: the sentence is what the engineer needs, not a verdict about it.
    if requirement.get("requirement_type") == requirements_3b.RELATIVE_LIMIT \
            and fact is not None and not fact.get("is_blank"):
        fragment = " ".join(
            (requirement.get("source_text")
             or requirement.get("requirement_text") or "").split())
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": (
                f"{RELATIVE_LIMIT_REASON}: this requirement states a "
                f"DIFFERENCE from another quantity, not a value, so it was "
                f"not compared against the submitted number. "
                f"The requirement reads: {fragment}"),
            "limit": None,
            "observed": _describe(_measurement_from_fact(fact), fact),
            "exception_applied": None,
        }
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

    # A RANGE IS COMPARED AT THE END THE RULE ASKS ABOUT, never at its mean.
    spread = fact_range(fact)
    if spread is not None:
        side = _range_side(governing.get("operator"))
        if side is None:
            quoted = " ".join((fact.get("field_value") or "").split())
            return {
                "status": NEEDS_ENGINEER_REVIEW,
                "rationale": (
                    f"{RANGE_VS_EQUALITY}: the submitted value is a range and "
                    f"the requirement asks for one exact value, so no "
                    f"comparison was made. The submittal states: {quoted}"),
                "limit": _describe(limit, governing), "observed": None,
                "exception_applied": exception,
            }
        chosen = spread[1] if side == "max" else spread[0]
        observed = claims.normalise(
            _plain(chosen), fact.get("raw_unit") or fact.get("unit") or "")
        # THE FINDING MUST NAME THE NUMBER THAT WAS COMPARED, and say that it
        # came from a range. "the submitted value 55 C" over a sheet reading
        # "-3 to 55 C" is a half-truth a reviewer cannot check.
        fact = {**fact, "raw_value": _plain(chosen),
                "compared_end": side,
                "compared_from": " ".join(
                    (fact.get("field_value") or "").split())}

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
    if fact.get("compared_end"):
        end = "highest" if fact["compared_end"] == "max" else "lowest"
        note = (f"; compared at the {end} of the submitted range "
                f"{fact['compared_from']}") + note
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


def _plain(number: float) -> str:
    """`55.0` as `55`, because that is what the document wrote."""
    return str(int(number)) if float(number).is_integer() else str(number)


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
    matched_phrase: str | None = None, match_method: str | None = None,
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
    elif model_opinion or match_method == METHOD_MODEL_CHOICE:
        # A MODEL CHOSE THE PAIRING, so the finding is only as good as that
        # choice however deterministic the arithmetic on top of it was. 0.5,
        # label "medium", never "high" (CLAUDE.md rule 4).
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
        # The pairing, recorded on the finding. `field` on
        # `standard_requirements` stays NULL and nothing here writes it - the
        # match is a property of THIS comparison, not of the requirement.
        "requirement_id": requirement.get("id"),
        "fact_id": (fact or {}).get("id"),
        "matched_phrase": matched_phrase,
        "match_method": match_method,
        # WHICH EQUIPMENT THE FINDING IS ABOUT, copied from the fact rather
        # than re-derived: the fact is what was actually compared, and a
        # finding naming a different valve from the value it quotes would be
        # worse than one naming none. NULL where the sheet does not say.
        "equipment_tag": (fact or {}).get("equipment_tag"),
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
                requirement_id, fact_id, matched_phrase, match_method,
                equipment_tag,
                governing_sources, citation_ids, status, approval_status,
                created_at, updated_at)
               VALUES (:id, :document_id, :review_run_id, :compliance_status,
                       :category, :severity, :requirement, :finding,
                       :required_action, :confidence, :contractor_page,
                       :contractor_section, :contractor_evidence_text,
                       :standard_document_id, :standard_clause, :standard_page,
                       :requirement_source_text, :ai_rationale,
                       :unresolved_evidence, :requirement_id, :fact_id,
                       :matched_phrase, :match_method, :equipment_tag,
                       '[]', '[]', 'open', 'pending',
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
    fields_estimated = pages * FIELDS_PER_PAGE_NOMINAL if pages else None
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
        pages = completeness.get("pages")
        # THE DENOMINATOR SAYS WHERE IT COMES FROM. "approximately 385 fields"
        # reads like somebody counted the sheet. Nobody did: it is the page
        # count times a nominal 35 slots per page, a figure taken from OTHER
        # datasheets entirely. A reader who thinks 385 was measured here will
        # also think 42/385 means something about this document's coverage.
        return (f"the review examined {read} fields; the denominator is a "
                f"NOMINAL ESTIMATE of {total} ({pages} pages x "
                f"{FIELDS_PER_PAGE_NOMINAL} fields per page, not a count of "
                f"this document), and that is not enough of the submittal to "
                f"recommend a code")
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

    # AN ENGINEER'S DECISION IS NOT OVERWRITTEN BY A RE-RUN.
    #
    # `replace=True` deletes this run's unconfirmed findings and writes new
    # ones, which is how every fix reaches the corpus - but a run somebody has
    # signed a final code against is a DECISION, and re-running it underneath
    # that signature would leave the code attached to findings it was never
    # made about. A new review is a new row: `POST /api/reviews/run` always
    # creates one, so nothing is blocked except overwriting history.
    if replace and run.get("engineer_final_code"):
        raise ComparisonError(
            f"this run carries an engineer's final code "
            f"({run['engineer_final_code']}); start a new review instead of "
            f"re-running the one the decision was made about")

    if replace:
        conn = connect()
        with conn:
            # CONFIRMED FINDINGS ARE NEVER DELETED. Re-running a comparison is
            # how every fix to this engine reaches the corpus, so a finding an
            # engineer has confirmed would otherwise survive only until the
            # next maintenance action - destroyed by a routine re-run, with
            # nothing on screen to say so.
            #
            # `standard_requirements` has followed this rule since 3B; findings
            # are the same kind of artefact and now follow it too.
            conn.execute(
                "DELETE FROM review_findings WHERE review_run_id = ?"
                " AND confirmed_by IS NULL",
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
    findings: list[dict] = []
    matches_attempted = matches_made = 0
    model_matches = 0
    model_reasons: dict[str, int] = {}
    # ONE CACHE AND ONE BUDGET FOR THE WHOLE RUN. The cache answers a repeated
    # question for free; the budget is the stop that keeps a pre-filter defect
    # from turning into a review that calls a model thousands of times.
    model_cache: dict = {}
    budget = _Budget(settings.match_max_calls_per_run)
    for requirement in requirements:
        # CONTAINMENT, NOT EXACT EQUALITY. Measured over this corpus, exact
        # equality between a requirement's subject and a datasheet caption
        # matched 0 of 77; containment matched the pairs an engineer picked.
        if is_matchable(requirement):
            matches_attempted += 1
        match = match_by_containment(requirement, facts)
        fact = match["fact"]
        # COUNTED HERE, BEFORE THE MODEL TIER, so `matches_made` keeps meaning
        # "paired deterministically". The model's pairings are reported
        # separately as `model_matches`; folding them into one number would
        # make a tier that guesses look like the tier that knows.
        if fact is not None:
            matches_made += 1

        # THE MODEL TIER. Second, never first, and only where containment had
        # nothing to say. A tie is deliberately excluded: AMBIGUOUS_MATCH means
        # two fields are equally named inside the requirement, which is a
        # question for a person - handing it to a model would replace "we could
        # not tell" with an answer nobody checked.
        model_reason: str | None = None
        if (fact is None and match["reason"] != AMBIGUOUS_MATCH
                and is_matchable(requirement)):
            if not settings.match_enabled:
                model_reason = MODEL_DISABLED
            else:
                chosen = match_by_model(
                    requirement, facts, cache=model_cache, budget=budget)
                if chosen["fact"] is not None:
                    match = chosen
                    fact = chosen["fact"]
                    model_matches += 1
                else:
                    model_reason = chosen["reason"]

        verdict = compare(requirement, fact, subject=subject)
        # THE TABLE-ROW REFUSAL OUTRANKS THE UNIT GUARD. Both end in
        # NEEDS_ENGINEER_REVIEW, but only one of them is the real reason: the
        # number is not a limit. Reporting "unit_mismatch" against a table row
        # tells a reviewer to go and reconcile kPa with bar, which would leave
        # them comparing a design pressure against a lookup boundary once the
        # units agreed.
        if fact is not None and requirement.get("requirement_type") != requirements_3b.TABLE_ROW:
            # THE UNIT GUARD. A match says the two are ABOUT the same thing; it
            # says nothing about whether their numbers can be compared. A
            # length against a pressure is not a breach and not a pass - it is
            # a question for a person, and the finding carries both raw units
            # so they can see what was compared with what.
            # `same_unit` compares MEASUREMENTS, and it compares the raw
            # spellings rather than the normalised ones on purpose - `dB(A)`
            # and `dB` are different units. The base unit is passed as the raw
            # spelling here so that a gauge pressure and a plain one still meet
            # (`bar` both sides); the gauge reference itself is carried on the
            # fact and is a separate question from whether the units match.
            # THE RAW SPELLINGS, WITH ANY GAUGE REFERENCE STRIPPED. `unit`
            # holds the NORMALISED unit, which is NULL for every unit the table
            # recognises but does not convert - dB(A) among them - so comparing
            # those columns reported a unit mismatch between two dB(A) values.
            # `same_unit` is a comparison of spellings and wants the spellings.
            requirement_unit = _unit_measure(requirement)
            fact_unit = _unit_measure(fact)
            if not _units_comparable(requirement, fact, requirement_unit, fact_unit):
                verdict = {
                    **verdict,
                    "status": NEEDS_ENGINEER_REVIEW,
                    "rationale": (
                        f"{UNIT_MISMATCH}: the requirement is in "
                        f"{requirement.get('raw_unit') or requirement.get('unit') or 'no unit'} "
                        f"and the submitted value is in "
                        f"{fact.get('raw_unit') or fact.get('unit') or 'no unit'}; "
                        "these are not the same quantity and were not compared"),
                }
        elif match["reason"] == AMBIGUOUS_MATCH:
            verdict = {
                **verdict,
                "status": NEEDS_ENGINEER_REVIEW,
                "rationale": (
                    f"{AMBIGUOUS_MATCH}: more than one submitted field is named "
                    f"inside this requirement ({', '.join(match['candidates'])}); "
                    "no value was chosen, because choosing one arbitrarily "
                    "would attach a real number to the wrong requirement"),
            }
        # THE PAIRING NOTE GOES ON LAST, after every verdict adjustment above,
        # because the unit guard and the tie branch REPLACE the rationale. A
        # prefix written before them would be silently dropped on exactly the
        # findings a reader most needs it on.
        if match["method"] == METHOD_MODEL_CHOICE:
            verdict = {**verdict, "rationale": (
                f"{MODEL_PAIR_PREFIX}{match.get('reason') or ''}. "
                f"{verdict.get('rationale') or ''}")}
        elif model_reason:
            # WHY NO MODEL PAIRING WAS MADE, in words, on the finding itself.
            # Without it "the model was off" and "the model was asked and
            # declined" read identically to an engineer.
            verdict = {**verdict, "rationale": (
                f"{verdict.get('rationale') or ''} "
                f"(model tier: {model_reason})")}
            model_reasons[model_reason] = model_reasons.get(model_reason, 0) + 1
        opinion = (model_opinions or {}).get(requirement.get("id"))
        findings.append(create_finding(
            review_run_id=review_run_id, submittal_document_id=submittal_id,
            requirement=requirement, fact=fact, verdict=verdict,
            model_opinion=opinion, matched_phrase=match["matched_phrase"],
            match_method=match["method"]))

    coverage = completeness_for_run(
        submittal_id, allowed_document_ids=allowed_document_ids,
        reference_coverage=reference_coverage)
    recommendation = recommend_code(findings, coverage)
    _store_run_outcome(review_run_id, recommendation, coverage)

    return {
        "review_run_id": review_run_id,
        "submittal_document_id": submittal_id,
        "requirements_evaluated": len(requirements),
        "facts_in_scope": len(facts),
        "matches_attempted": matches_attempted,
        "matches_made": matches_made,
        "model_matches": model_matches,
        "model_calls": budget.calls,
        "model_reasons": model_reasons,
        "findings": findings,
        "by_status": {
            status: sum(1 for f in findings if f["compliance_status"] == status)
            for status in (COMPLIANT, NON_COMPLIANT, MISSING_INFORMATION,
                           CONDITIONAL, NOT_APPLICABLE, NEEDS_ENGINEER_REVIEW)
        },
        "completeness": coverage,
        "recommended_code": recommendation,
    }


#: The requirement types a matcher may pair a submitted value with, and the
#: ONE HOME for that claim: `match_by_containment`, `candidate_facts` and
#: `run_comparison` all ask this rather than each carrying its own tuple.
#:
#: Three types, and only one of them is ever COMPARED:
#:   * `numeric_limit` - a real limit, compared.
#:   * `table_row`     - matched so the engineer sees which submitted value the
#:                       row bears on; `compare` refuses it and quotes the row.
#:   * `relative_limit` - the same, for a margin from a reference the submittal
#:                       does not carry.
#:
#: `applicability_trigger` is deliberately ABSENT. Its number is the threshold
#: at which another document takes over, so there is nothing for a submitted
#: value to be measured against and pairing one could only produce a verdict.
MATCHABLE_TYPES = frozenset({
    "numeric_limit", requirements_3b.TABLE_ROW, requirements_3b.RELATIVE_LIMIT})


def is_matchable(requirement: dict) -> bool:
    """May a matcher pair a submitted value with this requirement at all?

    THE TYPE AND THE NUMBER, TOGETHER. A requirement with no parsed number has
    nothing for a value to be paired against, whatever its type says.
    """
    return (requirement.get("requirement_type") in MATCHABLE_TYPES
            and requirement.get("raw_value") not in (None, ""))


#: Why a containment match was refused, when it was.
AMBIGUOUS_MATCH = "ambiguous_match"
TABLE_ROW_REASON = "table_row"
#: Why a numeric comparison was refused although both numbers were present:
#: the requirement's number is a MARGIN from a reference the submittal does
#: not carry. See `requirements_3b.RELATIVE_LIMIT`.
RELATIVE_LIMIT_REASON = "relative_limit"
#: Why a numeric comparison was refused although both sides carried numbers:
#: the submitted value is a RANGE and the requirement asks for one exact
#: value. See `_range_side`.
RANGE_VS_EQUALITY = "range_against_exact_value"
UNIT_MISMATCH = "unit_mismatch"

#: How a match was made. One value today; named so a second method cannot be
#: added without the finding saying which one produced it.
METHOD_CONTAINMENT = "containment"


def _unit_measure(row: dict) -> claims.Measurement:
    """A row's unit as a `Measurement` carrying the RAW SPELLING.

    `unit` holds the NORMALISED unit, which is NULL for every unit `claims`
    recognises but does not convert - dB(A) among them - so a comparison of
    those columns reports a mismatch between two dB(A) values. `same_unit`
    compares spellings and wants the spellings, with any gauge reference
    stripped: a gauge pressure and a plain one are both `bar`, and whether the
    reference matters is a separate question from whether the units do.

    ONE HOME FOR THIS. The unit guard in `run_comparison` and the candidate
    pre-filter in `candidate_facts` must ask the same question, or the model
    tier would be offered pairs the engine then refuses to compare.
    """
    return claims.Measurement(
        raw_value=str(row.get("raw_value") or ""),
        raw_unit=claims.split_reference(
            row.get("raw_unit") or row.get("unit"))[0] or "",
        normalized_value=None, normalized_unit=None, comparator=None)


def _units_comparable(requirement: dict, fact: dict,
                      requirement_unit: claims.Measurement,
                      fact_unit: claims.Measurement) -> bool:
    """May these two numbers be compared at all?

    BY DIMENSION WHEN BOTH SIDES NORMALISE, BY SPELLING WHEN EITHER DOES NOT.

    The spelling test alone was too strict: a limit in kPa and a value in bar
    are both pressures, `claims` converts between them exactly, and refusing
    them sent a comparison the engine could do to a human instead. Dimension
    equality is the right question there, and `_compatible` does the conversion.

    But dimension is the WRONG question when a unit has no conversion. `dB(A)`
    and `dB` share no dimension at all (both are None), and `°F` and `°C` share
    one while being unconvertible by deliberate design - "a wrong temperature
    conversion is a safety defect". For those the only safe test is that the
    spellings match, which is what `same_unit` asks.

    So: if both sides normalised, compare dimensions. If either did not, fall
    back to the spelling. That keeps kPa-against-bar working and keeps
    dB(A)-against-dB refused.
    """
    requirement_measure = _measurement_from_requirement(requirement)
    fact_measure = _measurement_from_fact(fact)
    both_normalised = (
        requirement_measure is not None
        and fact_measure is not None
        and requirement_measure.normalized_value is not None
        and fact_measure.normalized_value is not None)
    if both_normalised:
        left = claims.unit_dimension(requirement_unit.raw_unit or "")
        right = claims.unit_dimension(fact_unit.raw_unit or "")
        return left is not None and left == right
    return claims.same_unit(requirement_unit, fact_unit)


def match_by_containment(requirement: dict, facts: list[dict]) -> dict:
    """The fact a requirement is about, found by CONTAINMENT. Deterministic.

    A requirement's subject is a sentence fragment - "internal design pressure
    shall be according to the following table" - and a datasheet's field name is
    the bare noun phrase, "internal design pressure". Measured over 77
    requirements and 38 field names, EXACT EQUALITY MATCHED NOTHING and
    containment matched the two pairs an engineer would also pick. So the join
    is containment, and exact equality is the special case where the subject
    happens to be exactly the field name - no separate path.

    WHOLE WORDS ONLY. "design pressure" must not match inside "redesign
    pressure": the second is a different field, and a substring test would file
    a value under a requirement about something else.

    THE SCOPE IS NARROW ON PURPOSE:

      * only numeric_limit requirements that actually carry a value - a
        requirement with no number has nothing to compare and matching it would
        produce a finding whose verdict could only be "unknown";
      * only facts with a numeric value. A categorical fact ("yes", "N/A")
        never matches here, and that single rule is what keeps SAES-W-010's
        PWHT clause away from a field called `insulation` - the word is shared,
        the quantity is not.

    A TIE IS NOT RESOLVED BY PICKING. Several fields can be contained in one
    long subject; the longest field name wins because it is the most specific,
    and a genuine tie returns no match with the candidates named. Choosing
    arbitrarily would attach a real number to the wrong requirement and there
    would be nothing on the finding to say it was a guess.

    Returns `{"fact": ..., "matched_phrase": ..., "method": ...}` or
    `{"fact": None, "reason": ..., "candidates": [...]}`.
    """
    none: dict = {"fact": None, "matched_phrase": None, "method": None,
                  "reason": None, "candidates": []}
    # NUMERIC LIMITS AND TABLE ROWS. Both carry a parsed number, and a table
    # row has to be matchable or the one case a reviewer can act on never
    # arises: `compare` raises a table row to NEEDS_ENGINEER_REVIEW only when a
    # value was matched against it, so a matcher that skipped table rows would
    # leave that branch permanently dead and every table row reported as the
    # contractor's missing information.
    #
    # Matching one is not comparing it. `compare` still refuses the comparison
    # and quotes the row; the match is what tells the engineer WHICH submitted
    # value the row bears on.
    if not is_matchable(requirement):
        return none
    # THE TEST IS THE RAW NUMBER, NOT THE NORMALISED ONE.
    #
    # `value` is NULL for every unit `claims` recognises but does not convert -
    # dB(A) among them, which is the product's own worked example. Scoping on
    # it would have excluded the flagship comparison from matching at all,
    # while looking like a tightening. Two values in the same unit compare
    # perfectly well without a conversion, and `compare` already refuses the
    # pairs that cannot.
    if requirement.get("raw_value") in (None, ""):
        return none
    subject = _normalise_for_match(requirement.get("subject"))
    if not subject:
        return none

    rejected = _rejected_keys_for(requirement)
    tag_scoped = facts_are_tag_scoped(facts)
    hits: list[dict] = []
    for fact in facts:
        if not fact_has_number(fact):
            continue          # categorical or blank: never matched in this pass
        if fact_key(fact, tag_scoped=tag_scoped) in rejected:
            # A HUMAN ALREADY SAID THIS PAIR IS WRONG. Asking again is how an
            # engineer learns the machine does not listen, and they stop
            # correcting it.
            continue
        name = _normalise_for_match(fact.get("field_name"))
        if len(name) < 4:
            # A one- or two-word fragment is contained in half of everything.
            continue
        if _contains_words(subject, name):
            hits.append({"fact": fact, "name": name})
    if not hits:
        return none

    longest = max(len(h["name"]) for h in hits)
    best = [h for h in hits if len(h["name"]) == longest]
    if len(best) > 1:
        return {**none, "reason": AMBIGUOUS_MATCH,
                "candidates": sorted(h["name"] for h in best)}
    return {"fact": best[0]["fact"], "matched_phrase": best[0]["name"],
            "method": METHOD_CONTAINMENT, "reason": None, "candidates": []}


# ------------------------------------------------- the model tier (§14, 2nd)
#
# THE ONE-SENTENCE RULE, from the design: the model may CHOOSE a fact from a
# list Python built. It may never NAME one.
#
# Everything the model could get wrong is bounded by that. It answers with an
# INDEX into a list it was handed, so it cannot invent a field; it never sees a
# value, a unit or a page, so it cannot be pulled toward the pairing that makes
# the arithmetic work; and it never sets a status, so a wrong pairing produces
# a wrong QUESTION rather than a wrong verdict.

#: How the pairing was made. `containment` is deterministic and runs first;
#: `model` means a language model chose from a deterministic shortlist and an
#: engineer has not confirmed it.
METHOD_MODEL_CHOICE = "model"

#: At most this many candidates reach the prompt, longest field name first.
MAX_CANDIDATES = 12

#: Why the tier declined to pair. Every one of these returns containment's
#: "none" shape, so a failure is indistinguishable downstream from "no match" -
#: which is what it is.
MODEL_DISABLED = "model_disabled"
MODEL_UNAVAILABLE = "model_unavailable"
MODEL_MALFORMED = "model_malformed"
MODEL_OUT_OF_RANGE = "model_out_of_range"
MODEL_NAMED_OTHER = "model_named_other"
MODEL_UNSTABLE = "model_unstable"
MODEL_BUDGET = "model_budget"
MODEL_DECLINED = "model_declined"

#: Every model-paired finding says so in its own first words. A pairing the
#: machine guessed and a pairing it derived must not read alike - the same rule
#: `review_applicable_standards.selection_method` follows.
MODEL_PAIR_PREFIX = "Paired by model; engineer must confirm. Model reason: "


class _Budget:
    """How many model calls this run has left.

    A STOP, NOT A THROTTLE. The design expects tens of calls per review; a run
    that wants hundreds has a pre-filter defect, and the honest response is to
    stop asking and say on every remaining finding that the tier stopped -
    `model_budget` - rather than to carry on at cost or to fall silent.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.calls = 0

    def exhausted(self) -> bool:
        return self.calls >= self.limit

    def spend(self) -> None:
        self.calls += 1

PROMPT_TEMPLATE = """\
You are matching an engineering standard clause to a datasheet field.
Choose the ONE candidate whose field is the quantity this clause governs.
If none is clearly the same quantity, answer null. Do not guess.

Standard: {doc_number} clause {clause}
Clause text: {subject_or_text}

Candidates:
{candidates}

Answer as JSON only: {{"choice": <index or null>, "reason": "<one short sentence>"}}
"""


def candidate_facts(requirement: dict, facts: list[dict]) -> list[dict]:
    """The shortlist a model is allowed to choose from. Deterministic.

    BUILT BY PYTHON, BEFORE ANY CALL, and this is the control that makes the
    tier safe rather than the prompt wording. Three filters:

      * a numeric value. A categorical "yes" has nothing to compare, and the
        canonical false friend - SAES-W-010's PWHT clause against a field
        called `insulation` - is excluded here rather than argued with.
      * UNITS THE ENGINE COULD ACTUALLY COMPARE, by the same
        `_units_comparable` the unit guard asks: dimension when both sides
        normalise, spelling when either does not. §2 of the design says
        `unit_dimension`, and that is right for kPa against bar - but dB(A)
        has no dimension at all, so a bare dimension test would have made the
        product's own worked example permanently ineligible for this tier
        while looking like the stricter rule.
      * not a pairing an engineer has already refused, by the same identity
        keys `match_by_containment` uses.

    A FACT MAY APPEAR FOR MANY REQUIREMENTS. Several clauses legitimately
    govern one field, and excluding a fact once it has been paired would make
    the result depend on iteration order - see §2 of the design, corrected.

    Capped at `MAX_CANDIDATES`, longest field name first: the most specific
    names are the ones worth showing, and a list longer than a dozen is a
    pre-filter defect rather than a hard question.
    """
    # THE SAME SCOPE THE CONTAINMENT MATCHER USES, asked the same way. The
    # tier is only ever called from inside that scope today, so this is a
    # guard rather than a behaviour - but a shortlist is the one thing a model
    # can act on, and a helper that built one for a requirement no matcher may
    # pair would be a loaded gun left for the next caller.
    if not is_matchable(requirement):
        return []
    requirement_unit = _unit_measure(requirement)
    refused = _rejected_keys_for(requirement)
    tag_scoped = facts_are_tag_scoped(facts)
    out = []
    for fact in facts:
        if not fact_has_number(fact) or fact.get("is_blank"):
            continue
        if not _units_comparable(requirement, fact,
                                 requirement_unit, _unit_measure(fact)):
            continue
        if fact_key(fact, tag_scoped=tag_scoped) in refused:
            continue
        out.append(fact)
    out.sort(key=lambda f: (-len(f.get("field_name") or ""),
                            f.get("field_name") or ""))
    return out[:MAX_CANDIDATES]


def build_prompt(requirement: dict, candidates: list[dict]) -> str:
    """The rendered prompt. NO VALUE, NO UNIT, NO PAGE - see §3.

    A model that sees the numbers can be pulled toward whichever pairing makes
    the comparison come out cleanly. Pairing has to be decided on wording
    alone, so the only things that cross are: which standard and clause, what
    the clause says, and the candidate FIELD NAMES with their section headings.

    A test renders this and asserts no candidate value, unit or page appears in
    it, and that the requirement's own operator and value do not either.
    """
    text = " ".join(str(
        requirement.get("subject")
        or requirement.get("requirement_text") or "").split())[:400]
    lines = []
    for index, fact in enumerate(candidates):
        section = fact.get("section") or "-"
        lines.append(f"{index}. {fact.get('field_name')}   (section: {section})")
    return PROMPT_TEMPLATE.format(
        doc_number=requirement.get("standard_document_id") or "-",
        clause=requirement.get("clause") or "-",
        subject_or_text=text,
        candidates="\n".join(lines))


def _none_match(reason: str | None = None) -> dict:
    """Containment's "no match" shape. Every model failure returns this.

    IDENTICAL DOWNSTREAM TO "nothing matched", because that is what it is. A
    tier that failed and a tier that declined must produce the same finding;
    only the recorded `reason` differs, and that is for a person reading the
    rationale, never for a branch.
    """
    return {"fact": None, "matched_phrase": None, "method": None,
            "reason": reason, "candidates": []}


def _ask_model_once(requirement: dict, candidates: list[dict]) -> tuple[object, str | None]:
    """One call. Returns `(PairChoice, None)` or `(None, reason)`."""
    from . import model_transport
    body = {
        "model": settings.answer_model,
        "prompt": build_prompt(requirement, candidates),
        "stream": False,
        # THE ANSWER PATH ALREADY SETS THIS (`answer.py:_call_model`) and the
        # tier must too. `settings.answer_model` is a THINKING model: without
        # it Ollama returns the JSON in `thinking` and leaves `response` an
        # empty string, so every call would have read as `model_malformed` and
        # the tier would have paired nothing, on every machine, silently.
        "think": False,
        # NEW TO THIS CODEBASE. Ollama constrains decoding to valid JSON, which
        # turns "the model wrote prose" from the common failure into a rare one.
        "format": "json",
        # The answer path's reason: pay the cold load once for the run, not
        # once per requirement.
        "keep_alive": "30m",
        "options": {
            "temperature": 0,
            "seed": settings.match_seed,
            "num_ctx": settings.num_ctx,
            "num_predict": 120,
            "num_thread": settings.num_thread,
        },
    }
    try:
        raw = model_transport.post_json(
            "/api/generate", body, timeout=settings.match_timeout_seconds)
    except Exception:  # noqa: BLE001 - refused, timed out, or answered wrongly
        return None, MODEL_UNAVAILABLE
    try:
        payload = json.loads((raw or {}).get("response") or "")
        choice = schemas.PairChoice.model_validate(payload)
    except Exception:  # noqa: BLE001 - not JSON, or not this shape
        return None, MODEL_MALFORMED
    if choice.choice is not None and not 0 <= choice.choice < len(candidates):
        return None, MODEL_OUT_OF_RANGE
    if choice.choice is not None:
        # THE MODEL MAY CHOOSE, NOT NAME. If its sentence names a candidate
        # other than the one it picked, the index and the words disagree and
        # there is no way to tell which it meant.
        chosen = _normalise_for_match(
            candidates[choice.choice].get("field_name"))
        reason_text = _normalise_for_match(choice.reason)
        for index, fact in enumerate(candidates):
            if index == choice.choice:
                continue
            other = _normalise_for_match(fact.get("field_name"))
            if other and len(other) > 3 and _contains_words(reason_text, other) \
                    and not _contains_words(chosen, other):
                return None, MODEL_NAMED_OTHER
    return choice, None


def match_by_model(requirement: dict, facts: list[dict], *,
                   cache: dict | None = None,
                   budget: "_Budget | None" = None) -> dict:
    """Ask the model to choose. Returns containment's shape either way.

    THE VALIDATION CHAIN IS ORDERED and each step is a different failure:
    unavailable, malformed, out of range, named another, unstable. The last is
    the interesting one - the same question is asked TWICE with the same seed,
    and a model that answers differently has not decided anything, so no
    pairing is made.

    The agreed answer is cached per (requirement identity, candidate identities)
    for the run, so re-asking the same question costs nothing.
    """
    candidates = candidate_facts(requirement, facts)
    if not candidates:
        return _none_match()
    scoped = facts_are_tag_scoped(candidates)
    key = (requirement_key(requirement),
           tuple(sorted(fact_key(f, tag_scoped=scoped) for f in candidates)))
    if cache is not None and key in cache:
        return dict(cache[key])

    # THE BUDGET IS CHECKED AFTER THE CACHE. A question already answered costs
    # nothing, and refusing it once the budget ran out would make the result
    # depend on the order requirements happened to be iterated in.
    if budget is not None and budget.exhausted():
        return _none_match(MODEL_BUDGET)
    if budget is not None:
        budget.spend()
    first, reason = _ask_model_once(requirement, candidates)
    if reason is not None:
        return _none_match(reason)
    if budget is not None and budget.exhausted():
        return _none_match(MODEL_BUDGET)
    if budget is not None:
        budget.spend()
    second, reason = _ask_model_once(requirement, candidates)
    if reason is not None:
        return _none_match(reason)
    if first.choice != second.choice:
        result = _none_match(MODEL_UNSTABLE)
    elif first.choice is None:
        result = _none_match(MODEL_DECLINED)
    else:
        fact = candidates[first.choice]
        result = {"fact": fact, "matched_phrase": fact.get("field_name"),
                  "method": METHOD_MODEL_CHOICE, "reason": first.reason,
                  "candidates": []}
    if cache is not None:
        cache[key] = dict(result)
    return result


def requirement_key(requirement: dict) -> str:
    """The identity of a requirement, independent of its row id.

    WHICH STANDARD, WHICH CLAUSE, AND WHAT IT SAYS. `standard_requirements.id`
    is a uuid4 regenerated by every `replace=True` extraction, and
    re-extraction is how every fix to the extractor reaches the corpus - so
    anything keyed on the row id stops applying at the next re-run, silently.

    The text is hashed rather than stored so the key is a fixed length and
    carries no document text into a table that is not about document text.
    """
    text = _normalise_for_match(
        requirement.get("requirement_text") or requirement.get("source_text"))
    parts = "|".join((
        str(requirement.get("standard_document_id") or ""),
        str(requirement.get("clause") or ""),
        text,
    ))
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def facts_are_tag_scoped(facts: list[dict]) -> bool:
    """Does this document need the equipment tag to tell its facts apart?

    Only when it carries TWO OR MORE. Computed from the facts already in
    hand rather than queried, because every caller that needs it is already
    holding the document's facts and a per-fact query would run tens of
    thousands of times in one review.
    """
    return len({f.get("equipment_tag") for f in facts
                if f.get("equipment_tag")}) >= 2


def _document_is_tag_scoped(submittal_document_id: str | None) -> bool:
    """The same question asked of the database, for the one caller that has
    a single fact rather than the list: recording a human's rejection."""
    if not submittal_document_id:
        return False
    try:
        row = connect().execute(
            "SELECT COUNT(DISTINCT equipment_tag) AS n FROM submittal_facts"
            " WHERE submittal_document_id = ? AND equipment_tag IS NOT NULL",
            (submittal_document_id,)).fetchone()
    except Exception:  # noqa: BLE001 - a database without the column yet
        return False
    return bool(row and row["n"] >= 2)


def fact_key(fact: dict, *, tag_scoped: bool = False) -> str:
    """The identity of a submitted fact: which submittal, which field.

    NOT the value. A rejection says "this requirement is not about this
    field", which stays true when the contractor revises the number - and
    would be forgotten on every resubmission if the value were in the key.

    AND THE EQUIPMENT TAG ONLY WHERE IT DISTINGUISHES SOMETHING. A datasheet
    covering four pressure safety valves has four `set pressure` rows, and an
    engineer rejecting a pairing for PSV-4301 has said nothing about
    PSV-4360 - so there the tag is part of which fact this is.

    On a sheet covering one vessel it is not. Every fact carries the same tag,
    so adding it to the key changes every key while distinguishing no two
    facts - and that would silently retire every rejection ever recorded
    against that document, which is the failure this key exists to prevent
    (see `requirement_key`). Identity is what tells things apart; a tag that
    is the same everywhere tells nothing apart.

    The caller decides, because the caller is the one holding the document's
    facts - `facts_are_tag_scoped` for a list, `_document_is_tag_scoped` for
    a single row. A document that GAINS a second tag re-keys its facts, which
    is correct and is the one case where an old rejection stops applying: it
    was recorded when the system could not tell the two pieces of equipment
    apart.
    """
    parts = [
        str(fact.get("submittal_document_id") or ""),
        _normalise_for_match(fact.get("field_name")),
    ]
    if tag_scoped:
        parts.append(_normalise_for_match(fact.get("equipment_tag")))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def reject_pair(requirement: dict, fact: dict, *, rejected_by: str | None,
                reason: str | None = None) -> dict:
    """Record that a human says this requirement is not about this field.

    Takes the ROWS, not their ids, because the identity keys are computed from
    their contents - see `requirement_key`. The ids are stored beside the keys
    as informational columns so a rejection can be traced back to the run that
    produced it, and are never read when deciding whether it applies.

    Idempotent: rejecting the same pair twice keeps the first decision and its
    reason rather than overwriting who said it and when.
    """
    submittal_review.ensure_schema()
    scoped = _document_is_tag_scoped(fact.get("submittal_document_id"))
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO review_pair_rejections"
            " (requirement_key, fact_key, requirement_id, fact_id,"
            "  rejected_by, rejected_at, reason) VALUES (?,?,?,?,?,?,?)",
            (requirement_key(requirement), fact_key(fact, tag_scoped=scoped),
             requirement.get("id"), fact.get("id"), rejected_by, now, reason))
    return {"requirement_key": requirement_key(requirement),
            "fact_key": fact_key(fact, tag_scoped=scoped),
            "requirement_id": requirement.get("id"), "fact_id": fact.get("id"),
            "rejected_by": rejected_by, "rejected_at": now, "reason": reason}


def reject_pair_for_finding(
    finding_id: str, *, rejected_by: str | None, reason: str | None,
    allowed_document_ids: frozenset[str],
) -> dict | None:
    """An engineer refuses the pairing a finding was built on.

    SCOPED EXACTLY LIKE READING THE FINDING, and out of scope is reported as
    NOT FOUND - a caller who may not read a finding must not be able to learn
    it exists by being told they may not touch it.

    Returns None when there is no such finding in scope. Raises
    `ComparisonError` when the finding has no pairing to refuse: a
    MISSING_INFORMATION finding names no submitted value, and recording a
    rejection against nothing would sit in the table forever matching no pair.

    Both rows are re-read here rather than trusted from the finding, because
    the rejection is keyed on their CONTENTS (see `requirement_key`).
    """
    submittal_review.ensure_schema()
    scope, args = _scope_clause(allowed_document_ids, "document_id")
    finding = connect().execute(
        "SELECT * FROM review_findings" + scope + " AND id = ?",
        [*args, finding_id]).fetchone()
    if finding is None:
        return None
    finding = dict(finding)
    if not finding.get("requirement_id") or not finding.get("fact_id"):
        raise ComparisonError(
            "this finding records no pairing, so there is nothing to reject")

    standards_scope, standards_args = _scope_clause(
        allowed_document_ids, "standard_document_id")
    requirement = connect().execute(
        "SELECT * FROM standard_requirements" + standards_scope + " AND id = ?",
        [*standards_args, finding["requirement_id"]]).fetchone()
    facts_scope, facts_args = _scope_clause(
        allowed_document_ids, "submittal_document_id")
    fact = connect().execute(
        "SELECT * FROM submittal_facts" + facts_scope + " AND id = ?",
        [*facts_args, finding["fact_id"]]).fetchone()
    if requirement is None or fact is None:
        # The finding outlived one of the rows it paired - a re-extraction
        # replaced them. There is no identity left to key a rejection on.
        return None
    return reject_pair(dict(requirement), dict(fact),
                       rejected_by=rejected_by, reason=reason)


def _rejected_keys_for(requirement: dict) -> set[str]:
    """Fact KEYS a human has ruled out for this requirement."""
    try:
        return {
            row["fact_key"] for row in connect().execute(
                "SELECT fact_key FROM review_pair_rejections"
                " WHERE requirement_key = ?", (requirement_key(requirement),))
        }
    except Exception:  # noqa: BLE001 - a database without the table yet
        return set()


def _normalise_for_match(text: str | None) -> str:
    """Lowercased, punctuation to spaces, whitespace collapsed.

    The SAME shape on both sides, which is the only reason a comparison between
    them means anything: `datasheets.normalise_field_name` already does this to
    a field label, and a subject that kept its commas would never contain one.
    """
    folded = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", folded).strip()


def _contains_words(haystack: str, needle: str) -> bool:
    """Is `needle` a whole-word sequence inside `haystack`?"""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


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
    # THE CODE ITSELF FIRST. An unknown code is not an override of anything,
    # and reporting it as a missing reason sends the caller to fix the wrong
    # field - which is what this said until a test asked it for "Looks fine
    # to me" and was told to supply a reason.
    if code not in DEFAULT_CODES:
        raise ComparisonError(
            f"{code!r} is not one of the review codes: "
            + ", ".join(DEFAULT_CODES))
    recommended = stored.get("recommended_code")
    if recommended and code != recommended and not (override_reason or "").strip():
        raise ComparisonError(
            "overriding the recommended code requires a reason")

    now = _now()
    reason = (override_reason or "").strip() or None
    # THE DECISION GOES IN COLUMNS; THE RECOMMENDATION STAYS WHERE IT WAS.
    # `refusal_reason` is untouched here, so the AI's original code and its
    # sentence survive the engineer's decision - section 15 asks for both to
    # be stored, and a screen that showed only the final one would be hiding
    # what the machine actually said.
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = ?,"
            " override_reason = ?, decided_by = ?, decided_at = ?,"
            " updated_at = ? WHERE id = ?",
            (code, reason, reviewer, now, now, review_run_id))
    outcome = {
        **stored,
        "final_code": code,
        "reviewer": reviewer,
        "override_reason": reason,
        "decided_at": now,
    }
    _audit("review.code_recorded", actor, review_run_id,
           detail=f"recommended={recommended} final={code} "
                  f"overridden={bool(reason)}")
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
