"""B24 — can a requirement's condition be established from the submittal?

A clause that reads "For carbon steel, low-alloy steel and alloy steel systems, a
minimum C.A. of at least 1.6 mm shall be used" does not bind a vessel whose
material nobody has established. Before B24 the engine did the arithmetic anyway:
0 mm against 1.6 mm returned NON_COMPLIANT on a datasheet whose every material
field reads "N/A". The condition was extracted, stored, shipped to the UI and read
by nothing.

THAT SENTENCE IS TRUE OF THE MATERIAL FIELDS AND WAS STILL NOT ENOUGH (B49,
2026-09-23). On that same datasheet six fields genuinely state a material and all
six read "N/A" - but `_candidate_facts` did not select material fields, it
selected fields whose NAME contained "material", and two of those are corrosion
allowances reading "0 mm". Two stated values that were not "carbon steel" met the
only route to `NOT_SATISFIED`, and the gate answered NOT_APPLICABLE: it excused
the clause using the very fields the clause was being tested against. Measured,
not hypothesised. The evidence rule below was sound; the selector under it was
not, so a role test now decides what can be evidence - see `_candidate_facts`.

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

from . import claims, condition_choice, field_links

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


def _states_a_measurement(fact: dict) -> bool:
    """Does this fact state a QUANTITY rather than a name?

    B49, and it is a role test, not a name test. The units come from `claims`,
    which already owns every unit spelling and its dimension, so there is no
    word list here to keep in step with anything: if `claims` can give the
    value a dimension, the value is a measurement.

    Three sources, because extraction populates them unevenly: the unit
    columns, the normalised value, and - when no unit column was written - the
    value itself, which often carries its unit inline ("0 mm").
    """
    for unit in (fact.get("raw_unit"), fact.get("unit"), fact.get("normalized_unit")):
        if unit and claims.unit_dimension(str(unit)) is not None:
            return True
    if fact.get("normalized_value") is not None:
        return True
    head, _, tail = str(fact.get("field_value") or "").strip().partition(" ")
    return (claims.parse_value(head) is not None
            and claims.unit_dimension(tail.strip()) is not None)


def _candidate_facts(shape: str, facts: list[dict]) -> list[dict]:
    """The facts that could establish this condition - by ROLE, not by name.

    B49. The name hints below are a first pass and they are not sufficient on
    their own: on a real datasheet, `'design corrosion allowance for welded
    internal parts material 2'` contains "material" and is a LENGTH. It is not
    evidence about a material; it is the field under test. Selecting it let two
    corrosion allowances of "0 mm" stand as proof that the material was
    established and was not carbon steel, and the gate excused the clause -
    `NOT_APPLICABLE` on no evidence, the mirror failure this module exists to
    prevent.

    So for a MATERIAL condition a measured quantity is never evidence. The
    exclusion is deliberately limited to that shape: a material is never a
    quantity, while an equipment class legitimately can be - "low voltage
    cables" is established by a voltage, and `_FIELD_HINTS` lists "voltage" for
    exactly that reason.

    A fact dropped here does not make the condition false. It makes it
    unestablished, which is `UNKNOWN` - excusing a requirement stays harder
    than flagging one.
    """
    hints = _FIELD_HINTS.get(shape, ())
    if not hints:
        return []
    out = []
    for fact in facts:
        name = _fold(fact.get("field_name"))
        if not any(h in name for h in hints):
            continue
        if shape == SHAPE_MATERIAL and _states_a_measurement(fact):
            continue
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
    # A LOW-TRUST VALUE IS NOT EVIDENCE (review conditions, 2026-09-30): an
    # OCR-fallback or model-read material may neither apply nor excuse a clause.
    untrusted = [f for f in stated if _low_trust(f)]
    if untrusted:
        return _result(
            UNKNOWN, shape, condition,
            f"{_where(untrusted[0])}, and {_low_trust(untrusted[0])}; the "
            f"condition is not decided on a value not yet trusted")
    for fact in stated:
        value = _fold(fact.get("field_value"))
        for term in terms:
            if _contains_term(value, term):
                return _result(SATISFIED, shape, condition,
                               f"{fact.get('field_name')!r} states {term!r}",
                               _evidence_of(fact))
    # Every stated candidate was read and none carries the condition's term.
    # #633: THAT ALONE IS ABSENCE, NOT PROOF. "SA-516 Gr 70" is a carbon steel
    # this list does not spell; reading its silence as "not carbon steel"
    # excused the clause on no evidence. The only route to NOT_APPLICABLE is a
    # field that NAMES ANOTHER recognised value of the same kind ("stainless
    # steel" against a carbon-steel clause), and that field is the proof.
    table = {SHAPE_MATERIAL: _MATERIAL_TERMS, SHAPE_SERVICE: _SERVICE_TERMS,
             SHAPE_CLASS: _CLASS_TERMS}.get(shape, ())
    for named in stated:
        value = _fold(named.get("field_value"))
        other = next((t for t in table if t not in terms and _contains_term(value, t)), None)
        if other is not None:
            return _result(
                NOT_SATISFIED, shape, condition,
                f"{named.get('field_name')!r} states {other!r}, not "
                f"{', '.join(repr(t) for t in terms)}",
                _evidence_of(named))
    return _result(
        UNKNOWN, shape, condition,
        f"{len(stated)} field(s) state a value, but none names a "
        f"{shape.replace('_', ' ')} this check recognises (for example a grade code), so "
        f"it cannot say the condition does not hold")


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
        if _low_trust(fact):
            return _result(
                UNKNOWN, SHAPE_NUMERIC, condition,
                f"{_where(fact)}, and {_low_trust(fact)}; the condition is not "
                f"decided on a value not yet trusted")
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


# ============================================================================
# THE CONDITION READER (review conditions, 2026-09-30)
# ============================================================================
#
# The v1 gate above reads a condition as a bag of words: a material or service
# term, or a threshold whose subject words must appear in a field NAME. That
# cannot read the conditions standards actually write most often - "for pipes
# larger than 2 inch", "Class 600 and above", "above 60 °C" - because the size,
# class or temperature a datasheet states sits in a field whose name shares no
# word with the condition ("nominal size", "flange rating", "design
# temperature"). Those requirements were compared as if unconditional or sent
# to an engineer, never excused on the datasheet's own facts.
#
# The reader below closes that, in the same module and under the same rules:
#
#   * THE CONDITION IS PARSED BY `condition_choice.extract`, the deterministic
#     reader the chat already uses for sizes, temperatures, pressures, ASME
#     class / PN, service and material. No second set of patterns.
#   * THE DATASHEET FACT IS CHOSEN BY ROLE. A size condition is established
#     only by a field that IS a nominal size (NPS, DN, nominal size, line /
#     nozzle / pipe / valve size) and never by a wall thickness or any other
#     length; a temperature only by the design temperature (or the operating
#     temperature when the condition says "operating"); a class only by a
#     flange / pressure rating whose value reads as an ASME class or PN.
#   * THE WHOLE CONDITION MUST BE READ. Words left over after the read parts
#     and plain connectives are removed ("for critical service", "unless ...")
#     make the condition UNKNOWN - a condition read in part is not a condition
#     read. The one allowance: extra ALTERNATIVES of the same kind ("carbon
#     steel, low-alloy steel and alloy steel") may still let a matching fact
#     SATISFY the condition, but can never prove it does not hold.
#   * A LOW-TRUST VALUE IS NOT EVIDENCE ON ITS OWN, and the answer may not
#     change depending on whether low-trust values are counted
#     (`comparison.low_trust_reason` - the same test the breach guard uses).
#   * ONLY A FACT CLEARLY OUTSIDE THE CONDITION EXCUSES THE REQUIREMENT. A
#     value straddling the bound, a value in a unit the reader does not know,
#     a service or material outside the closed vocabulary: all UNKNOWN.
#
# Nothing read here reaches the old path. When `condition_choice` reads
# nothing at all in the condition, `evaluate` behaves exactly as before.

#: Kinds the reader decides. A condition that also names a kind outside this
#: set (a location, say) is treated as read only in part.
READER_KINDS = frozenset({"size", "temperature", "pressure", "class", "pn",
                          "service", "material"})

#: Connectives and generic nouns that carry no condition of their own. A word
#: NOT here, left over after the read parts are removed, makes the condition
#: read only in part. Deliberately short: adding a word here widens what the
#: reader claims to have understood.
_FILLER = frozenset({
    "for", "and", "or", "in", "of", "the", "a", "an", "with", "to", "on", "at",
    "all", "any", "where", "when", "is", "are", "be", "only", "applies",
    "service", "services", "system", "systems", "piping", "pipe", "pipes",
    "pipework", "line", "lines", "equipment", "application", "applications",
    "component", "components", "size", "sizes", "nominal", "design",
    "operating", "temperature", "temperatures", "pressure", "pressures",
    "rated", "rating", "ratings", "flange", "flanges", "valve", "valves",
    "nozzle", "nozzles", "material", "materials", "construction", "fluid",
    "fluids", "condition", "conditions", "environment", "environments",
})

#: "Class 600 and above" / "above Class 600": the bound around a class read.
_CLASS_AFTER = re.compile(
    r"^\s*(?:and|or)\s+(?P<dir>above|higher|greater|over|larger|more|below|lower|less|smaller|under)\b")
_CLASS_BEFORE = re.compile(
    r"(?P<dir>greater than|higher than|more than|above|over|exceeding|less than|"
    r"lower than|below|under|up to|not exceeding)\s*$")
_UP = frozenset({"above", "higher", "greater", "over", "larger", "more",
                 "greater than", "higher than", "more than", "exceeding"})
_STRICT = frozenset({"greater than", "higher than", "more than", "above", "over",
                     "exceeding", "less than", "lower than", "below", "under"})

#: Base-metal families. Two materials in different families exclude each other;
#: a material with no family here (galvanized - a coating) never proves
#: "outside".
_MATERIAL_FAMILY = {
    "carbon steel": "carbon steel", "low-alloy steel": "low-alloy steel",
    "stainless steel": "stainless", "duplex": "stainless",
    "super duplex": "stainless", "copper-nickel": "copper-nickel",
    "cast iron": "cast iron",
}
#: A material that IS also the listed ones: super duplex is a duplex, and both
#: are stainless steels. The reverse is not true - "stainless steel" does not
#: establish duplex.
_MATERIAL_IS_ALSO = {"duplex": {"stainless steel"},
                     "super duplex": {"duplex", "stainless steel"}}

#: Field roles, matched against `field_links.field_of`'s canonical name.
_SIZE_ROLE = re.compile(
    r"\b(?:nps|dn|nb|nominal (?:pipe )?size|nominal (?:bore|diameter)|"
    r"(?:line|nozzle|pipe|valve) size)\b")
_CLASS_ROLE = re.compile(
    r"(?:(?:asme|ansi|pressure|flange|nozzle|valve|body|end)\s+)*(?:class|rating)")
_SERVICE_ROLE = re.compile(r"\b(?:service|fluid|medium|contents|sour|h2s|nace)\b")
_PN_VALUE = re.compile(r"pn\s*(\d{1,3})", re.IGNORECASE)
#: A service stated as NOT the named one. Read BEFORE `extract`, which would
#: otherwise find "sour" inside "non-sour".
_NOT_SOUR = re.compile(r"\bnon[- ]?sour\b|\bnot sour\b|\bsweet\b", re.IGNORECASE)
_YES_WORDS = frozenset({"yes", "y"})
_NO_WORDS = frozenset({"no", "n"})

_ANY_INSIDE = "any_inside"       # material: one component in scope is enough
_UNANIMOUS = "unanimous"         # size, temperature, pressure, class
_EXPLICIT = "explicit"           # service: only a stated yes/no decides


class _Reading:
    """What the reader made of one condition text."""

    def __init__(self, needs, unread, alternatives_unread, problem):
        self.needs = needs                      # list[Condition]
        self.unread = unread                    # words not understood
        self.alternatives_unread = alternatives_unread  # same-kind options left
        self.problem = problem                  # why it cannot be decided, or None


def _class_need(cond, plain: str):
    """A class/PN condition as an interval on its number, with the bound the
    text puts round it ("Class 600 and above" -> [600, inf)). Returns the
    Condition (labelled as the standard writes it) and the folded text
    consumed. `plain` is the condition whitespace-collapsed, case kept."""
    folded = plain.lower()
    number = int(re.search(r"\d+", cond.value).group(0))
    kind = "pn" if cond.value.lower().startswith("pn") else "class"
    text = _fold(cond.text)
    at = folded.find(text)
    low = high = float(number)
    low_open = high_open = False
    consumed = text
    start, end = at, at + len(text)
    if at >= 0:
        after = _CLASS_AFTER.match(folded[at + len(text):])
        before = _CLASS_BEFORE.search(folded[:at])
        if after:
            consumed = text + folded[at + len(text):at + len(text) + after.end()]
            end = at + len(text) + after.end()
            if after.group("dir") in _UP:
                high = None
            else:
                low = None
        elif before:
            consumed = before.group(0) + folded[at:at + len(text)]
            start = before.start()
            word = before.group("dir")
            if word in _UP:
                high, low_open = None, word in _STRICT
            else:
                low, high_open = None, word in _STRICT
    label = plain[start:end].strip() if at >= 0 else cond.text
    return (condition_choice.Condition(kind, label, low=low, high=high,
                                       low_open=low_open, high_open=high_open),
            consumed)


def read_condition(condition: str | None) -> _Reading | None:
    """Parse a condition with `condition_choice.extract`. None when nothing in
    it is read - the caller then falls back to the v1 gate unchanged."""
    plain = " ".join(str(condition or "").split())
    folded = plain.lower()
    found = condition_choice.extract(plain)
    if not found:
        return None
    needs = []
    residue = folded
    for cond in found:
        if cond.kind == "class":
            need, consumed = _class_need(cond, plain)
        else:
            need, consumed = cond, _fold(cond.text)
        needs.append(need)
        residue = residue.replace(consumed, " ", 1)
    kinds = {n.kind for n in needs}
    unread = [w for w in (t.strip(".-/") for t in _WORD.findall(residue))
              if w and w not in _FILLER]
    problem = None
    alternatives_unread = False
    if kinds - READER_KINDS:
        problem = (f"it names {', '.join(sorted(kinds - READER_KINDS))}, which "
                   f"this reader does not decide")
    elif unread:
        table = {"material": _MATERIAL_TERMS, "service": _SERVICE_TERMS}.get(
            next(iter(kinds))) if len(kinds) == 1 else None
        covered = set()
        leftover = " ".join(unread)
        for term in table or ():
            if _contains_term(leftover, term):
                covered.update(_WORD.findall(term))
        if table and set(unread) <= covered:
            alternatives_unread = True
        else:
            problem = (f"part of it was not read ({' '.join(unread)!r}), so "
                       f"whether it holds cannot be decided")
    if problem is None:
        numeric = [n for n in needs if n.value is None and n.kind in
                   ("size", "temperature", "pressure")]
        if len(numeric) != len({n.kind for n in numeric}):
            problem = ("it states more than one bound of the same kind and the "
                       "reader does not decide how they combine")
        elif len(kinds) > 1 and _contains_term(folded, "or"):
            problem = ("it joins different kinds of condition with 'or', and the "
                       "reader decides only conditions that must all hold")
    return _Reading(needs, unread, alternatives_unread, problem)


def _canonical(fact: dict) -> tuple[str, str | None]:
    return field_links.field_of(fact.get("field_name"))


def _low_trust(fact: dict) -> str | None:
    # Late import: `comparison` imports this module.
    from .comparison import low_trust_reason
    return low_trust_reason(fact)


def _where(fact: dict) -> str:
    page = fact.get("page")
    return (f"{fact.get('field_name')!r}" + (f" (page {page})" if page else "")
            + f" states {fact.get('field_value')!r}")


def _value_texts(fact: dict, prefix: str | None = None) -> list[str]:
    """The texts a value may be read from: the value as printed, then the
    stored number with its unit. A bare number in an NPS or DN field is read
    with that prefix - the field's ROLE supplies it, never a guess."""
    out = []
    value = " ".join(str(fact.get("field_value") or "").split())
    raw, unit = fact.get("raw_value"), (fact.get("raw_unit") or fact.get("unit") or "")
    if value:
        out.append(value)
    if raw not in (None, ""):
        if str(unit).strip().lower() in ("in", "inch", "inches", '"'):
            unit = "inch"
        out.append(f"{raw} {unit}".strip())
    if prefix:
        for text in list(out):
            if re.fullmatch(r"\d+(?:[./]\d+)?(?:\s+\d+/\d+)?", text):
                out.append(f"{prefix} {text}")
    return out


def _read_interval(kind: str, fact: dict, prefix: str | None = None):
    """ONE interval of `kind` that accounts for every number in the text,
    else None. "6 x 4 inch", "95 °C / 203 °F" and "about 60" are not one
    reading and are never read as one."""
    for text in _value_texts(fact, prefix):
        got = [c for c in condition_choice.extract(text, question=True) if c.kind == kind]
        if len(got) != 1:
            continue
        numbers = condition_choice.stated_values(text)
        if numbers <= condition_choice.stated_values(got[0].text):
            return got[0]
    return None


def _read_class(fact: dict):
    value = " ".join(str(fact.get("field_value") or "").split())
    number = field_links.read_categorical("flange_rating", value)
    if number is not None:
        return condition_choice.Condition("class", value, low=float(number), high=float(number))
    pn = _PN_VALUE.fullmatch(value)
    if pn:
        return condition_choice.Condition("pn", value, low=float(pn.group(1)),
                                          high=float(pn.group(1)))
    return None


def _disjoint(a, b) -> bool:
    """Do two intervals share no point? Open ends respected."""
    def apart(left, right):      # left entirely below right?
        if left.high is None or right.low is None:
            return False
        if right.low > left.high + condition_choice._EPS:
            return True
        return (abs(right.low - left.high) <= condition_choice._EPS
                and (left.high_open or right.low_open))
    return apart(a, b) or apart(b, a)


def _interval_verdict(needs, observed) -> bool | None:
    if observed is None:
        return None
    if any(n.kind == observed.kind and n.holds_for(observed) for n in needs):
        return True
    if all(n.kind == observed.kind and _disjoint(n, observed) for n in needs):
        return False
    return None


def _material_verdict(needs, fact) -> bool | None:
    said = {c.value for c in condition_choice.extract(_fold(fact.get("field_value")))
            if c.kind == "material"}
    if not said:
        return None
    wanted = {n.value for n in needs}
    if any(s in wanted or wanted & _MATERIAL_IS_ALSO.get(s, set()) for s in said):
        return True
    families = {_MATERIAL_FAMILY.get(w) for w in wanted}
    if all(_MATERIAL_FAMILY.get(s) and _MATERIAL_FAMILY.get(s) not in families
           and None not in families for s in said):
        return False
    return None


def _service_verdict(needs, fact) -> bool | None:
    wanted = {n.value for n in needs}
    value = _fold(fact.get("field_value"))
    named = {c.value for c in condition_choice.extract(_fold(fact.get("field_name")))
             if c.kind == "service"}
    if named & wanted:
        # A field ABOUT the service ("Sour service", "H2S service"): yes / no.
        if value in _YES_WORDS:
            return True
        if value in _NO_WORDS:
            return False
    absent = set()
    if _NOT_SOUR.search(value):
        absent.add("sour")
        value = _NOT_SOUR.sub(" ", value)
    present = {c.value for c in condition_choice.extract(value) if c.kind == "service"}
    if present & wanted:
        return True
    if wanted and wanted <= absent:
        return False
    return None


def _roles(kind: str, needs, facts: list[dict], condition: str) -> list[tuple[dict, str | None]]:
    """(fact, NPS/DN prefix) for every fact whose ROLE can establish `kind`."""
    out = []
    folded = _fold(condition)
    which = ("operating" if _contains_term(folded, "operating")
             and not _contains_term(folded, "design") else "design")
    for fact in facts:
        name, _item = _canonical(fact)
        if kind == "size":
            if _SIZE_ROLE.search(name) and not condition_choice._MEASURE_WORD.search(name):
                prefix = "NPS" if re.search(r"\bnps\b", name) else \
                    "DN" if re.search(r"\bdn\b", name) else None
                out.append((fact, prefix))
        elif kind in ("temperature", "pressure"):
            if f"{which} {kind}" in name:
                out.append((fact, None))
        elif kind in ("class", "pn"):
            if name == "flange rating" or _CLASS_ROLE.fullmatch(name):
                out.append((fact, None))
        elif kind == "service":
            if _SERVICE_ROLE.search(name):
                out.append((fact, None))
        elif kind == "material":
            out.extend((f, None) for f in _candidate_facts(SHAPE_MATERIAL, [fact]))
    return out


def _same_item(facts: list[dict], about: dict | None) -> list[dict]:
    """Facts that can speak for the item `about` is about: the same equipment
    tag or nozzle mark, or no item at all (a sheet-wide field). N1's size says
    nothing about N3's flange."""
    if not about:
        return list(facts)
    tag = about.get("equipment_tag")
    item = _canonical(about)[1]
    out = []
    for fact in facts:
        if tag and fact.get("equipment_tag") and fact.get("equipment_tag") != tag:
            continue
        other = _canonical(fact)[1]
        if item and other and other != item:
            continue
        out.append(fact)
    return out


def _aggregate(rule: str, verdicts: list[bool | None]) -> bool | None:
    if not verdicts:
        return None
    if rule == _UNANIMOUS:
        if all(v is True for v in verdicts):
            return True
        if all(v is False for v in verdicts):
            return False
        return None
    if rule == _ANY_INSIDE:
        if any(v is True for v in verdicts):
            return True
        if all(v is False for v in verdicts):
            return False
        return None
    # _EXPLICIT: a stated yes or no decides; both stated is a conflict.
    if True in verdicts and False not in verdicts:
        return True
    if False in verdicts and True not in verdicts:
        return False
    return None


def _judge_kind(kind: str, needs, facts, condition: str) -> dict:
    """{verdict, fact, reason} for one kind of the condition."""
    label = " or ".join(repr(n.text) for n in needs)
    shown = "size" if kind == "size" else "class/PN rating" if kind in ("class", "pn") \
        else kind
    candidates = _roles(kind, needs, facts, condition)
    stated = [(f, p) for f, p in candidates if not _is_empty(f.get("field_value"))]
    if not candidates:
        return {"verdict": None, "fact": None,
                "reason": f"no datasheet field states the {shown} by role, so "
                          f"{label} is not established"}
    if not stated:
        return {"verdict": None, "fact": None,
                "reason": f"{len(candidates)} field(s) that could state the {shown} "
                          f"are blank or placeholders, so {label} is not established"}
    rule = _ANY_INSIDE if kind == "material" else _EXPLICIT if kind == "service" \
        else _UNANIMOUS
    judged = []
    for fact, prefix in stated:
        if kind == "material":
            v = _material_verdict(needs, fact)
        elif kind == "service":
            v = _service_verdict(needs, fact)
        elif kind in ("class", "pn"):
            v = _interval_verdict(needs, _read_class(fact))
        else:
            v = _interval_verdict(needs, _read_interval(kind, fact, prefix))
        judged.append((fact, v, _low_trust(fact)))
    trusted = [(f, v) for f, v, why in judged if why is None]
    untrusted = [(f, why) for f, v, why in judged if why is not None]
    decided = _aggregate(rule, [v for _f, v in trusted])
    if not trusted:
        f, why = untrusted[0]
        return {"verdict": None, "fact": f,
                "reason": f"the only field(s) stating the {shown} are not yet "
                          f"trusted - {_where(f)}, and {why}"}
    if untrusted and _aggregate(rule, [v for _f, v, _w in judged]) != decided:
        f, why = untrusted[0]
        return {"verdict": None, "fact": f,
                "reason": f"the answer would change with an untrusted reading - "
                          f"{_where(f)}, and {why}"}
    if decided is True:
        f = next(f for f, v in trusted if v is True)
        return {"verdict": True, "fact": f, "reason": f"{_where(f)}, inside {label}"}
    if decided is False:
        outside = [f for f, v in trusted if v is False]
        more = f" ({len(outside)} field(s) read, all outside)" if len(outside) > 1 else ""
        return {"verdict": False, "fact": outside[0],
                "reason": f"{_where(outside[0])}, which is outside {label}{more}"}
    unread = [f for f, v in trusted if v is None]
    if unread:
        return {"verdict": None, "fact": unread[0],
                "reason": f"{_where(unread[0])}, which the reader cannot place "
                          f"inside or outside {label}"}
    f = trusted[0][0]
    return {"verdict": None, "fact": f,
            "reason": f"the fields stating the {shown} disagree about {label} "
                      f"(for one, {_where(f)})"}


def _evaluate_read(reading: _Reading, condition: str, facts: list[dict]) -> dict:
    shape = "read:" + "+".join(sorted({n.kind for n in reading.needs}))
    if reading.problem:
        return _result(UNKNOWN, shape, condition,
                       f"the condition {condition!r} cannot be decided: "
                       f"{reading.problem}")
    by_kind: dict[str, list] = {}
    for need in reading.needs:
        by_kind.setdefault(need.kind, []).append(need)
    judged = {k: _judge_kind(k, v, facts, condition) for k, v in by_kind.items()}
    # ALL MUST HOLD. One kind clearly outside is enough to show the condition
    # does not hold - unless same-kind alternatives were left unread, in which
    # case "outside the ones read" is not "outside the condition".
    for kind, got in judged.items():
        if got["verdict"] is False and not reading.alternatives_unread:
            return _result(NOT_SATISFIED, shape, condition, got["reason"],
                           {**_evidence_of(got["fact"]), "match_kind": "condition_reader"})
    if all(got["verdict"] is True for got in judged.values()):
        first = next(iter(judged.values()))
        return _result(SATISFIED, shape, condition,
                       "; ".join(g["reason"] for g in judged.values()),
                       {**_evidence_of(first["fact"]), "match_kind": "condition_reader"})
    reasons = [g["reason"] for g in judged.values() if g["verdict"] is not True]
    if reading.alternatives_unread and any(g["verdict"] is False for g in judged.values()):
        reasons.append(f"the condition also lists {' '.join(reading.unread)!r}, "
                       f"which the reader does not decide")
    return _result(UNKNOWN, shape, condition, "; ".join(reasons))


def evaluate(requirement: dict, facts: list[dict] | None,
             about: dict | None = None) -> dict | None:
    """Is this requirement's condition established, and does it hold?

    Returns None when there is no condition to evaluate — the caller then
    behaves exactly as it did before B24. That is the 84.7% of requirements
    carrying no condition at all, and the 4,246 `table_value` rows whose
    `condition` column holds a table row label rather than a condition.

    `facts` is the submittal's fact set. **None or empty means UNKNOWN, never
    SATISFIED.** A caller that does not supply the evidence does not get a
    verdict; that is what makes this safe at every call site rather than only on
    the one path that remembers to pass it.

    `about` is the datasheet fact being compared, when there is one. Only facts
    about the same equipment tag or nozzle mark (or about no item) may then
    establish the condition - see `_same_item`.

    Order: the condition READER first (`read_condition`); when it reads nothing
    in the condition, the v1 shape gate below, exactly as before.
    """
    if (requirement or {}).get("requirement_type") != GATED_TYPE:
        return None
    condition = (requirement or {}).get("condition")
    if not _fold(condition):
        return None
    reading = read_condition(condition)
    if reading is not None:
        shape = "read:" + "+".join(sorted({n.kind for n in reading.needs}))
        if facts is None:
            return _result(UNKNOWN, shape, condition,
                           "no submittal facts were supplied to evaluate against")
        return _evaluate_read(reading, condition, _same_item(list(facts), about))
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
