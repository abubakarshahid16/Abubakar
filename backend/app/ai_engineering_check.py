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

ON BY DEFAULT since R26 step 7 (#763, owner rule "AI-first", 11 Oct;
`settings.review_ai_check_enabled`). It runs on the configured model: the
Claude lane when it is on (`reasoning_provider.claude_available`:
REASONING_PROVIDER=claude, both reader egress flags and a key) - through
`ClaudeProvider`, so `claude_spend.reserve` refuses it BEFORE it leaves if it
could cross the USD caps (and holds its worst case until it is settled); the
spend is booked to the step `review_ai_check` - else the LOCAL model, which
sends nothing off the machine, with its own timeout and a smaller output cap.
A timeout or a failed call is recorded on the run (a warning), never a
failed review. Every run records which engine and model ran it.

WHAT IT LOOKS FOR (R26 step 7): the concerns no rule covers - unusual
combinations, values that do not fit each other or the service - as drafts
"for the engineer", never counted as pass or fail.

The provider is injectable, so every test runs against a fake - no socket.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum

from . import claude_approved
from . import claude_spend, numparse
from .config import settings
from .db import connect
from .reader_api import _contains, _fold

#: The budget step (claude_spend) this lane is charged to.
STEP = "review_ai_check"
PROMPT_VERSION = "review-ai-check-v2"
#: `review_findings.origin` for every item this module stores.
ORIGIN = "ai_engineering_check"
#: The label the screen and the CRS print beside an item (owner order, table 1).
LABEL = "AI engineering check - not from the standard text - engineer to confirm"
#: W5b-11 (#559): an item that relates to a standard the library does NOT hold
#: comes from the model's memory of that standard, so it is its own class. It
#: leads the stored rationale (the CRS reads it there), its confidence is
#: "low", and it never carries a clause (the gate refuses one, `_held_clause`).
UNVERIFIED_LABEL = "Potential, unverified: source not held, engineer to verify"
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
#: The local model's output cap (R26 step 7): about 12 compact items.
LOCAL_MAX_OUTPUT_TOKENS = 2000
#: #844 THE LOCAL MODEL GETS SMALL CALLS: ONE DATASHEET PAGE EACH. Measured
#: on copies of three real sheets (F1 for #842): the whole-sheet packet is
#: 30,000 to 60,000 characters - far past the local model's context window -
#: and all three runs timed out at 300 s with nothing. So, for the local
#: engine only, each call carries one page, that page's fields and a capped
#: clause list, and asks for a few items. The caps are sizes, not guesses
#: about content: what does not fit is cut and the run says how many pages
#: it asked. The Claude lane keeps its one whole-sheet call.
#: #844, planner decision 12 Oct: ON THE LOCAL MODEL THE CHECK ASKS ONLY ABOUT
#: FIELDS THE CODE READERS READ AS BLANK. Measured on three real sheets with
#: the full scope: 49 drafts, about 30 of them wrong or noise - a 4B model
#: calling a normal value "unusual" or "impossible". A question about a blank
#: field is proved against the stored facts, not taken on the model's word.
#: The cloud / strong-model path keeps the full scope; revisit this when
#: Stage B picks the model (#816, #545). Said on every run, in these words.
LOCAL_SCOPE = "local model: questions about blank fields only"
LOCAL_PAGE_CHARS = 3000
LOCAL_FIELDS_PER_PAGE = 40
LOCAL_CLAUSES_PER_STANDARD = 6
LOCAL_STANDARDS = 12
LOCAL_ITEMS_PER_PAGE = 3
LOCAL_PAGE_OUTPUT_TOKENS = 500
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
    PAGE_NOT_ASKED = "page_not_the_one_asked"
    LAYOUT = "layout_not_engineering"
    NOT_A_BLANK_FIELD = "not_a_blank_field_question"


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
Look first for what a rule-by-rule check would miss: UNUSUAL COMBINATIONS (a \
material unusual for the stated fluid or temperature, a rating, size or type that \
does not fit the stated pressure, flow or service, a service condition the rest of \
the sheet seems to ignore) and values that do not fit EACH OTHER.

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
            "SELECT field_label, field_value, raw_unit, page, is_blank FROM submittal_facts"
            " WHERE submittal_document_id = ? AND superseded_at IS NULL ORDER BY page",
            (submittal_id,)).fetchall()
    except Exception:  # noqa: BLE001 - no submittal tables yet
        return []
    return [{"field": r["field_label"], "value": r["field_value"], "unit": r["raw_unit"],
             "page": r["page"], "is_blank": bool(r["is_blank"])} for r in rows]


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


def build_local_prompt(page: int, text: str, fields: list[dict], cited: list[str],
                       held: dict[str, list[str]]) -> str:
    """#844: the local model's prompt - ONE datasheet page, the fields the
    code readers read as BLANK on that page (`fields`), and a capped list of
    the standards and clauses it may name. Everything is cut to a fixed
    size, so the packet fits the local context window whatever the sheet."""
    lines = ["STANDARDS THE DATASHEET CITES (names only):"]
    lines += [f"- {name}" for name in cited[:LOCAL_STANDARDS]] or ["- (none)"]
    lines.append("\nHELD STANDARDS AND THE CLAUSES YOU MAY CITE:")
    lines += [f"- {name}: {', '.join(clauses[:LOCAL_CLAUSES_PER_STANDARD]) or '(no clause)'}"
              for name, clauses in list(held.items())[:LOCAL_STANDARDS]] or ["- (none: cite no clause)"]
    lines.append(f"\nFIELDS LEFT BLANK ON PAGE {page} (page | field | what is printed there):")
    lines += [f"p{f['page']} | {f['field']} | {f['value'] or ''}"
              for f in fields[:LOCAL_FIELDS_PER_PAGE]] or ["(none)"]
    lines.append(f"\nTHIS CALL IS ABOUT PAGE {page} ONLY, AND ONLY ABOUT THE BLANK FIELDS LISTED "
                 f"ABOVE. Pick the blank fields that matter most for this equipment and service "
                 f"and ask for each to be stated. \"field\" is the field name COPIED EXACTLY from "
                 f"the list; \"value\" is \"\". Say nothing about a field that has a value. "
                 f"At most {LOCAL_ITEMS_PER_PAGE} items, each citing page {page}. If none of the "
                 f"blank fields matters, answer with no items.")
    lines.append(f"\nDATASHEET PAGE:\n--- page {page} ---\n{text[:LOCAL_PAGE_CHARS]}")
    return "\n".join(lines)


def _timed_out(call_failed: str) -> bool:
    return "timed out" in call_failed.lower() or "timeout" in call_failed.lower()


def _local_page_calls(provider, fields: list[dict], pages: dict[int, str], cited: list[str],
                      held: dict[str, list[str]], timeout_s: float,
                      all_kept: list[dict], rejected: dict[str, int]) -> dict:
    """#844: the check on the LOCAL model, one page per call. Items are
    gated by the same `_gate_items` as every other call, and an item must
    cite the page it was asked about. A page whose call times out or fails is
    COUNTED AND NAMED on the run, never asked again; pages left when the
    run's time is spent are named too."""
    import time
    deadline = time.monotonic() + float(settings.review_ai_check_local_max_seconds)
    with_text = [p for p, text in pages.items() if (text or "").strip()]
    # #844: ONLY PAGES THE CODE READERS TOOK A VALUE FROM. A title page, a
    # contents page and a sketch page carry no value; asking the local model
    # about them cost 9 of 22 calls on three real sheets and gave 18 of 49
    # drafts, 13 of them noise. AND ONLY PAGES WITH A BLANK FIELD (the local
    # scope): a page with nothing blank has nothing to ask. The pages left
    # out are named on the run, each under its reason.
    has_value = {f.get("page") for f in fields
                 if str(f.get("value") or "").strip() or f.get("is_blank")}
    blank: dict[int, list[dict]] = {}
    for f in fields:
        if f.get("is_blank"):
            blank.setdefault(f.get("page"), []).append(f)
    asked = [p for p in with_text if p in has_value and p in blank]
    out = {"pages": len(asked), "done": [], "timed_out": [], "failed": [], "not_tried": [],
           "no_value_read": [p for p in with_text if p not in has_value],
           "no_blank_field": [p for p in with_text if p in has_value and p not in blank],
           "calls_made": 0, "proposed": 0, "engine": None}
    for page in asked:
        if time.monotonic() >= deadline:
            out["not_tried"].append(page)
            continue
        prompt = build_local_prompt(page, pages[page], blank[page], cited, held)
        response, call_failed = _call(provider, _local_packet(prompt, timeout_s))
        out["calls_made"] += 1
        if call_failed is not None:
            out["timed_out" if _timed_out(call_failed) else "failed"].append(page)
            continue
        out["engine"] = f"{response.provider}:{response.model_tag}"
        items = None if response.schema_errors else parse(response.text)
        if items is None and response.truncated:
            # cut off by the small output cap: the complete items before the cut stand
            items = parse_partial(response.text or "")
        if items is None:
            rejected[Reason.MALFORMED.value] = rejected.get(Reason.MALFORMED.value, 0) + 1
            out["failed"].append(page)
            continue
        items = items[:LOCAL_ITEMS_PER_PAGE]
        out["proposed"] += len(items)
        on_page = [i for i in items if isinstance(i, dict) and i.get("page") == page]
        if len(on_page) < len(items):
            key = Reason.PAGE_NOT_ASKED.value
            rejected[key] = rejected.get(key, 0) + len(items) - len(on_page)
        asks_a_blank = [i for i in on_page if _names_one_of(i.get("field"), blank[page])]
        if len(asks_a_blank) < len(on_page):
            key = Reason.NOT_A_BLANK_FIELD.value
            rejected[key] = rejected.get(key, 0) + len(on_page) - len(asks_a_blank)
        _gate_items(asks_a_blank, pages, held, cited, all_kept, rejected)
        out["done"].append(page)
    return out


def _names_one_of(field, blank_fields: list[dict]) -> bool:
    """Does the item's field name one of the page's blank fields? Folded and
    WHOLE: the same name; the blank field's whole name inside a longer one
    (the model added a note); or the model dropped only a clause reference or
    a mark from it (numbers, one or two letters). Never a single shared word:
    "Pressure" does not name "Hydrotest pressure"."""
    name = _words(field)
    if not name:
        return False
    for f in blank_fields:
        known = _words(f.get("field"))
        if not known:
            continue
        if name == known or _run_inside(known, name):
            return True
        if _run_inside(name, known):
            dropped = list(known)
            for word in name:
                dropped.remove(word)
            if all(word.isdigit() or len(word) <= 2 for word in dropped):
                return True
    return False


def _words(text) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", _fold(str(text or "")).lower()).split()


def _run_inside(short: list[str], long: list[str]) -> bool:
    """Is `short` a consecutive run of whole words inside `long`?"""
    n = len(short)
    return n < len(long) and any(long[i:i + n] == short for i in range(len(long) - n + 1))


def _local_packet(prompt: str, timeout_s: float):
    from . import reasoning_provider as rp
    return rp.Packet(prompt=prompt, system=SYSTEM, num_ctx=settings.num_ctx,
                     num_predict=LOCAL_PAGE_OUTPUT_TOKENS, json_schema=SCHEMA, step=STEP,
                     prompt_version=PROMPT_VERSION + "+local-page", timeout_s=timeout_s)


def _local_reason(local: dict, timeout_s: float) -> str | None:
    """Why the local run is not complete, with every count against its
    total - or None when every page was asked and answered."""
    left = len(local["timed_out"]) + len(local["failed"]) + len(local["not_tried"])
    if not left:
        return None
    parts = []
    if local["timed_out"]:
        parts.append(f"{len(local['timed_out'])} timed out after {timeout_s:.0f} s "
                     f"(page {', '.join(map(str, local['timed_out']))})")
    if local["failed"]:
        parts.append(f"{len(local['failed'])} gave no usable answer "
                     f"(page {', '.join(map(str, local['failed']))})")
    if local["not_tried"]:
        parts.append(f"{len(local['not_tried'])} not asked because the run's time was spent "
                     f"(page {', '.join(map(str, local['not_tried']))})")
    return (f"{left} of {local['pages']} page(s) were not checked on the local model: "
            + "; ".join(parts))


# ------------------------------------------------------------------ gate

def _numbers(text: str) -> set[float | str]:
    return numparse.number_keys(text)


def _strip_names(folded: str, names) -> str:
    for name in names:
        piece = _fold(name)
        if piece:
            folded = folded.replace(piece, " ")
    return folded


def _held_names(item: dict, held: dict[str, list[str]]) -> list[str]:
    """The held standards the item's `relates_to` names in full."""
    relates = _fold(item.get("relates_to") or "")
    if not relates:
        return []
    out = []
    for name in held:
        stem = _fold(re.sub(r"\.(pdf|docx?)$", "", name, flags=re.IGNORECASE))
        # The item must NAME the held standard in full (audit A10). The old
        # `relates in stem` also accepted "API" for "API 610" and "SAES-D-00"
        # for "SAES-D-001", attaching the clause to the wrong standard.
        if stem and re.search(r"(?<![a-z0-9])" + re.escape(stem) + r"(?![a-z0-9])",
                              relates):
            out.append(name)
    return out


def _held_clause(item: dict, held: dict[str, list[str]]) -> tuple[str, str] | None:
    """(held standard name, clause) when the item's clause is one read from
    the standard it names; None otherwise."""
    clause = str(item.get("clause") or "").strip()
    if not clause:
        return None
    for name in _held_names(item, held):
        if clause in held[name]:
            return name, clause
    return None


def from_memory(item: dict, held: dict[str, list[str]]) -> bool:
    """W5b-11 (#559): does the item rest on a standard the library does not
    hold? True when it names a standard and none of the names is a held one.
    An item that names no standard is a general observation, not this class."""
    return bool(str(item.get("relates_to") or "").strip()) and not _held_names(item, held)


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
        # R26 step 7: the local model instead - nothing leaves the machine.
        return True, "local"
    return True, "claude"


def _held_standards(review_run_id: str) -> dict[str, list[str]]:
    rows = connect().execute(
        """SELECT d.filename AS name, r.clause AS clause
           FROM review_applicable_standards a
           JOIN documents d ON d.id = a.standard_document_id
           LEFT JOIN standard_requirements r ON r.standard_document_id = a.standard_document_id
                AND r.superseded_at IS NULL
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
        return None, f"{CALL_FAILED} ({exc})"


#: How a failed call (not a budget refusal) is worded; `run_check` reads it
#: to tell the two apart (#870).
CALL_FAILED = "the model call failed"


#: #844 A DRAFT ABOUT THE SHEET'S FURNITURE IS NOT AN ENGINEERING OBSERVATION.
#: On three real sheets the local model raised "the revision number is zero",
#: "the contract number is present but ..." and "the contents list refers to
#: pages 4 to 5": the title block, the revision box and the index, not the
#: equipment. The item's FIELD names such a box - the whole field, never a
#: word inside a longer engineering name ("Hydrotest date" stays).
_LAYOUT_FIELD = re.compile(
    r"^(?:rev(?:ision)?(?:\s*(?:no|number|date))?(?:\s*[a-z]?\d{1,3}[a-z]?)?|issue(?:\s*(?:no|number|date))?"
    r"|(?:contract|purchase order|po|document|doc|drawing|dwg|project|job|sheet|page|file)"
    r"\s*(?:no|number|ref|reference|title|name)"
    r"|title|sheet title|document title|contents|table of contents|index|date"
    r"|(?:prepared|checked|approved|reviewed|issued)\s*(?:by|for)(?:\s+\w+)?)[\s.:]*$",
    re.IGNORECASE)
#: A contents row: the field ends on the word for a sheet or a page and the
#: value is only page numbers (the same shape the layout reader skips).
_SHEET_WORD_LAST = re.compile(r"(?:sht|shts|sheet|sheets|page|pages)[\s.:]*$", re.IGNORECASE)
_PAGE_NUMBERS_ONLY = re.compile(r"^\s*\d{1,4}(?:\s*(?:to|-|\u2013|,|&|and)\s*\d{1,4})?\s*$", re.IGNORECASE)


def about_layout(item: dict) -> bool:
    """Is this item about the title block, the revision box, a document
    number or a contents table - layout, not the equipment?"""
    field = re.sub(r"[\s.:#\-]+", " ", str(item.get("field") or "")).strip()
    if _LAYOUT_FIELD.match(field):
        return True
    value = str(item.get("value") or "")
    if _SHEET_WORD_LAST.search(field) and _PAGE_NUMBERS_ONLY.match(value):
        return True
    # the field IS the value: a title line or a number box copied whole
    return bool(value.strip()) and _fold(value) == _fold(str(item.get("field") or "")) \
        or bool(re.match(r"^(?:rev|contract|document|doc|drawing|dwg|project|job)\b.*\d", field, re.IGNORECASE)
                and len(field.split()) <= 5 and _fold(value) and _fold(value) in _fold(field))


def _gate_items(items: list, pages: dict[int, str], held: dict[str, list[str]],
                cited: list[str], all_kept: list[dict], rejected: dict[str, int]) -> None:
    """THE ONE PLACE any call's items are gated - a first call's and a
    retry's alike. There is exactly one call to `accept()` in this module's
    run loop so a retry-sourced item can never take a path that skips it."""
    # #844: drafts about the sheet's furniture go first, counted under their own reason
    layout = [item for item in items[:MAX_ITEMS] if isinstance(item, dict) and about_layout(item)]
    if layout:
        rejected[Reason.LAYOUT.value] = rejected.get(Reason.LAYOUT.value, 0) + len(layout)
        items = [item for item in items[:MAX_ITEMS] if not any(item is gone for gone in layout)]
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
    local = f" The check {status['local_instead']}." if status.get("local_instead") else ""
    if status.get("local_scope"):
        local += f" Scope on this run - {status['local_scope']}."
    if status["complete"]:
        return (f"AI engineering check complete: {status['kept_items']} of "
                f"{status['proposed_items']} proposed item(s) kept, over {calls} {call_word}.{local}")
    return (f"AI engineering check incomplete - {status['reason']}. "
            f"{status['kept_items']} item(s) kept so far (at most {status['requested_items']} "
            f"requested per call, {calls} {call_word} made).{local}")


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


@claude_approved.for_review      # #806 S3: the packet is the review's submittal and standards
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

    own_provider = provider is None          # False: a test or a caller handed one in
    ok, why = available() if provider is None else (True, "injected")
    if not ok:
        # #633: ASKED FOR AND COULD NOT RUN IS A FACT ON THE RUN, not silence
        # that reads as "the check found nothing".
        from . import absence
        _store_status(review_run_id, absence.check_failed_status(
            "AI engineering check", str(why)))
        return {"ran": False, "reason": why, "proposed": 0, "kept": 0, "rejected": {}}
    run = submittal_review.get_review_run(review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        return {"ran": False, "reason": "no review run with that id", "proposed": 0,
                "kept": 0, "rejected": {}}
    submittal = run["submittal_document_id"]
    pages = datasheet_pages(submittal)
    held = _held_standards(review_run_id)
    fields = datasheet_fields(submittal)
    local_instead: str | None = None
    if provider is None:
        provider = rp.get_provider("reasoning", step=STEP)
        if not isinstance(provider, rp.ClaudeProvider):
            # #819: this step's own engine says claude and EVERY document of
            # the review (its standards too) is approved: the full check, with
            # the clause list, runs on the cloud model. One unapproved
            # standard keeps it local, and the datasheet-only opinion follows.
            provider = rp.claude_for_task(opinion_engine(), step=STEP) or provider
        if isinstance(provider, rp.ClaudeProvider):
            # #838: documents not approved for the cloud model -> the local
            # model, said on the run. A budget refusal is NOT replaced.
            local_instead = claude_approved.local_instead()
            if local_instead:
                provider = rp.OllamaProvider()
    max_output_tokens = settings.review_ai_check_max_output_tokens
    timeout_s = 240.0
    if isinstance(provider, rp.OllamaProvider):
        # A local model writes far slower than the Claude lane: a smaller
        # output cap and its own timeout, so a review is never held for long.
        max_output_tokens = min(max_output_tokens, LOCAL_MAX_OUTPUT_TOKENS)
        timeout_s = float(settings.review_ai_check_local_timeout_s)
        provider = rp.OllamaProvider(timeout=timeout_s)
    engine: str | None = None

    all_kept: list[dict] = []
    rejected: dict[str, int] = {}
    proposed_total = 0
    cost_total = 0.0
    calls_made = 0
    complete = False
    reason: str | None = None
    covered: list[str] = []

    local_pages: dict | None = None
    if isinstance(provider, rp.OllamaProvider):
        # #844: the local model is asked one page at a time.
        local_pages = _local_page_calls(provider, fields, pages, cited, held, timeout_s,
                                        all_kept, rejected)
        calls_made, proposed_total = local_pages["calls_made"], local_pages["proposed"]
        engine = local_pages["engine"]
        reason = _local_reason(local_pages, timeout_s)
        complete = reason is None

    for call_index in range(0 if local_pages is not None else MAX_CALLS):
        prompt = build_prompt(fields, pages, cited, held,
                              covered=covered if call_index else None)
        response, call_failed = _call(provider, rp.Packet(
            prompt=prompt, system=SYSTEM, num_ctx=settings.num_ctx,
            num_predict=max_output_tokens, json_schema=SCHEMA,
            step=STEP, prompt_version=PROMPT_VERSION, timeout_s=timeout_s))
        calls_made += 1
        if call_failed is not None:
            reason = call_failed
            break
        engine = f"{response.provider}:{response.model_tag}"
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

    if (own_provider and local_pages is None and isinstance(provider, rp.ClaudeProvider)
            and str(reason or "").startswith(CALL_FAILED)):
        # #870: THE CLOUD MODEL'S CALL FAILED (an API error, a time-out; on a
        # live review the account's credit was finished and every call came
        # back refused). The check ran with nothing although the local model
        # could do it. A budget cap is not this: it is the owner's limit and
        # stays a stop. What the cloud model produced before failing is kept.
        local_timeout = float(settings.review_ai_check_local_timeout_s)
        local_pages = _local_page_calls(rp.OllamaProvider(timeout=local_timeout), fields, pages,
                                        cited, held, local_timeout, all_kept, rejected)
        calls_made += local_pages["calls_made"]
        proposed_total += local_pages["proposed"]
        engine = local_pages["engine"] or engine
        reason = _local_reason(local_pages, local_timeout)
        complete = reason is None
        local_instead = rp.CLOUD_CALL_FAILED

    status = {
        "ran": True,
        "complete": complete,
        "calls_made": calls_made,
        "requested_items": LOCAL_ITEMS_PER_PAGE if local_pages is not None else MAX_ITEMS,
        "proposed_items": proposed_total,
        "kept_items": len(all_kept),
        "rejected": dict(rejected),
        "reason": reason,
        "cost_usd": round(cost_total, 6),
        # R26 step 7 / AI-first rule 3: which engine and model ran it.
        "model": engine,
        # #838: None, or why the local model ran in the cloud model's place.
        "local_instead": local_instead,
        # #844: None on the Claude lane; on the local model, pages asked and
        # what became of each (page numbers only).
        "local_pages": None if local_pages is None else {
            k: local_pages[k] for k in ("pages", "done", "timed_out", "failed", "not_tried",
                                        "no_value_read", "no_blank_field")},
        # #844: None on the Claude lane (full scope); on the local model, what it was asked.
        "local_scope": None if local_pages is None else LOCAL_SCOPE,
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
        unverified = from_memory(item, held)
        relates = str(item.get("relates_to") or "").strip()
        finding = review_mod.create({
            "document_id": submittal,
            "category": "technical_query",
            "severity": "minor",
            "confidence": "low" if unverified else item["confidence"],
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
                 None if unverified else (verified[1] if verified else None),
                 (f"{UNVERIFIED_LABEL}. {LABEL}. Relates to: {relates}." if unverified
                  else f"{LABEL}. Relates to: {relates or 'no standard named'}."),
                 finding["id"]))
    # #501: every draft says which engine wrote it.
    with conn:
        conn.execute(
            "UPDATE review_findings SET ai_rationale = ai_rationale || ? WHERE review_run_id = ?"
            f" AND origin = ? AND ai_rationale NOT LIKE '%Written by %' AND {review_mod.UNDECIDED_SQL}",
            (_written_by(engine), review_run_id, ORIGIN))
    return {"ran": True, "reason": reason, "proposed": proposed_total, "kept": len(all_kept),
            "rejected": rejected, "cost_usd": round(cost_total, 6), "complete": complete,
            "calls_made": calls_made, "local_instead": local_instead}


# ------------------------------------- #501: the datasheet-only opinion
#
# OWNER DECISION 2026-10-12: Claude may be used for the AI engineering check
# on datasheets the owner approved - and standards text may not go. The check
# above lists the held standards and their clauses, so the approved-document
# lock refuses it on the cloud lane (and #838 runs it locally). This is a
# SECOND opinion beside it, not a replacement: the same instructions and the
# same gate, a packet that carries THE DATASHEET ALONE (its pages, its fields,
# the standard names the datasheet itself cites), declared as carrying only
# the submittal. With no clause list it can cite no clause: the gate refuses
# one. Every draft it writes says which engine wrote it and from what.

#: Marks a draft of the datasheet-only opinion in `ai_rationale`.
DATASHEET_ONLY = "from the datasheet alone - no standard's text was sent"


def opinion_engine() -> str:
    return str(settings.review_ai_check_engine or "ollama").strip().lower() or "ollama"


def _written_by(engine: str | None) -> str:
    return f" Written by {engine or 'an unnamed engine'}."


def run_datasheet_opinion(review_run_id: str, *, allowed_document_ids: frozenset[str],
                          cited: list[str], provider=None) -> dict:
    """Ask the Claude lane for a datasheet-only opinion and store the kept
    items as pending drafts beside the check's own. Returns counts, never
    text, and records the outcome under `claude_datasheet` in the run's
    `ai_check_status` - asked and refused is a fact on the run.

    NOT under `claude_approved.for_review`: that declares the review's
    standards. This declares the SUBMITTAL ONLY, which is all its packet
    carries - so it must be called on its own, never from inside `run_check`."""
    from . import review as review_mod
    from . import reasoning_provider as rp
    from . import submittal_review

    outcome = {"ran": False, "reason": None, "engine": None, "calls_made": 0, "proposed": 0,
               "kept": 0, "stored": 0, "rejected": {}, "cost_usd": 0.0}
    if not settings.review_ai_check_enabled or (provider is None and opinion_engine() != rp.CLAUDE):
        return outcome                      # not asked for: nothing to record
    if provider is None and str((ai_check_status(review_run_id, allowed_document_ids=allowed_document_ids)
                                 or {}).get("model") or "").startswith(rp.CLAUDE + ":"):
        # #819: the FULL check already ran on the cloud model for this run
        # (every document approved); a second, narrower opinion adds nothing.
        return outcome
    run = submittal_review.get_review_run(review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        return {**outcome, "reason": "no review run with that id"}
    submittal = run["submittal_document_id"]
    if provider is None:
        code, why = rp.claude_unavailable_for_task(opinion_engine())
        if code is not None:
            return _store_opinion(review_run_id, allowed_document_ids,
                                  {**outcome, "reason": f"the cloud model may not be used ({code})"})
        provider = rp.ClaudeProvider(settings.claude_reasoning_model, step=STEP)
    pages = datasheet_pages(submittal)
    fields = datasheet_fields(submittal)
    kept: list[dict] = []
    rejected: dict[str, int] = {}
    with claude_approved.carrying([submittal]):
        response, call_failed = _call(provider, _opinion_packet(fields, pages, cited))
    outcome["calls_made"] = 1
    if call_failed is not None:
        return _store_opinion(review_run_id, allowed_document_ids, {**outcome, "reason": call_failed})
    outcome["engine"] = f"{response.provider}:{response.model_tag}"
    outcome["cost_usd"] = round(response.cost_usd or 0.0, 6)
    items = None if response.schema_errors else parse(response.text)
    if items is None and response.truncated:
        items = parse_partial(response.text or "")
        outcome["reason"] = "the reply was cut off by the output limit before it finished"
    if items is None:
        rejected[Reason.MALFORMED.value] = 1
        return _store_opinion(review_run_id, allowed_document_ids,
                              {**outcome, "reason": Reason.MALFORMED.value, "rejected": rejected})
    outcome["proposed"] = len(items)
    # THE SAME GATE, with no held clause: a cited clause cannot be verified and is refused.
    _gate_items(items, pages, {}, cited, kept, rejected)
    outcome.update(ran=True, kept=len(kept), rejected=dict(rejected))

    conn = connect()
    known = {_item_identity(r["finding"], r["required_action"], r["contractor_page"], r["contractor_section"])
             for r in conn.execute(
                 "SELECT finding, required_action, contractor_page, contractor_section"
                 " FROM review_findings WHERE review_run_id = ? AND origin = ?", (review_run_id, ORIGIN))}
    for item in kept:
        identity = _item_identity(str(item["observation"])[:4000], str(item["action"])[:4000],
                                  item["page"], str(item["field"])[:400])
        if identity in known:               # already raised (or rejected by an engineer): not twice
            continue
        known.add(identity)
        relates = str(item.get("relates_to") or "").strip()
        finding = review_mod.create({
            "document_id": submittal, "category": "technical_query", "severity": "minor",
            "confidence": "low" if from_memory(item, {}) else item["confidence"],
            "requirement": str(item["topic"])[:4000], "finding": str(item["observation"])[:4000],
            "required_action": str(item["action"])[:4000], "status": "open",
            "approval_status": "pending"}, created_by=None)
        with conn:
            conn.execute(
                """UPDATE review_findings SET review_run_id = ?, origin = ?, contractor_page = ?,
                       contractor_section = ?, contractor_evidence_text = ?, ai_rationale = ?
                   WHERE id = ?""",
                (review_run_id, ORIGIN, item["page"], str(item["field"])[:400],
                 str(item.get("value") or "")[:400] or None,
                 f"{LABEL}. Relates to: {relates or 'no standard named'}."
                 f"{_written_by(outcome['engine'])[:-1]}, {DATASHEET_ONLY}.",
                 finding["id"]))
        outcome["stored"] += 1
    return _store_opinion(review_run_id, allowed_document_ids, outcome)


def _opinion_packet(fields: list[dict], pages: dict[int, str], cited: list[str]):
    from . import reasoning_provider as rp
    return rp.Packet(
        prompt=build_prompt(fields, pages, cited, {}), system=SYSTEM, num_ctx=settings.num_ctx,
        num_predict=settings.review_ai_check_max_output_tokens, json_schema=SCHEMA, step=STEP,
        prompt_version=PROMPT_VERSION + "+datasheet-only", timeout_s=240.0)


def _store_opinion(review_run_id: str, allowed_document_ids: frozenset[str], outcome: dict) -> dict:
    """Record the opinion's outcome on the run, beside the check's own."""
    status = ai_check_status(review_run_id, allowed_document_ids=allowed_document_ids) or {}
    status["claude_datasheet"] = outcome
    said = (f" Datasheet-only opinion by {outcome['engine']}: {outcome['kept']} of "
            f"{outcome['proposed']} proposed item(s) kept." if outcome["ran"]
            else f" Datasheet-only opinion by the cloud model did not run - {outcome['reason']}.")
    base = str(status.get("plain") or "").split(" Datasheet-only opinion by ")[0]
    status["plain"] = (base + said).strip()
    _store_status(review_run_id, status)
    return outcome


def _item_identity(finding, action, page, section) -> tuple:
    """What makes two AI check items the same comment - the fields
    `crs_mapping` keys its permanent number on, folded."""
    fold = lambda v: " ".join(str(v or "").lower().split())  # noqa: E731
    return (fold(finding), fold(action), page, fold(section))
