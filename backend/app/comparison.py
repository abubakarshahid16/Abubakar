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
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import (claims, conditions, datasheets, field_links, match_rules, numparse, page_ledger,
                requirements_3b, review, schemas, submittal_review)
from .config import settings
from .db import connect

# ----------------------------------------------------------------- statuses

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
MISSING_INFORMATION = "MISSING_INFORMATION"
CONDITIONAL = "CONDITIONAL"
NOT_APPLICABLE = "NOT_APPLICABLE"
NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"
#: B9/B22, owner-approved 2026-09-22. A requirement this SUBMITTAL TYPE cannot
#: answer - it has to be checked in another document. It is NOT a contractor
#: omission (that is MISSING_INFORMATION) and NOT a failure, so it never
#: counts toward "with comments", never rejects, and never approves.
#: Client-facing label (frontend): "Requires another document - not
#: answerable from this submittal type".
NOT_IN_DOCUMENT_SCOPE = "NOT_IN_DOCUMENT_SCOPE"
#: B5 / NORTH-STAR 2.4: a standard the submittal CITES that is not held
#: locally. Its requirements cannot be read, so nothing about it was checked;
#: the run is never approved while one is outstanding.
MISSING_LOCALLY = "MISSING_LOCALLY"

#: Machine-readable detail on a `NOT_IN_DOCUMENT_SCOPE` verdict: this specific
#: requirement names its own evidence (issue #163, criterion 4) - "submit a
#: calibration certificate" - and that document is not the one under review.
#: Embedded in `rationale` as a leading token, the same convention
#: `TABLE_ROW_REASON`/`RELATIVE_LIMIT_REASON` already use, so a caller that
#: greps the rationale (or a future column) can tell "not in scope because no
#: field named this" apart from "not in scope because the wrong DOCUMENT would
#: have to answer it".
REQUIRES_OTHER_DOCUMENT = "requires_other_document"

#: CRS quick wins (2026-09-27, audit crs.md defect 5). The OTHER reason a
#: `statement` is NOT_IN_DOCUMENT_SCOPE: no datasheet field was found for it.
#: It used to carry `REQUIRES_OTHER_DOCUMENT` too, so the CRS Review notes
#: said "9 requirements name their own evidence - a certificate, procedure,
#: drawing" on a sheet where 2 did; the other 7 (a manway size, a flange
#: class, PWHT...) named nothing of the kind. Only a clause whose own sentence
#: names a document (`required_evidence_type`) carries the first token now.
NO_FIELD_MATCHED = "no_field_matched"
#: The reason code a NOT_APPLICABLE finding leads with when the requirement's
#: condition was established as NOT holding by a datasheet fact (B24 and the
#: condition reader in `conditions`). Read by `crs_mapping` as a literal.
CONDITION_NOT_MET = "condition_not_met"

#: Statuses that block approval. `MISSING_INFORMATION` is deliberately NOT
#: here: a field nobody filled in is a question, not a failure, and it steers
#: the code through completeness rather than by masquerading as a breach.
BLOCKING = frozenset({NON_COMPLIANT})

#: THE SEVERITY BUG (found reviewing EF1975-DAS-M-03, 2026-09-28). Every call
#: to `create_finding`/`_prepare_finding` left `severity` at its hardcoded
#: default of "major" - nobody ever passed a status-aware value in. That put
#: a NOT_IN_DOCUMENT_SCOPE finding, which the comment above says explicitly
#: is "NOT a failure" and "never counts toward with comments", in the exact
#: same "major" bucket as a real NON_COMPLIANT breach. On that run, 1,223 of
#: 7,803 findings were NOT_IN_DOCUMENT_SCOPE and still read "major" - the
#: "unmeasured says unmeasured" rule, broken.
#:
#: NON_COMPLIANT is the only status this file calls a breach (`BLOCKING`
#: above); it is the only one that keeps "major" by default. Anything not
#: listed here (a future status, or a caller's own explicit override) still
#: gets "major" - the safe side when the status is not one this table has an
#: opinion about, never the silent side.
SEVERITY_BY_STATUS: dict[str, str] = {
    NOT_IN_DOCUMENT_SCOPE: "observation",   # not the contractor's to answer
    MISSING_LOCALLY: "observation",         # the standard was never read
    MISSING_INFORMATION: "minor",           # a blank to fill in, not a breach
    NEEDS_ENGINEER_REVIEW: "minor",         # unresolved, not yet a finding
    COMPLIANT: "observation",               # nothing wrong to flag
    CONDITIONAL: "minor",
}


def _default_severity(status: str | None) -> str:
    """The honest default severity for a verdict status, used whenever a
    caller does not name one explicitly (every caller in this file, today).
    Computed from the FINAL status - after `_reconcile` and the
    unresolved-evidence downgrade - never the verdict's original one, so a
    finding downgraded to NEEDS_ENGINEER_REVIEW is scored for what it became,
    not for what it started as."""
    return SEVERITY_BY_STATUS.get(status, "major")

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

#: CRS quick wins (2026-09-27): the client's LABELS for the four codes, by
#: role, in `reference/review_codes.json`. The defaults there are
#: `DEFAULT_CODES`. The policy that picks a role stays here, in code.
REVIEW_CODES_PATH = Path(__file__).parent / "reference" / "review_codes.json"
CODE_ROLES = ("approved", "approved_with_comments", "revise_and_resubmit", "manual_review")


def review_codes(path: Path | None = None) -> tuple[str, str, str, str]:
    """The four configured labels in `DEFAULT_CODES` order (approved, with
    comments, revise and resubmit, manual review).

    A missing file is the defaults. A file that names a role with no label,
    or gives two roles one label, is REFUSED with an error rather than half
    applied: two codes that print alike would let a reader mistake a
    rejection for an approval.
    """
    source = path or REVIEW_CODES_PATH
    if not source.exists():
        return DEFAULT_CODES
    data = json.loads(source.read_text(encoding="utf-8")).get("codes") or {}
    labels = tuple(" ".join(str(data.get(role) or "").split()) for role in CODE_ROLES)
    if not all(labels) or len(set(labels)) != len(labels):
        raise ComparisonError(
            "reference/review_codes.json must give four different, non-empty "
            "labels for: " + ", ".join(CODE_ROLES))
    return labels  # type: ignore[return-value]


def code_role(label: str | None, codes: tuple[str, ...] | None = None) -> str | None:
    """Which role a stored code label plays, under the configured labels or
    the defaults (a run recorded before a relabel keeps its old label)."""
    for table in (codes or review_codes(), DEFAULT_CODES):
        if label in table:
            return CODE_ROLES[table.index(label)]
    return None

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

#: Which denominator a completeness figure was computed on (CRS quick wins).
#: A review run's code is gated on BASIS_REQUIRED_FIELDS; the nominal basis
#: survives only where no comparison has run yet.
BASIS_REQUIRED_FIELDS = "required_by_applicable_standards"
BASIS_NOMINAL = "nominal_fields_per_page"


def _required_and_answered(findings: list[dict]) -> tuple[int, int]:
    """(requirements that ask this datasheet for a value, how many a field
    read from it answered), counted per REQUIREMENT - one clause judged for
    three nozzles is one requirement.

    Left out of both: datasheet self-checks (no requirement), and
    NOT_IN_DOCUMENT_SCOPE (the clause names another document, or no field on
    this sheet was found for a statement - B9's own boundary). A requirement
    whose value may sit on a page nobody read (UNREAD_PAGES) is counted as
    unanswered: not found is not present, and not read is not read.
    """
    asked: dict[str, bool] = {}
    for f in findings:
        rid = f.get("requirement_id")
        if not rid or f.get("compliance_status") == NOT_IN_DOCUMENT_SCOPE:
            continue
        answered = bool(f.get("fact_id")) and not (
            f.get("ai_rationale") or "").startswith(UNREAD_PAGES)
        asked[rid] = asked.get(rid, False) or answered
    return len(asked), sum(1 for v in asked.values() if v)

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
    return _normalise_in_document(
        str(raw_value), requirement.get("raw_unit") or "",
        requirement.get("standard_document_id"), requirement.get("operator"))


def _document_uses_decimal_comma(document_id: str | None) -> bool:
    """Does this stored document write a comma as a decimal mark anywhere?
    False when it cannot be told (no id, no database): the plain reading."""
    if not document_id:
        return False
    try:
        rows = connect().execute(
            "SELECT text FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
    except (sqlite3.Error, OSError, RuntimeError):   # no database (a unit test, a dry run)
        return False
    return numparse.uses_decimal_comma(" ".join(str(r["text"] or "") for r in rows))


def _normalise_in_document(raw: str, unit: str, document_id: str | None,
                           operator: str | None = None) -> claims.Measurement:
    """`claims.normalise`, reading a three-decimal dot value ("3.175") as
    AMBIGUOUS when its own document writes a decimal comma anywhere, and as a
    decimal otherwise (owner decision 2026-10-08). The database is asked only
    for that one shape."""
    if numparse.is_three_decimal_dot(raw) and _document_uses_decimal_comma(document_id):
        with numparse.document_context(True):
            return claims.normalise(raw, unit, operator)
    return claims.normalise(raw, unit, operator)


def _ambiguous_decimal(m: claims.Measurement | None, document_id: str | None) -> bool:
    """A value printed d.ddd ("3.175") in a document that writes a decimal
    comma elsewhere: a decimal or a thousands group, and the text cannot say.
    Decided by the shape and the document, not by the unit table, so it holds
    for units this engine cannot convert as well."""
    return (m is not None and numparse.is_three_decimal_dot(m.raw_value)
            and _document_uses_decimal_comma(document_id))


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
    return _normalise_in_document(
        str(raw_value), fact.get("raw_unit") or "", fact.get("document_id"))


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
    spellings = subject_spellings(subject)
    for exception in exceptions:
        applies_to = " ".join(str(exception.get("applies_to") or "").lower().split())
        if not applies_to:
            continue
        # Singular/plural tolerance without a stemmer: compare on the stem of
        # each word, which is enough for "valve"/"valves" and refuses to be
        # clever beyond that.
        b = {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", applies_to)}
        # ONE DIRECTION ONLY (audit 2026-09-30): every word of the exception's
        # equipment must be in the subject - the subject is AT LEAST as
        # specific as the exception. The reverse ("valve" inside "pressure
        # relief valves") would let a sheet classified only as a generic kind
        # borrow a narrower kind's relaxed limit, which excuses a breach.
        for wanted in spellings:
            a = {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", wanted)}
            if a and b and b <= a:
                return exception
    return None


#: A SUBJECT'S OTHER NAMES, where a standard names the same equipment class in
#: different words. Each entry is a CLASS MEMBERSHIP, one direction only: a
#: pressure safety valve IS a pressure relief valve (API 520 Part I uses
#: "pressure relief valve" as the generic term covering safety, relief and
#: safety-relief valves), so an exception for pressure relief valves covers a
#: PSV; an exception naming only safety valves does NOT cover every relief
#: valve. Nothing is added here that is not a strict "is a" relation.
_SUBJECT_IS_A: dict[str, tuple[str, ...]] = {
    "pressure safety valve": ("pressure relief valve", "safety valve", "relief valve"),
    "psv": ("pressure safety valve", "pressure relief valve", "safety valve",
            "relief valve"),
    "safety relief valve": ("pressure relief valve", "relief valve"),
}


def subject_spellings(subject: str | None) -> list[str]:
    """The subject folded to lowercase words, plus the classes it belongs to."""
    folded = " ".join(re.findall(r"[a-z0-9]+", str(subject or "").lower()))
    if not folded:
        return []
    out = [folded]
    for word, classes in _SUBJECT_IS_A.items():
        if word == folded or word == folded.rstrip("s"):
            out.extend(classes)
    return list(dict.fromkeys(out))


def equipment_subject(classification: dict | None) -> str | None:
    """What equipment this submittal is about, for `_applicable_exception`.

    The submittal's STORED classification `equipment_type` - the word an
    engineer confirmed, or the classifier read from the sheet's own title
    block (with its page and quote kept as evidence). None when there is none:
    the field names are NOT used here, because an exception applied on a guess
    excuses a breach, and an unknown subject gets the general limit.
    """
    value = ((classification or {}).get("equipment_type") or "").strip()
    return value or None


#: The reason code on a breach held back because the datasheet VALUE it rests
#: on is not yet trusted (audit 2026-09-30).
LOW_TRUST_VALUE = "LOW_TRUST_VALUE"
#: `submittal_facts.validation_state` values that mean "not yet trusted":
#: below the confidence threshold (the OCR fallback tier among them) and a
#: geometry reading that disagrees with the rule reader. Spelled here as
#: literals because `datasheets` owns them (`NEEDS_ENGINEER_REVIEW`,
#: `GEOMETRY_CONFLICT`); a test pins the two spellings together.
_LOW_TRUST_STATES = frozenset({"needs_engineer_review", "conflict"})


def low_trust_reason(fact: dict | None) -> str | None:
    """Why this datasheet value is not trusted enough to rest a breach on, or
    None. An engineer's confirmation of the value (`confirmed_by`) makes it
    trusted whatever read it."""
    if not fact or fact.get("confirmed_by"):
        return None
    state = (fact.get("validation_state") or "").strip().lower()
    if state in _LOW_TRUST_STATES:
        return (f"the value was read with validation state '{state}' "
                "(a low-confidence or conflicting reading)")
    if (fact.get("extraction_method") or "").strip().lower() == "model":
        return "the value was read by the model reader and no engineer has confirmed it"
    return None


#: The verdicts an untrusted value may not produce. BOTH of them (audit
#: leftover 2026-09-30): a COMPLIANT resting on an OCR-fallback or model-read
#: value is the same guess as a breach resting on one - it only fails the
#: other way, silently passing a value nobody has checked.
_VERDICTS_HELD_ON_LOW_TRUST = frozenset({NON_COMPLIANT, COMPLIANT})


def _hold_low_trust_breach(verdict: dict, fact: dict | None) -> dict:
    """A verdict - breach OR compliance - resting on an untrusted value becomes
    a question for the engineer, with the arithmetic kept in the words. Audit
    2026-09-30: an OCR-fallback or model-read value (confidence 0.5 or below)
    produced a contractor-facing breach, which is a guess shown as a finding
    (CLAUDE.md rule 4); the same value read as "within the limit" was
    accepted, which is the same guess. Every other status (already a
    question, missing information) passes unchanged."""
    if verdict.get("status") not in _VERDICTS_HELD_ON_LOW_TRUST:
        return verdict
    reason = low_trust_reason(fact)
    if reason is None:
        return verdict
    return {**verdict, "status": NEEDS_ENGINEER_REVIEW, "rationale": (
        f"{LOW_TRUST_VALUE}: {reason}, so no verdict (neither compliant nor a "
        f"breach) is stated until an engineer checks the value on the page; "
        f"the arithmetic on the value as read: "
        f"{verdict.get('rationale') or ''}")}


def compare(requirement: dict, fact: dict | None, *,
            subject: str | None = None,
            submittal_facts: list[dict] | None = None) -> dict:
    """`_compare`'s verdict, with a breach on an untrusted value held for an
    engineer (`_hold_low_trust_breach`). Every caller gets the guard."""
    return _hold_low_trust_breach(
        _compare(requirement, fact, subject=subject, submittal_facts=submittal_facts),
        fact)


def _compare(requirement: dict, fact: dict | None, *,
             subject: str | None = None,
             submittal_facts: list[dict] | None = None) -> dict:
    """The DETERMINISTIC verdict for one requirement against one fact.

    Returns `{status, rationale, limit, observed, exception_applied}`, plus
    `condition` when B24's gate had something to say. No model is called and none
    can be: this function is the reason a numeric breach is reproducible.

    The order of the checks is the policy, and each one refuses to fall through
    into a stronger claim than the evidence supports:

      0. the requirement names its own evidence (a certificate, a drawing, ...)
         and it is not the datasheet this engine reads
                                  -> NOT_IN_DOCUMENT_SCOPE (#163)
      1. no fact at all           -> MISSING_INFORMATION (never a failure)
      2. the fact is blank        -> MISSING_INFORMATION (never a failure)
      3. the requirement's CONDITION is not established
                                  -> NEEDS_ENGINEER_REVIEW (B24)
         ...or is established as NOT holding, with a fact that proves it
                                  -> NOT_APPLICABLE (B24)
      4. no numeric limit         -> NEEDS_ENGINEER_REVIEW (a human reads it)
      5. units cannot be compared -> NEEDS_ENGINEER_REVIEW (never a guess)
      6. the numbers compare      -> COMPLIANT or NON_COMPLIANT

    `submittal_facts` is the submittal's fact set, used only by the B24 condition
    gate. **Omitting it does not skip the gate — it fails it.** A conditional
    `numeric_limit` with no facts supplied returns NEEDS_ENGINEER_REVIEW rather
    than a verdict, so a caller that forgets cannot get a confident answer. That
    is the same discipline `keyword.search` applies to `allowed_document_ids`:
    the unsafe default is not available.
    """
    # ISSUE #163, CRITERION 2 & 4 - BEFORE EVERY OTHER BRANCH, INCLUDING THE
    # ABSENT-FACT ONE AND THE TABLE-ROW ONE BELOW.
    #
    # `required_evidence_type` is set only when the requirement's OWN
    # SENTENCE names a document to hand over - "submit a calibration
    # certificate", "furnish vendor drawings" - via
    # `requirements_3b.required_evidence_type`. It has been extracted and
    # stored on every `standard_requirements` row since #162 and read by
    # nothing here: a numeric_limit clause that also demands a certificate
    # ("... confirmed by a calibration certificate to within 0.5%") could be
    # paired by field-name containment to an unrelated datasheet value and
    # compared as arithmetic, emitting a COMPLIANT/NON_COMPLIANT verdict this
    # engine has no evidence for - the datasheet is not the certificate the
    # clause asked for. Everything this pipeline reads comes from the
    # submittal's DATASHEET extraction (`datasheets.py`), so
    # `DATA_SHEET_EVIDENCE` is the one value that names what is actually being
    # compared; any other named document routes to `NOT_IN_DOCUMENT_SCOPE`
    # exactly as B9 already routes a `statement` with no matching field -
    # this is the same claim ("this submittal type cannot answer it") for a
    # requirement that says so explicitly rather than by shape.
    required_evidence = requirement.get("required_evidence_type")
    if required_evidence and required_evidence != requirements_3b.DATA_SHEET_EVIDENCE:
        return {
            "status": NOT_IN_DOCUMENT_SCOPE,
            "rationale": (
                f"{REQUIRES_OTHER_DOCUMENT}: this requirement names its own "
                f"evidence - a {required_evidence.replace('_', ' ')} - which is "
                f"a different document from the one under review; it has to "
                f"be checked against that document, not against this "
                f"submittal's datasheet"),
            "limit": None, "observed": None, "exception_applied": None,
        }

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
        # B9, RULE R1 (owner-approved, to be sample-checked before trusted):
        # a `statement` names no field, subject or value a datasheet could
        # fill in, so "the sheet does not state it" says nothing about the
        # contractor - the question is answered by another document. Only
        # when NOTHING matched: a statement that did meet a fact, blank or
        # not, is still judged below exactly as before.
        if requirement.get("requirement_type") == requirements_3b.STATEMENT:
            return {
                "status": NOT_IN_DOCUMENT_SCOPE,
                # WHAT WAS CHECKED, NOT A CLAIM ABOUT ANOTHER DOCUMENT (CRS
                # quick wins): no field read from this datasheet was found for
                # the clause. It does not name a certificate or drawing - the
                # branch above is the one for a clause that does.
                "rationale": (
                    f"{NO_FIELD_MATCHED}: no field read from this datasheet was "
                    f"found for this requirement, and it states no value a "
                    f"field could be compared with; an engineer checks it "
                    f"against the datasheet or the document that governs it"),
                "limit": None, "observed": None, "exception_applied": None,
            }
        return {
            "status": MISSING_INFORMATION,
            # WHAT WAS CHECKED, not what the document says (honesty audit 50):
            # extraction reads some fields of a page, not necessarily all.
            "rationale": "no field read from the submittal answers this requirement",
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

    # ---------------------------------------------------------------- B24 gate
    # AFTER the two MISSING_INFORMATION branches and BEFORE any arithmetic.
    #
    # After, because "the submittal says nothing" is a truer description than
    # "the condition is unestablished" when there is no value at all, and
    # weakening MISSING_INFORMATION would trade one honest status for a vaguer
    # one. Before, because everything below this line can return COMPLIANT or
    # NON_COMPLIANT, and a verdict on a requirement whose condition nobody has
    # established is the defect this gate exists for: 0 mm against a 1.6 mm
    # minimum that binds only carbon steel, on a datasheet whose every material
    # field reads N/A, returned NON_COMPLIANT.
    #
    # B49: the gate then failed the same case in the opposite direction, by
    # answering NOT_APPLICABLE off two corrosion-allowance fields that merely
    # had "material" in their names. What may serve as evidence is now a role
    # test in `conditions._candidate_facts`, not a name test.
    #
    # `conditions.evaluate` returns None unless this is a `numeric_limit` row
    # carrying a real condition, so every other requirement type - including the
    # 4,246 `table_value` rows whose `condition` column holds a table row label
    # like "Arsenic" or "100" - reaches the code below unchanged.
    # `about=fact`: only facts about the same tag / nozzle as the compared
    # value may establish the condition (review conditions, 2026-09-30).
    condition = conditions.evaluate(requirement, submittal_facts, about=fact)
    if condition is not None and condition["state"] != conditions.SATISFIED:
        if condition["state"] == conditions.NOT_SATISFIED:
            return {
                # POSITIVE EVIDENCE ONLY. This branch is reachable solely when a
                # fact was read and states something the condition is not, and
                # that fact travels with the finding.
                "status": NOT_APPLICABLE,
                # CONDITION_NOT_MET leads, so the CRS can list the excused
                # requirement - with the condition and the datasheet value
                # that excused it - on the engineer's Review notes rather than
                # dropping it or printing it as a breach (`crs_mapping`).
                "rationale": (
                    f"{CONDITION_NOT_MET}: this requirement is conditional on "
                    f"{condition['condition']!r} and the submittal establishes "
                    f"otherwise: {condition['reason']}"),
                "limit": None,
                "observed": _describe(_measurement_from_fact(fact), fact),
                "exception_applied": None,
                "condition": condition,
            }
        return {
            # UNKNOWN, and it stays unknown. Not NOT_APPLICABLE - that would
            # excuse the requirement on no evidence, which is the mirror of the
            # defect this gate closes.
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": (
                f"this requirement applies only where "
                f"{condition['condition']!r}, and that condition is not "
                f"established by the submittal: {condition['reason']}. No "
                f"comparison was made."),
            "limit": None,
            "observed": _describe(_measurement_from_fact(fact), fact),
            "exception_applied": None,
            "condition": condition,
        }

    # CRS QUICK WINS: A CLOSED CATEGORICAL CLAUSE IS COMPARED AS TEXT.
    # "minimum pressure rating of Class 300" against CL150, "full
    # radiography" against SPOT. Only the three closed families
    # `field_links` reads, only against a field OF that family, and a
    # conditional clause is reported, never decided (`compare_categorical`).
    if requirement.get("requirement_type") == requirements_3b.STATEMENT:
        rule = field_links.categorical_requirement(
            requirement.get("source_text") or requirement.get("requirement_text"))
        family_field = field_links.field_of(fact.get("field_name"))[0]
        if rule is not None and family_field in field_links.FAMILY_FIELDS[rule["family"]]:
            judged = field_links.compare_categorical(rule, fact.get("field_value"))
            if judged is not None:
                return {"status": judged["status"], "rationale": judged["rationale"],
                        "limit": None,
                        "observed": _describe(_measurement_from_fact(fact), fact),
                        "exception_applied": None}

    # A SATISFIED condition travels with the verdict too. NORTH-STAR section 4
    # requires a review run to preserve its applicability evidence, and "this
    # clause was applied because the shell material field states carbon steel" is
    # exactly that. `_cond` is {} for an unconditional requirement, so those
    # findings keep the shape they have always had.
    _cond = {"condition": condition} if condition is not None else {}

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
                "exception_applied": exception, **_cond,
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
            "exception_applied": exception, **_cond,
        }
    if observed is None:
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": "the submitted value could not be read as a quantity",
            "limit": _describe(limit, governing), "observed": None,
            "exception_applied": exception, **_cond,
        }

    # UNITS MUST BE COMPARABLE, AND AN UNKNOWN UNIT IS NOT A GUESS. `claims`
    # owns this: it converts within a dimension, compares directly when both
    # sides carry the identical spelling, and returns None when it cannot do
    # either. None means NO COMPARISON WAS MADE, which is a result.
    for which, m, doc in (("submitted", observed, fact.get("document_id")),
                          ("required", limit, governing.get("standard_document_id"))):
        if _ambiguous_decimal(m, doc):
            return {
                "status": NEEDS_ENGINEER_REVIEW,
                "rationale": (f"the {which} value {m.raw_value!r} has three decimals and "
                              "its document writes a decimal comma elsewhere, so it may "
                              "be a decimal or a thousands group; no comparison was made"),
                "limit": _describe(limit, governing),
                "observed": _describe(observed, fact),
                "exception_applied": exception, **_cond,
            }
    verdict = claims._compatible(observed, limit)
    if verdict is None and (claims.parse_value(str(observed.raw_value or "")) is None
                            or claims.parse_value(str(limit.raw_value or "")) is None):
        # AN UNREADABLE NUMBER IS NOT A UNIT PROBLEM (audit 2026-09-30). The
        # sentence below used to read "the submitted unit 'mm' and the
        # required unit 'mm' cannot be compared" for a value like "see note"
        # - a false reason, naming two identical units as the obstacle.
        which, value = (("submitted", observed.raw_value)
                        if claims.parse_value(str(observed.raw_value or "")) is None
                        else ("required", limit.raw_value))
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": (f"the {which} value {value!r} could not be read as a "
                          "number, so no comparison was made"),
            "limit": _describe(limit, governing),
            "observed": _describe(observed, fact),
            "exception_applied": exception, **_cond,
        }
    if verdict is None:
        return {
            "status": NEEDS_ENGINEER_REVIEW,
            "rationale": _unit_obstacle(fact.get("raw_unit"), governing.get("raw_unit")),
            "limit": _describe(limit, governing),
            "observed": _describe(observed, fact),
            "exception_applied": exception, **_cond,
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
        "exception_applied": exception, **_cond,
    }


#: The fixed words every "a unit is missing" refusal ends with, so a reader of
#: `ai_rationale` (`claude_recheck`'s blocked check) matches them the way it
#: matches the two-unit refusal's "no conversion is guessed".
UNIT_NOT_GUESSED_PHRASE = "no unit is guessed, so no comparison was made"


def _unit_obstacle(submitted_unit: str | None, required_unit: str | None) -> str:
    """Why two readable numbers were not compared, naming only the units that
    exist. Audit leftover 2026-09-30: two values with no unit read "the
    submitted unit '' and the required unit '' cannot be compared" - a
    sentence about two units nobody wrote."""
    got = (submitted_unit or "").strip()
    want = (required_unit or "").strip()
    if not got and not want:
        return ("neither the submitted value nor the requirement states a unit, "
                "so this system cannot tell whether they measure the same "
                f"quantity; {UNIT_NOT_GUESSED_PHRASE}")
    if not got:
        return (f"the submitted value states no unit and the requirement is in "
                f"{want!r}; {UNIT_NOT_GUESSED_PHRASE}")
    if not want:
        return (f"the requirement states no unit and the submitted value is in "
                f"{got!r}; {UNIT_NOT_GUESSED_PHRASE}")
    return (f"the submitted unit {got!r} and the required unit {want!r} cannot "
            "be compared by this system; no conversion is guessed")


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
    model_opinion: str | None = None, severity: str | None = None,
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

    One finding, one transaction. `run_comparison` does not come through here:
    it prepares every finding of a run with `_prepare_finding` (the same gates)
    and writes them together in ONE transaction (`_write_run_findings`).
    """
    submittal_review.ensure_schema()
    row, unresolved = _prepare_finding(
        review_run_id=review_run_id, submittal_document_id=submittal_document_id,
        requirement=requirement, fact=fact, verdict=verdict, comment=comment,
        model_opinion=model_opinion, severity=severity, category=category,
        matched_phrase=matched_phrase, match_method=match_method)
    conn = connect()
    with conn:
        _insert_findings(conn, [row])
    return {**row, "unresolved_evidence": unresolved,
            "citation_resolves": not unresolved}


def _prepare_finding(
    *, review_run_id: str, submittal_document_id: str, requirement: dict,
    fact: dict | None, verdict: dict, comment: str | None = None,
    model_opinion: str | None = None, severity: str | None = None,
    category: str = "requirement_deviation",
    matched_phrase: str | None = None, match_method: str | None = None,
    pending: dict | None = None, stored_replaced: bool = False,
) -> tuple[dict, list[str]]:
    """Every gate `create_finding` applies, and the row it would write. No write.

    `pending` maps (requirement_id, fact_id) to the id of a finding already
    prepared for the SAME run but not yet written - the duplicate gate must
    see those as well as the stored rows, or a batch could hold two findings
    for one pair. `stored_replaced` says the run's stored unconfirmed findings
    are about to be deleted in the same transaction as this write, so they
    cannot be duplicates of anything.
    """
    # THE DUPLICATE GATE. A finding's identity within a run is the PAIR it is
    # about - which requirement, which fact (or no fact, for a
    # MISSING_INFORMATION verdict) - not the row id that will be minted for
    # it below. Two findings about the same pair inside the same run would
    # double the same claim in every count and hand an engineer two rows to
    # resolve for one question. Confirmed findings are excluded from the
    # check on purpose: a confirmed row is a human's decision and a fresh,
    # unconfirmed proposal about the same pair is exactly what `run_comparison`
    # writes on every re-run - see `run_comparison`'s "confirmed findings are
    # never deleted" note. This gate stops a SECOND unconfirmed row from
    # existing beside the first, not a re-run from proposing one at all.
    fact_id = (fact or {}).get("id")
    from . import review as review_mod
    duplicate = None if stored_replaced else connect().execute(
        "SELECT id FROM review_findings WHERE review_run_id = ?"
        f" AND requirement_id = ? AND fact_id IS ? AND {review_mod.UNDECIDED_SQL}",
        (review_run_id, requirement.get("id"), fact_id)).fetchone()
    # The same test against the batch not yet written. `requirement_id = ?`
    # never matches a NULL in SQL, so a requirement with no id is never a
    # duplicate there, and is not one here either.
    if (duplicate is None and pending and requirement.get("id") is not None
            and (requirement.get("id"), fact_id) in pending):
        duplicate = {"id": pending[(requirement.get("id"), fact_id)]}
    if duplicate is not None:
        raise ComparisonError(
            f"a finding already exists for this requirement and fact in this "
            f"review run ({duplicate['id']}); a duplicate finding is refused "
            f"rather than written")

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
    elif model_opinion or match_method in (METHOD_MODEL_CHOICE, METHOD_FIELD_NAME):
        # A MODEL CHOSE THE PAIRING, so the finding is only as good as that
        # choice however deterministic the arithmetic on top of it was. 0.5,
        # label "medium", never "high" (CLAUDE.md rule 4).
        confidence = CONFIDENCE_MODEL_ASSISTED
    else:
        confidence = CONFIDENCE_DETERMINISTIC

    # THE SEVERITY FIX. A caller that named a severity explicitly keeps it;
    # every caller in this file today does not, so this is what actually
    # decides every finding's severity - see `SEVERITY_BY_STATUS` above.
    if severity is None:
        severity = _default_severity(status)

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
    return row, unresolved


def _insert_findings(conn, rows: list[dict]) -> None:
    """INSERT prepared findings and their first history event. Caller commits."""
    for row in rows:
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
        # B10: THE HISTORY STARTS AT THE MACHINE. A finding's trail began at
        # the first human edit, so it could not say the review wrote it. No
        # actor - no person made it - and pending, never approved.
        review._event(conn, row["id"], "created_by_review", {
            "review_run_id": row["review_run_id"],
            "compliance_status": row["compliance_status"],
            "approval_status": "pending"}, None, row["created_at"])


def _write_run_findings(review_run_id: str, rows: list[dict], *,
                        replace: bool) -> None:
    """A run's findings, written in ONE transaction - and, on a re-run, the
    old unconfirmed findings deleted in that same transaction.

    WHY ONE TRANSACTION. Each finding used to be its own commit, and with
    `ensure_schema` re-checked per finding that was 8.7 ms a finding: 11.8 s
    of a 1,355-requirement review spent on bookkeeping (perf audit item 1).
    It also made a run ATOMIC, which it was not: a run that failed half way
    left the old findings deleted and half of the new ones written, and the
    review screen showed that half as the answer. Now a failure leaves the
    previous findings exactly as they were.

    Nothing slow happens inside it. The model tier, the matching and the
    citation checks all run BEFORE this, while no write lock is held; only
    the INSERTs are inside, so other writers wait milliseconds, not minutes.
    """
    conn = connect()
    with conn:
        if replace:
            # CONFIRMED FINDINGS ARE NEVER DELETED. Re-running a comparison is
            # how every fix to this engine reaches the corpus, so a finding an
            # engineer has confirmed would otherwise survive only until the
            # next maintenance action - destroyed by a routine re-run, with
            # nothing on screen to say so.
            #
            # `standard_requirements` has followed this rule since 3B; findings
            # are the same kind of artefact and now follow it too.
            #
            # Audit 2026-09-30: "confirmed" meant `confirmed_by` only, so a
            # rejection or acceptance (`approval_status`) was deleted here and
            # the rejected comment came back as a new draft. Any engineer
            # decision now keeps the row (`review.UNDECIDED_SQL`).
            from . import review as review_mod
            conn.execute(
                "DELETE FROM review_findings WHERE review_run_id = ?"
                f" AND {review_mod.UNDECIDED_SQL}",
                (review_run_id,))
        _insert_findings(conn, rows)


def _required_action(status: str) -> str:
    return {
        COMPLIANT: "None. The requirement is met.",
        NON_COMPLIANT: "Revise the submittal to meet the stated requirement.",
        MISSING_INFORMATION: "Provide the missing value.",
        CONDITIONAL: "Confirm the condition under which this requirement holds.",
        NOT_APPLICABLE: "None. The requirement does not govern this submittal.",
        NEEDS_ENGINEER_REVIEW: "An engineer must review this manually.",
        NOT_IN_DOCUMENT_SCOPE: "Check this in the document that governs it; "
                               "this submittal type cannot answer it.",
    }.get(status, "An engineer must review this manually.")


#: B3. The reason code on a finding whose value could not be looked for on
#: every page: the review may not call it the contractor's omission.
UNREAD_PAGES = "UNREAD_PAGES"
#: Entry 68: an absence on a page read only by the geometry/vision reader.
PAGE_READER_ONLY = "PAGE_READER_ONLY"


def qualify_by_pages(verdict: dict, pages: dict) -> dict:
    """What a MISSING_INFORMATION verdict may claim, given the pages read.

    NORTH-STAR 2.2: an omission finding preserves "the exact contractor
    pages/sections/fields searched", and "not retrieved" never means "not
    present". So:

    - every page read into fields BY THE RULE/TEXT READER: still
      MISSING_INFORMATION, and the rationale names the pages searched;
    - a page read only by the geometry/vision reader: NEEDS_ENGINEER_REVIEW
      (PAGE_READER_ONLY) - the page is read, but that reader is not known to
      find every field on it;
    - any page NOT read into fields (no fields parsed, unreadable, never
      reached, extraction never ran), or no page accounted for at all:
      NEEDS_ENGINEER_REVIEW. The value may sit on the unread page, so the
      review cannot tell the contractor it is missing.
    """
    total = pages.get("pages_total")
    searched = pages.get("fact_pages") or []
    unread = pages.get("pages_not_read_into_fields") or []
    where = (f"page{'s' if len(searched) != 1 else ''} "
             f"{page_ledger.page_list(searched)}" if searched else "no page")
    if not total:
        return {**verdict, "status": NEEDS_ENGINEER_REVIEW, "rationale": (
            f"{UNREAD_PAGES}: no page of this submittal is accounted for, so an "
            "omission cannot be stated; an engineer must check the document")}
    if unread:
        return {**verdict, "status": NEEDS_ENGINEER_REVIEW, "rationale": (
            f"{UNREAD_PAGES}: no value for this requirement was found in the "
            f"fields read from {where} of {total}; "
            f"page{'s' if len(unread) != 1 else ''} {page_ledger.page_list(unread)} "
            "were not read into fields, so the value may be there. An engineer "
            "must check those pages before this becomes a comment to the "
            "contractor")}
    page_reader_only = pages.get("pages_read_only_by_page_reader") or []
    if page_reader_only:
        # Owner decision 2026-09-26 (honesty audit entry 68): these pages are
        # READ - the ledger says so - but only by the geometry/vision reader,
        # which is not known to find every field on a page. An absence there
        # is an engineer's question, never the contractor's omission.
        return {**verdict, "status": NEEDS_ENGINEER_REVIEW, "rationale": (
            f"{PAGE_READER_ONLY}: value not found by the page reader - engineer "
            f"to check the page{'s' if len(page_reader_only) != 1 else ''} "
            f"{page_ledger.page_list(page_reader_only)}. No value for this "
            f"requirement was found in the fields read from {where} of {total}")}
    return {**verdict, "rationale": (
        f"{verdict.get('rationale') or ''}; fields were read from every page "
        f"({where} of {total})")}


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
    findings: list[dict] | None = None,
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
    if findings is not None:
        # CRS QUICK WINS (audit crs.md defect 7): THE DENOMINATOR IS WHAT THE
        # APPLICABLE STANDARDS ACTUALLY ASK THIS DATASHEET FOR, not the page
        # count times a nominal 35. The nominal figure scored a compact sheet
        # read 31 of 34 fields at 31/70 = 0.44 and gated it to Manual. Now:
        # of the requirements this run evaluated that ask for a datasheet
        # value (every one except those that need another document, or have
        # no field on any datasheet), how many were answered by a field read
        # from THIS sheet - blank or not, because a blank is the sheet
        # answering "not provided", which is a finding, not a reading gap.
        required, answered = _required_and_answered(findings)
        extraction = round(answered / required, 3) if required else None
        basis = {"basis": BASIS_REQUIRED_FIELDS, "fields_required": required,
                 "fields_answered": answered, "fields_estimated": None}
    else:
        # No findings yet (the applicability screen, before any comparison):
        # the old NOMINAL figure, labelled nominal wherever it is printed.
        fields_estimated = pages * FIELDS_PER_PAGE_NOMINAL if pages else None
        extraction = (
            round(min(fields_read / fields_estimated, 1.0), 3)
            if fields_estimated else None)
        basis = {"basis": BASIS_NOMINAL, "fields_estimated": fields_estimated}

    # B18, the same rule as `applicability.completeness`: extraction None means
    # the page count is unknown, so how much of the sheet was examined was
    # never MEASURED. Taking the min of what is left reported the reference
    # half alone as the whole review. None instead - unless reference coverage
    # is already 0, which no unknown can raise. A None reference coverage
    # (nothing cited) is still simply left out.
    if extraction is None:
        overall = 0.0 if reference_coverage == 0 else None
    else:
        parts = [p for p in (extraction, reference_coverage) if p is not None]
        overall = round(min(parts), 3)
    return {
        "fields_read": fields_read,
        **basis,
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
                   codes: tuple[str, ...] | None = None,
                   missing_references: list[str] | tuple[str, ...] = (),
                   page_coverage: dict | None = None) -> dict:
    """The recommendation, with `reason` in PLAIN WORDS for the engineer and
    the technical sentence kept as `details` (owner order 2g, 2026-09-26).

    The screen and the CRS print `reason`; "Details" shows `details`. Both are
    true - the plain one just leaves out the words only a developer reads
    ("NOMINAL ESTIMATE", "denominator", "MISSING_LOCALLY").
    """
    codes = codes or review_codes()
    result = _recommend_code(findings, completeness, codes=codes,
                             missing_references=missing_references)
    missing = [m for m in dict.fromkeys(missing_references or ()) if m]
    if result["code"] == codes[2]:
        # A PROVEN BREACH, IN AN ENGINEER'S WORDS, with what else is open.
        n = result["blocking"]
        plain = f"{n} requirement{'s are' if n != 1 else ' is'} not met."
        also = []
        if result["unresolved"]:
            also.append(f"{result['unresolved']} more need{'s' if result['unresolved'] == 1 else ''}"
                        " an engineer")
        if result["missing_information"]:
            k = result["missing_information"]
            also.append(f"{k} value{'s are' if k != 1 else ' is'} left for the contractor")
        extraction = completeness.get("extraction_coverage")
        if extraction is None or extraction < COMPLETENESS_THRESHOLD:
            also.append("not enough of the datasheet was checked to say the rest is met")
        if also:
            plain += " Also: " + "; ".join(also) + "."
        if missing:
            plain += " " + _standards_sentence(missing, _not_checked(missing))
        return {**result, "details": result["reason"], "reason": plain}
    return {**result, "details": result["reason"],
            "reason": plain_reason(result["code"], result["reason"], completeness,
                                   page_coverage, missing, codes=codes)}


def _pages_part(page_coverage: dict | None) -> str:
    total = (page_coverage or {}).get("pages_total")
    if not total:
        return ""
    read = len((page_coverage or {}).get("fact_pages") or [])
    return f" on {read} of {total} page{'s' if total != 1 else ''}"


#: How many missing standards the plain sentence names; the rest are
#: counted ("and 20 more") and all are named in Details and on the
#: CRS "Applicable standards" sheet.
PLAIN_NAMES_SHOWN = 5


def _standards_sentence(missing: list[str], tail: str) -> str:
    n = len(missing)
    names = ", ".join(missing[:PLAIN_NAMES_SHOWN]) + (
        f" and {n - PLAIN_NAMES_SHOWN} more" if n > PLAIN_NAMES_SHOWN else "")
    return (f"{n} standard{'s' if n != 1 else ''} the datasheet cites "
            f"{'are' if n != 1 else 'is'} not in your library ({names}), {tail}")


def _not_checked(missing: list[str]) -> str:
    return "so they were not checked." if len(missing) != 1 else "so it was not checked."


def plain_reason(code: str, technical: str, completeness: dict | None,
                 page_coverage: dict | None, missing: list[str], *,
                 codes: tuple[str, ...] | None = None) -> str:
    """The recommendation's reason as an engineer says it.

    Built from the same counts as the technical sentence, never from a
    different source: the fields read, the pages read out of the page total,
    and the cited standards not in the library. The estimate of how many
    fields a sheet holds is NOT a count of this document, so it is not in
    the plain sentence at all - it stays in `details`, labelled nominal.
    """
    completeness = completeness or {}
    codes = codes or review_codes()
    manual = codes[3]
    if (completeness.get("basis") == BASIS_REQUIRED_FIELDS
            and "not enough to recommend a code" in technical):
        required = completeness.get("fields_required") or 0
        answered = completeness.get("fields_answered") or 0
        head = (f"Found {answered} of the {required} datasheet value"
                f"{'s' if required != 1 else ''} the applicable standards ask for."
                if required else
                "No applicable standard asks this datasheet for a value that was checked.")
        if missing:
            return f"{head} " + _standards_sentence(
                missing, "so a review code can't be suggested yet.")
        return f"{head} That is not enough to suggest a review code yet."
    gated = ("NOMINAL ESTIMATE" in technical
             or technical.startswith("the submittal could not be read well enough"))
    if gated:
        read = completeness.get("fields_read")
        head = (f"Checked {read} datasheet field{'s' if read != 1 else ''}"
                f"{_pages_part(page_coverage)}." if read is not None
                else "The datasheet could not be read well enough.")
        if missing:
            return f"{head} " + _standards_sentence(
                missing, "so a review code can't be suggested yet.")
        return f"{head} That is not enough of the datasheet to suggest a review code yet."
    if code == manual and missing and "not held locally" in technical:
        if technical.startswith("Manual review: no requirement") or "none was evaluated" in technical:
            return ("No requirement could be checked against this datasheet. "
                    + _standards_sentence(missing, _not_checked(missing)))
        return "Needs an engineer: " + _standards_sentence(missing, _not_checked(missing))
    if technical.startswith("Manual review: no requirement was evaluated"):
        return "No requirement could be checked against this datasheet, so a review code can't be suggested yet."
    if technical.startswith("Manual review: all ") and "none was evaluated" in technical:
        return "Every requirement read as not applicable, so nothing was checked and no code is suggested."
    # Every other reason is already plain (the owner's own wording included,
    # "Manual review: 3 requirements require other documents"): unchanged.
    return technical


def plain_outcome(outcome: dict) -> tuple[str | None, str | None]:
    """(plain reason, details) for a STORED outcome. A run stored before 2g
    carries only the technical sentence; its plain one is derived here from
    the same stored counts, and the stored sentence becomes the details."""
    reason = outcome.get("reason")
    if reason is None:
        return None, None
    if "details" in outcome:
        return reason, outcome.get("details")
    missing = [m.get("identifier") for m in (outcome.get("missing_references") or [])
               if isinstance(m, dict) and m.get("identifier")]
    return plain_reason(outcome.get("recommended_code") or "", reason,
                        outcome.get("completeness"), outcome.get("page_coverage"),
                        missing), reason


def _recommend_code(findings: list[dict], completeness: dict, *,
                    codes: tuple[str, ...] = DEFAULT_CODES,
                    missing_references: list[str] | tuple[str, ...] = ()) -> dict:
    """The AI-RECOMMENDED review code. Deterministic policy, never the model.

    A PROVEN BREACH COMES FIRST (CRS quick wins, 2026-09-27): a requirement
    shown by arithmetic to be unmet sends the sheet back whatever else is
    open, with the open items stated beside it. THEN THE COMPLETENESS GATE,
    which overrides every approval: a review that examined nine fields and
    returns "Approved with Comments" is making a claim about the two hundred
    and forty nobody looked at - and the code is exactly what a reader takes
    as that claim. Section 15 scopes Manual Review Required to "insufficient
    confidence"; insufficient extraction is the same thing wearing different
    clothes. A breach is not a claim about what nobody looked at, which is
    why it may come before the gate and an approval may not.

    `codes` is a parameter because the client may use different names or
    numbers (section 15). The POLICY is fixed; the labels are not.
    """
    approved, with_comments, rejected, manual = codes
    statuses = [f.get("compliance_status") for f in findings]

    blocking = [s for s in statuses if s in BLOCKING]
    unresolved = [s for s in statuses if s == NEEDS_ENGINEER_REVIEW]
    missing = [s for s in statuses if s == MISSING_INFORMATION]
    # B9: counted APART from missing, in every outcome below. Never a
    # contractor omission, never a failure - and never an approval either.
    out_of_scope = [s for s in statuses if s == NOT_IN_DOCUMENT_SCOPE]

    missing_locally = [m for m in dict.fromkeys(missing_references or ()) if m]
    # CRS QUICK WINS (audit crs.md defect 7): A PROVEN BREACH COMES FIRST.
    # The completeness gate and the open questions used to be checked before
    # it, so a sheet with three proven breaches and one open question, or
    # with five breaches and a public code not held, was "Manual Review
    # Required" - on every synthetic and every real run the audit measured.
    # A requirement shown by arithmetic to be unmet is a reason to send the
    # sheet back whatever else is unknown; the unknowns are stated beside it
    # (they lower confidence, they do not erase the breach), and the engineer
    # still decides the final code.
    if blocking:
        caveats = []
        if unresolved:
            caveats.append(f"{len(unresolved)} more requirement(s) need an engineer")
        if missing:
            caveats.append(f"{len(missing)} value(s) are left for the contractor "
                           "to provide")
        extraction = completeness.get("extraction_coverage")
        if extraction is None or extraction < COMPLETENESS_THRESHOLD:
            caveats.append("the review did not cover enough of the datasheet to "
                           "say the rest is met")
        if missing_locally:
            caveats.append(f"{len(missing_locally)} cited standard(s) are not held "
                           f"locally ({MISSING_LOCALLY}) and were not checked: "
                           f"{', '.join(missing_locally)}")
        return {
            "code": rejected,
            "reason": f"{len(blocking)} requirement(s) are not met"
                      + (f"; {'; '.join(caveats)}" if caveats else ""),
            "blocking": len(blocking), "unresolved": len(unresolved),
            "missing_information": len(missing),
            "not_in_document_scope": len(out_of_scope),
            "missing_locally": len(missing_locally),
        }
    if not completeness.get("sufficient"):
        reason = _insufficient_reason(completeness)
        if missing_locally:
            # A missing cited standard is one CAUSE of low completeness; say
            # which, so the reader knows what to load (B5).
            reason += (f"; {len(missing_locally)} cited standard(s) are not held "
                       f"locally ({MISSING_LOCALLY}): {', '.join(missing_locally)}")
        return {
            "code": manual,
            "reason": reason,
            "blocking": len(blocking), "unresolved": len(unresolved),
            "missing_information": len(missing),
            "not_in_document_scope": len(out_of_scope),
            "missing_locally": len(missing_locally),
        }
    # B5: NOTHING EVALUATED IS NOTHING APPROVED. With no finding - or only
    # findings that a requirement does not apply - the tail of this function
    # read "every evaluated requirement is met" over zero requirements.
    evaluated = [s for s in statuses if s != NOT_APPLICABLE]
    if not evaluated:
        why = ("no requirement was evaluated against this submittal"
               if not statuses else
               f"all {len(statuses)} requirement(s) read as not applicable; "
               "none was evaluated")
        if missing_locally:
            why += (f"; {len(missing_locally)} cited standard(s) are not held "
                    f"locally ({MISSING_LOCALLY}): {', '.join(missing_locally)}")
        return {
            "code": manual, "reason": f"Manual review: {why}",
            "blocking": 0, "unresolved": 0, "missing_information": 0,
            "not_in_document_scope": 0, "missing_locally": len(missing_locally),
        }
    if unresolved:
        return {
            "code": manual,
            "reason": f"{len(unresolved)} requirement(s) could not be evaluated "
                      "and need an engineer",
            "blocking": 0, "unresolved": len(unresolved),
            "missing_information": len(missing),
            "not_in_document_scope": len(out_of_scope),
            "missing_locally": len(missing_locally),
        }
    if missing_locally:
        # B5: A CITED STANDARD THAT IS NOT HELD WAS NEVER CHECKED. Nothing
        # below this line may approve - not with comments, not outright.
        return {
            "code": manual,
            "reason": (f"Manual review: {len(missing_locally)} standard(s) the "
                       f"submittal cites are not held locally ({MISSING_LOCALLY}) "
                       f"and were not checked: {', '.join(missing_locally)}"),
            "blocking": 0, "unresolved": 0, "missing_information": len(missing),
            "not_in_document_scope": len(out_of_scope),
            "missing_locally": len(missing_locally),
        }
    if missing:
        return {
            # MISSING INFORMATION IS NOT A FAILURE, so it does not reject. It
            # is also not nothing, so it does not approve silently.
            "code": with_comments,
            "reason": f"{len(missing)} field(s) are left for the contractor to "
                      "provide; no requirement was found unmet",
            "blocking": 0, "unresolved": 0, "missing_information": len(missing),
            "not_in_document_scope": len(out_of_scope),
            "missing_locally": 0,
        }
    if out_of_scope:
        return {
            # NOT AN APPROVAL. Without this branch a run whose unmatched
            # requirements are all out of scope fell through to "every
            # evaluated requirement is met" - approval of a sheet on questions
            # it could never answer. NORTH-STAR 2.2: uncertainty never
            # produces automatic approval. Not the contractor's omission
            # either, so not "with comments": an engineer checks them where
            # they are answered.
            "code": manual,
            # The owner's wording, 2026-09-22: a specific reason, never a
            # generic manual flag. The reader learns WHY it is manual.
            # CRS quick wins: a statement with NO FIELD FOUND is not a
            # requirement "for another document" (NO_FIELD_MATCHED); it is
            # counted and named apart so the sentence stays true.
            "reason": _out_of_scope_reason(findings),
            "blocking": 0, "unresolved": 0, "missing_information": 0,
            "not_in_document_scope": len(out_of_scope),
            "missing_locally": 0,
        }
    return {
        "code": approved,
        "reason": "every evaluated requirement is met",
        "blocking": 0, "unresolved": 0, "missing_information": 0,
        "not_in_document_scope": 0, "missing_locally": 0,
    }


def _out_of_scope_reason(findings: list[dict]) -> str:
    scoped = [f for f in findings if f.get("compliance_status") == NOT_IN_DOCUMENT_SCOPE]
    no_field = sum(1 for f in scoped
                   if (f.get("ai_rationale") or f.get("rationale") or "").startswith(NO_FIELD_MATCHED))
    other = len(scoped) - no_field
    parts = []
    if other:
        parts.append(f"{other} requirement{' requires' if other == 1 else 's require'}"
                     " other documents")
    if no_field:
        parts.append(f"{no_field} requirement{' has' if no_field == 1 else 's have'} no "
                     "datasheet field found for "
                     f"{'it' if no_field == 1 else 'them'}")
    return "Manual review: " + "; ".join(parts)


def _insufficient_reason(completeness: dict) -> str:
    """Why the review was gated, WITH THE COUNTS."""
    read = completeness.get("fields_read")
    total = completeness.get("fields_estimated")
    if completeness.get("basis") == BASIS_REQUIRED_FIELDS:
        required = completeness.get("fields_required") or 0
        answered = completeness.get("fields_answered") or 0
        cover = completeness.get("reference_coverage")
        if not required:
            head = ("no requirement of an applicable standard asks this datasheet "
                    "for a value, so how much of it the review covered was not "
                    "measured")
        else:
            head = (f"{answered} of the {required} datasheet values the applicable "
                    f"standards' requirements ask for were found in the fields read "
                    f"from this submittal")
        if cover is not None and cover < COMPLETENESS_THRESHOLD:
            head += (f"; the library holds {round(cover * 100)}% of the standards "
                     "the submittal cites")
        return f"{head}, and that is not enough to recommend a code"
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
    missing_references: list[str] | None = None,
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

    # A RE-RUN REPLACES THIS RUN'S UNCONFIRMED FINDINGS - in the same
    # transaction that writes the new ones (`_write_run_findings`), so the
    # run never shows an empty or half-written set while this one computes.

    applicable = submittal_review.list_applicable_standards(
        review_run_id, allowed_document_ids=allowed_document_ids,
        include_excluded=False)
    standard_ids = [a["standard_document_id"] for a in applicable]

    requirements: list[dict] = []
    for standard_id in standard_ids:
        from . import standards as standards_mod
        # #596/#597: a definition, and text the quality gate holds, are not
        # compared. They stay in the library; they never reach a finding.
        requirements.extend(
            r for r in standards_mod.list_requirements(
                standard_id, allowed_document_ids=allowed_document_ids)
            if standards_mod.is_reviewable(r))

    facts = datasheets.list_facts(
        submittal_id, allowed_document_ids=allowed_document_ids)
    # B3: WHICH PAGES WERE READ INTO FIELDS, once per run, so no finding says
    # the contractor omitted a value that could sit on a page nobody read.
    page_ledger.refresh(submittal_id, as_submittal=True)
    pages_read = page_ledger.coverage(submittal_id)
    # THE SHEET'S KIND, ONCE PER RUN. The classification's word when an
    # engineer or the classifier gave one; the field names otherwise.
    from . import classification as classification_mod
    stored = classification_mod.of_document(submittal_id) or {}
    sheet = match_rules.sheet_kind(facts, stored.get("equipment_type"))
    # THE EQUIPMENT SUBJECT, for equipment-specific exceptions ("90 dB(A),
    # except pressure relief valves 115 dB(A)"). Audit 2026-09-30: neither
    # production caller passed one, so every exception was dead code and a
    # PSV at 100 dB(A) was reported as a breach. Derived HERE, once, so no
    # caller can forget it; a caller that names a subject still wins.
    if subject is None:
        subject = equipment_subject(stored)
    findings: list[dict] = []
    # The run's findings, prepared and gated but NOT yet written: they go in
    # one transaction after the loop. `pending` is the duplicate gate's view
    # of them (see `_prepare_finding`).
    prepared_rows: list[dict] = []
    pending: dict = {}
    # PAIRS AN ENGINEER REJECTED in this run. The rejected finding is kept
    # (`_write_run_findings`), and proposing the same pair again would put the
    # rejected comment back on the sheet as a new draft (audit 2026-09-30).
    from . import review as review_mod
    rejected_pairs = {(r.get("requirement_id"), r.get("fact_id"))
                      for r in review_mod.rejected_in_run(review_run_id)
                      if r.get("requirement_id")}
    matches_attempted = matches_made = 0
    rule_refusals: dict[str, int] = {}
    model_matches = 0
    model_reasons: dict[str, int] = {}
    # ONE CACHE AND ONE BUDGET FOR THE WHOLE RUN. The cache answers a repeated
    # question for free; the budget is the stop that keeps a pre-filter defect
    # from turning into a review that calls a model thousands of times.
    model_cache: dict = {}
    budget = _Budget(settings.match_max_calls_per_run)
    # B4 (#193 5.2/5.3), FLAG-GATED: canonical field names for the numeric
    # requirements and the facts' labels, named by the labelling model under
    # code-verified gates (see field_naming). None with the flag off - the
    # pre-B4 matching, untouched.
    field_names = None
    field_name_matches = 0
    if settings.geometry_reader_enabled:
        from . import field_naming
        field_names = field_naming.ensure_names(requirements, facts)
    for requirement in requirements:
        # CONTAINMENT, NOT EXACT EQUALITY. Measured over this corpus, exact
        # equality between a requirement's subject and a datasheet caption
        # matched 0 of 77; containment matched the pairs an engineer picked.
        if is_matchable(requirement):
            matches_attempted += 1
        match = None
        if field_names is not None:
            # FIELD-NAME EQUALITY FIRST (B4 5.3), then containment as before.
            match = match_by_field_name(requirement, facts, field_names, sheet_kind=sheet)
        if match is None:
            match = match_by_containment(requirement, facts, sheet_kind=sheet)
        fact = match["fact"]
        for refusal in match.get("refused", ()):
            rule_refusals[refusal["reason"]] = rule_refusals.get(refusal["reason"], 0) + 1
        # COUNTED HERE, BEFORE THE MODEL TIER, so `matches_made` keeps meaning
        # "paired deterministically". The model's pairings are reported
        # separately as `model_matches`; folding them into one number would
        # make a tier that guesses look like the tier that knows. A
        # field-name pairing rests on model-assigned names: `field_name_matches`.
        if fact is not None and match["method"] == METHOD_FIELD_NAME:
            field_name_matches += 1
        elif fact is not None:
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

        # OWNER ORDER 2a + 2b: A TABLE OR FORMULA RULE IS EVALUATED IN CODE,
        # against its OUTPUT field. "Design pressure from maximum operating
        # pressure" was paired with the operating pressure (the rule's INPUT)
        # and sent to an engineer. When the rule parses (rule_eval: code, or
        # the model's parse verified number by number), the verdict is the
        # arithmetic on the design pressure, and the input it used is named.
        rule_verdict = None
        rule_unread = None
        if requirement.get("requirement_type") in (requirements_3b.TABLE_ROW,
                                                    requirements_3b.RELATIVE_LIMIT):
            from . import rule_eval
            rule, rule_unread = rule_eval.rule_for(requirement)
            if rule is not None:
                rule_verdict, fact = rule_eval.judge(rule, facts)
                match = {**match, "fact": fact, "matched_phrase": rule["output"],
                         "method": METHOD_RULE, "reason": None}
        # ONE FINDING PER ITEM (CRS quick wins): the same field about several
        # named items - N1/N2/N3, or P-101A/P-101B - is one clause judged
        # against each (`_resolve_hits`); otherwise the one matched fact.
        targets = (match.get("items") or [fact]) if rule_verdict is None else [fact]
        governing_requirement = requirement
        for fact in targets:
            requirement = _unit_from_clause_text(governing_requirement, fact)
            # `facts` is the WHOLE submittal's fact set, not the matched fact. B24
            # needs the material/service/class fields to establish a condition, and
            # those are different rows from the one being compared.
            verdict = (_hold_low_trust_breach(rule_verdict, fact) if rule_verdict
                       else compare(requirement, fact, subject=subject,
                                    submittal_facts=facts))
            if rule_verdict is None and rule_unread and verdict.get("status") == NEEDS_ENGINEER_REVIEW:
                verdict = {**verdict, "rationale": f"{verdict.get('rationale') or ''}; {rule_unread}"}
            # THE TABLE-ROW REFUSAL OUTRANKS THE UNIT GUARD. Both end in
            # NEEDS_ENGINEER_REVIEW, but only one of them is the real reason: the
            # number is not a limit. Reporting "unit_mismatch" against a table row
            # tells a reviewer to go and reconcile kPa with bar, which would leave
            # them comparing a design pressure against a lookup boundary once the
            # units agreed.
            # A BLANK FIELD HAS NO NUMBER AND NO UNIT TO GUARD (B4 item 2: a blank
            # can now be paired by field name); `compare` has already said what
            # it is - left to be provided.
            # A STATEMENT HAS NO NUMBER AND NO UNIT TO GUARD either (CRS quick
            # wins, `match_statement`): `compare` has already said what it is -
            # a categorical verdict or an engineer's question - and "the
            # requirement is in no unit" would overwrite that with a reason
            # that is not the real one.
            if (fact is not None and not fact.get("is_blank") and rule_verdict is None
                    and requirement.get("requirement_type") not in (
                        requirements_3b.TABLE_ROW, requirements_3b.STATEMENT)):
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
            # B3: "NOT FOUND" IS NOT "NOT PRESENT". A requirement no field answered
            # is only the contractor's omission if every page was read into fields.
            if fact is None and verdict.get("status") == MISSING_INFORMATION:
                verdict = qualify_by_pages(verdict, pages_read)
            # THE PAIRING NOTE GOES ON LAST, after every verdict adjustment above,
            # because the unit guard and the tie branch REPLACE the rationale. A
            # prefix written before them would be silently dropped on exactly the
            # findings a reader most needs it on.
            if match["method"] == METHOD_MODEL_CHOICE:
                verdict = {**verdict, "rationale": (
                    f"{MODEL_PAIR_PREFIX}{match.get('reason') or ''}. "
                    f"{verdict.get('rationale') or ''}")}
            elif match["method"] == METHOD_FIELD_NAME:
                # A MODEL-NAMED PAIRING NEVER CARRIES A VERDICT. The arithmetic
                # is shown, the status waits for an engineer: measured on a copy
                # (2026-09-25) a seal-selection table's temperature band, paired
                # by name with the sheet's pumping temperature, read
                # NON_COMPLIANT - the right field and the wrong kind of rule.
                # B4 item 2: EVERY status is held, not only the two verdicts -
                # a blank field paired by a model-assigned name reads
                # MISSING_INFORMATION only if the pairing is right, so it waits
                # for the engineer too, with the comparison's own words kept.
                status = verdict.get("status")
                held = status != NEEDS_ENGINEER_REVIEW
                said = ("The numbers read" if status in (COMPLIANT, NON_COMPLIANT)
                        else "The comparison read")
                others = match.get("candidates") or []
                verdict = {**verdict,
                           "status": NEEDS_ENGINEER_REVIEW,
                           "rationale": (
                               f"{FIELD_NAME_PAIR_PREFIX}{match.get('matched_phrase') or ''}. "
                               + (f"{said} {status}, held for "
                                  "an engineer because the pairing is unconfirmed. " if held else "")
                               + (f"Blank fields under the same name, not used: {', '.join(others)}. "
                                  if others else "")
                               + f"{verdict.get('rationale') or ''}")}
            elif model_reason:
                # WHY NO MODEL PAIRING WAS MADE, in words, on the finding itself.
                # Without it "the model was off" and "the model was asked and
                # declined" read identically to an engineer.
                verdict = {**verdict, "rationale": (
                    f"{verdict.get('rationale') or ''} "
                    f"(model tier: {model_reason})")}
                model_reasons[model_reason] = model_reasons.get(model_reason, 0) + 1
            # HOW THE PAIRING WAS MADE, when it was not word for word (CRS
            # quick wins): through the synonym table, and/or with the clause's
            # unit read from its own text. Both are on the finding so an
            # engineer can see what the verdict rests on.
            if fact is not None and match["method"] == METHOD_CONTAINMENT:
                notes = []
                if match.get("synonym"):
                    notes.append(f"field linked through the synonym table as "
                                 f"'{match['synonym']}'")
                if requirement.get("unit_from_clause_text"):
                    notes.append(f"the clause's unit {requirement.get('raw_unit')!r} was "
                                 "read from its own text beside its number")
                if notes:
                    verdict = {**verdict, "rationale": (
                        f"{verdict.get('rationale') or ''} ({'; '.join(notes)})")}
            if (requirement.get("id"), (fact or {}).get("id")) in rejected_pairs:
                continue
            opinion = (model_opinions or {}).get(requirement.get("id"))
            # ONE FINDING PER ITEM, WRITTEN THROUGH THE BATCH HELPER: `_prepare_finding`
            # applies every gate `create_finding` would (duplicate check against
            # both the stored rows and this run's own `pending` batch, citation
            # resolution, confidence), but does not write; the row joins
            # `prepared_rows` and is written once for the whole run by
            # `_write_run_findings` below (perf/quick-wins) - the same gates the
            # per-item loop always had (CRS quick wins), now paid for once per run
            # instead of once per finding.
            row, unresolved = _prepare_finding(
                review_run_id=review_run_id, submittal_document_id=submittal_id,
                requirement=requirement, fact=fact, verdict=verdict,
                model_opinion=opinion,
                matched_phrase=(_normalise_for_match(fact.get("field_name"))
                                if match.get("items") and fact is not None
                                else match["matched_phrase"]),
                match_method=match["method"], pending=pending,
                stored_replaced=replace)
            pending[(row["requirement_id"], row["fact_id"])] = row["id"]
            prepared_rows.append(row)
            findings.append({**row, "unresolved_evidence": unresolved,
                             "citation_resolves": not unresolved})

    # ONE TRANSACTION FOR THE RUN (and the re-run's delete). Before the
    # datasheet self-checks below, which add their own rows to this run and
    # must not be deleted by it.
    _write_run_findings(review_run_id, prepared_rows, replace=replace)

    # OWNER ORDER 2c: DATASHEET SELF-CHECKS (kind B) - the sheet against
    # itself, pure arithmetic, no standard needed. Written before the code is
    # recommended, so a design pressure below the operating pressure counts
    # like any other unmet requirement.
    from . import datasheet_checks
    page_texts = {r["page_no"]: r["text"] or "" for r in connect().execute(
        "SELECT page_no, text FROM pages WHERE document_id = ?", (submittal_id,))}
    findings.extend(datasheet_checks.store(
        review_run_id, submittal_id,
        datasheet_checks.evaluate(facts, equipment_type=stored.get("equipment_type"),
                                  page_texts=page_texts),
        pages_read=pages_read))

    coverage = completeness_for_run(
        submittal_id, allowed_document_ids=allowed_document_ids,
        reference_coverage=reference_coverage, findings=findings)
    recommendation = recommend_code(findings, coverage,
                                    missing_references=missing_references or (),
                                    page_coverage=pages_read)
    _store_run_outcome(review_run_id, recommendation, coverage,
                       page_coverage=pages_read,
                       missing_references=missing_references or [])

    return {
        "review_run_id": review_run_id,
        "submittal_document_id": submittal_id,
        "requirements_evaluated": len(requirements),
        "facts_in_scope": len(facts),
        "matches_attempted": matches_attempted,
        "matches_made": matches_made,
        "model_matches": model_matches,
        **({"field_name_matches": field_name_matches,
            "field_naming": {k: v for k, v in field_names.items()
                             if k not in ("requirements", "facts")}}
           if field_names is not None else {}),
        "model_calls": budget.calls,
        "model_reasons": model_reasons,
        "sheet_kind": sheet,
        "rule_refusals": rule_refusals,
        "findings": findings,
        "by_status": {
            status: sum(1 for f in findings if f["compliance_status"] == status)
            for status in (COMPLIANT, NON_COMPLIANT, MISSING_INFORMATION,
                           CONDITIONAL, NOT_APPLICABLE, NEEDS_ENGINEER_REVIEW,
                           NOT_IN_DOCUMENT_SCOPE)
        },
        "completeness": coverage,
        "page_coverage": pages_read,
        "recommended_code": recommendation,
    }


def _unit_from_clause_text(requirement: dict, fact: dict | None) -> dict:
    """The requirement, with its unit read from its OWN sentence when the
    parser lost it. CRS quick wins (audit crs.md [C]: "P4.4 3.0 mm/s -> unit
    None").

    ONLY WHEN THE CLAUSE PRINTS THE FACT'S UNIT RIGHT AFTER THE SAME NUMBER:
    "shall not exceed 3.0 mm/s" against a fact in mm/s. Nothing is converted
    and nothing is guessed - a clause reading "1.3 times the design
    pressure" has no unit beside its number and keeps none, so it stays an
    engineer's question. The copy carries `unit_from_clause_text` so the
    finding says where the unit came from.
    """
    if (fact is None or fact.get("is_blank") or requirement.get("raw_unit")
            or requirement.get("raw_value") in (None, "")
            or requirement.get("requirement_type") != "numeric_limit"):
        return requirement
    unit = (fact.get("raw_unit") or "").strip()
    if not unit:
        return requirement
    text = " ".join(str(requirement.get("source_text")
                        or requirement.get("requirement_text") or "").split())
    pattern = (r"(?<![\d.])" + re.escape(str(requirement["raw_value"]).strip())
               + r"\s*" + re.escape(unit) + r"(?![\w/])")
    if not re.search(pattern, text, re.IGNORECASE):
        return requirement
    return {**requirement, "raw_unit": unit, "unit_from_clause_text": True}


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
#: Every containment hit was refused by a `match_rules` rule. The `refused`
#: list on the result names each hit and the rule that removed it.
REFUSED_BY_RULE = "refused_by_rule"
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
#: Owner order 2b: the fact was chosen as a parsed rule's OUTPUT field.
METHOD_RULE = "rule"


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


def match_by_containment(requirement: dict, facts: list[dict], *,
                         sheet_kind: str | None = None) -> dict:
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

    THREE RULES RUN BEFORE LONGEST-WINS. `match_rules` refuses a hit whose
    unit is in another dimension, whose sentence names a different kind of
    equipment than this sheet, or whose field is the INPUT of a lookup table
    rather than the quantity the table constrains. They run before the tie is
    resolved, not after, because the third one changes which field wins: on
    "the internal design pressure shall be according to the following table:
    Maximum Operating Pressure ...", longest-wins picked `maximum operating
    pressure` (the input) over `internal design pressure` (the constrained
    quantity), and a filter applied afterwards could only have turned that
    wrong pairing into silence. Measured on gold/PAIRS-216400C.csv: 8 false
    pairings and 0 correct before; the rules are what made the correct one
    reachable.

    `sheet_kind` is the equipment domain of the datasheet (see
    `match_rules.sheet_kind`); when the caller has none it is read from the
    field names, and when that is undecidable the domain rule never refuses.

    Returns `{"fact": ..., "matched_phrase": ..., "method": ...}` or
    `{"fact": None, "reason": ..., "candidates": [...]}`. Either shape carries
    `refused`, a list of `{"name", "reason"}` for every hit a rule removed, so
    a run can count what each rule did.
    """
    none: dict = {"fact": None, "matched_phrase": None, "method": None,
                  "reason": None, "candidates": [], "refused": []}
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
    if requirement.get("requirement_type") == requirements_3b.STATEMENT:
        # CRS QUICK WINS: a statement that names a datasheet field is an
        # engineer's question (or a closed categorical check), not a note
        # hidden as "requires another document". See `match_statement`.
        return match_statement(requirement, facts, sheet_kind=sheet_kind)
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

    # NUMBERS FIRST; A BLANK ONLY WHEN NO NUMBER ANSWERS THE CLAUSE (CRS
    # quick wins). A "vendor to advise" field is the most common real CRS
    # comment, and `compare` has always had its branch ("the submittal
    # leaves this field to be provided") - but no blank ever reached it,
    # because this pass skipped every fact without a number.
    hits = _containment_hits(requirement, subject, facts, fact_has_number)
    if not hits:
        hits = _containment_hits(requirement, subject, facts,
                                 lambda f: bool(f.get("is_blank")))
    if not hits:
        return none
    return _resolve_hits(requirement, facts, hits, sheet_kind=sheet_kind)


def _containment_hits(requirement: dict, subject: str, facts: list[dict],
                      eligible) -> list[dict]:
    """Every fact `eligible` accepts whose field name is contained, as whole
    words, in `subject` - literally, or through the field synonym table
    (`field_links.canonical`, applied to BOTH sides).

    A hit made only through the table carries `synonym` = the canonical
    phrase, so the finding can say the pairing rests on it.
    """
    rejected = _rejected_keys_for(requirement)
    tag_scoped = facts_are_tag_scoped(facts)
    canonical_subject = field_links.canonical(subject)
    subject_form = _match_form(subject)
    hits: list[dict] = []
    for fact in facts:
        if not eligible(fact):
            continue
        if fact_key(fact, tag_scoped=tag_scoped) in rejected:
            # A HUMAN ALREADY SAID THIS PAIR IS WRONG. Asking again is how an
            # engineer learns the machine does not listen, and they stop
            # correcting it.
            continue
        name = _normalise_for_match(fact.get("field_name"))
        canonical_name, item = field_links.field_of(name)
        if len(name) < 4 or len(canonical_name) < 4:
            # A one- or two-word fragment is contained in half of everything.
            continue
        if _contains_words(subject, name):
            hits.append({"fact": fact, "name": name, "key": canonical_name,
                         "item": item, "synonym": None})
        elif _contains_words(canonical_subject, canonical_name):
            hits.append({"fact": fact, "name": name, "key": canonical_name,
                         "item": item, "synonym": canonical_name})
        elif (_contains_words(subject_form, _match_form(name))
              and len(_match_form(name)) >= 4
              and _same_quantity_units(requirement, fact)):
            # ABBREVIATION / GENERIC-WORD TOLERANCE (audit N5): "Noise" meets
            # "Noise level", "Maximum operating temperature" meets "Max
            # operating temperature". Only the fact name's own words are
            # searched inside the subject (never the reverse, which would let
            # "Pressure" claim "Design pressure"), and only when both sides
            # state a unit of the same quantity - this route is the loosest
            # one, so it carries the strictest unit gate.
            hits.append({"fact": fact, "name": name, "key": canonical_name,
                         "item": item, "synonym": None})
    return hits


#: Abbreviations a datasheet label and a standard's sentence spell differently.
_ABBREVIATIONS_FOR_MATCH = {
    "max": "maximum", "min": "minimum", "temp": "temperature",
    "press": "pressure", "pres": "pressure", "dia": "diameter",
}
#: Words that only say "this is the number": dropped from the END of a name.
_GENERIC_TRAILING_WORDS = frozenset({"level", "value", "values", "rating", "data"})


def _match_form(text: str) -> str:
    """`_normalise_for_match` text with abbreviations spelled out and trailing
    generic words (level, value, rating, data) removed. Never empties a name
    to nothing: a name made only of generic words is left as it was."""
    words = [_ABBREVIATIONS_FOR_MATCH.get(w, w) for w in text.split()]
    trimmed = list(words)
    while len(trimmed) > 1 and trimmed[-1] in _GENERIC_TRAILING_WORDS:
        trimmed.pop()
    return " ".join(trimmed)


def _same_quantity_units(requirement: dict, fact: dict) -> bool:
    """Both sides state a unit, and it is the same unit or the same known
    dimension. A missing or unknown unit is NOT compatible here."""
    left = str(requirement.get("raw_unit") or "").strip()
    right = str(fact.get("raw_unit") or "").strip()
    if not left or not right:
        return False
    if claims.same_unit(claims.Measurement("", left, None, None, None),
                        claims.Measurement("", right, None, None, None)):
        return True
    left_dim, right_dim = claims.unit_dimension(left), claims.unit_dimension(right)
    return left_dim is not None and left_dim == right_dim


def _item_of(hit: dict) -> str | None:
    """Which piece of equipment (or nozzle) a hit's value is about."""
    return hit.get("item") or hit["fact"].get("equipment_tag")


def _resolve_hits(requirement: dict, facts: list[dict], hits: list[dict], *,
                  sheet_kind: str | None) -> dict:
    """The rules, then longest-wins, then the tie - shared by the numeric and
    the statement passes so both obey the same three `match_rules` rules."""
    none: dict = {"fact": None, "matched_phrase": None, "method": None,
                  "reason": None, "candidates": [], "refused": []}

    # THE RULES, BEFORE THE TIE. See the docstring: rule 3 is what lets the
    # constrained quantity win over the table's input.
    sheet = sheet_kind if sheet_kind is not None else match_rules.sheet_kind(facts)
    refused: list[dict] = []
    allowed: list[dict] = []
    for hit in hits:
        reason = match_rules.refusal(requirement, hit["fact"], sheet=sheet)
        if reason is None:
            allowed.append(hit)
        else:
            refused.append({"name": hit["name"], "reason": reason})
    if not allowed:
        return {**none, "reason": REFUSED_BY_RULE if refused else None,
                "refused": refused}

    # LONGEST WINS, measured on the field's CANONICAL name, so "n3 size"
    # (read as "nozzle size") competes as the nozzle's size it is.
    longest = max(len(h["key"]) for h in allowed)
    best = [h for h in allowed if len(h["key"]) == longest]
    if len(best) > 1:
        # THE SAME FIELD FOR SEVERAL ITEMS IS NOT A TIE (CRS quick wins).
        # "Nozzle size >= 50 mm" against N1, N2 and N3, or noise level for
        # P-101A and P-101B, is one clause about each item - an engineer
        # writes a comment per offending item. Every hit must be the same
        # field (one canonical name) about a DIFFERENT, named item; anything
        # else is still the question it always was.
        items = [_item_of(h) for h in best]
        if (len({h["key"] for h in best}) == 1 and all(items)
                and len(set(items)) == len(items)):
            ordered = sorted(best, key=_item_of)
            return {"fact": ordered[0]["fact"], "matched_phrase": ordered[0]["name"],
                    "method": METHOD_CONTAINMENT, "reason": None, "candidates": [],
                    "refused": refused, "synonym": ordered[0]["synonym"],
                    "items": [h["fact"] for h in ordered]}
        return {**none, "reason": AMBIGUOUS_MATCH,
                "candidates": sorted(h["name"] for h in best),
                "refused": refused}
    return {"fact": best[0]["fact"], "matched_phrase": best[0]["name"],
            "method": METHOD_CONTAINMENT, "reason": None, "candidates": [],
            "refused": refused, "synonym": best[0]["synonym"]}


def match_statement(requirement: dict, facts: list[dict], *,
                    sheet_kind: str | None = None) -> dict:
    """The datasheet field a `statement` clause is about, or none. CRS quick
    wins (audit crs.md defect 5).

    A statement ("Manways shall have a minimum inside diameter of 450 mm",
    "Nozzle flanges shall have a minimum pressure rating of Class 300") has
    no parsed number, so the numeric pass never saw it and `compare` sent it
    to "requires another document" - hiding a manway, a flange class, a
    radiography extent and a blank PWHT field on the audit's vessel sheet.

    TWO WAYS, BOTH DETERMINISTIC:
      * a CLOSED CATEGORICAL clause (`field_links.categorical_requirement`:
        flange class, radiography extent, PWHT yes/no) pairs with the one
        field of its family - by the family, not by words in the subject;
      * otherwise the subject is searched as the numeric pass searches it
        (whole words, through the synonym table), over blank, numeric and
        closed-answer facts alike. What such a pairing produces is decided by
        `compare`: blank -> the contractor's to provide; anything else -> a
        question for the engineer with both sides shown, never a verdict.
    """
    none: dict = {"fact": None, "matched_phrase": None, "method": None,
                  "reason": None, "candidates": [], "refused": []}
    text = requirement.get("source_text") or requirement.get("requirement_text") or ""
    rule = field_links.categorical_requirement(text)
    if rule is not None:
        rejected = _rejected_keys_for(requirement)
        tag_scoped = facts_are_tag_scoped(facts)
        hits = []
        for fact in facts:
            name = _normalise_for_match(fact.get("field_name"))
            key, item = field_links.field_of(name)
            if (key in field_links.FAMILY_FIELDS[rule["family"]]
                    and fact_key(fact, tag_scoped=tag_scoped) not in rejected):
                hits.append({"fact": fact, "name": name, "key": key, "item": item,
                             "synonym": key if key != name else None})
        if hits:
            return _resolve_hits(requirement, facts, hits, sheet_kind=sheet_kind)
    subject = _normalise_for_match(requirement.get("subject"))
    if not subject:
        return none
    hits = _containment_hits(
        requirement, subject, facts,
        lambda f: bool(f.get("is_blank")) or fact_has_number(f)
        or datasheets.is_categorical_value(f.get("field_value")))
    if not hits:
        return none
    return _resolve_hits(requirement, facts, hits, sheet_kind=sheet_kind)


# ------------------------------------------- B4 5.3: field-name equality
#
# Behind `settings.geometry_reader_enabled`. A requirement and a fact are
# paired when the labelling model gave BOTH the same canonical field name
# under `field_naming`'s code gates (dictionary index, verified quote, the
# quote names the field). The model never saw a value; it only named.

#: How the pairing was made: equal model-assigned field names. Not
#: deterministic - the names came from a model - so a finding paired this way
#: carries CONFIDENCE_MODEL_ASSISTED and says so in its rationale.
METHOD_FIELD_NAME = "field_name"
FIELD_NAME_PAIR_PREFIX = ("Paired by model-assigned field name; engineer must "
                          "confirm. Field: ")


def match_by_field_name(requirement: dict, facts: list[dict], names: dict, *,
                        sheet_kind: str | None = None) -> dict | None:
    """The fact whose canonical field name EQUALS the requirement's, or None
    to let containment decide.

    Every guard containment has still applies: only a matchable requirement
    with a number, only facts with a number, never a pairing an engineer
    rejected, and the `match_rules` refusals. Two or more facts under the
    same name is a TIE, returned as AMBIGUOUS_MATCH - never a pick.
    None (fall through) when the requirement is unnamed or no fact passes.
    """
    if not is_matchable(requirement) or requirement.get("raw_value") in (None, ""):
        return None
    field = (names.get("requirements") or {}).get(str(requirement.get("id")))
    if not field:
        return None
    fact_names = names.get("facts") or {}
    rejected = _rejected_keys_for(requirement)
    tag_scoped = facts_are_tag_scoped(facts)
    # B4 item 2: a BLANK field pairs too - "the sheet leaves this to be
    # provided" is an answer about the requirement's quantity.
    hits = [f for f in facts
            if (fact_has_number(f) or f.get("is_blank"))
            and fact_names.get(str(f.get("id"))) == field
            and fact_key(f, tag_scoped=tag_scoped) not in rejected]
    sheet = sheet_kind if sheet_kind is not None else match_rules.sheet_kind(facts)
    refused: list[dict] = []
    allowed: list[dict] = []
    for fact in hits:
        reason = match_rules.refusal(requirement, fact, sheet=sheet)
        if reason is None:
            allowed.append(fact)
        else:
            refused.append({"name": field, "reason": reason})
    if not allowed:
        return None
    if len(allowed) > 1:
        filled = [f for f in allowed if fact_has_number(f) and not f.get("is_blank")]
        if not filled:
            # EVERY CANDIDATE IS BLANK: whichever is cited, the answer is the
            # same - the sheet leaves this quantity to be provided. The one
            # whose OWN label is the name comes first, then by page and label;
            # the others are NAMED; no value was chosen between.
            from .field_naming import own_names
            ordered = sorted(allowed, key=lambda f: (field not in own_names(f),
                                                     f.get("page") or 0,
                                                     f.get("field_label") or ""))
            return {"fact": ordered[0], "matched_phrase": field, "method": METHOD_FIELD_NAME,
                    "reason": None,
                    "candidates": sorted({f"{f.get('field_label') or field} (page {f.get('page')})"
                                          for f in ordered[1:]}),
                    "refused": refused}
        if len(filled) == 1:
            # ONE FILLED VALUE AND THE REST BLANK is not a tie: the blanks
            # are the columns the sheet left open (NORMAL beside RATED). The
            # filled one is used and the blanks are NAMED in the rationale.
            return {"fact": filled[0], "matched_phrase": field, "method": METHOD_FIELD_NAME,
                    "reason": None,
                    "candidates": sorted({f"{f.get('field_label') or field} (page {f.get('page')})"
                                          for f in allowed if f is not filled[0]}),
                    "refused": refused}
        return {"fact": None, "matched_phrase": None, "method": None,
                "reason": AMBIGUOUS_MATCH,
                "candidates": sorted({f"{field} (page {f.get('page')})" for f in allowed}),
                "refused": refused}
    return {"fact": allowed[0], "matched_phrase": field, "method": METHOD_FIELD_NAME,
            "reason": None, "candidates": [], "refused": refused}


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
        "keep_alive": settings.ollama_keep_alive,
        "options": {
            "temperature": 0,
            "seed": settings.match_seed,
            "num_ctx": settings.num_ctx,
            "num_predict": 120,
            "num_thread": settings.num_thread,
            # The same runner as every other caller (model_transport.
            # runner_options): a missing num_batch made Ollama reload the model.
            "num_batch": settings.num_batch,
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
            " WHERE submittal_document_id = ? AND equipment_tag IS NOT NULL"
            " AND superseded_at IS NULL",           # current facts only (#179)
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
        inserted = conn.execute(
            "INSERT OR IGNORE INTO review_pair_rejections"
            " (requirement_key, fact_key, requirement_id, fact_id,"
            "  rejected_by, rejected_at, reason) VALUES (?,?,?,?,?,?,?)",
            (requirement_key(requirement), fact_key(fact, tag_scoped=scoped),
             requirement.get("id"), fact.get("id"), rejected_by, now, reason)).rowcount
        # B10: an engineer's rejection is audited like their code decision -
        # same transaction, ids only. A repeat (ignored) rejection records nothing.
        if inserted:
            _audit(conn, "review.pair_rejected",
                   {"id": rejected_by, "email": rejected_by} if rejected_by else None,
                   requirement.get("id"), detail=f"fact={fact.get('id')}")
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


def attach_crs_context(findings: list[dict]) -> list[dict]:
    """What the CRS wording needs that a finding row does not carry, looked
    up by the finding's own ids (CRS quick wins, `crs_mapping`):

      * `requirement_limit` - the clause's parsed subject, operator, value and
        unit, so the comment says "requires corrosion allowance ... not less
        than 3 mm" instead of pasting the clause; with the unit recovered
        from the clause text exactly as the comparison recovered it
        (`_unit_from_clause_text`);
      * `crs_field_label` / `crs_is_blank` - the field as the DATASHEET
        printed it, and whether the sheet left it blank.

    READ-ONLY, in place, and nothing is invented: a finding whose requirement
    or fact is gone gets nothing added, and the wording falls back to the
    clause's own words. Returns the same list.
    """
    req_ids = sorted({f["requirement_id"] for f in findings if f.get("requirement_id")})
    fact_ids = sorted({f["fact_id"] for f in findings if f.get("fact_id")})
    requirements: dict = {}
    facts: dict = {}
    conn = connect()
    for start in range(0, len(req_ids), 500):
        chunk = req_ids[start:start + 500]
        marks = ",".join("?" for _ in chunk)
        for r in conn.execute(
                "SELECT id, subject, operator, raw_value, raw_unit, requirement_type,"
                " source_text, requirement_text FROM standard_requirements"
                f" WHERE id IN ({marks})", chunk):
            requirements[r["id"]] = dict(r)
    for start in range(0, len(fact_ids), 500):
        chunk = fact_ids[start:start + 500]
        marks = ",".join("?" for _ in chunk)
        for r in conn.execute(
                "SELECT id, field_label, field_value, raw_unit, is_blank"
                f" FROM submittal_facts WHERE id IN ({marks})", chunk):
            facts[r["id"]] = dict(r)
    for f in findings:
        fact = facts.get(f.get("fact_id"))
        requirement = requirements.get(f.get("requirement_id"))
        if requirement is not None:
            governing = _unit_from_clause_text(requirement, fact)
            f["requirement_limit"] = {k: governing.get(k) for k in
                                      ("subject", "operator", "raw_value", "raw_unit",
                                       "requirement_type")}
        if fact is not None:
            f["crs_field_label"] = fact.get("field_label")
            f["crs_is_blank"] = bool(fact.get("is_blank"))
    return findings


def _store_run_outcome(review_run_id: str, recommendation: dict,
                       coverage: dict, *, page_coverage: dict | None = None,
                       missing_references: list[str] | None = None) -> None:
    """Persist the AI recommendation and the completeness it was gated on.

    B3: `page_coverage` is the page ledger's summary AT THE TIME OF THE RUN -
    which pages were read into fields and why the others were not - so the
    run keeps saying what it searched after the ledger is refreshed again.

    The FINAL code is not written here. The AI recommends; the engineer
    decides, and `record_engineer_code` is where that happens - section 15's
    "the engineer's final action is governance, not the initial review".
    """
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE review_runs SET status = ?, refusal_reason = ?,"
            " updated_at = ?, completed_at = ? WHERE id = ?",
            ("completed", json.dumps({
                "recommended_code": recommendation["code"],
                "reason": recommendation["reason"],
                # 2g: the technical sentence, for "Details" on the screen.
                "details": recommendation.get("details"),
                "completeness": coverage,
                "page_coverage": page_coverage,
                # B5: each cited standard not held, with its status, AS OF
                # THIS RUN - the run keeps saying what it could not check.
                "missing_references": [
                    {"identifier": ref, "status": MISSING_LOCALLY}
                    for ref in (missing_references or [])],
            # completed_at: the readiness strip's "since the last run" is
            # measured from here, not from updated_at (which the engineer's
            # code decision moves later).
            }), _now(), _now(), review_run_id))


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
    # THE CONFIGURED LABELS (reference/review_codes.json), which default to
    # DEFAULT_CODES: a client coding A/B/C/D is offered and stores A/B/C/D.
    codes = review_codes()
    if code not in codes:
        raise ComparisonError(
            f"{code!r} is not one of the review codes: "
            + ", ".join(codes))
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
        # B10: IN THE SAME TRANSACTION. A decision whose audit row could not be
        # written is rolled back with it - an unaudited code is not recorded.
        _audit(conn, "review.code_recorded", actor, review_run_id,
               detail=f"recommended={recommended} final={code} "
                      f"overridden={bool(reason)}")
    outcome = {
        **stored,
        "final_code": code,
        "reviewer": reviewer,
        "override_reason": reason,
        "decided_at": now,
    }
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


def _audit(conn, action: str, actor: dict | None, resource_id: str | None,
           detail: str | None = None) -> None:
    """Durable record of a review decision. Ids and codes only.

    Written on the CALLER'S connection, inside the caller's transaction, and
    never swallowed (B10): it used to catch every error and carry on, so a
    decision could be recorded with no audit row at all."""
    conn.execute(
        """INSERT INTO audit_events
               (at, actor_user_id, actor_username, action,
                resource_type, resource_id, outcome, detail)
           VALUES (?, ?, ?, ?, 'review', ?, 'ok', ?)""",
        (_now(), (actor or {}).get("id"),
         ((actor or {}).get("email") or "unauthenticated")[:200],
         action, resource_id, detail))
