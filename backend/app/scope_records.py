"""A standard's SCOPE, read once per edition into a verified record (B5,
owner order 2026-09-25 sections 4.3-4.5). PROPOSAL STAGE: not called by any
live route.

  find_passages - the scope finder (4.3): Scope / Application / Exclusions
      headings on ANY page (General / Introduction to page 10), a scope that
      runs off its page with the next page as a continuation, then the app's
      own hybrid search on that standard, then the first pages; top
      MAX_PASSAGES passages, each with its page and the method.
  read_scope - one model call through the reasoning provider (Claude or
      Ollama) with a JSON schema; every item's quote is verified against the
      page it names (`model_evidence.quote_verified`) or the item is dropped.
      One retry with a "short quotes" instruction on invalid output; still
      invalid = UNKNOWN. Model, prompt version and input hash are recorded.
      Exclusions and limits carry a `cue_context` cut by code from the page.
  read_scope_batch - the same for many standards through the Message
      Batches API (half price), one retry batch, a budget check per round.
  decide_with_confirmation - `applicability_v2.decide`, and a NOT_APPLICABLE
      stands only if 3 independent re-reads all decide NOT_APPLICABLE (4.5.4).

The decision itself is code (`applicability_v2`); the model only fills the
record. Nothing unapproved is baked in: the lexicon is a parameter.
"""
from __future__ import annotations

import json
import re

from . import applicability_v2, search
from .db import connect
from .model_evidence import _collapse, quote_verified  # the verifier's own normalisation
from .reasoning_provider import Packet

PROMPT_VERSION = "scope-record-v4"

#: A heading alone on its line ("1 Scope", "Scope:"), or a heading word
#: followed by . : or ; and text on the same line ("Scope. This code applies
#: to the following:", "1.2 Application; Specifically ..."). A heading word
#: running on into a sentence ("Application for which the equipment ...") is
#: body text, not a heading; so is a lower-case word wrapped onto its own line.
_HEAD = re.compile(r"(?im)^[ \t]*(?:\d+(?:\.\d+)*\.?[ \t]*)?(Scope|Purpose|Applicability|Application|Coverage|"
                   r"Exclusions?|General|Introduction)\b[ \t]*(?:[:;.][ \t]*(?=\S)|:?[ \t]*$)")
_PRIMARY = {"scope", "purpose", "applicability", "application", "coverage", "exclusion", "exclusions"}
#: A scope section that is still open at the end of its page (no next section
#: began) continues on the next page.
_NEXT_SECTION = re.compile(r"(?m)^[ \t]*(?:[2-9]|1\d)\.?[ \t]+[A-Z]|Conflicts and Deviations|Normative References")
PASSAGE_CHARS = 1500
CONTINUATION_CHARS = 900
MAX_PASSAGES = 4
#: Secondary headings (General, Introduction) are only looked for this early.
SECONDARY_PAGES = 10


def page_text(document_id: str, page_no: int) -> str:
    row = connect().execute("SELECT text FROM pages WHERE document_id=? AND page_no=?",
                            (document_id, page_no)).fetchone()
    return (row["text"] if row else "") or ""


def find_passages(document_id: str, *, search_fn=None) -> list[dict]:
    """Up to MAX_PASSAGES candidate scope passages: {page, method, text}.
    A Scope/Application/Exclusions heading is looked for on EVERY page (a
    long standard puts its scope on page 18); a scope that runs off the end of
    its page brings the head of the next page as a `continuation` passage."""
    cands = []
    rows = list(connect().execute("SELECT page_no, text FROM pages WHERE document_id=? ORDER BY page_no",
                                  (document_id,)))
    texts = {r["page_no"]: r["text"] or "" for r in rows}
    for page_no, text in texts.items():
        for m in _HEAD.finditer(text):
            word = m.group(1)
            primary = word.lower() in _PRIMARY
            if not word[0].isupper() or (not primary and page_no > SECONDARY_PAGES):
                continue
            body = text[m.end(): m.end() + PASSAGE_CHARS].strip()
            if len(body) < 40 or "....." in body:          # a table-of-contents line
                continue
            rank = 0 if primary else 1
            cands.append({"page": page_no, "method": f"heading:{word}", "rank": (rank, page_no, 0), "text": body})
            nxt = texts.get(page_no + 1, "").strip()
            if (primary and nxt and len(text) - m.end() < PASSAGE_CHARS
                    and not _NEXT_SECTION.search(text[m.end():])):
                cands.append({"page": page_no + 1, "method": f"continuation:{word}", "rank": (rank, page_no, 1),
                              "text": nxt[:CONTINUATION_CHARS]})
    try:
        res = (search_fn or search.search)("scope applies to equipment exclusions", limit=6,
                                           allowed_document_ids=frozenset({document_id}))
        for i, hit in enumerate(res["hits"][:4]):
            cands.append({"page": hit["page_start"], "method": "hybrid-search", "rank": (2, i, 0),
                          "text": (hit["text"] or "")[:PASSAGE_CHARS]})
    except Exception:  # noqa: BLE001 - search is one of three sources; the others still count
        pass
    for p in range(1, 7):
        text = texts.get(p, "").strip()
        if text:
            cands.append({"page": p, "method": "first-pages", "rank": (3, p, 0), "text": text[:PASSAGE_CHARS]})
    cands.sort(key=lambda c: c["rank"])
    kept: list[dict] = []
    for c in cands:
        head = " ".join(c["text"].split())[:80]
        if any(k["page"] == c["page"] and (head in " ".join(k["text"].split())
                                            or " ".join(k["text"].split())[:80] in " ".join(c["text"].split()))
               for k in kept):
            continue
        kept.append({key: c[key] for key in ("page", "method", "text")})
        if len(kept) == MAX_PASSAGES:
            break
    return kept


_ITEM = {"type": "object", "properties": {"term": {"type": "string"}, "quote": {"type": "string"},
                                           "page": {"type": "integer"}}, "required": ["term", "quote", "page"]}
#: min / max / unit are OPTIONAL: requiring them on a non-numeric limit
#: rejected 2 of 8 real answers in the M-03 run (2026-09-25). Numbers are
#: still compared by code, never trusted from the model.
_LIMIT = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["equipment", "pressure", "temperature", "size", "service", "facility",
                                        "stage"]},
    "term": {"type": "string"}, "min": {"type": ["number", "null"]}, "max": {"type": ["number", "null"]},
    "unit": {"type": ["string", "null"]}, "quote": {"type": "string"}, "page": {"type": "integer"}},
    "required": ["kind", "term", "quote", "page"]}
_ACTIVITY = {"type": "object", "properties": {
    "activity": {"type": "string", "enum": ["design", "fabrication", "inspection", "testing", "installation",
                                            "operation", "repair", "maintenance", "other"]},
    "quote": {"type": "string"}, "page": {"type": "integer"}}, "required": ["activity", "quote", "page"]}
_QUOTE = {"type": "object", "properties": {"quote": {"type": "string"}, "page": {"type": "integer"}},
          "required": ["quote", "page"]}
SCHEMA = {"type": "object", "properties": {
    "covered_equipment": {"type": "array", "items": _ITEM},
    "covered_activities": {"type": "array", "items": _ACTIVITY},
    "new_construction": {"type": "array", "items": _QUOTE},
    "explicit_exclusions": {"type": "array", "items": _ITEM},
    "explicit_limits": {"type": "array", "items": _LIMIT},
    "generic_scope": {"type": "boolean"}},
    "required": ["covered_equipment", "covered_activities", "new_construction", "explicit_exclusions",
                 "explicit_limits", "generic_scope"]}
#: The fields `verify` keeps from each model item; anything else the model
#: adds (a `cue_context` of its own, say) is dropped.
_FIELDS = {"covered_equipment": ("term", "quote", "page"),
           "covered_activities": ("activity", "quote", "page"),
           "new_construction": ("quote", "page"),
           "explicit_exclusions": ("term", "quote", "page"),
           "explicit_limits": ("kind", "term", "min", "max", "unit", "quote", "page")}

INSTRUCTIONS = (
    "Read the SCOPE of one engineering standard from the passages below; each passage is marked with its "
    "page. Fill the JSON:\n"
    "- covered_equipment: equipment the standard covers, ONE item per kind of equipment. Include equipment "
    "named in an 'applies to' sentence or as 'X within the scope of <another standard>'. term = the words "
    "of the quote that name that equipment.\n"
    "- covered_activities: design / fabrication / inspection / testing / installation / operation / repair / "
    "maintenance it covers. Welding, NDT or materials for building equipment are fabrication.\n"
    "- new_construction: quotes showing the scope covers NEW equipment (its design, fabrication, construction "
    "or manufacture). Empty if the passages do not say so.\n"
    "- explicit_exclusions: ONLY what the text says the standard does NOT cover or does not apply to "
    "(\"does not apply\", \"excluding\", \"except\", \"not covered\", \"excluded from the scope are:\"). ONE "
    "item per excluded kind of equipment, term = that kind (e.g. a list 'safety-relief, relief and pilot "
    "valves' gives three items); an item of a list under such an intro counts, quoting the list item. A "
    "sentence about purchasing, documents or responsibilities is not an exclusion.\n"
    "- explicit_limits: only where the text restricts where it applies (\"only\", \"limited to\", \"above\", "
    "\"below\", \"onshore\", \"offshore\", \"in-service\"); kind = equipment / pressure / temperature / size / "
    "service / facility / stage (stage = limited to existing or in-service equipment, or to new equipment); "
    "give min / max / unit only for numbers.\n"
    "- generic_scope: true if the scope names no specific equipment, only general words such as equipment, "
    "facilities, plants or piping.\n"
    "Every quote must be copied EXACTLY from a passage, character for character, and SHORT (under 20 "
    "words). page = the page of the passage the quote comes from. Use only these passages; empty lists if "
    "nothing applies. JSON only.\n")
RETRY = "Keep every list to at most 5 items and every quote under 12 words.\n"
#: Output cap per call. A v4 record is 300-900 tokens; the cap is what a
#: runaway answer costs at most.
NUM_PREDICT = 1500


def _parse(text: str) -> dict | None:
    body = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", body, re.S)
    try:
        value = json.loads(fence.group(1) if fence else body)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def cue_context(quote: str | None, page: str | None) -> str:
    """The verified words that come BEFORE `quote` in its own sentence, plus
    the list intro it hangs from (the last "...:" within 400 characters).
    Cut from the page, never from the model - `applicability_v2` reads an
    exclusion or limit cue from here as well as from the quote. Words AFTER
    the quote are not included: in "covers centrifugal pumps excluding
    submersible pumps" the cue belongs to the submersible pumps only."""
    text, needle = _collapse(page), _collapse(quote)
    at = text.find(needle) if needle else -1
    if at < 0:
        return ""
    start = max(text.rfind(". ", 0, at), text.rfind("; ", 0, at), text.rfind(" but ", 0, at))
    context = text[start + 1 if start >= 0 else 0: at].strip()
    colon = text.rfind(":", max(0, at - 400), at)
    if colon >= 0 and colon < (start if start >= 0 else 0):
        intro_start = text.rfind(". ", 0, colon)
        context = text[intro_start + 2 if intro_start >= 0 else 0: colon + 1].strip() + " ... " + context
    return context[-500:]


def verify(parsed: dict, passages: list[dict], document_id: str, lexicon: dict) -> tuple[dict, int, int]:
    """Keep only items whose quote is on the page they name. Returns
    (record, dropped, kept_count). generic_scope is the model's flag AND no
    verified covered term names a taxonomy node. Exclusions and limits carry
    a code-cut `cue_context` (see `cue_context`)."""
    texts = {p["page"]: page_text(document_id, p["page"]) for p in passages}
    kept: dict = {}
    dropped = 0
    for key, fields in _FIELDS.items():
        kept[key] = []
        for it in parsed.get(key) or []:
            if isinstance(it, dict) and it.get("page") in texts and quote_verified(it.get("quote"), texts[it["page"]]):
                item = {f: it.get(f) for f in fields if f in it}
                if key in ("explicit_exclusions", "explicit_limits"):
                    item["cue_context"] = cue_context(it["quote"], texts[it["page"]])
                kept[key].append(item)
            else:
                dropped += 1
    specific = any(applicability_v2.nodes_for(i.get("term"), lexicon) for i in kept["covered_equipment"])
    kept["generic_scope_model"] = bool(parsed.get("generic_scope"))
    kept["generic_scope"] = kept["generic_scope_model"] and not specific
    count = sum(len(kept[k]) for k in ("covered_equipment", "covered_activities", "explicit_exclusions",
                                       "explicit_limits"))
    return kept, dropped, count


def packet(passages: list[dict], *, step: str, seed: int | None = None, retry: bool = False,
           num_predict: int = NUM_PREDICT) -> Packet:
    """The one request for one standard's scope - the same for a single call
    and for a Message Batches request."""
    body = "".join(f"[PASSAGE {i + 1} - page {p['page']}]\n{p['text']}\n\n" for i, p in enumerate(passages))
    return Packet(prompt=(RETRY if retry else "") + body + "ANSWER:\n", system=INSTRUCTIONS, num_ctx=8192,
                  num_predict=num_predict, json_schema=SCHEMA, step=step, seed=seed,
                  prompt_version=PROMPT_VERSION)


def usable(response) -> dict | None:
    """The parsed answer, or None when it is invalid (schema errors,
    truncated, not JSON)."""
    if response is None or response.schema_errors or response.truncated:
        return None
    return _parse(response.text)


def record_from(document_id: str, passages: list[dict], responses: list, *, lexicon: dict,
                seed: int | None = None) -> dict:
    """The scope-record result from the (one or two) responses of one
    standard: the last response decides; invalid after the retry = UNKNOWN."""
    out = {"document_id": document_id, "prompt_version": PROMPT_VERSION, "seed": seed,
           "passages": [{"page": p["page"], "method": p["method"]} for p in passages]}
    if not passages:
        return {**out, "status": "UNKNOWN", "why": "no scope passage found", "record": None,
                "invalid_output": False, "tries": 0}
    last = responses[-1]
    parsed = usable(last)
    out.update({"tries": len(responses), "model": last.model_tag, "input_sha256": last.prompt_sha256,
                "first_try_invalid": len(responses) > 1, "invalid_output": parsed is None})
    if parsed is None:
        return {**out, "status": "UNKNOWN", "why": "invalid output after one retry", "record": None}
    record, dropped, count = verify(parsed, passages, document_id, lexicon)
    return {**out, "record": record if count else None, "dropped_unverified": dropped, "verified_items": count,
            "status": "PROPOSED" if count else "UNKNOWN", "why": None if count else "no item with a verified quote"}


def read_scope(document_id: str, provider, *, lexicon: dict, step: str, seed: int | None = None,
               passages: list[dict] | None = None) -> dict:
    """One scope record for one standard edition. `seed` distinguishes the
    independent re-reads of the NOT_APPLICABLE confirmation (it is part of the
    response-cache key, so a re-read is a real call)."""
    passages = find_passages(document_id) if passages is None else passages
    responses: list = []
    if passages:
        for retry in (False, True):
            responses.append(provider.reason(packet(passages, step=step, seed=seed, retry=retry)))
            if usable(responses[-1]) is not None:
                break
    return record_from(document_id, passages, responses, lexicon=lexicon, seed=seed)


def read_scope_batch(passages_by_doc: dict[str, list[dict]], provider, *, lexicon: dict, step: str,
                     num_predict: int = NUM_PREDICT, compact: bool = False, retry_num_predict: int | None = None,
                     may_send=None, **batch_kw) -> dict[str, dict]:
    """`read_scope` for many standards through `provider.reason_batch`
    (Message Batches, half price): one batch, then ONE retry batch - with the
    RETRY instruction - for the answers that were invalid. Same verification,
    same record shape, same UNKNOWN rules as a single read.

    `compact` sends the RETRY instruction (short lists, short quotes) from the
    first round, to bound the output; the retry round may then allow more
    tokens (`retry_num_predict`). `may_send(packets) -> bool` is asked before
    each round (a budget check); a refused round is not sent and its
    standards stay UNKNOWN ("not read")."""
    ids = [d for d, ps in passages_by_doc.items() if ps]
    responses: dict[str, list] = {d: [] for d in passages_by_doc}
    for retry in (False, True):
        todo = [d for d in ids if responses[d] and usable(responses[d][-1]) is None] if retry else ids
        if not todo:
            continue
        cap = (retry_num_predict or num_predict) if retry else num_predict
        packets = [packet(passages_by_doc[d], step=step, retry=retry or compact, num_predict=cap) for d in todo]
        if may_send is not None and not may_send(packets):
            continue
        for d, r in zip(todo, provider.reason_batch(packets, **batch_kw)):
            responses[d].append(r)
    out = {}
    for d, ps in passages_by_doc.items():
        if ps and not responses[d]:
            out[d] = {"document_id": d, "prompt_version": PROMPT_VERSION, "status": "UNKNOWN",
                      "why": "not read (batch not sent)", "record": None, "invalid_output": False, "tries": 0,
                      "passages": [{"page": p["page"], "method": p["method"]} for p in ps]}
        else:
            out[d] = record_from(d, ps, responses[d], lexicon=lexicon)
    return out


def decide_with_confirmation(document_id: str, provider, profile, *, lexicon: dict, step: str,
                             first: dict | None = None, passages: list[dict] | None = None) -> dict:
    """The decision for one (standard, submittal). A NOT_APPLICABLE is kept
    only when three further independent reads OF THE SAME PASSAGES all agree;
    otherwise UNKNOWN."""
    passages = find_passages(document_id) if passages is None else passages
    first = first or read_scope(document_id, provider, lexicon=lexicon, step=step, passages=passages)
    decision = applicability_v2.decide(first["record"], profile, lexicon)
    if decision["decision"] != applicability_v2.NOT_APPLICABLE:
        return {**decision, "confirmations": None}
    rereads = [applicability_v2.decide(read_scope(document_id, provider, lexicon=lexicon, step=step, seed=s,
                                                  passages=passages)["record"], profile, lexicon)
               for s in (1, 2, 3)]
    if applicability_v2.confirm_not_applicable(rereads):
        return {**decision, "confirmations": 3}
    agreeing = sum(1 for r in rereads if r["decision"] == applicability_v2.NOT_APPLICABLE)
    return {"decision": applicability_v2.UNKNOWN,
            "basis": f"NOT_APPLICABLE held back: {agreeing}/3 re-reads agreed",
            "quote": None, "page": None, "term": None, "confirmations": agreeing}
