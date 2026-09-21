"""Which standards apply to a datasheet: the model PROPOSES, Python DECIDES.

THE DIVISION OF LABOUR IS `reader_api.py`'s, APPLIED TO SELECTION. The model
is handed a numbered list of standards that Python built from the corpus, and
it answers with INDEXES into that list, a basis and one sentence of reason.
It never names a standard - `comparison.match_by_model`'s one-sentence rule,
"the model may CHOOSE from a list Python built; it may never NAME one" - so
it cannot put a standard on the list that is not in the library, and it never
sees a review run, a verdict or a confidence, so a wrong proposal produces a
wrong QUESTION for the engineer rather than a wrong row nobody asked for.

WHY A MODEL HERE AT ALL, when `applicability.select` already picks standards
by six deterministic rules. Because those rules read CITATIONS and
CLASSIFICATION FIELDS, and the corpus has standards whose scope is stated in
prose the rules cannot see: a datasheet for a centrifugal pump cites nothing,
is classified "Mechanical", and a standard titled "Design Criteria for
Rotating Equipment" applies on its scope alone. Rule 5, dense retrieval, finds
it sometimes. A model reading the scope excerpt finds it and SAYS WHY, and the
"why" is what an engineer can confirm or refuse in one glance. The model is
trusted to read; it is not trusted to be right, which is what `accept()` is
for.

TWO BASES, AND THE GATE TREATS THEM DIFFERENTLY. `CONTRACTUAL` is the claim
"the datasheet names this standard", and Python can check that claim: the
standard's code must appear in the identifiers `datasheets.referenced_standards`
reads from the sheet. A CONTRACTUAL proposal for a standard the sheet does not
cite is REJECTED (`contractual_not_referenced`), because it is the model
asserting a contract term that is not on the page. `DEMONSTRATION` is the
weaker claim "this standard's scope covers this kind of equipment, shown for
the demo" - it asserts nothing about the contract, so it needs no citation and
is stored at lower confidence. The same standard can be refused as CONTRACTUAL
and accepted as DEMONSTRATION in one answer, and that is the gate working.

EVERY REJECTION IS NAMED (`Reason`), never silent, and every proposal - kept
or dropped - carries the candidate's `code` and `document_id`, because "2
rejected" tells a reviewer nothing until it says WHICH standards and WHY.

THE MODEL IS INJECTED AS A CALLABLE (`model_call(prompt) -> str`), exactly as
`reader_api.read_sentence` takes it. This module imports no HTTP client and
opens no socket: `tests/test_socket_containment.py` globs the whole package
and fails any module outside its allowlist that constructs one. A real caller
gets a callable from `reader_api.model_call_via(transport)`; every test here
runs against a fake with no transport and no key.

STORAGE IS A THIN, GUARDED WRITE. `review_applicable_standards` is the phase 1
relation and `applicability.record_selection` is its writer - but that writer
refuses any `selection_method` outside its own six rules plus `manual`, and
it DELETEs the existing (run, standard) row before inserting, which would let
a model proposal overwrite an engineer's `manual` decision. So
`store_selection` writes the same columns itself with `selection_method =
"model"` (the value the table's own comment reserves for this tier), and it
never touches a row another method wrote: a `manual` row is an engineer's
decision, a `referenced` row is a stronger fact than a model's guess, and
only a previous `model` row for the same pair is replaced on a re-run.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum

from . import applicability, datasheets, standards, submittal_review
from .db import connect

# --------------------------------------------------------------- vocabulary

#: What the model may say a standard applies ON. Two words and no more. The
#: contractual claim is checkable against the sheet's citations; the
#: demonstration claim is checkable against nothing, which is why it is stored
#: at lower confidence and why the prompt tells the model to prefer it when
#: unsure.
BASIS_CONTRACTUAL = "CONTRACTUAL"
BASIS_DEMONSTRATION = "DEMONSTRATION"
BASES = (BASIS_CONTRACTUAL, BASIS_DEMONSTRATION)

#: How a model-chosen row is recorded. The table's own comment on
#: `selection_method` reserves this word for "a model guessed", so a model
#: selection and a rule selection never read alike.
SELECTION_METHOD = "model"

#: Every stored reason begins with this, in these exact words, so a row the
#: model proposed cannot be mistaken for one a rule derived or an engineer
#: chose - `comparison.MODEL_PAIR_PREFIX`'s precedent. The basis follows the
#: prefix and then the model's own sentence.
REASON_PREFIX = "Proposed by model; engineer must confirm. Basis: "

#: CONFIDENCE IS NEVER "high" (CLAUDE.md rule 4). A CONTRACTUAL proposal has
#: passed a citation check, so it sits just under `applicability`'s
#: `referenced` ceiling of 0.9; a DEMONSTRATION proposal has passed nothing
#: but the index check and sits at a coin toss.
CONFIDENCE = {BASIS_CONTRACTUAL: 0.8, BASIS_DEMONSTRATION: 0.5}

#: How many datasheet field names reach the prompt. Enough to say what kind
#: of equipment the sheet describes; not the whole sheet, which is where the
#: page-sized-prompt traps in `reader_api` came from.
MAX_FIELD_NAMES = 40

#: The longest scope excerpt a candidate gets in the prompt.
MAX_SCOPE_CHARS = 400


class Reason(Enum):
    """Why a proposal was thrown away. A NAMED REASON, ALWAYS.

    A plain `Enum` and every caller uses `.value`, for `reader_api.Reason`'s
    reason: a `str` mixin lets a raw member reach JSON.
    """

    #: The model's answer was not the JSON that was asked for. Call-level.
    MODEL_MALFORMED = "model_malformed"
    #: An index that is not 1..N. The model may choose from the list; a number
    #: outside it names nothing, and nothing is what it gets.
    INDEX_OUT_OF_RANGE = "index_out_of_range"
    BASIS_UNKNOWN = "basis_unknown"
    #: A proposal with no sentence of reason is not something an engineer can
    #: confirm or refuse, so it is not stored.
    REASON_MISSING = "reason_missing"
    #: Basis CONTRACTUAL, but the standard's code is not among the identifiers
    #: the datasheet cites. The model asserted a contract term the sheet does
    #: not carry.
    CONTRACTUAL_NOT_REFERENCED = "contractual_not_referenced"
    #: The same index proposed twice in one answer. The second is dropped and
    #: SAID to be dropped: two proposals for one standard with two bases is
    #: the model not having decided, not a stronger case.
    DUPLICATE_INDEX = "duplicate_index"
    #: Two runs did not agree on (index, basis).
    MODEL_UNSTABLE = "model_unstable"


# ------------------------------------------------------------------- prompt

PROMPT = """You are deciding which engineering STANDARDS apply to one DATASHEET.

You are given the datasheet's classification, some of its field names, the
standards it cites by name, and a NUMBERED LIST of candidate standards from
the library, each with a short excerpt of its scope.

Answer with JSON only, in exactly this shape:
{"applicable": [{"index": <n>, "basis": "CONTRACTUAL" | "DEMONSTRATION",
                 "reason": "<one sentence>"}],
 "not_applicable": [{"index": <n>, "reason": "<one sentence>"}]}

index is the NUMBER of a candidate in the list below. Refer to a standard by
its number ONLY. Do not write a standard's name or code in place of a number,
and do not propose a standard that is not in the list.

basis is exactly one of:
  CONTRACTUAL   - the datasheet ITSELF names this standard (in its cited
                  standards, its notes or its scope). Use this only when the
                  citation is on the datasheet; it will be checked.
  DEMONSTRATION - the standard's scope covers this KIND of equipment and the
                  reviewer is showing it for the demonstration, not because
                  the contract cites it. When unsure, use this.

reason is ONE SENTENCE saying what in the datasheet or the scope excerpt led
you to the answer. Every entry needs one.

Answer with JSON and nothing else.

DATASHEET
"""


def _field_names(summary: dict) -> list[str]:
    names = summary.get("field_names") or summary.get("fields") or []
    out = []
    for name in names:
        text = " ".join(str(name or "").split())
        if text and text not in out:
            out.append(text)
    return out[:MAX_FIELD_NAMES]


def _summary_references(summary: dict) -> list[str]:
    """Every identifier the datasheet cites: the ones the caller passed, plus
    the ones phase 4's detector reads from any text the caller passed."""
    refs = list(summary.get("referenced_standards") or [])
    text = summary.get("text") or ""
    if text:
        refs.extend(datasheets.referenced_standards(text))
    out: list[str] = []
    for ref in refs:
        ref = " ".join(str(ref or "").split())
        if ref and ref not in out:
            out.append(ref)
    return out


def build_prompt(datasheet_summary: dict, candidates: list[dict]) -> str:
    """The rendered prompt. Candidates are NUMBERED 1..N; the model answers
    with numbers.

    What crosses: equipment type, discipline, service, up to `MAX_FIELD_NAMES`
    field names, the standards the sheet cites, and for each candidate its
    number, title and a scope excerpt of at most `MAX_SCOPE_CHARS`. No review
    run id, no document id, no confidence: the model is asked which standards
    apply and why, and nothing about how the answer will be stored.
    """
    s = datasheet_summary or {}
    lines = [
        f"equipment_type: {s.get('equipment_type') or '-'}",
        f"discipline: {s.get('discipline') or '-'}",
        f"service: {s.get('service') or '-'}",
    ]
    if s.get("project"):
        lines.append(f"project: {s['project']}")
    names = _field_names(s)
    lines.append("field names: " + (", ".join(names) if names else "-"))
    refs = _summary_references(s)
    lines.append("standards the datasheet cites: " + (", ".join(refs) if refs else "none"))
    lines.append("")
    lines.append("CANDIDATE STANDARDS (answer by number)")
    for number, cand in enumerate(candidates, start=1):
        scope = " ".join(str(cand.get("scope") or "").split())[:MAX_SCOPE_CHARS]
        title = " ".join(str(cand.get("title") or cand.get("code") or "").split())
        lines.append(f"{number}. {title}")
        lines.append(f"   scope: {scope or '-'}")
    return PROMPT + "\n".join(lines) + "\n"


# -------------------------------------------------------------------- parse

def _int_or_none(value) -> int | None:
    """An index as the model wrote it. `3`, `3.0` and `"3"` are 3; a word is
    not an index and becomes None, which the gate reports as out of range -
    the model was told to answer with a number and did not."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value)
    return None


def parse_response(raw: str) -> tuple[list[dict], str | None]:
    """Strict parse. Anything malformed yields no proposals AND A REASON.

    Never repaired: half-JSON patched into a list is the module inventing a
    selection and calling it the model's. Each proposal carries `verdict`
    ("applicable" or "not_applicable"), the raw `index`, the `basis` (upper-
    cased; None on a not_applicable entry) and the `reason` text.
    """
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [], Reason.MODEL_MALFORMED.value
    if not isinstance(body, dict):
        return [], Reason.MODEL_MALFORMED.value
    applicable = body.get("applicable", [])
    not_applicable = body.get("not_applicable", [])
    if not isinstance(applicable, list) or not isinstance(not_applicable, list):
        return [], Reason.MODEL_MALFORMED.value
    out: list[dict] = []
    for verdict, entries in (("applicable", applicable),
                             ("not_applicable", not_applicable)):
        for entry in entries:
            if not isinstance(entry, dict):
                return [], Reason.MODEL_MALFORMED.value
            basis = entry.get("basis")
            out.append({
                "verdict": verdict,
                "index": _int_or_none(entry.get("index")),
                "basis": (str(basis).strip().upper()
                          if basis not in (None, "") else None),
                "reason": " ".join(str(entry.get("reason") or "").split()),
            })
    return out, None


# --------------------------------------------------------------- the gate

def _identifier_key(identifier: str | None) -> str:
    """One comparison key for a standard code however it was written.

    `applicability.library_identifier` first, so "SAES-B-14" (a filename with
    the zero dropped) and "SAES-B-014" (the citation) meet; then
    `normalise_identifier`, so punctuation and spacing are not identity.
    """
    padded = applicability.library_identifier(identifier or "")
    return applicability.normalise_identifier(padded or identifier or "")


def _candidate_fields(cand: dict) -> dict:
    """What every proposal and rejection carries so a reviewer can act on it."""
    return {"document_id": cand.get("document_id"), "code": cand.get("code"),
            "title": cand.get("title")}


def is_referenced(code: str | None, datasheet_summary: dict) -> bool:
    """Does the datasheet cite this code? The CONTRACTUAL check.

    Python's answer, not the model's: the code is keyed and looked for among
    the identifiers `datasheets.referenced_standards` reads, so a CONTRACTUAL
    claim is re-derivable from the sheet afterwards without the model.
    """
    key = _identifier_key(code)
    if not key:
        return False
    return key in {_identifier_key(r) for r in _summary_references(datasheet_summary or {})}


def accept(proposals: list[dict], candidates: list[dict],
           datasheet_summary: dict) -> dict:
    """THE GATE. A proposal is kept only when ALL of these hold:

      1. its index is a number in 1..N
      2. it is the first proposal for that index in this answer
      3. it carries a sentence of reason
      4. (applicable only) its basis is CONTRACTUAL or DEMONSTRATION
      5. (CONTRACTUAL only) the candidate's code is among the standards the
         datasheet cites
      6. (in `select_standards`) two runs agreed on (index, basis)

    Returns `{"accepted": [...], "rejected": [...], "counts": {reason: n}}`.
    A rejected entry's `reason` is the named rejection and its `model_reason`
    is the sentence the model gave, so neither is lost. Accepted entries are the APPLICABLE proposals that passed, each with the
    candidate's `document_id`, `code` and `title`. A not_applicable entry that
    passes rules 1-3 is kept under `declined`, with its reason, because "the
    model looked at this and said no" is a fact the reviewer asked for - but
    it is never a stored row, since a row not written is not a row the
    engineer has to undo.
    """
    accepted: list[dict] = []
    declined: list[dict] = []
    rejected: list[dict] = []
    seen: set[int] = set()

    def drop(proposal: dict, reason: Reason, cand: dict | None) -> None:
        rejected.append({**proposal, **_candidate_fields(cand or {}),
                         "reason": reason.value,
                         "model_reason": proposal.get("reason")})

    for p in proposals:
        index = p.get("index")
        if index is None or not 1 <= index <= len(candidates):
            drop(p, Reason.INDEX_OUT_OF_RANGE, None)
            continue
        cand = candidates[index - 1]
        if index in seen:
            drop(p, Reason.DUPLICATE_INDEX, cand)
            continue
        seen.add(index)
        if not (p.get("reason") or "").strip():
            drop(p, Reason.REASON_MISSING, cand)
            continue
        if p.get("verdict") == "not_applicable":
            declined.append({**p, **_candidate_fields(cand)})
            continue
        if p.get("basis") not in BASES:
            drop(p, Reason.BASIS_UNKNOWN, cand)
            continue
        if p["basis"] == BASIS_CONTRACTUAL and not is_referenced(
                cand.get("code"), datasheet_summary):
            drop(p, Reason.CONTRACTUAL_NOT_REFERENCED, cand)
            continue
        accepted.append({**p, **_candidate_fields(cand),
                         "confidence": CONFIDENCE[p["basis"]]})
    return {"accepted": accepted, "declined": declined, "rejected": rejected,
            "counts": rejection_counts(rejected)}


def rejection_counts(rejected: list[dict]) -> dict:
    """`{reason: n}`, for the sentence a caller has to be able to write:
    "3 proposals rejected: 2 contractual-not-referenced, 1 out-of-range"."""
    counts: dict = {}
    for r in rejected:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    return counts


# ------------------------------------------------------------ the two runs

def _identity(p: dict) -> tuple:
    """What two runs must agree ON: verdict, index and basis. Not the reason
    sentence - two runs choosing the same standard on the same basis in
    different words agree about the standard."""
    return (p.get("verdict"), p.get("index"), p.get("basis"))


def select_standards(datasheet_summary: dict, candidates: list[dict],
                     model_call, second_call=None) -> dict:
    """The datasheet through the model TWICE and then through the gate.

    `reader_api.read_sentence`'s rule 5, kept whole: `second_call` defaults to
    the same model again rather than to skipping the check. A standard only
    one run proposed is one the datasheet does not compel, and it is REPORTED
    as `model_unstable` with its code and document id, never dropped quietly.

    Returns the `accept()` shape plus `prompt` (so a reviewer can see what was
    asked) and `error` when either answer was not JSON, in which case nothing
    is accepted.
    """
    prompt = build_prompt(datasheet_summary, candidates)
    empty = {"accepted": [], "declined": [], "rejected": [], "counts": {},
             "prompt": prompt}
    first, err = parse_response(model_call(prompt))
    if err:
        return {**empty, "error": err}
    again = second_call if second_call is not None else model_call
    second, err2 = parse_response(again(prompt))
    if err2:
        return {**empty, "error": err2}
    seen = {_identity(p) for p in second}
    stable = [p for p in first if _identity(p) in seen]
    unstable = []
    for p in first:
        if _identity(p) in seen:
            continue
        index = p.get("index")
        cand = (candidates[index - 1]
                if index is not None and 1 <= index <= len(candidates) else {})
        unstable.append({**p, **_candidate_fields(cand),
                         "reason": Reason.MODEL_UNSTABLE.value,
                         "model_reason": p.get("reason")})
    gate = accept(stable, candidates, datasheet_summary)
    gate["rejected"].extend(unstable)
    gate["counts"] = rejection_counts(gate["rejected"])
    gate["prompt"] = prompt
    gate["error"] = None
    return gate


# --------------------------------------------------------------- the corpus

#: A standard code inside a title or filename when the classification has
#: recorded no `document_number`: the same families phase 4 recognises as
#: citations, plus the two-digit SAES form a filename may carry.
_CODE_IN_NAME = re.compile(
    r"\b(SAES-[A-Z]-\d{2,4}|\d{2}-SAMSS-\d{3}|API\s*(?:RP\s*)?\d{3}"
    r"|NACE\s*MR[-\s]?\d{4}|ISO\s*\d{4,5}|IEC\s*\d{5}|ASTM\s*[A-Z]\d{1,4}"
    r"|ASME\s*B\d{1,2}\.\d{1,3}|EN\s*\d{3,5})\b", re.IGNORECASE)


def code_of(entry: dict) -> str | None:
    """The standard's code, e.g. "SAES-D-001". Or None when nothing carries one.

    The classification's `document_number` first - it is the recorded fact.
    Then `applicability.library_identifier` on the filename, which pads
    "SAES-B-14" to SAES-B-014 so the code meets the citation. Then a regex
    over the title and the filename. A candidate with no code can still be
    proposed as DEMONSTRATION; it can never pass the CONTRACTUAL check, which
    is right - nothing can cite it.
    """
    number = " ".join(str(entry.get("document_number") or "").split())
    if number:
        return number
    padded = applicability.library_identifier(entry.get("filename") or "")
    if padded:
        return padded
    for text in (entry.get("title"), entry.get("filename")):
        match = _CODE_IN_NAME.search(str(text or ""))
        if match:
            found = " ".join(match.group(1).split()).upper()
            return applicability.library_identifier(found) or found
    return None


def _scope_excerpt(document_id: str) -> str:
    """The first retrievable chunk of the standard, whitespace-folded and cut
    at `MAX_SCOPE_CHARS`. A standard's first page is its title, scope and
    purpose; that is what the model needs and no more."""
    row = connect().execute(
        "SELECT text FROM chunks WHERE document_id = ?"
        " ORDER BY ordinal LIMIT 1", (document_id,)).fetchone()
    text = " ".join(str(row["text"] or "").split()) if row else ""
    return text[:MAX_SCOPE_CHARS]


def candidates_from_corpus(*, allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every SELECTABLE standard the caller may read, as a candidate.

    `standards.list_standards` with superseded revisions excluded - the 3A
    rule, reused: a superseded standard is readable and citable and may not
    be selected. Each candidate carries `document_id`, `code`, `title`,
    `filename` and a `scope` excerpt. Ordered by code then title so the
    numbering the model sees is stable between the two runs.
    """
    rows = standards.list_standards(allowed_document_ids=allowed_document_ids,
                                    include_superseded=False)
    out = []
    for row in rows:
        code = code_of(row)
        title = " ".join(str(row.get("title") or "").split()) or code or row["filename"]
        out.append({
            "document_id": row["id"],
            "code": code,
            "title": title,
            "filename": row.get("filename"),
            "scope": _scope_excerpt(row["id"]),
        })
    out.sort(key=lambda c: (c["code"] or "~", c["title"], c["document_id"]))
    return out


# --------------------------------------------------------------- storage

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def selection_reason(basis: str, reason: str) -> str:
    """The stored reason: `REASON_PREFIX`, the basis, a full stop, the model's
    sentence. In that order and no other, so a row can be told apart by its
    first words."""
    return f"{REASON_PREFIX}{basis}. {(reason or '').strip()}"


def store_selection(review_run_id: str, accepted: list[dict],
                    candidates: list[dict], *,
                    allowed_document_ids: frozenset[str]) -> dict:
    """Write ACCEPTED proposals to `review_applicable_standards`.

    Returns `{"written": [rows], "kept_existing": [...], "skipped": [...]}`.

    NEVER OVER AN ENGINEER'S ROW. An existing row for the same (run, standard)
    whose `selection_method` is anything but `model` - `manual` above all,
    but also a rule's `referenced` - is left exactly as it is and reported
    under `kept_existing`; only an earlier `model` row is replaced, so a
    re-run updates the model's own proposal and nothing else. See the module
    docstring for why this is not `applicability.record_selection`.

    SCOPED. A standard outside `allowed_document_ids` is not written and is
    reported under `skipped`: proposing a standard does not grant it.
    """
    submittal_review.ensure_schema()
    by_id = {c.get("document_id"): c for c in candidates}
    written: list[dict] = []
    kept: list[dict] = []
    skipped: list[dict] = []
    conn = connect()
    for p in accepted:
        document_id = p.get("document_id")
        basis = p.get("basis")
        if basis not in BASES or not (p.get("reason") or "").strip():
            skipped.append({**p, "why": "not an accepted proposal"})
            continue
        if not document_id or document_id not in allowed_document_ids \
                or document_id not in by_id:
            skipped.append({**p, "why": "standard not in scope"})
            continue
        existing = conn.execute(
            "SELECT selection_method FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = ?",
            (review_run_id, document_id)).fetchone()
        if existing is not None and existing["selection_method"] != SELECTION_METHOD:
            kept.append({**p, "existing_method": existing["selection_method"]})
            continue
        row = {
            "id": str(uuid.uuid4()),
            "review_run_id": review_run_id,
            "standard_document_id": document_id,
            "selection_reason": selection_reason(basis, p["reason"]),
            "selection_method": SELECTION_METHOD,
            "confidence": CONFIDENCE[basis],
            "included": 1,
            "exclusion_reason": None,
            "created_at": _now(),
        }
        with conn:
            conn.execute(
                "DELETE FROM review_applicable_standards"
                " WHERE review_run_id = ? AND standard_document_id = ?"
                " AND selection_method = ?",
                (review_run_id, document_id, SELECTION_METHOD))
            conn.execute(
                """INSERT INTO review_applicable_standards
                   (id, review_run_id, standard_document_id, selection_reason,
                    selection_method, confidence, included, exclusion_reason,
                    created_at)
                   VALUES (:id, :review_run_id, :standard_document_id,
                           :selection_reason, :selection_method, :confidence,
                           :included, :exclusion_reason, :created_at)""", row)
        written.append({**row, "code": p.get("code"), "basis": basis})
    return {"written": written, "kept_existing": kept, "skipped": skipped}


__all__ = [
    "BASES",
    "BASIS_CONTRACTUAL",
    "BASIS_DEMONSTRATION",
    "CONFIDENCE",
    "MAX_FIELD_NAMES",
    "MAX_SCOPE_CHARS",
    "PROMPT",
    "REASON_PREFIX",
    "Reason",
    "SELECTION_METHOD",
    "accept",
    "build_prompt",
    "candidates_from_corpus",
    "code_of",
    "is_referenced",
    "parse_response",
    "rejection_counts",
    "select_standards",
    "selection_reason",
    "store_selection",
]
