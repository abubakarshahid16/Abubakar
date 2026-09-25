"""A standard's SCOPE, read once per edition into a verified record (B5,
owner order 2026-09-25 sections 4.3-4.5). PROPOSAL STAGE: not called by any
live route.

  find_passages - the scope finder (4.3): headings (Scope, Purpose,
      Applicability, ...), then the app's own hybrid search on that standard,
      then the first pages; top 3 passages, each with its page and the method.
  read_scope - one model call through the reasoning provider (Claude or
      Ollama) with a JSON schema; every item's quote is verified against the
      page it names (`model_evidence.quote_verified`) or the item is dropped.
      One retry with a "short quotes" instruction on invalid output; still
      invalid = UNKNOWN. Model, prompt version and input hash are recorded.
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
from .model_evidence import quote_verified
from .reasoning_provider import Packet

PROMPT_VERSION = "scope-record-v3"

_HEAD = re.compile(r"(?im)^[ \t]*(?:\d+(?:\.\d+)*\.?[ \t]*)?(Scope|Purpose|Applicability|Application|Coverage|"
                   r"Exclusions?|General|Introduction)[ \t]*:?[ \t]*$")
_PRIMARY = {"scope", "purpose", "applicability", "application", "coverage", "exclusion", "exclusions"}
PASSAGE_CHARS = 1500
MAX_PASSAGES = 3


def page_text(document_id: str, page_no: int) -> str:
    row = connect().execute("SELECT text FROM pages WHERE document_id=? AND page_no=?",
                            (document_id, page_no)).fetchone()
    return (row["text"] if row else "") or ""


def find_passages(document_id: str, *, search_fn=None) -> list[dict]:
    """Up to 3 candidate scope passages: {page, method, text}."""
    cands = []
    for row in connect().execute("SELECT page_no, text FROM pages WHERE document_id=? AND page_no <= 10 "
                                 "ORDER BY page_no", (document_id,)):
        text = row["text"] or ""
        for m in _HEAD.finditer(text):
            body = text[m.end(): m.end() + PASSAGE_CHARS].strip()
            if len(body) < 40 or "....." in body:          # a table-of-contents line
                continue
            primary = m.group(1).lower() in _PRIMARY
            cands.append({"page": row["page_no"], "method": f"heading:{m.group(1)}",
                          "rank": (0 if primary else 1, row["page_no"]), "text": body})
    try:
        res = (search_fn or search.search)("scope applies to equipment exclusions", limit=6,
                                           allowed_document_ids=frozenset({document_id}))
        for i, hit in enumerate(res["hits"][:4]):
            cands.append({"page": hit["page_start"], "method": "hybrid-search", "rank": (2, i),
                          "text": (hit["text"] or "")[:PASSAGE_CHARS]})
    except Exception:  # noqa: BLE001 - search is one of three sources; the others still count
        pass
    for p in range(1, 7):
        text = page_text(document_id, p).strip()
        if text:
            cands.append({"page": p, "method": "first-pages", "rank": (3, p), "text": text[:PASSAGE_CHARS]})
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
    "kind": {"type": "string", "enum": ["equipment", "pressure", "temperature", "size", "service", "facility"]},
    "term": {"type": "string"}, "min": {"type": ["number", "null"]}, "max": {"type": ["number", "null"]},
    "unit": {"type": ["string", "null"]}, "quote": {"type": "string"}, "page": {"type": "integer"}},
    "required": ["kind", "term", "quote", "page"]}
_ACTIVITY = {"type": "object", "properties": {
    "activity": {"type": "string", "enum": ["design", "fabrication", "inspection", "testing", "installation",
                                            "operation", "repair", "maintenance", "other"]},
    "quote": {"type": "string"}, "page": {"type": "integer"}}, "required": ["activity", "quote", "page"]}
SCHEMA = {"type": "object", "properties": {
    "covered_equipment": {"type": "array", "items": _ITEM},
    "covered_activities": {"type": "array", "items": _ACTIVITY},
    "explicit_exclusions": {"type": "array", "items": _ITEM},
    "explicit_limits": {"type": "array", "items": _LIMIT},
    "generic_scope": {"type": "boolean"}},
    "required": ["covered_equipment", "covered_activities", "explicit_exclusions", "explicit_limits",
                 "generic_scope"]}

INSTRUCTIONS = (
    "Read the SCOPE of one engineering standard from the passages below; each passage is marked with its "
    "page. Fill the JSON:\n"
    "- covered_equipment: equipment the standard covers.\n"
    "- covered_activities: design / fabrication / inspection / testing / installation / operation / repair / "
    "maintenance it covers.\n"
    "- explicit_exclusions: ONLY what the text says the standard does NOT cover or does not apply to "
    "(\"does not apply\", \"excluding\", \"except\", \"not covered\"). A sentence about purchasing, documents or "
    "responsibilities is not an exclusion.\n"
    "- explicit_limits: only where the text restricts where it applies (\"only\", \"limited to\", \"above\", "
    "\"below\", \"onshore\", \"offshore\"); kind = equipment / pressure / temperature / size / service / "
    "facility; give min / max / unit only for numbers.\n"
    "- generic_scope: true if the scope names no specific equipment, only general words such as equipment, "
    "facilities, plants or piping.\n"
    "Every quote must be copied EXACTLY from a passage, character for character, and SHORT (under 20 "
    "words). page = the page of the passage the quote comes from. Use only these passages; empty lists if "
    "nothing applies. JSON only.\n")
RETRY = "Keep every list to at most 5 items and every quote under 12 words.\n"


def _parse(text: str) -> dict | None:
    body = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", body, re.S)
    try:
        value = json.loads(fence.group(1) if fence else body)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def verify(parsed: dict, passages: list[dict], document_id: str, lexicon: dict) -> tuple[dict, int, int]:
    """Keep only items whose quote is on the page they name. Returns
    (record, dropped, kept_count). generic_scope is the model's flag AND no
    verified covered term names a taxonomy node."""
    texts = {p["page"]: page_text(document_id, p["page"]) for p in passages}
    kept: dict = {}
    dropped = 0
    for key in ("covered_equipment", "covered_activities", "explicit_exclusions", "explicit_limits"):
        kept[key] = []
        for it in parsed.get(key) or []:
            if isinstance(it, dict) and it.get("page") in texts and quote_verified(it.get("quote"), texts[it["page"]]):
                kept[key].append(it)
            else:
                dropped += 1
    specific = any(applicability_v2.nodes_for(i.get("term"), lexicon) for i in kept["covered_equipment"])
    kept["generic_scope_model"] = bool(parsed.get("generic_scope"))
    kept["generic_scope"] = kept["generic_scope_model"] and not specific
    count = sum(len(kept[k]) for k in ("covered_equipment", "covered_activities", "explicit_exclusions",
                                       "explicit_limits"))
    return kept, dropped, count


def read_scope(document_id: str, provider, *, lexicon: dict, step: str, seed: int | None = None,
               passages: list[dict] | None = None) -> dict:
    """One scope record for one standard edition. `seed` distinguishes the
    independent re-reads of the NOT_APPLICABLE confirmation (it is part of the
    response-cache key, so a re-read is a real call)."""
    passages = find_passages(document_id) if passages is None else passages
    out = {"document_id": document_id, "prompt_version": PROMPT_VERSION, "seed": seed,
           "passages": [{"page": p["page"], "method": p["method"]} for p in passages]}
    if not passages:
        return {**out, "status": "UNKNOWN", "why": "no scope passage found", "record": None,
                "invalid_output": False, "tries": 0}
    body = "".join(f"[PASSAGE {i + 1} - page {p['page']}]\n{p['text']}\n\n" for i, p in enumerate(passages))
    tries, parsed, response = 0, None, None
    for extra in ("", RETRY):
        tries += 1
        response = provider.reason(Packet(prompt=extra + body + "ANSWER:\n", system=INSTRUCTIONS,
                                          num_ctx=8192, num_predict=1500, json_schema=SCHEMA, step=step,
                                          seed=seed, prompt_version=PROMPT_VERSION))
        if not response.schema_errors and not response.truncated:
            parsed = _parse(response.text)
            if parsed is not None:
                break
    out.update({"tries": tries, "model": response.model_tag, "input_sha256": response.prompt_sha256,
                "first_try_invalid": tries > 1, "invalid_output": parsed is None})
    if parsed is None:
        return {**out, "status": "UNKNOWN", "why": "invalid output after one retry", "record": None}
    record, dropped, count = verify(parsed, passages, document_id, lexicon)
    return {**out, "record": record if count else None, "dropped_unverified": dropped, "verified_items": count,
            "status": "PROPOSED" if count else "UNKNOWN", "why": None if count else "no item with a verified quote"}


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
