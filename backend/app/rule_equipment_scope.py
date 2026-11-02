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

import httpx

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
    r"covers|requirements for|provisions for)\b",
    re.IGNORECASE,
)
_LEADING_FOR = re.compile(r"^\W*for\b", re.IGNORECASE)
_STOP = re.compile(r"[.;:]|\b(?:shall|must|should|may|will)\b", re.IGNORECASE)
_WINDOW_WORDS = 8
_PREPOSITION = re.compile(
    r"\b(?:of|for|in|on|at|with|from|to|by|within|under)\b", re.IGNORECASE
)
_MODAL = re.compile(
    r"\b(?:shall|must|should|may|will|needs? to|is to|are to)\b", re.IGNORECASE
)
# A type named inside a negated, excluded, contrasted or deferred phrase is NOT the rule's
# scope (rule 4). A negation cue masks from the cue to the end of its phrase: the sentence
# end, or a comma that leads into the main clause ("Unlike heat exchangers, vessels shall").
_NEGATION = re.compile(
    r"\b(?:not|no|never|neither|nor|cannot|except(?:ing)?|exclud(?:e|es|ed|ing)|"
    r"other than|unlike|instead of|rather than|apart from|without)\b",
    re.IGNORECASE,
)
# A deferral masks the whole sentence: the rule says where the equipment is dealt with, not
# that this clause is written for it.
_DEFERRAL = re.compile(
    r"\b(?:elsewhere|see|refer(?:red)? to|given in|specified in|covered (?:by|in)|"
    r"not (?:covered|included|applicable))\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.;:]")
_MASK = " \u00a6 "
# What a heading or subject is ABOUT stops where a modifier phrase starts: "Piping connected
# to pumps" is about piping; "Valves in compressor service" is about valves. "for" or "of"
# followed by the equipment stays a scope ("Requirements for pumps") unless it ends in
# "service".
_MODIFIER = re.compile(
    r"\b(?:connected|attached|used|serving|associated|installed|mounted|located|supplied|"
    r"handling|in|on|at|with|from|within|under|to|by)\b|\bfor\b(?=[^.]*\bservice\b)",
    re.IGNORECASE,
)


def _sentence_end(text: str, start: int) -> int:
    m = _SENTENCE_END.search(text, start)
    return m.start() if m else len(text)


def masked(text: str) -> str:
    """`text` with every negated, excluded, contrasted or deferred phrase blanked."""
    text = str(text or "")
    spans: list[tuple[int, int]] = []
    for m in _NEGATION.finditer(text):
        end = _sentence_end(text, m.end())
        comma = text.find(",", m.end(), end)
        while comma != -1:
            if not _MODAL.search(text[m.end() : comma]) and _MODAL.search(
                text[comma:end]
            ):
                end = comma
                break
            comma = text.find(",", comma + 1, end)
        spans.append((m.start(), end))
    for m in _DEFERRAL.finditer(text):
        begin = max(text.rfind(c, 0, m.start()) for c in ".;:") + 1
        spans.append((begin, _sentence_end(text, m.end())))
    for begin, end in sorted(spans, reverse=True):
        text = text[:begin] + _MASK + text[end:]
    return text


def _types(text: str, vocab) -> set[str]:
    """Equipment types named by SPECIFIC phrases. A generic phrase ("valves", "turbine")
    that the vocabulary maps to several types names none of them: never guess one."""
    if vocab.pattern is None:
        return set()
    found: set[str] = set()
    for match in vocab.pattern.finditer(subject_scope._fold(text)):
        types = vocab.phrases[match.group(0)]
        if len(types) == 1:
            found |= {t for t in types if vocab.kind.get(t) == subject_scope.EQUIPMENT}
    return found


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
        found = _types(window, vocab)
        if found:
            return found, _words(text[m.start() : m.end()] + " " + window)
    lead = _LEADING_FOR.match(text)
    if lead:
        window = _phrase_window(text, lead.end())
        found = _types(window, vocab)
        if found:
            return found, _words(text[: lead.end()] + " " + window)
    return set(), ""


def scope_of(
    requirement: dict, headings: dict[str, str] | None = None, vocab=None
) -> dict:
    """{"types": sorted list (empty = unknown), "quote", "page", "method"}."""
    vocab = vocab or subject_scope.vocabulary()
    raw = str(requirement.get("requirement_text") or "")
    text = masked(raw)
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
    types = _types(subject, vocab)
    if types:
        return out(types, _words(lead_in), SUBJECT)
    chain = [requirement.get("chunk_section")]
    clause = requirement.get("clause")
    if clause:
        chain.append((headings or {}).get(clause))
        chain.extend((headings or {}).get(a) for a in subject_scope._ancestors(clause))
    for head in chain:
        shown = masked(head)
        types = _types(_MODIFIER.split(shown, maxsplit=1)[0], vocab)
        if types:
            return out(types, _words(head), HEADING)
    return out(set(), "", UNKNOWN)


def ask_local_model(
    requirement: dict, vocab=None, post: Callable | None = None
) -> dict | None:
    """OPTIONAL pass for a clause the code left unknown. Local Ollama only, through
    `model_transport`. Returns a scope dict (method local_model) or None. Code verifies:
    every type must be an equipment type of the vocabulary and the quote must be a run of
    the clause's own words."""
    from . import local_engine_bar, model_transport
    from .config import settings

    if post is None and local_engine_bar.refuses("rule_equipment_scope"):
        return None  # stays unknown, and the run says the step was skipped
    vocab = vocab or subject_scope.vocabulary()
    text = str(requirement.get("requirement_text") or "")
    allowed = sorted(t for t, k in vocab.kind.items() if k == subject_scope.EQUIPMENT)
    prompt = (
        "Which equipment type is this clause written for? Answer JSON "
        '{"types": [...], "quote": "..."} with types only from '
        + json.dumps(allowed)
        + " and quote copied word for word from the clause. If the clause names none, "
        'answer {"types": [], "quote": ""}.\nClause: ' + text[:1500]
    )
    send = post or model_transport.post_json
    try:
        reply = send(
            "/api/generate",
            {
                "model": settings.ai_task_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120.0,
        )
        data = json.loads(reply.get("response") or "{}")
    except (
        httpx.HTTPError,
        OSError,
        ValueError,
        AttributeError,
        TypeError,
    ):  # a failed model leaves it unknown
        return None
    types = {str(t).strip().lower() for t in data.get("types") or []}
    quote = str(data.get("quote") or "").strip()
    folded = " ".join(
        masked(text).lower().split()
    )  # the quote may not sit in a negated phrase
    if (
        not types
        or not types <= set(allowed)
        or not quote
        or " ".join(quote.lower().split()) not in folded
    ):
        return None
    return {
        "types": sorted(types),
        "quote": _words(quote),
        "page": requirement.get("page"),
        "method": MODEL,
    }


def stored_fields(scope: dict) -> dict:
    """The two columns for a derived scope; {} when unknown (the columns stay NULL)."""
    if not scope["types"]:
        return {}
    return {
        "equipment_type": ", ".join(scope["types"]),
        "equipment_scope_evidence": json.dumps(
            {k: scope[k] for k in ("types", "quote", "page", "method")}
        ),
    }


def store(row: dict, fields: dict) -> dict:
    """Write the two scope columns of a just-created rule row (nothing when `fields` is
    empty, so a switch-off run never touches the column). Returns the row."""
    if fields:
        from .db import add_column_if_missing, connect

        conn = connect()
        add_column_if_missing(
            conn, "standard_requirements", "equipment_scope_evidence", "TEXT"
        )
        with conn:
            conn.execute(
                "UPDATE standard_requirements SET equipment_type = ?, equipment_scope_evidence = ?"
                " WHERE id = ?",
                (
                    fields["equipment_type"],
                    fields["equipment_scope_evidence"],
                    row["id"],
                ),
            )
    return row


class _Off:
    def fields(self, *_sentence_clause_chunk) -> dict:
        return {}

    def store(self, row: dict, *sentence_clause_chunk) -> dict:
        return store(row, self.fields(*sentence_clause_chunk))


class _On(_Off):
    def __init__(self, chunks) -> None:
        self.headings = headings_from_sections(c["section"] for c in chunks)

    def fields(self, sentence, clause, chunk) -> dict:
        requirement = {
            "requirement_text": sentence,
            "clause": clause,
            "chunk_section": chunk["section"],
            "page": chunk["page_start"],
        }
        return stored_fields(scope_of(requirement, self.headings))


def for_chunks(chunks):
    """What extraction asks per sentence: `.fields(sentence, clause, chunk)`. With the
    switch off it answers {} and reads nothing."""
    return _On(chunks) if extract_enabled() else _Off()
