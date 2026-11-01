"""Which equipment type a stored rule is written for, read from the rule's OWN clause
text and its section-heading chain. Never from the standard's name (rule 13: no
per-standard or per-layout code) and never guessed (rule 4: unknown stays unknown).

Returns (types, quote, page, method). Several types named: all of them, never one picked.
Order of evidence, first hit wins: (1) an explicit scope phrase in the clause ("applies to
centrifugal pumps", "intended for ...", a sentence opening "For shell and tube heat
exchangers,"); (2) the grammatical subject before the first "shall" ("The pump casing
shall"); (3) the heading chain ("5.2 Heat Exchangers"). Types come from
`subject_scope.vocabulary()` (equipment kind only; a component such as piping names none).

Behind `settings.rule_equipment_scope_extract_enabled` (extraction writes
`standard_requirements.equipment_type`, evidence in `equipment_scope_evidence`) and
`scripts/reextract_rule_equipment_scope.py` (a COPY of the database only). The optional
local-model pass (`rule_equipment_scope_model_enabled`, off) reaches only `model_transport`
(local Ollama); the code verifies its answer: the types must be in the vocabulary and the
quote must be words of the clause, or the answer is dropped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable

from . import subject_scope

UNKNOWN = "unknown"
WORDING = "wording_scope_phrase"
SUBJECT = "wording_subject"
HEADING = "heading"
MODEL = "local_model"
QUOTE_WORDS = 25

_STRONG = re.compile(
    r"\b(?:applies to|apply to|applicable to|intended for|specific to|only for|"
    r"for use (?:in|on|with)|(?:when|where) (?:used|applied|installed) (?:in|on|for|with)|"
    r"covers|requirements for|provisions for)\b", re.IGNORECASE)
_LEADING_FOR = re.compile(r"^\W*for\b", re.IGNORECASE)
_STOP = re.compile(r"[.;:]|\b(?:shall|must|should|may|will)\b", re.IGNORECASE)
_WINDOW_WORDS = 8
_PREPOSITION = re.compile(r"\b(?:of|for|in|on|at|with|from|to|by|within|under)\b", re.IGNORECASE)
_MODAL = re.compile(r"\b(?:shall|must|should|may|will|needs? to|is to|are to)\b", re.IGNORECASE)


def extract_enabled() -> bool:
    from .config import settings

    return bool(settings.rule_equipment_scope_extract_enabled)


def model_enabled() -> bool:
    from .config import settings

    return bool(settings.rule_equipment_scope_model_enabled)


def _words(text: str, n: int = QUOTE_WORDS) -> str:
    return " ".join(str(text or "").split()[:n])


def headings_from_sections(sections: Iterable[str | None]) -> dict[str, str]:
    """{clause number: section heading} from chunk section strings."""
    from .standards import clause_number

    out: dict[str, str] = {}
    for section in sections:
        number = clause_number(section) if section else None
        if number and section:
            out.setdefault(number, section)
    return out


def _phrase_window(text: str, start: int) -> str:
    rest = text[start:]
    stop = _STOP.search(rest)
    rest = rest[: stop.start()] if stop else rest
    return " ".join(rest.split()[:_WINDOW_WORDS])


def _scope_phrase(text: str, vocab) -> tuple[set[str], str]:
    for m in _STRONG.finditer(text):
        window = _phrase_window(text, m.end())
        found = vocab.equipment_in(window)
        if found:
            return found, _words(text[m.start(): m.end()] + " " + window)
    lead = _LEADING_FOR.match(text)
    if lead:
        window = _phrase_window(text, lead.end())
        found = vocab.equipment_in(window)
        if found:
            return found, _words(text[: lead.end()] + " " + window)
    return set(), ""


def scope_of(requirement: dict, headings: dict[str, str] | None = None, vocab=None) -> dict:
    """{"types": sorted list (empty = unknown), "quote", "page", "method"}."""
    vocab = vocab or subject_scope.vocabulary()
    text = str(requirement.get("requirement_text") or "")
    page = requirement.get("page")

    def out(types: set[str], quote: str, method: str) -> dict:
        return {"types": sorted(types), "quote": quote, "page": page, "method": method}

    found, quote = _scope_phrase(text, vocab)
    if found:
        return out(found, quote, WORDING)
    verb = _MODAL.search(text)
    lead_in = text[: verb.start()] if verb else text
    # the grammatical subject only: "Bolts for the flange of the vessel" is about bolts
    subject = _PREPOSITION.split(lead_in, maxsplit=1)[0]
    types = vocab.equipment_in(subject)
    if types:
        return out(types, _words(lead_in), SUBJECT)
    chain = [requirement.get("chunk_section")]
    clause = requirement.get("clause")
    if clause:
        chain.append((headings or {}).get(clause))
        chain.extend((headings or {}).get(a) for a in subject_scope._ancestors(clause))
    for head in chain:
        types = vocab.equipment_in(head)
        if types:
            return out(types, _words(head), HEADING)
    return out(set(), "", UNKNOWN)


def ask_local_model(requirement: dict, vocab=None, post: Callable | None = None) -> dict | None:
    """OPTIONAL pass for a clause the code left unknown. Local Ollama only, through
    `model_transport`. Returns a scope dict (method local_model) or None. Code verifies:
    every type must be an equipment type of the vocabulary and the quote must be a run of
    the clause's own words."""
    from . import model_transport
    from .config import settings

    vocab = vocab or subject_scope.vocabulary()
    text = str(requirement.get("requirement_text") or "")
    allowed = sorted(t for t, k in vocab.kind.items() if k == subject_scope.EQUIPMENT)
    prompt = (
        "Which equipment type is this clause written for? Answer JSON "
        '{"types": [...], "quote": "..."} with types only from ' + json.dumps(allowed)
        + ' and quote copied word for word from the clause. If the clause names none, '
        'answer {"types": [], "quote": ""}.\nClause: ' + text[:1500])
    send = post or model_transport.post_json
    try:
        reply = send("/api/generate", {"model": settings.ai_task_model, "prompt": prompt,
                                       "stream": False, "format": "json"}, timeout=120.0)
        data = json.loads(reply.get("response") or "{}")
    except Exception:  # noqa: BLE001 - a model that fails leaves the clause unknown
        return None
    types = {str(t).strip().lower() for t in data.get("types") or []}
    quote = str(data.get("quote") or "").strip()
    folded = " ".join(text.lower().split())
    if (not types or not types <= set(allowed) or not quote
            or " ".join(quote.lower().split()) not in folded):
        return None
    return {"types": sorted(types), "quote": _words(quote), "page": requirement.get("page"),
            "method": MODEL}


def stored_fields(scope: dict) -> dict:
    """The two columns for a derived scope; {} when unknown (the columns stay NULL)."""
    if not scope["types"]:
        return {}
    return {"equipment_type": ", ".join(scope["types"]),
            "equipment_scope_evidence": json.dumps(
                {k: scope[k] for k in ("types", "quote", "page", "method")})}
