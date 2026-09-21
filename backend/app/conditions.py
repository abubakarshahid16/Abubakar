"""B24 — can a requirement's condition be established from the submittal?

A clause that reads "For carbon steel, low-alloy steel and alloy steel systems, a
minimum C.A. of at least 1.6 mm shall be used" does not bind a vessel whose
material nobody has established. Before B24 the engine did the arithmetic anyway:
0 mm against 1.6 mm returned NON_COMPLIANT on a datasheet whose every material
field reads "N/A". The condition was extracted, stored, shipped to the UI and read
by nothing.

This module answers one question — *is the condition established, and does it
hold?* — and refuses to guess. It never decides compliance; `comparison.compare`
owns that. It only reports whether the comparison is entitled to happen.

SCOPED BY `requirement_type`, AND THAT IS THE WHOLE DESIGN. The `condition` column
carries two unrelated meanings:

  * on `numeric_limit` rows it is a real condition — 87 of 1,659, and not one of
    them is extraction noise;
  * on `table_value` rows it is the table's ROW LABEL — all 4,246 of them, 1,601
    of which are bare numbers like "100" and the rest pollutant names like
    "Arsenic".

A gate that read `condition` for every type would abstain on 4,246 rows because a
table row is called "Arsenic", and bury the 87 that matter. That is B20's defect
in mirror image: a confident wrong answer replaced by a confident wrong refusal.
`comparison.MATCHABLE_TYPES` already keeps `table_value` out of `compare` entirely,
so the type check here is a second lock on the same door, deliberately.

EXACT MATCHING ONLY, v1. `applicability.py` states that a semantically similar
standard "is NOT a citation and not evidence of applicability on its own". A
condition decides whether a requirement applies at all, so the same rule holds
harder: a near neighbour is not evidence. No embeddings, no fuzzy distance, no
synonym expansion. A curated, versioned, engineer-approved synonym table may come
later; it would be data with provenance, not inference.

UNKNOWN IS NOT "NOT APPLICABLE". They are opposite failures and the difference is
the point. "The material is not established" leaves the requirement possibly
governing and needs an engineer. "The material is established and it is stainless"
proves the carbon-steel clause does not govern. Collapsing the first into the
second would excuse a real breach, so `NOT_SATISFIED` is returned only with the
fact that proves it, and everything else is `UNKNOWN`.
"""

from __future__ import annotations

import re

from . import claims

#: The condition is established and holds — the comparison may proceed.
SATISFIED = "SATISFIED"
#: The condition is established and does NOT hold, and a fact proves it.
#: Only this state may become NOT_APPLICABLE.
NOT_SATISFIED = "NOT_SATISFIED"
#: Nothing in the submittal establishes the condition either way.
UNKNOWN = "UNKNOWN"

#: Condition shapes v1 recognises. Anything else is `SHAPE_UNRECOGNISED` and
#: resolves to UNKNOWN — a shape this module cannot read is not a shape it may
#: guess at.
SHAPE_MATERIAL = "named_material"
SHAPE_SERVICE = "named_service_or_fluid"
SHAPE_NUMERIC = "numeric_threshold"
SHAPE_CLASS = "equipment_or_area_class"
SHAPE_UNRECOGNISED = "unrecognised"

#: The only `requirement_type` whose `condition` column holds a condition.
#: See the module docstring for why this is not negotiable.
GATED_TYPE = "numeric_limit"

#: Values a field carries when it is saying nothing. A field reading "N/A" does
#: not establish a material; it establishes that nobody filled it in. Treated as
#: absent, never as a mismatch — which is the difference between UNKNOWN and
#: NOT_APPLICABLE.
_EMPTY_VALUES = frozenset({
    "", "n/a", "na", "n.a.", "not applicable", "none", "nil", "-", "--", "---",
    "----", "tba", "tbd", "by vendor", "by others", "later", "hold", "?", "xxx",
})

_MATERIAL_TERMS = (
    "carbon steel", "low alloy", "low-alloy", "alloy steel", "stainless steel",
    "stainless", "duplex", "super duplex", "austenitic", "ferritic",
    "martensitic", "inconel", "monel", "hastelloy", "titanium", "nickel alloy",
    "copper", "brass", "bronze", "aluminium", "aluminum", "galvanised",
    "galvanized", "clad", "overlay", "cr-mo", "chrome moly", "uns n06625",
    "uns n08825",
)
_SERVICE_TERMS = (
    "sour service", "sour", "sweet", "h2s", "hydrogen", "amine", "caustic",
    "chloride", "seawater", "sea water", "potable water", "fire water",
    "firewater", "steam", "crude", "molten sulfur", "molten sulphur",
    "hydrocarbon", "flare", "utility", "wet gas", "dry gas", "glycol",
)
_CLASS_TERMS = (
    "zone 0", "zone 1", "zone 2", "division 1", "division 2", "hazardous area",
    "hazardous", "pressure vessel", "vessel", "pump", "compressor", "piping",
    "pipeline", "valve", "relief valve", "psv", "tank", "heater", "exchanger",
    "instrument", "electrical", "motor", "onshore", "offshore", "buried",
    "underground", "atmospheric", "low voltage", "medium voltage",
    "thermocouple", "cable", "cables",
)

#: Field-name hints per shape. The evaluator looks only at facts whose field name
#: plausibly speaks to the condition; a corrosion-allowance field cannot establish
#: a material however many words it shares.
_FIELD_HINTS = {
    SHAPE_MATERIAL: ("material", "moc", "metallurgy", "grade"),
    SHAPE_SERVICE: ("service", "fluid", "medium", "contents", "process"),
    SHAPE_CLASS: ("type", "class", "category", "area", "zone", "equipment",
                  "voltage", "description"),
}

_NUMERIC_CONDITION = re.compile(
    r"(?P<cmp>greater than or equal to|less than or equal to|not less than|"
    r"not more than|at least|at most|greater than|less than|more than|"
    r"exceeding|exceeds|exceed|above|below|over|under|up to)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>[A-Za-z%°/]+(?:\s?[A-Za-z0-9/]+)?)?",
    re.IGNORECASE,
)

_WORD = re.compile(r"[A-Za-z0-9.\-/]+")


def _fold(text: str | None) -> str:
    """Lowercased, whitespace-collapsed. The only normalisation applied here."""
    return " ".join(str(text or "").lower().split())


def _is_empty(value: str | None) -> bool:
    return _fold(value) in _EMPTY_VALUES


def _contains_term(haystack: str, term: str) -> bool:
    """Whole-word containment, not substring.

    Substring matching would let "alloy" match "unalloyed" and "cs" match
    "physics". Both sides are already folded.
    """
    hay = _WORD.findall(haystack)
    needle = _WORD.findall(term)
    if not needle or len(needle) > len(hay):
        return False
    for i in range(len(hay) - len(needle) + 1):
        if hay[i:i + len(needle)] == needle:
            return True
    return False


def classify(condition: str) -> str:
    """The shape of a condition, or SHAPE_UNRECOGNISED.

    Order matters. A numeric threshold is the most specific signal and is tested
    first, so "flanges with T greater than 50 mm" is read as a threshold rather
    than as the equipment word "flanges".
    """
    folded = _fold(condition)
    if not folded:
        return SHAPE_UNRECOGNISED
    if _NUMERIC_CONDITION.search(folded):
        return SHAPE_NUMERIC
    for term in _MATERIAL_TERMS:
        if _contains_term(folded, term):
            return SHAPE_MATERIAL
    for term in _SERVICE_TERMS:
        if _contains_term(folded, term):
            return SHAPE_SERVICE
    for term in _CLASS_TERMS:
        if _contains_term(folded, term):
            return SHAPE_CLASS
    return SHAPE_UNRECOGNISED


def _terms_for(shape: str, condition: str) -> list[str]:
    table = {SHAPE_MATERIAL: _MATERIAL_TERMS, SHAPE_SERVICE: _SERVICE_TERMS,
             SHAPE_CLASS: _CLASS_TERMS}.get(shape, ())
    folded = _fold(condition)
    return [t for t in table if _contains_term(folded, t)]


def _candidate_facts(shape: str, facts: list[dict]) -> list[dict]:
    hints = _FIELD_HINTS.get(shape, ())
    if not hints:
        return []
    out = []
    for fact in facts:
        name = _fold(fact.get("field_name"))
        if any(h in name for h in hints):
            out.append(fact)
    return out


def _result(state: str, shape: str, condition: str, reason: str,
            evidence: dict | None = None) -> dict:
    return {"state": state, "shape": shape, "condition": condition,
            "reason": reason, "evidence": evidence}


def _evidence_of(fact: dict) -> dict:
    """The locator for a condition decision, same discipline as a finding's."""
    return {
        "submittal_facts_row_id": fact.get("id"),
        "field_name": fact.get("field_name"),
        "field_value": fact.get("field_value"),
        "page": fact.get("page"),
        "extraction_method": fact.get("extraction_method"),
        "confidence": fact.get("confidence"),
        "match_kind": "exact_term",
    }


def _evaluate_terms(shape: str, condition: str, facts: list[dict]) -> dict:
    terms = _terms_for(shape, condition)
    if not terms:
        return _result(UNKNOWN, shape, condition,
                       "no term in this condition is one v1 recognises")
    candidates = _candidate_facts(shape, facts)
    if not candidates:
        return _result(UNKNOWN, shape, condition,
                       f"the submittal carries no field that could establish "
                       f"{shape.replace('_', ' ')}")
    stated = [f for f in candidates if not _is_empty(f.get("field_value"))]
    if not stated:
        return _result(
            UNKNOWN, shape, condition,
            f"{len(candidates)} candidate field(s) exist but none states a value "
            f"(all blank or placeholder), so the condition is not established")
    for fact in stated:
        value = _fold(fact.get("field_value"))
        for term in terms:
            if _contains_term(value, term):
                return _result(SATISFIED, shape, condition,
                               f"{fact.get('field_name')!r} states {term!r}",
                               _evidence_of(fact))
    # Every stated candidate was read and none carries the condition's term.
    # THIS is the only route to NOT_APPLICABLE, and it carries its proof.
    return _result(
        NOT_SATISFIED, shape, condition,
        f"{len(stated)} field(s) state a value and none of them is "
        f"{', '.join(repr(t) for t in terms)}",
        _evidence_of(stated[0]))


def _evaluate_numeric(condition: str, facts: list[dict]) -> dict:
    match = _NUMERIC_CONDITION.search(_fold(condition))
    if not match:
        return _result(UNKNOWN, SHAPE_NUMERIC, condition,
                       "the threshold could not be parsed")
    unit = (match.group("unit") or "").strip()
    if not unit:
        return _result(UNKNOWN, SHAPE_NUMERIC, condition,
                       "the threshold carries no unit, so nothing can be "
                       "compared against it without guessing one")
    operator = claims.parse_comparator(match.group("cmp"))
    if not operator:
        return _result(UNKNOWN, SHAPE_NUMERIC, condition,
                       f"the comparator {match.group('cmp')!r} is not one this "
                       f"system parses")
    limit = claims.normalise(match.group("value"), unit)
    if limit.normalized_value is None:
        return _result(UNKNOWN, SHAPE_NUMERIC, condition,
                       f"the threshold unit {unit!r} is not in the unit table")

    # The subject words of the condition, used to find a fact that speaks to it.
    subject_words = [w for w in _WORD.findall(_fold(condition))
                     if len(w) > 3 and not w.replace(".", "").isdigit()
                     and w not in {"than", "less", "more", "over", "under",
                                   "with", "least", "most", "equal", "greater",
                                   "exceeding", "exceeds", "exceed", "above",
                                   "below"}]
    for fact in facts:
        if _is_empty(fact.get("field_value")):
            continue
        name = _fold(fact.get("field_name"))
        if not any(_contains_term(name, w) for w in subject_words):
            continue
        observed = claims.normalise(
            str(fact.get("raw_value") or ""),
            str(fact.get("raw_unit") or fact.get("unit") or ""))
        if observed.normalized_value is None:
            continue
        # Routed through claims, so the B20 dimension guard applies: a length
        # against a temperature is undecidable, never a pass.
        verdict = claims._compatible(
            claims.normalise(str(fact.get("raw_value") or ""),
                             str(fact.get("raw_unit") or fact.get("unit") or ""),
                             operator),
            limit)
        if verdict is None:
            return _result(
                UNKNOWN, SHAPE_NUMERIC, condition,
                f"{fact.get('field_name')!r} and the threshold cannot be "
                f"compared; no conversion is guessed")
        state = SATISFIED if verdict else NOT_SATISFIED
        return _result(state, SHAPE_NUMERIC, condition,
                       f"{fact.get('field_name')!r} = "
                       f"{fact.get('field_value')!r} against {operator} "
                       f"{match.group('value')} {unit}",
                       _evidence_of(fact))
    return _result(UNKNOWN, SHAPE_NUMERIC, condition,
                   "no submitted field speaks to this threshold")


def evaluate(requirement: dict, facts: list[dict] | None) -> dict | None:
    """Is this requirement's condition established, and does it hold?

    Returns None when there is no condition to evaluate — the caller then
    behaves exactly as it did before B24. That is the 84.7% of requirements
    carrying no condition at all, and the 4,246 `table_value` rows whose
    `condition` column holds a table row label rather than a condition.

    `facts` is the submittal's fact set. **None or empty means UNKNOWN, never
    SATISFIED.** A caller that does not supply the evidence does not get a
    verdict; that is what makes this safe at every call site rather than only on
    the one path that remembers to pass it.
    """
    if (requirement or {}).get("requirement_type") != GATED_TYPE:
        return None
    condition = (requirement or {}).get("condition")
    if not _fold(condition):
        return None
    shape = classify(condition)
    if shape == SHAPE_UNRECOGNISED:
        return _result(UNKNOWN, shape, condition,
                       "v1 does not recognise the shape of this condition")
    if facts is None:
        return _result(UNKNOWN, shape, condition,
                       "no submittal facts were supplied to evaluate against")
    if shape == SHAPE_NUMERIC:
        return _evaluate_numeric(condition, list(facts))
    return _evaluate_terms(shape, condition, list(facts))
