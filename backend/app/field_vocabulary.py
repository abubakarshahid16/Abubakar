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
    the quote is in the sentence, the quote names EXACTLY the quantity: its canonical spelling is the
    name and nothing that changes the quantity - min/max, drop, margin, tolerance ... - rides with it). Stored model-named, unconfirmed, with provenance (provider, model,
    prompt hash) in `canonical_field_names`, keyed by the vocabulary's own hash.
  * a sheet fact's name needs no model: the canonical phrase of its own label (`fact_name`).
  * a FOURTH gate (`number_fits`, s2's 259.5 measure: 11 of 30 names were right, the rest named a
    noun the sentence mentions, not the quantity the number limits): the sentence's own number must
    follow the name with only limit words between them (or stand directly before it), and its unit
    must be of the kind the name is (a pressure is not in minutes, a size is not a count).
A pairing needs the SAME phrase on both sides. It rides `comparison.match_by_field_name`, so it never
carries a verdict (NEEDS_ENGINEER_REVIEW) until a family of names has passed `rule_trust`.

Nothing here writes a value, reads a document, or calls a model by itself.
"""

from __future__ import annotations

import re

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


#: Words that may sit around a quantity's name in a quote without changing the quantity.
_NEUTRAL = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "for",
        "at",
        "in",
        "to",
        "is",
        "be",
        "shall",
        "pump",
        "pumps",
        "vessel",
        "equipment",
        "unit",
        "system",
    ]
)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(field_links.canonical(text))


def names_the_quantity(quote: str | None, name: str) -> bool:
    """Gate 3 for the closed vocabulary: the quote, in its canonical spelling (the synonym table),
    contains the name's words as one run, and every OTHER word of the quote is neutral. So "max
    allowable working pressure" names `mawp`; "min flow" never names `max flow`; "design pressure
    drop" never names `design pressure`; "NPSH margin" never names `npsh required`; a bare "flow"
    never names `max flow`. Stricter than `field_naming.names_the_field`, which ignores min/max."""
    if not quote:
        return False
    q, n = _tokens(quote), name.split()
    if not n or len(q) < len(n):
        return False
    for at in range(len(q) - len(n) + 1):
        if q[at : at + len(n)] == n:
            rest = q[:at] + q[at + len(n) :]
            return all(w in _NEUTRAL for w in rest)
    return False


#: Gate 4. The unit families a number may have for each name; `()` = no unit at all (a ratio). A name
#: not listed here cannot be checked, so it is never kept (refusing is the safe side).
_PRESSURE, _TEMPERATURE, _FLOW = (
    ("pressure",),
    ("temperature",),
    ("volumetric_flow", "mass_flow"),
)
_FIT = {
    **dict.fromkeys(
        [
            "built up back pressure",
            "cdtp",
            "design pressure",
            "flange rating",
            "hydrotest",
            "mawp",
            "operating pressure",
            "set pressure",
            "superimposed back pressure",
            "test pressure",
        ],
        _PRESSURE,
    ),
    "overpressure": ("pressure", "percent"),
    **dict.fromkeys(
        ["design temperature", "operating temperature", "relieving temperature"],
        _TEMPERATURE,
    ),
    **dict.fromkeys(
        [
            "max flow",
            "min flow",
            "minimum continuous flow",
            "rated flow",
            "rated capacity",
            "required capacity",
        ],
        _FLOW,
    ),
    **dict.fromkeys(
        ["npsh", "npsh available", "npsh required", "manway size"], ("length",)
    ),
    "density relieving": ("density",),
    "viscosity relieving": ("viscosity",),
    "motor rating": ("power",),
    "rated speed": ("rotation",),
    "noise level": ("sound",),
    "vibration": ("velocity", "length"),
    "empty weight": ("mass",),
    **dict.fromkeys(["orifice area", "required area"], ("area",)),
    **dict.fromkeys(["compressibility", "specific heat ratio"], ()),
}
#: Units `claims` has no dimension for, by family.
_LITERAL_UNITS = {
    "power": {"w", "kw", "mw", "hp", "bhp"},
    "rotation": {"rpm", "r/min"},
    "sound": {"db", "dba", "db(a)"},
    "mass": {"kg", "g", "t", "lb", "lbs"},
    "area": {"mm2", "cm2", "m2", "in2", "ft2", "sq in", "sq mm"},
    "viscosity": {"cst", "cp", "mpa.s", "mm2/s"},
}
#: Words that may stand between a name and its number without changing what the number limits.
_LIMIT_WORDS = frozenset(
    [
        "shall",
        "should",
        "must",
        "will",
        "be",
        "not",
        "exceed",
        "exceeding",
        "exceeds",
        "less",
        "greater",
        "more",
        "than",
        "at",
        "least",
        "most",
        "minimum",
        "maximum",
        "min",
        "max",
        "of",
        "is",
        "are",
        "to",
        "the",
        "a",
        "an",
        "equal",
        "equals",
        "above",
        "below",
        "under",
        "over",
        "up",
        "limited",
        "rated",
        "approximately",
    ]
)


def _unit_families(unit: str | None) -> set[str]:
    from . import claims

    unit = " ".join((unit or "").lower().split())
    if not unit:
        return set()
    out = {d for d in (claims.unit_dimension(unit),) if d}
    out.update(f for f, spellings in _LITERAL_UNITS.items() if unit in spellings)
    return out


def number_fits(
    text: str, quote: str | None, name: str, raw_value: str | None, raw_unit: str | None
) -> bool:
    """Gate 4: the requirement's own number is the limit of the NAMED quantity. (1) its unit is of
    that quantity's kind (none for a ratio); (2) in the sentence it follows the quote with only limit
    words between ("shall not exceed"), or stands directly before it ("30 bar design pressure"), with
    no other number, colon or semicolon between. Anything else - a duration, a size that only says
    when the clause applies, a formula - is refused."""
    value = (raw_value or "").strip().lower()
    if not quote or not value or name not in _FIT:
        return False
    wanted, have = _FIT[name], _unit_families(raw_unit)
    if (not wanted and have) or (wanted and not set(wanted) & have):
        return False
    t, q = " ".join(text.lower().split()), " ".join(quote.lower().split())
    at = t.find(q)
    if at < 0:
        return False
    number = re.compile(r"(?<![\w.])" + re.escape(value) + r"(?![\w])")
    after = t[at + len(q) :]
    m = number.search(after)
    if m:
        between = re.sub(r"\([^)]*\)", " ", after[: m.start()])
        return not re.search(r"[;:]", between) and all(
            w in _LIMIT_WORDS for w in _WORD.findall(between)
        )
    before = t[:at]
    hits = list(number.finditer(before))
    if not hits:
        return False
    gap = before[hits[-1].end() :]
    unit_words = set(_WORD.findall((raw_unit or "").lower()))
    return all(w in unit_words or w in _NEUTRAL for w in _WORD.findall(gap))


def verify(
    answer: dict,
    items: list[tuple[str, str]],
    dictionary: list[str],
    numbers: dict[str, tuple[str | None, str | None]],
):
    """The four gates on ONE model answer, with this vocabulary's gate 3 (not
    `field_naming.verify`'s, which ignores min/max) and gate 4 (`number_fits`; `numbers` is
    {requirement id: (raw_value, raw_unit)}, an id missing from it fits nothing). Returns (item index, {field_name, quote}) with
    field_name None when it maps nothing, or None when the answer names no valid item."""
    i = answer.get("i") if isinstance(answer, dict) else None
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(items):
        return None
    field = answer.get("field")
    quote = answer.get("quote") if isinstance(answer.get("quote"), str) else None
    unmapped = (i, {"field_name": None, "quote": None})
    if (
        not isinstance(field, int)
        or isinstance(field, bool)
        or not 0 <= field < len(dictionary)
    ):
        return unmapped  # gate 1
    if not field_naming.quote_verified(quote, items[i][1]):
        return unmapped  # gate 2
    if not names_the_quantity(quote, dictionary[field]):
        return unmapped  # gate 3
    raw_value, raw_unit = numbers.get(items[i][0], (None, None))
    if not number_fits(items[i][1], quote, dictionary[field], raw_value, raw_unit):
        return unmapped  # gate 4
    return i, {"field_name": dictionary[field], "quote": quote}


def name_requirements(
    requirements: list[dict], provider, stats: dict | None = None
) -> dict[str, dict]:
    """Name the numeric requirements against the closed vocabulary and store every answer. Returns
    {requirement id: {field_name | None, quote | None}} for all of them (stored + new). `stats`, when
    given, gets `unreadable`: the items of batches whose reply could not be read (truncated or not
    matching the schema), which are NOT stored, so a re-run asks them again."""
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
    return _name_items(
        items,
        vocabulary(),
        provider,
        stats if stats is not None else {},
        _numbers(requirements),
    )


def _numbers(requirements: list[dict]) -> dict[str, tuple[str | None, str | None]]:
    """{requirement id: (raw_value, raw_unit)}, as the document wrote them (gate 4)."""
    return {
        str(r["id"]): (r.get("raw_value"), r.get("raw_unit") or r.get("unit"))
        for r in requirements
    }


def _name_items(
    items: list[tuple[str, str]],
    dictionary: list[str],
    provider,
    stats: dict,
    numbers: dict[str, tuple[str | None, str | None]],
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
        if response.schema_errors or response.truncated:
            # a reply we could not read says nothing about these items: store nothing, count it
            stats["unreadable"] = stats.get("unreadable", 0) + len(batch)
            continue
        answers: dict[str, dict] = {}
        for raw in field_naming._parse(response.text):
            checked = verify(raw, batch, dictionary, numbers)
            if checked is not None:
                answers[batch[checked[0]][0]] = checked[1]
        for (
            key,
            _text,
        ) in batch:  # an item the model skipped is unmapped: recorded, not re-asked
            answers.setdefault(key, {"field_name": None, "quote": None})
        field_naming._store(REQUIREMENT, answers, dictionary, response)
        known.update(answers)
    return known


def fact_name(fact: dict, vocab: set[str] | None = None) -> str | None:
    """The vocabulary phrase a sheet fact's own label canonicalises to, or None."""
    from . import datasheet_checks
    from .datasheets import normalise_field_name

    vocab = vocab if vocab is not None else set(vocabulary())
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
    closed-vocabulary names of the requirements, each RE-CHECKED now against the requirement's
    current text and this vocabulary's gate 3 (an edited sentence or a changed rule loses its old
    name), plus the rule names of the facts. No model call. With nothing stored: the legacy
    per-sheet naming only when the geometry reader is on, else no names."""
    from .config import settings

    wanted_ids = {
        str(r["id"]): " ".join((r.get("requirement_text") or "").split())[
            : field_naming.REQUIREMENT_CHARS
        ]
        for r in requirements
        if r.get("requirement_type") in field_naming.NUMERIC_TYPES
    }
    vocab = vocabulary()
    numbers = _numbers(requirements)
    stored = field_naming.stored_names(REQUIREMENT, list(wanted_ids), vocab)
    named = {
        k: v["field_name"]
        for k, v in stored.items()
        if v.get("field_name")
        and field_naming.quote_verified(v.get("quote"), wanted_ids.get(k, ""))
        and names_the_quantity(v.get("quote"), v["field_name"])
        and number_fits(
            wanted_ids.get(k, ""),
            v.get("quote"),
            v["field_name"],
            *numbers.get(k, (None, None)),
        )
    }
    if not named:
        if settings.geometry_reader_enabled:
            return field_naming.ensure_names(requirements, facts)
        return {
            "requirements": {},
            "facts": {},
            "source": "closed vocabulary (nothing stored)",
            "requirements_asked": len(wanted_ids),
            "requirements_named": 0,
        }
    wanted = set(named.values())
    vocab_set = set(vocab)
    fact_names = {}
    for fact in facts:
        if not field_naming._nameable(fact):
            continue
        name = fact_name(fact, vocab_set)
        if name in wanted:
            fact_names[str(fact["id"])] = name
    return {
        "requirements": named,
        "facts": fact_names,
        "source": "closed vocabulary (stored, model-named, unconfirmed)",
        "requirements_asked": len(wanted_ids),
        "requirements_named": len(named),
    }
