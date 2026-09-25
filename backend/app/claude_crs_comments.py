"""Draft the CRS comments: the model WRITES the prose, Python CHECKS every fact.

WHAT THE CLIENT RECEIVES. The CRS (`crs_export.py`) is one row per finding:
the page/section of the reviewed document, the comment, who made it, and the
recommended review code on the summary row. Today the comment column is
machine text - `crs_mapping._comment_text` concatenates "Requirement: ...",
"Submitted: ..." and the rationale - which is TRUE but reads like a log line.
A reviewer at Saudi Aramco or the client writes something else: two or three
sentences that cite the clause, state what was submitted against what is
required, and tell the contractor what to do. This module asks the model for
that voice and then refuses every draft it cannot prove is honest.

THE DIVISION OF LABOUR IS `reader_api.py`'S, AND IT IS NOT NEGOTIABLE. The
model never decides compliance, never picks a code and never supplies a fact:
the status, the values, the clause and the page all arrive from the stored
finding, and the model's only job is to say them well. `accept()` is the
enforcement: a comment that cites a different clause, drops the standard
code, or mentions a number that is not among the inputs is thrown away WITH A
NAMED REASON - `Reason`, on `reader_api.Reason`'s pattern - never repaired,
never quietly kept.

WHY EVERY NUMBER IS CHECKED. A CRS comment is quoted back by the contractor
and argued over in a meeting. "Submitted 8 g/L against a 5 g/L limit" with a
model-invented "typically 6 g/L" in the middle is a comment the engineer
cannot defend, and the invention is the kind of thing a fluent model does
without noticing. So every number in the draft must appear in the inputs
(after `reader_api._fold_numbers`, so "8,300" and "8300" are one number); the
clause's own digits and the page reference are excused because they are
inputs too, and are stripped before the check so "Para. 6.2.3" is not read as
three numbers.

WHY TWO RUNS BUT NOT EQUALITY. `reader_api.read_sentence` asks twice and
keeps a proposal only when both runs agree, because a limit has one right
answer. A comment is prose, and two honest drafts of the same finding differ
in wording; demanding equality would reject nearly everything and prove
nothing. What CAN be demanded is that both drafts pass the gate: a finding
the model can state honestly once but not twice is one it is not reliably
reading, and that is reported as `model_unstable` rather than shipped on the
strength of the lucky run.

MARKED AS DRAFTED, ALWAYS. An accepted draft enters the sheet under
`MODEL_DRAFT_PREFIX` and the machine comment it replaces is kept beside it
(`apply_drafts`), so the engineer sees which words a model wrote, can compare
them with the deterministic text, and edits before the sheet leaves. The
prefix is a constant so the exporter, a UI and a test all name it identically.

NOTHING IS WRITTEN TO THE DATABASE. `review_findings` has no engineer-comment
column: `response_text` is the contractor's answer, `finding` and
`ai_rationale` are the deterministic engine's words that `crs_mapping` prints,
and overwriting either would make the machine comment unrecoverable and put
model prose where the code expects arithmetic. Adding a column is a migration
this task may not make. So `draft_run` returns the drafts and `apply_drafts`
lays them over a `build_crs_view` result in memory; where they are stored is
the integration's decision, under the same prefix.

THE MODEL IS INJECTED AS A CALLABLE (prompt -> raw text), exactly as
`reader_api` and `claude_selection` do. This module imports no HTTP client
and opens no socket - `tests/test_socket_containment.py` guards the whole
package - and every test runs against a fake that returns a string.
"""

from __future__ import annotations

import copy
import json
from enum import Enum

from . import comparison, crs_mapping
from .crs_export import row_reference
from .reader_api import _NUMBER, _contains, _fold, _fold_numbers

# --------------------------------------------------------------- constants

#: THE EXACT PREFIX a model-drafted comment carries on the sheet. One
#: definition, so an exporter, a UI and a later store all mark a draft the
#: same way and a reader can grep for it.
MODEL_DRAFT_PREFIX = "[Draft by model - engineer to confirm] "

#: Longest draft accepted, comment and action together. A CRS cell that runs
#: past this is a memo, not a comment; the template's comment column is 93
#: characters wide and the engineer has to read the row at a glance.
MAX_DRAFT_CHARS = 600

#: Words a NON_COMPLIANT comment may not contain, and words a COMPLIANT one
#: may not. DELIBERATELY SMALL and exactly these: the gate is not a sentiment
#: model, it catches the one defect that reverses a verdict in the client's
#: hands - a row filed as non-compliant whose prose tells the contractor they
#: are fine, or the reverse. Negated spellings of "acceptable" ("not
#: acceptable") are stripped before the check so a correct rejection is not
#: read as an approval; "unacceptable" is a different word and never matches.
NON_COMPLIANT_MAY_NOT_SAY = ("complies", "acceptable", "no comment")
COMPLIANT_MAY_NOT_SAY = ("does not comply", "shall revise")
_NEGATED_ACCEPTABLE = ("not acceptable", "is not acceptable")


class Reason(Enum):
    """Why a draft was thrown away. A NAMED REASON, ALWAYS.

    A plain `Enum` whose members carry the stored string, and every caller
    uses `.value` - `reader_api.Reason`'s rule, for its reason: a `str` mixin
    lets a raw member reach JSON.

    The count of these is what a run report says: "14 drafted, 3 rejected:
    2 number-not-in-inputs, 1 model-unstable". "The model drafted nothing"
    and "the model invented three numbers and we dropped them" are different
    facts, and only one is a reason to look at the prompt.
    """

    #: The answer was not the JSON object that was asked for.
    MODEL_MALFORMED = "model_malformed"
    #: The JSON parsed but carried no comment text.
    COMMENT_MISSING = "comment_missing"
    #: The clause number the finding cites does not appear in the comment.
    CLAUSE_NOT_CITED = "clause_not_cited"
    #: The standard's code does not appear in the comment.
    STANDARD_NOT_CITED = "standard_not_cited"
    #: A number in the comment or action is not among the finding's inputs.
    #: This is the fabrication catch.
    NUMBER_NOT_IN_INPUTS = "number_not_in_inputs"
    #: Comment plus action longer than `MAX_DRAFT_CHARS`.
    TOO_LONG = "too_long"
    #: The prose says the opposite of the stored status.
    STATUS_CONTRADICTED = "status_contradicted"
    #: Only one of two runs produced a draft that passes the gate.
    MODEL_UNSTABLE = "model_unstable"


# ------------------------------------------------------------------ inputs

def standard_code(finding: dict) -> str:
    """The code the reviewer cites - "SAES-D-001", never "SAES-D-001.pdf".

    `main.py`'s CRS route puts the standard's FILENAME on the finding as
    `standard_name`; the clause citation the client expects carries the code
    alone. The extension is stripped and nothing else is guessed: a finding
    with neither a name nor an id cites nothing, and the gate then refuses
    every draft for it rather than letting the model pick a standard.
    """
    name = str(finding.get("standard_name")
               or finding.get("standard_document_id") or "").strip()
    lowered = name.lower()
    for ext in (".pdf", ".docx", ".doc"):
        if lowered.endswith(ext):
            return name[: -len(ext)]
    return name


def clause_citation(finding: dict) -> str:
    """"SAES-D-001 Para. 6.2.3" - the form the prompt asks the model to copy
    character for character. Code alone when the finding names no clause."""
    code = standard_code(finding)
    clause = str(finding.get("standard_clause") or "").strip()
    if code and clause:
        return f"{code} Para. {clause}"
    return code or clause


def draft_inputs(finding: dict, row: dict) -> dict:
    """EVERYTHING THE MODEL IS ALLOWED TO KNOW, in one place.

    The prompt is built from this and the number check is run against this,
    so a fact the model could only have got from somewhere else is, by
    construction, a fact it invented. Values that the finding does not carry
    are absent, never defaulted: `required_value`, `required_unit` and the
    comparator exist on findings written from a parsed limit and not on one
    written from a statement or a table pointer.
    """
    row = row or {}
    return {
        "standard_code": standard_code(finding),
        "clause": str(finding.get("standard_clause") or "").strip(),
        "citation": clause_citation(finding),
        "requirement": str(finding.get("requirement_source_text")
                           or finding.get("requirement") or "").strip(),
        "matched_field": str(finding.get("matched_phrase") or "").strip(),
        "submitted_value": str(finding.get("contractor_evidence_text")
                               or "").strip(),
        "submitted_unit": str(finding.get("submitted_unit") or "").strip(),
        "required_value": str(finding.get("required_value") or "").strip(),
        "required_unit": str(finding.get("required_unit") or "").strip(),
        "comparator": str(finding.get("comparator")
                          or finding.get("operator") or "").strip(),
        "status": str(finding.get("compliance_status") or "").strip(),
        "page_section": str(row.get("page_section") or "").strip(),
        "equipment_tag": str(finding.get("equipment_tag") or "").strip(),
    }


# ------------------------------------------------------------------- prompt

#: THE STYLE RULES ARE IN THE PROMPT AND THE GATE ENFORCES THEM. Asking for the
#: right thing is cheaper than rejecting the wrong thing twice; the gate is
#: still what decides.
PROMPT = """You are a senior document reviewer at a Saudi Aramco-style operating \
company, writing ONE comment for a Comment Resolution Sheet (CRS) on a \
contractor's submittal. The review has ALREADY been decided by the engineering \
comparison below. You do not decide compliance; you state the finding well.

Answer as JSON only:
{"comment": "<2-3 sentences>", "action": "<what the contractor must do, one \
sentence, or null if the finding is compliant>"}

STYLE RULES, ALL MANDATORY:
1. Cite the clause EXACTLY as given below, character for character, e.g. \
"SAES-D-001 Para. 6.2.3". The comment must contain that citation.
2. State the submitted value and the required value, with their units, as \
given below. Do not round, convert or restate them.
3. Use NO number that is not in the inputs below. No typical values, no \
margins, no percentages, no estimates. A number you did not receive is an \
invention and the comment will be discarded.
4. No speculation about why the contractor did what they did or what else \
might be wrong. Only what the inputs state.
5. The comment must agree with the compliance status. A NON_COMPLIANT finding \
is stated as a deviation. A COMPLIANT finding notes conformance and has \
action null. A NEEDS_ENGINEER_REVIEW finding says what could not be verified.
6. The action is in the imperative voice of the company: "Contractor shall \
revise ...", "Contractor shall confirm ...".
7. Formal, direct, third person. No greetings, no hedging, no bullet points.

INPUTS:
"""


def build_prompt(finding: dict, row: dict) -> str:
    """The prompt for one finding. A function, so the inputs are rendered in
    exactly one place and `draft_inputs` is the one list of what the model
    sees."""
    inputs = draft_inputs(finding, row)
    lines = []
    for label, key in (
        ("Standard", "standard_code"),
        ("Clause", "clause"),
        ("Cite as", "citation"),
        ("Requirement", "requirement"),
        ("Matched field", "matched_field"),
        ("Submitted value", "submitted_value"),
        ("Submitted unit", "submitted_unit"),
        ("Required value", "required_value"),
        ("Required unit", "required_unit"),
        ("Comparator", "comparator"),
        ("Compliance status", "status"),
        ("Page/Section", "page_section"),
        ("Equipment", "equipment_tag"),
    ):
        value = inputs[key]
        lines.append(f"{label}: {value if value else '(not given)'}")
    return PROMPT + "\n".join(lines) + "\n\nAnswer with JSON and nothing else."


# -------------------------------------------------------------------- parse

def parse_response(raw: str) -> tuple[dict | None, str | None]:
    """Strict parse. Anything malformed yields no draft AND A REASON.

    Never repaired: half-JSON patched into a comment would be this module
    inventing words and calling them the model's. A JSON code fence around
    an otherwise valid object is stripped, because that is formatting and not
    content.
    """
    if not isinstance(raw, str):
        return None, Reason.MODEL_MALFORMED.value
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        body = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, Reason.MODEL_MALFORMED.value
    if not isinstance(body, dict) or "comment" not in body:
        return None, Reason.MODEL_MALFORMED.value
    comment = body.get("comment")
    action = body.get("action")
    return {
        "comment": str(comment).strip() if comment is not None else "",
        "action": (str(action).strip()
                   if action not in (None, "", "null") else None),
    }, None


# --------------------------------------------------------------- the gate

def _numbers(text: str) -> set[float]:
    return {float(n) for n in _NUMBER.findall(_fold_numbers(text))}


def _strip_citations(folded: str, inputs: dict) -> str:
    """The draft with the clause citation, the standard code, the clause
    number and the page/section removed, so their digits are not read as
    numbers. "SAES-D-001 Para. 6.2.3" would otherwise contribute 001, 6.2
    and 3 to the check, and a citation is a name, not a quantity."""
    for key in ("citation", "standard_code", "page_section", "clause"):
        piece = _fold(inputs[key])
        if piece:
            folded = folded.replace(piece, " ")
    return folded


def _numbers_in_inputs(inputs: dict) -> set[float]:
    """Every number the model was handed. Includes the page/section text so a
    draft that repeats "submittal p4" is not refused for the 4."""
    text = " ".join(v for v in inputs.values() if v)
    return _numbers(text)


def _status_contradicted(status: str, prose: str) -> bool:
    folded = _fold(prose)
    if status == comparison.NON_COMPLIANT:
        for negated in _NEGATED_ACCEPTABLE:
            folded = folded.replace(negated, " ")
        return any(_contains(folded, phrase)
                   for phrase in NON_COMPLIANT_MAY_NOT_SAY)
    if status == comparison.COMPLIANT:
        return any(_contains(folded, phrase)
                   for phrase in COMPLIANT_MAY_NOT_SAY)
    return False


def accept(proposal: dict, finding: dict, row: dict) -> dict:
    """THE GATE. A draft is kept only when ALL of these hold:

      1. it has a comment
      2. the clause number appears in the comment
      3. the standard code appears in the comment
      4. every number in comment + action appears in the inputs
         (`_fold_numbers` both sides; the citation and page are excused)
      5. comment + action is at most `MAX_DRAFT_CHARS`
      6. the prose does not contradict the stored status
      7. (in `draft_comment`) both runs passed 1-6

    Rules 2-4 are one idea: EVERY FACT IN THE COMMENT MUST BE RE-DERIVABLE
    FROM THE FINDING BY SOMETHING THAT CANNOT IMAGINE. Rule 6 is the one that
    reverses a verdict in the client's hands, which is worse than a lost
    comment. Rules fire in this order and the FIRST failure is the reason,
    so counts are stable across runs.

    Returns `{"accepted": bool, "reason": str | None, "proposal": ...}`.
    """
    inputs = draft_inputs(finding, row)
    comment = (proposal or {}).get("comment") or ""
    action = (proposal or {}).get("action") or ""

    def refuse(reason: Reason) -> dict:
        return {"accepted": False, "reason": reason.value, "proposal": proposal}

    if not comment.strip():
        return refuse(Reason.COMMENT_MISSING)
    folded_comment = _fold(comment)
    if not inputs["clause"] or not _contains(folded_comment, _fold(inputs["clause"])):
        return refuse(Reason.CLAUSE_NOT_CITED)
    if not inputs["standard_code"] or not _contains(
            folded_comment, _fold(inputs["standard_code"])):
        return refuse(Reason.STANDARD_NOT_CITED)
    prose = f"{comment} {action}"
    allowed = _numbers_in_inputs(inputs)
    found = _numbers(_strip_citations(_fold(prose), inputs))
    if not found <= allowed:
        return refuse(Reason.NUMBER_NOT_IN_INPUTS)
    if len(comment) + len(action) > MAX_DRAFT_CHARS:
        return refuse(Reason.TOO_LONG)
    if _status_contradicted(inputs["status"], prose):
        return refuse(Reason.STATUS_CONTRADICTED)
    return {"accepted": True, "reason": None, "proposal": proposal}


def rejection_counts(rejected) -> dict:
    """`{reason: n}`, for the sentence a run report has to be able to say."""
    counts: dict = {}
    for r in rejected:
        reason = r["reason"] if isinstance(r, dict) else r
        counts[reason] = counts.get(reason, 0) + 1
    return counts


# ------------------------------------------------------------ the two runs

def draft_comment(finding: dict, row: dict, model_call, second_call=None) -> dict:
    """One finding through the model TWICE and each answer through the gate.

    BOTH RUNS MUST PASS; THE FIRST IS KEPT. Exact equality is not required -
    a comment is prose and two honest drafts differ in wording, so an equality
    rule would reject nearly everything and prove nothing. What is required is
    that the model can state the finding honestly on demand and not only by
    luck: when exactly one run passes, the result is `model_unstable`, never
    the draft that happened to pass. When neither passes, the first run's
    reason is reported, since that is the one the caller would have seen.

    `second_call` defaults to `model_call` again; determinism is the caller's
    to arrange, this is what checks that it held.

    Returns `{"finding_id", "accepted", "comment", "action", "reason"}`.
    """
    finding_id = str(finding.get("id") or finding.get("finding_id") or "")
    prompt = build_prompt(finding, row)
    out = {"finding_id": finding_id, "accepted": False,
           "comment": None, "action": None, "reason": None}

    first, err = parse_response(model_call(prompt))
    if err:
        return {**out, "reason": err}
    again = second_call if second_call is not None else model_call
    second, err2 = parse_response(again(prompt))
    if err2:
        return {**out, "reason": err2}

    gate1 = accept(first, finding, row)
    gate2 = accept(second, finding, row)
    if gate1["accepted"] and gate2["accepted"]:
        return {**out, "accepted": True, "comment": first["comment"],
                "action": first["action"]}
    if gate1["accepted"] != gate2["accepted"]:
        return {**out, "reason": Reason.MODEL_UNSTABLE.value}
    return {**out, "reason": gate1["reason"]}


def draft_run(review_run_id: str, model_call, *,
              allowed_document_ids: frozenset[str],
              findings: list[dict] | None = None,
              rows: list[dict] | None = None,
              submittal_name: str = "",
              second_call=None) -> dict:
    """Every finding of a run that enters the CRS, drafted and gated.

    `findings` and `rows` are injectable so the tests need no database; left
    out, findings come from `comparison.list_findings` under the caller's
    grants and rows from `crs_mapping.build_crs_rows`, the same builder the
    export route uses - so the page/section the model sees is the one the
    sheet prints. Only findings WITH a CRS row are drafted: a COMPLIANT or
    MISSING_INFORMATION finding never enters the sheet, and drafting a comment
    nobody will print is a model call with no reader.

    Each draft carries `row_ref`, minted with `crs_export.row_reference` from
    the same row, so `apply_drafts` can find its row in a `build_crs_view`
    result, whose rows print the reference but not the finding id.

    Returns `{"review_run_id", "drafts": {finding_id: draft}, "drafted",
    "rejected", "counts": {reason: n}, "skipped"}`.
    """
    if findings is None:
        findings = comparison.list_findings(
            review_run_id, allowed_document_ids=allowed_document_ids)
    if rows is None:
        rows = crs_mapping.build_crs_rows(findings, [], submittal_name)
    by_id = {str(r.get("finding_id") or ""): r for r in rows}

    drafts: dict = {}
    rejected: list[str] = []
    skipped = 0
    for finding in findings:
        fid = str(finding.get("id") or finding.get("finding_id") or "")
        row = by_id.get(fid)
        if row is None:
            skipped += 1
            continue
        draft = draft_comment(finding, row, model_call, second_call)
        draft["row_ref"] = row_reference(review_run_id, row)
        drafts[fid] = draft
        if not draft["accepted"]:
            rejected.append(draft["reason"])
    return {
        "review_run_id": review_run_id,
        "drafts": drafts,
        "drafted": sum(1 for d in drafts.values() if d["accepted"]),
        "rejected": len(rejected),
        "counts": rejection_counts(rejected),
        "skipped": skipped,
    }


# ---------------------------------------------------------- onto the sheet

def apply_drafts(view: dict, drafts: dict) -> dict:
    """A `build_crs_view` result with accepted drafts laid over its comments.

    PURE: the input is deep-copied and returned changed, never mutated, so a
    preview built from the machine text and one built from the drafts can be
    shown side by side from the same view.

    For a row with an accepted draft, `comment` becomes `MODEL_DRAFT_PREFIX` +
    the draft comment, then the action on its own line when there is one. The
    machine text the draft replaced is kept, verbatim, under
    `machine_comment`, so the engineer can compare and revert.

    THE REFERENCE IS A COLUMN NOW, so nothing has to be preserved from the
    old text to keep the contractor's handle: `row_ref` is beside the comment,
    not inside it. The `Ref:` branch below stays for a view built by an older
    build, where dropping that line would have renumbered the sheet.

    Rows without an accepted draft are returned exactly as they came. A draft
    is matched to its row by `row_ref` first, then by a `finding_id` the row
    happens to carry; `drafts` is `draft_run`'s `drafts` mapping, or that
    whole result.
    """
    if isinstance(drafts, dict) and "drafts" in drafts and isinstance(
            drafts["drafts"], dict):
        drafts = drafts["drafts"]
    by_ref = {d.get("row_ref"): d for d in drafts.values()
              if isinstance(d, dict) and d.get("accepted") and d.get("row_ref")}
    by_id = {fid: d for fid, d in drafts.items()
             if isinstance(d, dict) and d.get("accepted")}

    out = copy.deepcopy(view)
    for row in out.get("rows", []):
        draft = by_ref.get(row.get("row_ref")) or by_id.get(
            str(row.get("finding_id") or ""))
        if draft is None:
            continue
        original = str(row.get("comment", ""))
        first_line, _, rest = original.partition("\n")
        body = MODEL_DRAFT_PREFIX + draft["comment"]
        if draft.get("action"):
            body += f"\nAction: {draft['action']}"
        row["machine_comment"] = original
        if first_line.startswith("Ref:"):
            row["comment"] = f"{first_line}\n{body}"
        else:
            row["comment"] = body
        row["model_drafted"] = True
    return out
