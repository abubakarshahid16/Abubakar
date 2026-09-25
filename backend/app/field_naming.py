"""Canonical field names for printed labels and numeric requirements (#193
plan B4, orders 5.2 and 5.3). Behind `settings.geometry_reader_enabled`.

THE MODEL NAMES; IT NEVER WRITES A VALUE. A language model (the labelling
provider: Haiku when Claude is configured and allowed, the local engine
otherwise) is handed a NUMBERED dictionary of field names built by Python and
a batch of items - datasheet labels, or requirement sentences. For each item
it may answer one dictionary NUMBER and a quote, or null. It cannot invent a
name (only a number that indexes Python's list), and nothing it says is
stored as a value: the stored row is the dictionary entry and the quote.

A NAME IS KEPT ONLY WHEN THE CODE CAN CHECK IT. Three gates, all in code:

  1. the number indexes the dictionary (an out-of-range or non-integer answer
     is unmapped);
  2. the quote is found in the item's own text (`model_evidence.
     quote_verified` - exact after the owner's closed normalisation list);
  3. the quote NAMES the field: EVERY content word of the dictionary entry
     (limit words like "maximum" aside) appears in the quote, a shared
     4-letter stem counting ("PRESS." names "pressure"). One shared word is
     not enough - "interpass temperature" does not name "operating
     temperature".

Anything else stays UNMAPPED. Unmapped is an answer, not a failure.

THE DICTIONARY is built from what the system already stores, never from an
answer key: the extractor's own normalised names for the submittal's numeric
fields, then the subjects of the numeric requirements in scope (short noun
phrases only - a sentence fragment is not a field name). Requirements are
named against it; datasheet labels are then named ONLY against the names the
requirements received, so a pairing needs one entry on both sides and a label
is never simply "named" to itself.

STORAGE is a side table, `canonical_field_names`, created only by
`ensure_names` (the flag-on path). Every reader tolerates its absence: with
the flag off nothing creates it and nothing reads it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .db import connect
from .model_evidence import quote_verified

#: The claude_spend step every naming call is charged to.
NAMING_STEP = "b4-naming"
PROMPT_VERSION = "b4-naming-v1"
#: Items per model call.
BATCH = 40
#: Requirement text shown to the model (and verified against) - the head of
#: the sentence, where the quantity is named.
REQUIREMENT_CHARS = 400

REQUIREMENT, LABEL = "requirement", "label"
NUMERIC_TYPES = ("numeric_limit", "table_row", "relative_limit")

_STOP = frozenset("""
a an and are as at be by for from if in is it of on or per shall the to with
which but when where than that this these those all any each not no note
""".split())
#: Limit words, not the quantity: "maximum pump speed" and "pump speed" name
#: one quantity, and a requirement says "shall not exceed" where a label says
#: "MAX." - so these never have to be quoted.
_QUALIFIERS = frozenset("maximum minimum max min allowable allow allowed required reqd req".split())
_WORD = re.compile(r"[a-z][a-z0-9]*")


def _norm(text: str | None) -> str:
    text = re.sub(r"\([^)]*\)", " ", (text or "").lower())
    text = re.sub(r"[^\w\s/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if len(w) >= 3 and w not in _STOP]


def _same_word(fw: str, qw: str) -> bool:
    return fw == qw or (len(fw) >= 4 and len(qw) >= 4 and fw[:4] == qw[:4]
                        and (fw.startswith(qw) or qw.startswith(fw)))


def names_the_field(quote: str | None, field_name: str) -> bool:
    """Gate 3: EVERY content word of `field_name` (limit words aside) is in
    `quote` - exactly, or as a stem of at least four letters ("PRESS." for
    "pressure"). One shared word is not enough: "interpass temperature" does
    not name "operating temperature"."""
    quoted = _content_words(quote or "")
    needed = [w for w in _content_words(field_name) if w not in _QUALIFIERS]
    return bool(needed) and all(any(_same_word(fw, qw) for qw in quoted) for fw in needed)


def _noun_phrase(subject: str | None) -> str | None:
    """A requirement subject usable as a field name: 1-8 words, a letter,
    not opening with a function word ("which", "but", "Note 2:")."""
    name = _norm(subject)
    words = name.split()
    if not words or len(words) > 8 or len(name) < 4 or words[0] in _STOP:
        return None
    if not any(ch.isalpha() for ch in name) or words[0].isdigit():
        return None
    return name


def _numeric(fact: dict) -> bool:
    """A fact a limit could be compared with (comparison.fact_has_number's rule)."""
    return (fact.get("raw_value") not in (None, "")
            or (fact.get("value_min") is not None and fact.get("value_max") is not None))


def build_dictionary(requirements: list[dict], facts: list[dict]) -> list[str]:
    """The REQUIREMENT-side dictionary: the extractor's own names for the
    submittal's numeric fields FIRST (the datasheet's vocabulary; short
    names starting with a letter), then the numeric requirements' own
    subjects. Sorted within each part, each name once."""
    from_facts = sorted({n for f in facts if _numeric(f)
                         for n in [_noun_phrase(f.get("field_name"))] if n})
    from_reqs = sorted({n for r in requirements if r.get("requirement_type") in NUMERIC_TYPES
                        for n in [_noun_phrase(r.get("subject"))] if n} - set(from_facts))
    return from_facts + from_reqs


# ------------------------------------------------------------------ storage

_TABLE = """CREATE TABLE IF NOT EXISTS canonical_field_names (
    subject_kind TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    dictionary_sha256 TEXT NOT NULL,
    field_name TEXT,
    quote TEXT,
    provider TEXT,
    model_tag TEXT,
    prompt_sha256 TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (subject_kind, subject_key, dictionary_sha256))"""


def _dictionary_sha(dictionary: list[str]) -> str:
    import hashlib
    return hashlib.sha256("\n".join(dictionary).encode("utf-8")).hexdigest()


def stored_names(kind: str, keys: list[str], dictionary: list[str]) -> dict[str, dict]:
    """The stored answers (mapped AND unmapped) for `keys` under this exact
    dictionary. {} when the side table does not exist."""
    if not keys:
        return {}
    sha = _dictionary_sha(dictionary)
    out: dict[str, dict] = {}
    try:
        conn = connect()
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            marks = ",".join("?" for _ in chunk)
            for r in conn.execute(
                    "SELECT subject_key, field_name, quote FROM canonical_field_names"
                    f" WHERE subject_kind = ? AND dictionary_sha256 = ? AND subject_key IN ({marks})",
                    [kind, sha, *chunk]):
                out[r["subject_key"]] = {"field_name": r["field_name"], "quote": r["quote"]}
    except Exception:  # noqa: BLE001 - no side table: nothing named yet
        return {}
    return out


def _store(kind: str, answers: dict[str, dict], dictionary: list[str], response) -> None:
    sha = _dictionary_sha(dictionary)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = connect()
    with conn:
        conn.execute(_TABLE)
        conn.executemany(
            "INSERT OR REPLACE INTO canonical_field_names (subject_kind, subject_key,"
            " dictionary_sha256, field_name, quote, provider, model_tag, prompt_sha256,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            [(kind, key, sha, a["field_name"], a["quote"], response.provider,
              response.model_tag, response.prompt_sha256, now) for key, a in answers.items()])


# ------------------------------------------------------------------ the model

_SCHEMA = {
    "type": "object", "required": ["names"],
    "properties": {"names": {"type": "array", "items": {
        "type": "object", "required": ["i", "field", "quote"],
        "properties": {"i": {"type": "integer"}, "field": {"type": ["integer", "null"]},
                       "quote": {"type": "string"}}}}},
}


def _system(dictionary: list[str]) -> str:
    lines = "\n".join(f"{n}: {name}" for n, name in enumerate(dictionary))
    return (
        "You name engineering fields. You are given a NUMBERED FIELD DICTIONARY and a list "
        "of ITEMS (datasheet labels or requirement sentences). For each item, answer the "
        "number of the ONE dictionary entry that names EXACTLY the quantity the item is "
        "about, or null when no entry does. A more general entry ('temperature' for a "
        "bearing temperature) or a different quantity that shares a word ('operating "
        "temperature' for an interpass temperature) is NOT the same quantity: answer null. "
        "When two entries name exactly the same quantity, answer the LOWER number. With "
        "each answer give `quote`: the exact words, copied character for character from "
        "the item, that name that quantity. Never write a value, a number from the item, "
        "or a name that is not in the dictionary. If unsure, answer null.\n\n"
        "FIELD DICTIONARY:\n" + lines)


def _parse(text: str) -> list[dict]:
    body = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", body, re.DOTALL)
    if fence:
        body = fence.group(1)
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return []
    names = value.get("names") if isinstance(value, dict) else None
    return names if isinstance(names, list) else []


def verify(answer: dict, items: list[tuple[str, str]], dictionary: list[str]) -> tuple[int, dict] | None:
    """The three gates on ONE model answer. Returns (item index, {field_name,
    quote}) - field_name None when the answer maps nothing - or None when the
    answer does not even name a valid item."""
    i = answer.get("i") if isinstance(answer, dict) else None
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(items):
        return None
    field = answer.get("field")
    quote = answer.get("quote") if isinstance(answer.get("quote"), str) else None
    unmapped = {"field_name": None, "quote": None}
    if not isinstance(field, int) or isinstance(field, bool) or not 0 <= field < len(dictionary):
        return i, unmapped                                   # gate 1
    if not quote_verified(quote, items[i][1]):
        return i, unmapped                                   # gate 2
    if not names_the_field(quote, dictionary[field]):
        return i, unmapped                                   # gate 3
    return i, {"field_name": dictionary[field], "quote": quote}


def name_items(kind: str, items: list[tuple[str, str]], dictionary: list[str], provider) -> dict[str, dict]:
    """Name `items` = [(key, text)] not yet named under this dictionary, in
    batches, and store every verified answer (mapped or unmapped). Returns
    the answers for ALL `items` (stored + new). A provider refusal stops the
    naming and is re-raised after what was named so far is stored."""
    from .reasoning_provider import Packet

    known = stored_names(kind, [k for k, _t in items], dictionary)
    todo = [(k, t) for k, t in items if k not in known]
    system = _system(dictionary)
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        prompt = json.dumps({"kind": kind, "items": [{"i": n, "text": t}
                                                      for n, (_k, t) in enumerate(batch)]},
                            ensure_ascii=False)
        packet = Packet(prompt=prompt, num_ctx=16384, num_predict=60 * len(batch) + 200,
                        json_schema=_SCHEMA, system=system, step=NAMING_STEP,
                        prompt_version=PROMPT_VERSION)
        response = provider.reason(packet)
        answers: dict[str, dict] = {}
        if not response.schema_errors and not response.truncated:
            for raw in _parse(response.text):
                checked = verify(raw, batch, dictionary)
                if checked is not None:
                    answers[batch[checked[0]][0]] = checked[1]
        # An item the model skipped is unmapped too - recorded, so it is not
        # asked again under the same dictionary.
        for key, _text in batch:
            answers.setdefault(key, {"field_name": None, "quote": None})
        _store(kind, answers, dictionary, response)
        known.update(answers)
    return known


def label_key(label: str | None) -> str:
    return _norm(label)


def _label_of(fact: dict) -> str:
    return fact.get("field_label") or fact.get("field_name") or ""


def ensure_names(requirements: list[dict], facts: list[dict], *, provider=None) -> dict:
    """Name the numeric requirements, then the numeric facts' labels (only
    what is not named yet).

    TWO PASSES, TWO DICTIONARIES. Requirements are named against
    `build_dictionary`. Labels are then named ONLY against the names the
    requirements received: a label can take a name only if some requirement
    has it, so a label is never "named" to itself and a pairing needs the
    same entry on both sides. A label whose fact carries no number is not
    asked - it could never be paired.

    Returns {"requirements": {req_id: field}, "facts": {fact_id: field},
    counts, "refused": reason or None}. A refusal (budget, egress, engine
    down) keeps what was named and reports why."""
    from .reasoning_provider import get_provider

    dictionary = build_dictionary(requirements, facts)
    numeric = [r for r in requirements if r.get("requirement_type") in NUMERIC_TYPES]
    req_items = [(str(r["id"]), " ".join((r.get("requirement_text") or "").split())[:REQUIREMENT_CHARS])
                 for r in numeric]
    labels = {label_key(_label_of(f)): " ".join(_label_of(f).split()) for f in facts if _numeric(f)}
    label_items = sorted((k, v) for k, v in labels.items() if k)
    refused = None
    req_names: dict[str, dict] = {}
    label_names: dict[str, dict] = {}
    label_dictionary: list[str] = []
    if dictionary and req_items:
        provider = provider or get_provider("labelling", step=NAMING_STEP)
        try:
            req_names = name_items(REQUIREMENT, req_items, dictionary, provider)
            label_dictionary = sorted({v["field_name"] for v in req_names.values() if v.get("field_name")})
            if label_dictionary and label_items:
                label_names = name_items(LABEL, label_items, label_dictionary, provider)
        except Exception as exc:  # noqa: BLE001 - ProviderRefused, BudgetExceeded, engine errors
            refused = f"{type(exc).__name__}: {exc}"
            req_names = req_names or stored_names(REQUIREMENT, [k for k, _t in req_items], dictionary)
            label_dictionary = sorted({v["field_name"] for v in req_names.values() if v.get("field_name")})
            label_names = stored_names(LABEL, [k for k, _t in label_items], label_dictionary)
    fact_names = {}
    for f in facts:
        named = (label_names.get(label_key(_label_of(f))) or {}).get("field_name")
        if named and _numeric(f):
            fact_names[str(f["id"])] = named
    return {
        "requirements": {k: v["field_name"] for k, v in req_names.items() if v.get("field_name")},
        "facts": fact_names,
        "dictionary": len(dictionary), "label_dictionary": len(label_dictionary),
        "requirements_asked": len(req_items), "labels_asked": len(label_items),
        "requirements_named": sum(1 for v in req_names.values() if v.get("field_name")),
        "labels_named": sum(1 for v in label_names.values() if v.get("field_name")),
        "refused": refused,
    }
