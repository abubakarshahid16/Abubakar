"""AI engineering check (kind C): observations a reviewer would raise, as DRAFTS.

Owner order 2026-09-26, item 2d. When a datasheet cites standards the library
does not hold, the review has nothing to compare against and says nothing. An
experienced reviewer would still say something: "the hydrotest pressure is
not stated", "the corrosion allowance looks thin for this service". This asks
Claude for exactly that - engineering observations from the datasheet and
general knowledge - and then refuses every one it cannot prove is honest.

WHAT IT IS NOT, ENFORCED IN CODE:

  * NEVER A VERDICT. An item is stored with NO compliance status, pending,
    unconfirmed, `origin = 'ai_engineering_check'`. `comparison.recommend_code`
    counts statuses, so an item cannot move the suggested review code; and it
    runs after that code was decided.
  * NEVER FROM THE STANDARD. It may NAME a standard the observation relates to
    (a name, not text). It may cite a clause only when that standard is HELD
    for this run and a requirement at that clause was read from it; it may not
    quote a sentence that is not on the datasheet page.
  * NEVER AN INVENTED VALUE. The datasheet value it quotes must be on the page
    it cites, and every number in its words must be on that page too (the
    standard's own designator and a verified clause excepted). A "typical"
    figure the model brought with it is exactly the thing an engineer cannot
    defend in a meeting.
  * NO PASS/FAIL WORDS. "Complies", "non-compliant", "approved" ... are the
    engine's and the engineer's words, never a draft's.
  * CONFIDENCE low OR medium. Never "high" (CLAUDE.md rule 4).

A refused item is DROPPED WITH A NAMED REASON (`Reason`), never repaired: the
run reports "5 proposed, 3 kept: 1 value not on page, 1 pass/fail word".

OFF BY DEFAULT (`settings.review_ai_check_enabled`), and even on it needs the
Claude lane (`reasoning_provider.claude_available`: REASONING_PROVIDER=claude,
both reader egress flags and a key). The call goes through `ClaudeProvider`,
so `claude_spend.reserve` refuses it BEFORE it leaves if it could cross the
USD caps (and holds its worst case until it is settled); the spend is booked
to the step `review_ai_check`.

The provider is injectable, so every test runs against a fake - no socket.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum

from . import claude_spend, numparse
from .config import settings
from .db import connect
from .reader_api import _contains, _fold

#: The budget step (claude_spend) this lane is charged to.
STEP = "review_ai_check"
PROMPT_VERSION = "review-ai-check-v1"
#: `review_findings.origin` for every item this module stores.
ORIGIN = "ai_engineering_check"
#: The label the screen and the CRS print beside an item (owner order, table 1).
LABEL = "AI engineering check - not from the standard text - engineer to confirm"
#: Comment By on the CRS once an engineer has confirmed an item.
CONFIRMED_BY_PREFIX = "AI engineering check, confirmed by "

#: A pass/fail word is the engine's or the engineer's, never a draft's.
#: Matched whole-word on the folded text. Data, one list.
PASS_FAIL_WORDS = (
    "complies", "comply", "complied", "compliant", "non-compliant", "noncompliant",
    "non compliant", "approved", "approve", "acceptable", "unacceptable", "accepted",
    "rejected", "pass", "passes", "passed", "fail", "fails", "failed",
    "meets the requirement", "does not meet",
    # A09: verdicts in other words. "satisfies the spec" was accepted.
    "satisfies", "satisfy", "satisfied", "does not satisfy", "conforms", "conform",
    "conforming", "conformance", "non-conforming", "nonconforming", "does not conform",
    "meets", "meet", "adequate", "inadequate", "violates", "violation",
    "not acceptable", "not compliant", "not approved", "in compliance",
)
CONFIDENCES = ("low", "medium")

#: Caps on what is sent: a datasheet page is rarely longer, and the prompt's
#: worst case is what the spend check prices.
MAX_PAGE_CHARS = 6000
MAX_PROMPT_CHARS = 60000
#: 2026-09-27: lowered from 25. Fewer items requested per call means a
#: complete answer fits inside the output cap far more often; the retry below
#: covers what a first call still cannot fit.
MAX_ITEMS = 12
MAX_TEXT_CHARS = 600
#: Kept as the fallback default only; every call site reads
#: `settings.review_ai_check_max_output_tokens`, which is what changed
#: 2026-09-27 (raised from this same 4000 - the ledger showed every one of
#: the 10 historical calls hitting exactly this cap and being thrown away).
MAX_OUTPUT_TOKENS = 4000
#: At most this many Claude calls per run: one first attempt and one retry
#: for whatever a truncated first reply left uncovered. Never more - a run
#: that keeps retrying is a budget leak, not a more complete answer.
MAX_CALLS = 2

#: "clause 6.2.3", "para. 5", "section 7.1", "§ 4.2", "paragraph 3.1".
_CLAUSE_REF = re.compile(
    r"(?:\bclause|\bpara(?:graph)?\.?|\bsection|\bsec\.|§)\s*(\d+(?:\.\d+)*[a-z]?)",
    re.IGNORECASE)
#: A quoted span of five or more words: "..." or “...” or '...'.
_QUOTED = re.compile(r"[\"“”']([^\"“”']{3,})[\"“”']")


class Reason(Enum):
    MALFORMED = "model_malformed"
    MISSING_FIELD = "missing_field"
    BAD_CONFIDENCE = "confidence_not_low_or_medium"
    PAGE_NOT_IN_DATASHEET = "page_not_in_datasheet"
    VALUE_NOT_ON_PAGE = "value_not_on_page"
    NUMBER_NOT_ON_PAGE = "number_not_on_page"
    CLAUSE_NOT_VERIFIED = "clause_not_verified"
    QUOTE_NOT_ON_PAGE = "quote_not_on_page"
    PASS_FAIL_WORD = "pass_fail_word"
    TOO_LONG = "too_long"


SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "required": ["topic", "page", "field", "value", "observation", "action",
                     "relates_to", "confidence"],
        "properties": {
            "topic": {"type": "string"}, "page": {"type": "integer"},
            "field": {"type": "string"}, "value": {"type": "string"},
            "observation": {"type": "string"}, "action": {"type": "string"},
            "relates_to": {"type": "string"}, "clause": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        }}}},
}

SYSTEM = """You are a senior mechanical engineer reviewing a contractor's equipment \
datasheet for an operating company. Raise the observations an experienced reviewer \
would raise from the datasheet itself and general engineering knowledge: values that \
look missing, inconsistent, unusual for the service, or needing confirmation.

RULES, ALL MANDATORY - an item that breaks one is discarded:
1. Cite the datasheet page and the field. "value" is the datasheet's value for that \
field COPIED EXACTLY as printed on that page ("" if the field is blank or absent).
2. Use NO number that is not printed on that datasheet page. No typical values, \
margins, percentages or figures from memory.
3. You MAY name the standard an observation relates to (from the list given). Do NOT \
quote a standard's text and do NOT cite a clause number unless you are given it.
4. Never say whether anything complies, passes, fails, is acceptable or approved. You \
raise questions; an engineer decides.
5. "action" is what the contractor should do, one sentence ("Contractor to confirm ...").
6. confidence is "low" or "medium". Never "high".
7. At most """ + str(MAX_ITEMS) + """ items.
8. BE COMPACT. "observation" and "action" are each ONE short sentence (aim for \
under 120 characters). No repeated boilerplate between items - state the point \
once and stop. Plain, formal English, no markdown."""


# ---------------------------------------------------------------- inputs

def datasheet_pages(submittal_id: str) -> dict[int, str]:
    """The submittal's text by page, from its chunks (the text the review read)."""
    pages: dict[int, list[str]] = {}
    for row in connect().execute(
            "SELECT page_start, page_end, text FROM chunks WHERE document_id = ?"
            " ORDER BY ordinal", (submittal_id,)):
        for p in range(row["page_start"] or 1, (row["page_end"] or row["page_start"] or 1) + 1):
            pages.setdefault(p, []).append(row["text"] or "")
    return {p: "\n".join(parts) for p, parts in sorted(pages.items())}


def datasheet_fields(submittal_id: str) -> list[dict]:
    """The current facts read from the submittal: label, value, unit, page."""
    try:
        rows = connect().execute(
            "SELECT field_label, field_value, raw_unit, page FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL ORDER BY page",
            (submittal_id,)).fetchall()
    except Exception:  # noqa: BLE001 - no submittal tables yet
        return []
    return [{"field": r["field_label"], "value": r["field_value"], "unit": r["raw_unit"],
             "page": r["page"]} for r in rows]


def build_prompt(fields: list[dict], pages: dict[int, str], cited: list[str],
                 held: dict[str, list[str]], *, covered: list[str] | None = None) -> str:
    """The user prompt. `cited` = standard names the datasheet cites; `held` =
    held standard name -> clauses a requirement was read from.

    `covered` (the retry call only) names what a first, truncated reply
    already raised, one line per kept item, so the retry asks for what is
    still missing instead of repeating work the first call already paid for.
    """
    lines = ["STANDARDS THE DATASHEET CITES (names only):"]
    lines += [f"- {name}" for name in cited] or ["- (none)"]
    lines.append("\nHELD STANDARDS AND THE CLAUSES YOU MAY CITE:")
    lines += [f"- {name}: {', '.join(clauses) or '(no clause)'}" for name, clauses in held.items()] \
        or ["- (none: cite no clause)"]
    lines.append("\nFIELDS READ FROM THE DATASHEET (page | field | value | unit):")
    lines += [f"p{f['page']} | {f['field']} | {f['value'] or ''} | {f['unit'] or ''}"
              for f in fields] or ["(none)"]
    if covered:
        lines.append("\nALREADY RAISED - a previous, cut-off reply covered these. Do NOT repeat "
                      "them; raise ONLY new observations not already on this list:")
        lines += [f"- {line}" for line in covered]
    lines.append("\nDATASHEET PAGES:")
    for page, text in pages.items():
        lines.append(f"--- page {page} ---\n{text[:MAX_PAGE_CHARS]}")
    return "\n".join(lines)[:MAX_PROMPT_CHARS]


# ------------------------------------------------------------------ gate

def _numbers(text: str) -> set[float | str]:
    return numparse.number_keys(text)


def _strip_names(folded: str, names) -> str:
    for name in names:
        piece = _fold(name)
        if piece:
            folded = folded.replace(piece, " ")
    return folded


def _held_clause(item: dict, held: dict[str, list[str]]) -> tuple[str, str] | None:
    """(held standard name, clause) when the item's clause is one read from
    the standard it names; None otherwise."""
    clause = str(item.get("clause") or "").strip()
    relates = _fold(item.get("relates_to") or "")
    if not clause or not relates:
        return None
    for name, clauses in held.items():
        stem = _fold(re.sub(r"\.(pdf|docx?)$", "", name, flags=re.IGNORECASE))
        # The item must NAME the held standard in full (audit A10). The old
        # `relates in stem` also accepted "API" for "API 610" and "SAES-D-00"
        # for "SAES-D-001", attaching the clause to the wrong standard.
        if stem and re.search(r"(?<![a-z0-9])" + re.escape(stem) + r"(?![a-z0-9])",
                              relates) and clause in clauses:
            return name, clause
    return None


def accept(item: dict, pages: dict[int, str], held: dict[str, list[str]],
           cited: list[str]) -> dict:
    """THE GATE. `{"accepted", "reason", "item"}`; the FIRST failure is the reason."""
    def refuse(reason: Reason) -> dict:
        return {"accepted": False, "reason": reason.value, "item": item}

    if not isinstance(item, dict):
        return refuse(Reason.MALFORMED)
    for key in ("topic", "field", "observation", "action"):
        if not str(item.get(key) or "").strip():
            return refuse(Reason.MISSING_FIELD)
    if item.get("confidence") not in CONFIDENCES:
        return refuse(Reason.BAD_CONFIDENCE)
    page = item.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page not in pages:
        return refuse(Reason.PAGE_NOT_IN_DATASHEET)
    page_text = pages[page]
    value = str(item.get("value") or "").strip()
    if value and not numparse.value_in_text(value, page_text):
        return refuse(Reason.VALUE_NOT_ON_PAGE)
    prose = f"{item['observation']} {item['action']}"
    if len(prose) + len(item["topic"]) > MAX_TEXT_CHARS:
        return refuse(Reason.TOO_LONG)
    verified = _held_clause(item, held)
    refs = {m.group(1) for m in _CLAUSE_REF.finditer(prose)}
    if (item.get("clause") and verified is None) or (refs and (verified is None
                                                              or refs != {verified[1]})):
        return refuse(Reason.CLAUSE_NOT_VERIFIED)
    for quoted in _QUOTED.findall(prose):
        if len(quoted.split()) >= 5 and _fold(quoted) not in _fold(pages[page]):
            return refuse(Reason.QUOTE_NOT_ON_PAGE)
    # Only the names this run KNOWS are excused - never the item's own
    # "relates_to", or a model could launder a number through a made-up name.
    names = [*cited, *held]
    stripped = _strip_names(_fold(prose), names)
    if verified is not None:
        stripped = _CLAUSE_REF.sub(" ", stripped)
    if not _numbers(stripped) <= _numbers(page_text):
        return refuse(Reason.NUMBER_NOT_ON_PAGE)
    folded = _fold(prose)
    if any(_contains(folded, word) for word in PASS_FAIL_WORDS):
        return refuse(Reason.PASS_FAIL_WORD)
    return {"accepted": True, "reason": None, "item": item}


def parse(text: str) -> list | None:
    body = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", body, re.DOTALL)
    if fence:
        body = fence.group(1)
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    items = value.get("items") if isinstance(value, dict) else None
    return items if isinstance(items, list) else None


def parse_partial(text: str) -> list[dict]:
    """The complete items inside a TRUNCATED `{"items": [...]}` reply.

    A reply cut off mid-answer (`finish_reason == "length"`) is not valid
    JSON, so `parse` returns None and, before this, the whole reply was
    thrown away - proposed 0, kept 0, on every one of the 10 historical
    calls. This walks the `items` array by hand, one balanced `{...}` object
    at a time, and stops at the FIRST one that never closes. It never repairs
    or guesses a partial object - an item that was cut off mid-object is
    simply not returned, exactly as if it had never been proposed.
    """
    body = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)$", body, re.DOTALL)
    if fence:
        body = fence.group(1)
    key = body.find('"items"')
    if key == -1:
        return []
    start = body.find("[", key)
    if start == -1:
        return []
    items: list[dict] = []
    i, n = start + 1, len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n or body[i] == "]":
            break
        if body[i] != "{":
            break  # not the start of an object - stop rather than guess
        obj_start = i
        depth = 0
        in_string = False
        escape = False
        j = i
        closed = False
        while j < n:
            ch = body[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        closed = True
                        break
            j += 1
        if not closed:
            break  # the object never closed - the cut-off point
        try:
            obj = json.loads(body[obj_start:j])
        except (json.JSONDecodeError, TypeError, ValueError):
            break
        if isinstance(obj, dict):
            items.append(obj)
        i = j
    return items


# ------------------------------------------------------------- the run

def available() -> tuple[bool, str]:
    """Whether the check may run, and if not, why - in plain words."""
    if not settings.review_ai_check_enabled:
        return False, "the AI engineering check is off (REVIEW_AI_CHECK_ENABLED)"
    from . import reasoning_provider
    ok, why = reasoning_provider.claude_available()
    if not ok:
        return False, f"the Claude lane is off ({why})"
    return True, "claude"


def _held_standards(review_run_id: str) -> dict[str, list[str]]:
    rows = connect().execute(
        """SELECT d.filename AS name, r.clause AS clause
           FROM review_applicable_standards a
           JOIN documents d ON d.id = a.standard_document_id
           LEFT JOIN standard_requirements r ON r.standard_document_id = a.standard_document_id
           WHERE a.review_run_id = ? AND COALESCE(a.included, 1) = 1""",
        (review_run_id,)).fetchall()
    held: dict[str, list[str]] = {}
    for r in rows:
        clauses = held.setdefault(r["name"], [])
        if r["clause"] and r["clause"] not in clauses:
            clauses.append(r["clause"])
    return held


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _covered_lines(kept: list[dict]) -> list[str]:
    """One line per item already kept, for the retry prompt's "already
    raised" section - so the retry fills gaps instead of repeating work."""
    return [f"p{item.get('page')} {item.get('field')}: {item.get('topic')}" for item in kept]


def _call(provider, packet) -> tuple[object | None, str | None]:
    """One call to the provider: `(response, None)`, or `(None, plain reason)`
    when the call could not be made at all - a budget refusal or a transport
    failure. Never raised further here: a call this run could not afford or
    reach is a RESULT of the run, to be recorded on it, not a crash of the
    review the run belongs to (review_jobs._ai_check already treats an
    unexpected exception this way; this makes the expected ones visible
    too, on the run itself, rather than only a log line naming an exception
    type)."""
    from . import reasoning_provider as rp
    try:
        return provider.reason(packet), None
    except claude_spend.BudgetExceeded as exc:
        return None, f"a budget cap stopped the call ({exc})"
    except rp.ProviderRefused as exc:
        return None, f"the model call failed ({exc})"


def _gate_items(items: list, pages: dict[int, str], held: dict[str, list[str]],
                cited: list[str], all_kept: list[dict], rejected: dict[str, int]) -> None:
    """THE ONE PLACE any call's items are gated - a first call's and a
    retry's alike. There is exactly one call to `accept()` in this module's
    run loop so a retry-sourced item can never take a path that skips it."""
    for item in items[:MAX_ITEMS]:
        gate = accept(item, pages, held, cited)
        if gate["accepted"]:
            all_kept.append(item)
        else:
            rejected[gate["reason"]] = rejected.get(gate["reason"], 0) + 1


def _plain_status(status: dict) -> str:
    """The boundary sentence a reviewer sees - every count states what it is
    out of (CLAUDE.md rule 4): never a bare number, never "compliant" and
    never a guess dressed as a result."""
    calls = status["calls_made"]
    call_word = "call" if calls == 1 else "calls"
    if status["complete"]:
        return (f"AI engineering check complete: {status['kept_items']} of "
                f"{status['proposed_items']} proposed item(s) kept, over {calls} {call_word}.")
    return (f"AI engineering check incomplete - {status['reason']}. "
            f"{status['kept_items']} item(s) kept so far (at most {status['requested_items']} "
            f"requested per call, {calls} {call_word} made).")


def _store_status(review_run_id: str, status: dict) -> None:
    conn = connect()
    with conn:
        conn.execute("UPDATE review_runs SET ai_check_status = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(status), _now(), review_run_id))


def ai_check_status(review_run_id: str, *, allowed_document_ids: frozenset[str]) -> dict | None:
    """This run's own AI-check outcome, under the caller's grants - the same
    read shape as `comparison.run_outcome`. None when the run does not exist,
    the caller may not read it, or the check never stored one (never ran)."""
    from . import submittal_review
    run = submittal_review.get_review_run(review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        return None
    raw = run.get("ai_check_status")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def run_check(review_run_id: str, *, allowed_document_ids: frozenset[str],
              cited: list[str], provider=None) -> dict:
    """Ask Claude for engineering observations, gate every item, store the
    kept ones as pending drafts.

    A reply cut off by the output cap is not thrown away: the complete items
    before the cut-off point are parsed and kept (`parse_partial`), and ONE
    retry asks only for what is still missing (`covered`) - capped at
    `MAX_CALLS` total calls, so this can never loop or blow the step budget.
    The SAME gate (`accept`) gates every item from every call; nothing
    retry-sourced skips it.

    Earlier UNCONFIRMED items of this run are replaced; a confirmed one is an
    engineer's decision and is never deleted. Returns counts, never text -
    and ALWAYS records this run's `ai_check_status` (read back by
    `ai_check_status`), so a truncated, retried or refused check is a fact a
    reviewer can see, never silence that reads as "nothing to raise".
    """
    from . import review as review_mod
    from . import reasoning_provider as rp
    from . import submittal_review

    ok, why = available() if provider is None else (True, "injected")
    if not ok:
        return {"ran": False, "reason": why, "proposed": 0, "kept": 0, "rejected": {}}
    run = submittal_review.get_review_run(review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        return {"ran": False, "reason": "no review run with that id", "proposed": 0,
                "kept": 0, "rejected": {}}
    submittal = run["submittal_document_id"]
    pages = datasheet_pages(submittal)
    held = _held_standards(review_run_id)
    fields = datasheet_fields(submittal)
    if provider is None:
        provider = rp.get_provider("reasoning", step=STEP)
    max_output_tokens = settings.review_ai_check_max_output_tokens

    all_kept: list[dict] = []
    rejected: dict[str, int] = {}
    proposed_total = 0
    cost_total = 0.0
    calls_made = 0
    complete = False
    reason: str | None = None
    covered: list[str] = []

    for call_index in range(MAX_CALLS):
        prompt = build_prompt(fields, pages, cited, held,
                              covered=covered if call_index else None)
        response, call_failed = _call(provider, rp.Packet(
            prompt=prompt, system=SYSTEM, num_ctx=settings.num_ctx,
            num_predict=max_output_tokens, json_schema=SCHEMA,
            step=STEP, prompt_version=PROMPT_VERSION, timeout_s=240))
        calls_made += 1
        if call_failed is not None:
            reason = call_failed
            break
        cost_total += response.cost_usd or 0.0
        items = None if response.schema_errors else parse(response.text)
        if items is None and response.truncated:
            # Cut off by the output cap: keep every complete item before the
            # cut-off point rather than discarding the whole reply.
            items = parse_partial(response.text)
            proposed_total += len(items)
            _gate_items(items, pages, held, cited, all_kept, rejected)
            reason = "the reply was cut off by the output limit before it finished"
            covered = _covered_lines(all_kept)
            continue  # eligible for the retry, if one is left
        if items is None:
            # Malformed for a reason OTHER than truncation: a retry of the
            # same prompt is not expected to fix it, so this is the answer.
            reason = Reason.MALFORMED.value
            rejected[Reason.MALFORMED.value] = rejected.get(Reason.MALFORMED.value, 0) + 1
            break
        proposed_total += len(items)
        _gate_items(items, pages, held, cited, all_kept, rejected)
        complete = True
        reason = None
        break

    status = {
        "ran": True,
        "complete": complete,
        "calls_made": calls_made,
        "requested_items": MAX_ITEMS,
        "proposed_items": proposed_total,
        "kept_items": len(all_kept),
        "rejected": dict(rejected),
        "reason": reason,
        "cost_usd": round(cost_total, 6),
    }
    status["plain"] = _plain_status(status)
    _store_status(review_run_id, status)

    conn = connect()
    # An engineer's decision survives a re-run (`review.UNDECIDED_SQL`), and an
    # item they rejected is not proposed again word for word beside it.
    rejected_items = {_item_identity(r.get("finding"), r.get("required_action"),
                                     r.get("contractor_page"), r.get("contractor_section"))
                      for r in review_mod.rejected_in_run(review_run_id, ORIGIN)}
    with conn:
        conn.execute("DELETE FROM review_findings WHERE review_run_id = ? AND origin = ?"
                     f" AND {review_mod.UNDECIDED_SQL}", (review_run_id, ORIGIN))
    for item in all_kept:
        if _item_identity(str(item["observation"])[:4000], str(item["action"])[:4000],
                          item["page"], str(item["field"])[:400]) in rejected_items:
            continue
        verified = _held_clause(item, held)
        finding = review_mod.create({
            "document_id": submittal,
            "category": "technical_query",
            "severity": "minor",
            "confidence": item["confidence"],
            "requirement": str(item["topic"])[:4000],
            "finding": str(item["observation"])[:4000],
            "required_action": str(item["action"])[:4000],
            "status": "open",
            "approval_status": "pending",
        }, created_by=None)
        with conn:
            conn.execute(
                """UPDATE review_findings SET review_run_id = ?, origin = ?,
                       contractor_page = ?, contractor_section = ?,
                       contractor_evidence_text = ?, standard_clause = ?, ai_rationale = ?
                   WHERE id = ?""",
                (review_run_id, ORIGIN, item["page"], str(item["field"])[:400],
                 str(item.get("value") or "")[:400] or None,
                 verified[1] if verified else None,
                 f"{LABEL}. Relates to: {str(item.get('relates_to') or '').strip() or 'no standard named'}.",
                 finding["id"]))
    return {"ran": True, "reason": reason, "proposed": proposed_total, "kept": len(all_kept),
            "rejected": rejected, "cost_usd": round(cost_total, 6), "complete": complete,
            "calls_made": calls_made}


def _item_identity(finding, action, page, section) -> tuple:
    """What makes two AI check items the same comment - the fields
    `crs_mapping` keys its permanent number on, folded."""
    fold = lambda v: " ".join(str(v or "").lower().split())  # noqa: E731
    return (fold(finding), fold(action), page, fold(section))


def relates_to(finding: dict) -> str:
    """The standard name an item relates to, read back from its rationale."""
    text = finding.get("ai_rationale") or ""
    marker = "Relates to: "
    return text.split(marker, 1)[1].rstrip(".") if marker in text else ""
