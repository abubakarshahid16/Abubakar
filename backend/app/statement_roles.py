"""Order 263.1: a STATEMENT rule ("the pump shall have X") limits a TEXT field of the form to a value.

`rule_roles` maps numeric rules to the numeric fields of an equipment type's form. Numeric rules are
13% of M-03; 75% are statements. A statement is a check only when it names a field the form already
asks for (casing material, seal type, bearing type ...) AND the value the clause requires for it:
  * the local model (offline, on a copy) answers one TEXT field of the type's form, the words that
    name the field, and the words that state the required value, all copied from the sentence;
  * code keeps the answer only if (gate 1) the field number indexes the list, (gate 2) both
    quotes are in the sentence, (gate 3) the field quote names exactly that field, (a) the value
    is whole words of the sentence and is not the field's own name, and (c) the sentence has no
    negation, exception, condition or alternative word (not, except, unless, if, when, where,
    only, or ...): such a sentence is the engineer's;
  * the kept mapping goes to the same reviewed DRAFT file as the numeric ones, with NO document text:
    a label, a clause number, the hash of the rule text, the form field, and the hash and word
    count of the value phrase. At run time the phrase is found again in the rule text from its
    hash; a rule whose text changed loses its mapping.
A pairing from it is NEEDS_ENGINEER_REVIEW (order 262), so it never carries a verdict.

Nothing here calls a model by itself, reads a document, or writes a value.
"""

from __future__ import annotations

import json
import re

from . import (
    field_links,
    field_naming,
    field_vocabulary,
    form_reader_fields,
    rule_roles,
)

KIND = "statement_rule"
STATEMENT = "statement"
#: Words that make a statement conditional, negative, exceptional or a choice: not a plain "shall be X".
_CUES = frozenset(
    "not no never non except excepting excluding unless if when whenever where while only without "
    "neither nor other otherwise or either alternative alternatively optional may".split()
)
MAX_PHRASE_WORDS = 6
_SCHEMA = {
    "type": "object",
    "required": ["names"],
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["i", "field", "field_quote", "value"],
                "properties": {
                    "i": {"type": "integer"},
                    "field": {"type": ["integer", "null"]},
                    "field_quote": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
        }
    },
}


def form(equipment_type: str) -> tuple[list[str], dict[str, str]]:
    """(dictionary, {name: role}) of the TEXT fields of the type's own form."""
    names: dict[str, str] = {}
    for f in form_reader_fields.field_list_for(equipment_type):
        if f.unit_kind == "text":
            names[field_links.canonical(f.key.replace("_", " "))] = f.key
    return sorted(names), names


def _system(dictionary: list[str]) -> str:
    lines = "\n".join(f"{n}: {name}" for n, name in enumerate(dictionary))
    return (
        "You read engineering requirement sentences. You are given a NUMBERED FIELD DICTIONARY "
        "of datasheet fields and a list of SENTENCES. For each sentence, answer the number of "
        "the ONE dictionary field the sentence says must have a particular value ('X shall be "
        "Y', 'X shall have Y'), or null. Give `field_quote`: the exact words, copied character "
        "for character from the sentence, that name that field, and `value`: the exact words, "
        "copied from the sentence, that state the value required for it. Answer null when the "
        "sentence is negative, conditional, offers alternatives, states a number or a limit, or "
        "is about anything the dictionary does not list. Never invent a field or a value. "
        "If unsure, answer null.\n\nFIELD DICTIONARY:\n" + lines
    )


def _tokens(text: str) -> list[str]:
    return field_vocabulary._tokens(text)


def _sentence_of(text: str, phrase_tokens: list[str]) -> list[str]:
    """Tokens of the sentence (split on . ; :) that holds the phrase; [] when none does."""
    for part in re.split(r"(?<=[.;:])\s+", text):
        toks = _tokens(part)
        if _find(toks, phrase_tokens) is not None:
            return toks
    return []


def _find(tokens: list[str], phrase: list[str]) -> int | None:
    n = len(phrase)
    for at in range(len(tokens) - n + 1):
        if tokens[at : at + n] == phrase:
            return at
    return None


def value_fits(text: str, field_quote: str, value: str, name: str) -> bool:
    """Gates (a) and (c) on the sentence: the value is whole words of the sentence, 1 to
    `MAX_PHRASE_WORDS` of them, not made only of neutral words, not the field's own name; and the
    sentence holds no negation, exception, condition or alternative word."""
    phrase = _tokens(value)
    if not phrase or len(phrase) > MAX_PHRASE_WORDS:
        return False
    if all(w in field_vocabulary._NEUTRAL for w in phrase) or phrase == name.split():
        return False
    sentence = _sentence_of(text, phrase)
    if not sentence or _find(sentence, _tokens(field_quote)) is None:
        return False
    return not any(w in _CUES for w in sentence)


def verify(answer: dict, items: list[tuple[str, str]], dictionary: list[str]):
    """All the gates on ONE model answer. Returns (item index, {field_name, quote}) with field_name
    None when it maps nothing (`quote` is the JSON {"f": field words, "v": value words}), or None
    when the answer names no valid item."""
    i = answer.get("i") if isinstance(answer, dict) else None
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(items):
        return None
    unmapped = (i, {"field_name": None, "quote": None})
    field = answer.get("field")
    fq, value = answer.get("field_quote"), answer.get("value")
    if (
        not isinstance(field, int)
        or isinstance(field, bool)
        or not 0 <= field < len(dictionary)
        or not isinstance(fq, str)
        or not isinstance(value, str)
    ):
        return unmapped  # gate 1
    text = items[i][1]
    if not (
        field_naming.quote_verified(fq, text)
        and field_naming.quote_verified(value, text)
    ):
        return unmapped  # gate 2
    if not field_vocabulary.names_the_quantity(fq, dictionary[field]):
        return unmapped  # gate 3
    if not value_fits(text, fq, value, dictionary[field]):
        return unmapped  # gates (a) and (c)
    return i, {
        "field_name": dictionary[field],
        "quote": json.dumps({"f": fq, "v": value}),
    }


def propose(
    requirements: list[dict], equipment_type: str, provider, stats: dict | None = None
) -> dict[str, dict]:
    """Ask for the (text field, required value) of each statement rule and store every answer (the
    offline pass). {requirement id: {field_name | None, quote | None}} for all of them."""
    from .reasoning_provider import Packet

    stats = stats if stats is not None else {}
    dictionary, _roles = form(equipment_type)
    items = [
        (
            str(r["id"]),
            " ".join((r.get("requirement_text") or "").split())[
                : field_naming.REQUIREMENT_CHARS
            ],
        )
        for r in requirements
        if r.get("requirement_type") == STATEMENT and r.get("requirement_text")
    ]
    known = field_naming.stored_names(KIND, [k for k, _t in items], dictionary)
    todo = [(k, t) for k, t in items if k not in known]
    system = _system(dictionary)
    for start in range(0, len(todo), field_naming.BATCH):
        batch = todo[start : start + field_naming.BATCH]
        packet = Packet(
            prompt=json.dumps(
                {
                    "kind": KIND,
                    "items": [{"i": n, "text": t} for n, (_k, t) in enumerate(batch)],
                },
                ensure_ascii=False,
            ),
            num_ctx=16384,
            num_predict=90 * len(batch) + 200,
            json_schema=_SCHEMA,
            system=system,
            step=field_naming.NAMING_STEP,
            prompt_version=field_naming.PROMPT_VERSION + "-statement",
        )
        response = provider.reason(packet)
        if response.schema_errors or response.truncated:
            stats["unreadable"] = stats.get("unreadable", 0) + len(batch)
            continue
        answers: dict[str, dict] = {}
        for raw in field_naming._parse(response.text):
            checked = verify(raw, batch, dictionary)
            if checked is not None:
                answers[batch[checked[0]][0]] = checked[1]
        for key, _text in batch:
            answers.setdefault(key, {"field_name": None, "quote": None})
        field_naming._store(KIND, answers, dictionary, response)
        known.update(answers)
    return known


def _phrase_hash(phrase_tokens: list[str]) -> str:
    return rule_roles.text_hash(" ".join(phrase_tokens))


def entries(requirements: list[dict], equipment_type: str, label_of) -> list[dict]:
    """The statement mappings to keep, from the stored answers (re-verified now). No document text."""
    dictionary, roles = form(equipment_type)
    stored = field_naming.stored_names(
        KIND, [str(r["id"]) for r in requirements], dictionary
    )
    out = []
    for r in requirements:
        got = stored.get(str(r["id"])) or {}
        name = got.get("field_name")
        if not name or name not in roles or r.get("requirement_type") != STATEMENT:
            continue
        try:
            quotes = json.loads(got.get("quote") or "")
        except ValueError:
            continue
        text = " ".join((r.get("requirement_text") or "").split())[
            : field_naming.REQUIREMENT_CHARS
        ]
        v, f = quotes.get("v"), quotes.get("f")
        if not (isinstance(v, str) and isinstance(f, str)):
            continue
        if not (
            field_naming.quote_verified(f, text)
            and field_naming.quote_verified(v, text)
            and field_vocabulary.names_the_quantity(f, name)
            and value_fits(text, f, v, name)
        ):
            continue
        phrase = _tokens(v)
        out.append(
            {
                "kind": STATEMENT,
                "standard": label_of(r.get("standard_document_id")),
                "clause": r.get("clause"),
                "text_sha256": rule_roles.text_hash(r.get("requirement_text")),
                "field": roles[name],
                "expected_sha256": _phrase_hash(phrase),
                "expected_words": len(phrase),
            }
        )
    return sorted(
        out, key=lambda e: (e["standard"] or "", e["clause"] or "", e["text_sha256"])
    )


def expected_phrase(text: str, entry: dict) -> str | None:
    """The value phrase of a kept mapping, found again in the rule's current text from its hash and
    word count (the file holds no words). None when the text no longer holds it."""
    toks = _tokens(text)
    n = int(entry.get("expected_words") or 0)
    if n < 1:
        return None
    for at in range(len(toks) - n + 1):
        if _phrase_hash(toks[at : at + n]) == entry.get("expected_sha256"):
            return " ".join(toks[at : at + n])
    return None


def reviewed(
    requirements: list[dict], equipment_type: str | None, files=None
) -> dict[str, dict]:
    """{requirement id: {"role", "name", "expected"}} for the statement rules a reviewed file maps FOR
    THIS EQUIPMENT TYPE whose text still hashes the same and still holds the value phrase."""
    by_hash: dict[str, tuple[str, dict]] = {}
    for file_type, entry in rule_roles.load(files):
        if entry.get("kind") == STATEMENT and rule_roles.same_type(
            file_type, equipment_type
        ):
            by_hash[entry["text_sha256"]] = (file_type, entry)
    out: dict[str, dict] = {}
    for r in requirements:
        if r.get("requirement_type") != STATEMENT:
            continue
        hit = by_hash.get(rule_roles.text_hash(r.get("requirement_text")))
        if not hit:
            continue
        file_type, entry = hit
        _dictionary, roles = form(file_type)
        name = next((n for n, k in roles.items() if k == entry["field"]), None)
        phrase = expected_phrase(r.get("requirement_text") or "", entry)
        if name and phrase:
            out[str(r["id"])] = {
                "role": entry["field"],
                "name": name,
                "expected": phrase,
            }
    return out


def value_agrees(sheet_value: str | None, expected: str) -> bool:
    """Does the sheet's value hold the expected phrase as whole words (canonical spelling)? A blank
    value agrees with nothing."""
    toks = _tokens(sheet_value or "")
    return bool(toks) and _find(toks, _tokens(expected)) is not None


def _role_of_fact(fact: dict, rules: dict) -> str | None:
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    label = fact.get("field_label") or fact.get("field_name") or ""
    return datasheet_checks.role_of(normalise_field_name(label), rules) if label else None


def match(requirement: dict, facts: list[dict], names: dict, sheet_kind: str | None = None):
    """The sheet fact a reviewed STATEMENT mapping pairs a statement rule with, in the shape of
    `comparison.match_by_field_name` (method `field_name`, so `compare`'s verdict is held for an
    engineer), or None. The phrase says both sides: what the clause requires and what the sheet
    states, and whether the sheet holds the required words. Two facts of the role that state
    different values are a tie: no pick."""
    from . import comparison, datasheet_checks

    info = (names.get("statements") or {}).get(str(requirement.get("id")))
    if requirement.get("requirement_type") != STATEMENT or not info:
        return None
    rules = datasheet_checks.load_rules()
    rejected = comparison._rejected_keys_for(requirement)
    tag_scoped = comparison.facts_are_tag_scoped(facts)
    hits = [
        f
        for f in facts
        if _role_of_fact(f, rules) == info["role"]
        and comparison.fact_key(f, tag_scoped=tag_scoped) not in rejected
    ]
    if not hits:
        return None
    values = {" ".join(str(f.get("field_value") or "").split()).lower() for f in hits}
    if len(values) > 1:
        return {
            "fact": None,
            "matched_phrase": info["name"],
            "method": None,
            "reason": comparison.AMBIGUOUS_MATCH,
            "candidates": sorted(f"{f.get('field_label') or info['name']} (page {f.get('page')})" for f in hits),
            "refused": [],
        }
    fact = sorted(hits, key=lambda f: (f.get("page") or 0, f.get("field_label") or ""))[0]
    stated = " ".join(str(fact.get("field_value") or "").split())
    if fact.get("is_blank") or not stated:
        said = "the sheet leaves it to be provided"
    elif value_agrees(stated, info["expected"]):
        said = f"the sheet states '{stated}', which holds those words"
    else:
        said = f"the sheet states '{stated}', which does not hold those words"
    return {
        "fact": fact,
        "matched_phrase": f"{info['name']}; the clause requires '{info['expected']}', {said}",
        "method": comparison.METHOD_FIELD_NAME,
        "reason": None,
        "candidates": [],
        "refused": [],
    }
