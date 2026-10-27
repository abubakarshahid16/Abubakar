"""One closed vocabulary of quantities, so a standard's numeric limit is named ONCE (order 259.5).

`field_naming.ensure_names` names a requirement against a dictionary built from THIS sheet's fields,
so the answer is good for one sheet and is asked again for the next. The quantities the system
already owns do not depend on a sheet: the canonical phrases of `reference/field_synonyms.json`
("rated speed", "absorbed power", "design pressure"...) and the roles of the approved checklists
(`reference/datasheet_checks.json`). That list is the CLOSED VOCABULARY here.

TWO HALVES, BOTH CHECKED BY CODE:
  * a requirement's name comes from an OFFLINE pass (`name_requirements`, run by
    `scripts/name_numeric_limits.py` on a diagnostic copy) in which a local model answers one
    vocabulary NUMBER and a quote, under `field_naming`'s three gates (the number indexes the list,
    the quote is in the sentence, the quote names the quantity: a word of the name or any spelling
    the synonym table gives it). Stored model-named, unconfirmed, with provenance (provider, model,
    prompt hash) in `canonical_field_names`, keyed by the vocabulary's own hash.
  * a sheet fact's name needs no model: the canonical phrase of its own label (`fact_name`).
A pairing needs the SAME phrase on both sides. It rides `comparison.match_by_field_name`, so it never
carries a verdict (NEEDS_ENGINEER_REVIEW) until a family of names has passed `rule_trust`.

Nothing here writes a value, reads a document, or calls a model by itself.
"""

from __future__ import annotations

from . import field_links, field_naming

REQUIREMENT = field_naming.REQUIREMENT


def vocabulary() -> list[str]:
    """The closed list: every canonical phrase of the synonym table and every numeric checklist role,
    each in its canonical spelling, sorted. The same list every time (its hash keys the stored names)."""
    from . import datasheet_checks

    _pattern, to_canonical, _attributes = field_links._table()
    names = set(to_canonical.values())
    for role, body in datasheet_checks.load_rules()["roles"].items():
        if body.get("kind") != "text":
            names.add(field_links.canonical(role.replace("_", " ")))
    return sorted(n for n in names if n and len(n) >= 4)


def names_the_quantity(quote: str | None, name: str) -> bool:
    """Gate 3 for the closed vocabulary: the quote carries every word of the name, OR it carries a
    spelling the synonym table rewrites to that name ("pump speed" names "rated speed")."""
    if field_naming.names_the_field(quote, name):
        return True
    return bool(quote) and field_links.names_head(field_links.canonical(quote), name)


def verify(answer: dict, items: list[tuple[str, str]], dictionary: list[str]):
    """`field_naming.verify` with this vocabulary's gate 3."""
    checked = field_naming.verify(answer, items, dictionary)
    if checked is not None and checked[1]["field_name"] is None:
        # the strict gate refused it: give the synonym-aware gate its chance, gates 1 and 2 unchanged
        i = answer.get("i") if isinstance(answer, dict) else None
        field = answer.get("field") if isinstance(answer, dict) else None
        quote = answer.get("quote") if isinstance(answer.get("quote"), str) else None
        if (
            isinstance(field, int)
            and not isinstance(field, bool)
            and 0 <= field < len(dictionary)
            and field_naming.quote_verified(quote, items[i][1])
            and names_the_quantity(quote, dictionary[field])
        ):
            return i, {"field_name": dictionary[field], "quote": quote}
    return checked


def name_requirements(requirements: list[dict], provider) -> dict[str, dict]:
    """Name the numeric requirements against the closed vocabulary and store every answer. Returns
    {requirement id: {field_name | None, quote | None}} for all of them (stored + new)."""
    items = [
        (
            str(r["id"]),
            " ".join((r.get("requirement_text") or "").split())[
                : field_naming.REQUIREMENT_CHARS
            ],
        )
        for r in requirements
        if r.get("requirement_type") in field_naming.NUMERIC_TYPES
        and r.get("requirement_text")
    ]
    return _name_items(items, vocabulary(), provider)


def _name_items(
    items: list[tuple[str, str]], dictionary: list[str], provider
) -> dict[str, dict]:
    """`field_naming.name_items` with this vocabulary's gate 3 (the same batches, prompt, schema and
    storage; only the verifier differs). Answers for ALL `items` (stored + new)."""
    import json

    from .reasoning_provider import Packet

    known = field_naming.stored_names(REQUIREMENT, [k for k, _t in items], dictionary)
    todo = [(k, t) for k, t in items if k not in known]
    system = field_naming._system(dictionary)
    for start in range(0, len(todo), field_naming.BATCH):
        batch = todo[start : start + field_naming.BATCH]
        prompt = json.dumps(
            {
                "kind": REQUIREMENT,
                "items": [{"i": n, "text": t} for n, (_k, t) in enumerate(batch)],
            },
            ensure_ascii=False,
        )
        packet = Packet(
            prompt=prompt,
            num_ctx=16384,
            num_predict=60 * len(batch) + 200,
            json_schema=field_naming._SCHEMA,
            system=system,
            step=field_naming.NAMING_STEP,
            prompt_version=field_naming.PROMPT_VERSION,
        )
        response = provider.reason(packet)
        answers: dict[str, dict] = {}
        if not response.schema_errors and not response.truncated:
            for raw in field_naming._parse(response.text):
                checked = verify(raw, batch, dictionary)
                if checked is not None:
                    answers[batch[checked[0]][0]] = checked[1]
        for (
            key,
            _text,
        ) in batch:  # a skipped item is unmapped too: recorded, not asked again
            answers.setdefault(key, {"field_name": None, "quote": None})
        field_naming._store(REQUIREMENT, answers, dictionary, response)
        known.update(answers)
    return known


def fact_name(fact: dict) -> str | None:
    """The vocabulary phrase a sheet fact's own label canonicalises to, or None."""
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    vocab = set(vocabulary())
    for own in field_naming.own_names(fact):
        canon = field_links.canonical(own)
        if canon in vocab:
            return canon
    rules = datasheet_checks.load_rules()
    label = fact.get("field_label") or fact.get("field_name") or ""
    role = (
        datasheet_checks.role_of(normalise_field_name(label), rules) if label else None
    )
    if role:
        canon = field_links.canonical(role.replace("_", " "))
        if canon in vocab:
            return canon
    return None


def names_for(requirements: list[dict], facts: list[dict]) -> dict:
    """The names a run pairs by, in the shape `comparison.match_by_field_name` reads: the STORED
    closed-vocabulary names of the requirements plus the rule names of the facts (no model call);
    when no requirement has a stored name, the per-sheet naming (`field_naming.ensure_names`)."""
    ids = [
        str(r["id"])
        for r in requirements
        if r.get("requirement_type") in field_naming.NUMERIC_TYPES
    ]
    stored = field_naming.stored_names(REQUIREMENT, ids, vocabulary())
    named = {k: v["field_name"] for k, v in stored.items() if v.get("field_name")}
    if not named:
        return field_naming.ensure_names(requirements, facts)
    wanted = set(named.values())
    fact_names = {}
    for fact in facts:
        if not field_naming._nameable(fact):
            continue
        name = fact_name(fact)
        if name in wanted:
            fact_names[str(fact["id"])] = name
    return {
        "requirements": named,
        "facts": fact_names,
        "source": "closed vocabulary (stored, model-named, unconfirmed)",
        "requirements_asked": len(ids),
        "requirements_named": len(named),
    }
