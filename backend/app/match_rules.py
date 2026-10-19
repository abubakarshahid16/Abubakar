"""Rules that decide WHICH containment hit a requirement may be paired with.

WHY THIS EXISTS. `comparison.match_by_containment` joins a requirement to a
datasheet field by whole-word containment and resolves ties by "longest field
name wins". Measured on a filled gold pairing sheet (kept local, not tracked -
see `gold/README.md`) that made 8 pairings, of which 0 were right and 8 were
FALSE - every one a real clause number and a real page attached to a number
the clause was not about:

  * `design life = 25 years` on a pressure vessel paired with SAES-P-103 5.2.5,
    "the design life of the BATTERY shall be at least 20 years";
  * `normal operating temperature = 30 °C` paired with SAES-X-500 6.6.3, a
    limit in ohm-cm (electrolyte resistivity);
  * `maximum operating pressure = 2.2 bar` paired with SAES-D-001 6.2.3, "the
    internal design pressure shall be according to the following table" -
    where MOP is the table's INPUT and the internal design pressure is the
    quantity being constrained.

Containment cannot see any of that: the words are all genuinely in the
sentence. These three rules can. Each one answers a single question, returns a
NAMED reason when it refuses, and refuses ONLY when it is sure - an unknown
sheet kind, an unrecognised unit or a sentence with no table are all "no
opinion", never "reject". A rule that guessed would put silence where a
correct pairing used to be, and silence is invisible on the engineer's screen.

NOT A FILTER ONLY. Rule 3 changes WHICH pairing is made, not merely whether
one is: it removes the table's input field from the tie so the constrained
quantity wins. That is why this module is named for the rules and not for a
gate, and why it runs BEFORE longest-wins rather than after.

The three rules, in the order they run:

  1. UNIT DIMENSION. A limit in a pressure unit is never about a field in a
     temperature unit. Decided with `claims.unit_dimension`: reject when both
     dimensions are known and differ, or when exactly one is known and the
     other spelling is not a unit `claims` recognises at all. Two unrecognised
     spellings, or two recognised ones with no dimension (`dB(A)` and `dB`,
     `years` and `h`), are left to `compare`, which already refuses them.
  2. EQUIPMENT DOMAIN. A requirement whose sentence names a kind of equipment
     applies to that kind. When the sheet's kind is known - from the document's
     classification, or from the field names when every domain word on the
     sheet agrees - and the sentence names other kinds and not this one, the
     pairing is refused. A sentence that names no equipment, or a sheet whose
     kind cannot be told, is never refused on this rule.
  3. TABLE LOOKUP KEY. "<A> shall be according to the following table: <B>"
     constrains A and takes B as the input. A field that appears only in the
     part after the table marker is the input, and the pairing is refused so
     that the constrained quantity is what remains for longest-wins.

MEASURED (VS Code, on the dead worktree, before it was lost): review scope
2 false -> 0 false, 1 correct, 18/18 NONE rows silent; corpus scope 8 -> 1
false. This file is that design rebuilt from its record; the numbers must be
re-measured with `scripts/gold_pairs_score.py` before they are quoted again.
"""

from __future__ import annotations

import json
import re
from functools import cache, lru_cache
from pathlib import Path

from . import claims

# ------------------------------------------------------------------ reasons
#: Why a containment hit was refused. Every refusal carries one of these so a
#: run can report how many pairings each rule removed, and a rule that removes
#: a correct pairing can be found by its name rather than by reading findings.
UNIT_DIMENSION = "unit_dimension"
EQUIPMENT_DOMAIN = "equipment_domain"
TABLE_LOOKUP_INPUT = "table_lookup_input"
COMPOUND_TERM = "compound_term"
QUALIFIER = "qualifier"
#: Rule 6 (order 139): the two sides name different kinds of quantity.
QUANTITY_KIND = "quantity_kind"

REASONS: tuple[str, ...] = (
    UNIT_DIMENSION,
    EQUIPMENT_DOMAIN,
    TABLE_LOOKUP_INPUT,
    COMPOUND_TERM,
    QUALIFIER,
    QUANTITY_KIND,
)

# ------------------------------------------------------------------ domains
#: Ten kinds of equipment a clause names when it applies to one kind only. The
#: plural is folded to the singular before lookup. Deliberately short: a word
#: here refuses pairings, so each one must be a word a clause uses to mean
#: "this rule is about that machine" and nothing else. "valve" is not here
#: because a vessel datasheet legitimately carries valve fields; "pipe" is not
#: here because piping clauses govern nozzles on every kind of equipment.
DOMAIN_NOUNS: tuple[str, ...] = (
    "battery", "cable", "anode", "transformer", "pump", "vessel", "tank",
    "exchanger", "motor", "compressor",
)

_PLURALS = {"batteries": "battery", "cables": "cable", "anodes": "anode",
            "transformers": "transformer", "pumps": "pump", "vessels": "vessel",
            "tanks": "tank", "exchangers": "exchanger", "motors": "motor",
            "compressors": "compressor"}

#: How `document_classification.equipment_type` spellings fold onto a domain
#: noun. Anything not listed is folded by looking for a domain noun inside it.
_EQUIPMENT_TYPE_ALIASES = {
    "pressure vessel": "vessel", "vessel": "vessel", "drum": "vessel",
    "column": "vessel", "separator": "vessel", "storage tank": "tank",
    "heat exchanger": "exchanger", "shell and tube": "exchanger",
    "centrifugal pump": "pump", "electric motor": "motor",
    "power transformer": "transformer",
}


def _words(text: str | None) -> list[str]:
    folded = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return folded.split()


def domains_in(text: str | None) -> frozenset[str]:
    """The equipment domains a piece of text names, as a set of nouns."""
    found: set[str] = set()
    for word in _words(text):
        word = _PLURALS.get(word, word)
        if word in DOMAIN_NOUNS:
            found.add(word)
    return frozenset(found)


def requirement_domains(requirement: dict) -> frozenset[str]:
    """The domains a requirement's own sentence names.

    The SENTENCE, not just the subject: "the design life of the battery" puts
    the noun in the subject, but "for cables, the ... shall not exceed" puts it
    before the subject begins. Both are the clause saying what it is about.
    """
    text = " ".join(str(requirement.get(key) or "") for key in
                    ("requirement_text", "source_text", "subject"))
    return domains_in(text)


def sheet_kind_from_equipment_type(equipment_type: str | None) -> str | None:
    """The domain noun a classification's `equipment_type` names, or None."""
    if not equipment_type:
        return None
    folded = " ".join(_words(equipment_type))
    if folded in _EQUIPMENT_TYPE_ALIASES:
        return _EQUIPMENT_TYPE_ALIASES[folded]
    found = domains_in(folded)
    return next(iter(found)) if len(found) == 1 else None


def sheet_kind_from_facts(facts: list[dict]) -> str | None:
    """The one domain the field names agree on, or None.

    "vessel support corrosion allowance" says vessel. If field names name two
    different domains - a pump sheet with a "motor rated power" field - the
    sheet's kind is not decidable from names alone and this says so with None,
    which means rule 2 never refuses anything on that sheet.
    """
    found: set[str] = set()
    for fact in facts:
        found |= domains_in(fact.get("field_name"))
    return next(iter(found)) if len(found) == 1 else None


def sheet_kind(facts: list[dict], equipment_type: str | None = None) -> str | None:
    """The classification's word first; the field names only when it has none."""
    return (sheet_kind_from_equipment_type(equipment_type)
            or sheet_kind_from_facts(facts))


# ------------------------------------------------------------------ rule 1
def unit_dimension_conflict(requirement: dict, fact: dict) -> bool:
    """True when the two units cannot be about the same quantity.

    Both dimensions known and different: a pressure against a temperature.
    Exactly one known and the other spelling not a unit at all: `°C` against
    `ohm-cm`. Everything else is left alone - `compare` has the last word on
    whether two numbers can actually be compared.
    """
    left = claims.base_unit(requirement.get("raw_unit") or requirement.get("unit"))
    right = claims.base_unit(fact.get("raw_unit") or fact.get("unit"))
    if not left or not right:
        return False
    left_dim, right_dim = claims.unit_dimension(left), claims.unit_dimension(right)
    if left_dim is not None and right_dim is not None:
        return left_dim != right_dim
    if left_dim is None and right_dim is None:
        return False
    # Exactly one side has a dimension. The other is either a recognised unit
    # with no dimension (years, dB, kg - which `compare` will refuse itself)
    # or not a unit `claims` knows. Only the second is refused here.
    unknown = right if left_dim is not None else left
    return not claims.is_unit(unknown)


# ------------------------------------------------------------------ rule 2
def equipment_domain_conflict(requirement: dict, sheet: str | None) -> bool:
    """True when the sentence names equipment and this sheet is not it."""
    if not sheet:
        return False
    named = requirement_domains(requirement)
    if not named:
        return False
    return sheet not in named


# ------------------------------------------------------------------ rule 3
#: "<A> shall be according to the following table" and its spellings. The
#: match ends at the marker; what follows is the table, whose first column is
#: the lookup input.
_TABLE_MARKER = re.compile(
    r"\b(?:shall|must|should|will|may)\s+be\s+"
    r"(?:according\s+to|in\s+accordance\s+with|as\s+(?:given|shown|specified)\s+in"
    r"|per|based\s+on)\s+"
    r"(?:the\s+)?(?:(?:following|below)\s+table|table\s+below)\b",
    re.IGNORECASE)


#: Words that make a subject a sentence rather than a table's column header.
_HEADER_VERB = re.compile(
    r"\b(?:shall|must|should|will|may|is|are|be|been|according|per)\b")


def table_lookup_split(text: str | None) -> tuple[str, str] | None:
    """`(constrained part, input part)` of a table-lookup sentence, or None.

    The constrained part is the text BEFORE the marker, the input part the text
    AFTER it. Returned normalised the way `comparison._normalise_for_match`
    normalises a field name, so containment tests on either half use the same
    shape as the matcher.
    """
    if not text:
        return None
    hit = _TABLE_MARKER.search(text)
    if hit is None:
        return None
    before = _normalise(text[:hit.start()])
    after = _normalise(text[hit.end():])
    return before, after


def _normalise(text: str) -> str:
    folded = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", folded).strip()


def _contains_words(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def table_lookup_input_conflict(requirement: dict, field_name: str) -> bool:
    """True when `field_name` is the table's input, not the constrained quantity.

    "The internal design pressure shall be according to the following table:
    Maximum Operating Pressure ... Design Pressure ..." - `maximum operating
    pressure` is in the part after the marker and not in the part before it,
    so it is the input. `internal design pressure` is before the marker and
    is what the clause constrains.
    """
    name = _normalise(field_name)
    if not name:
        return False
    marked = False
    for key in ("requirement_text", "source_text", "subject"):
        split = table_lookup_split(requirement.get(key))
        if split is None:
            continue
        marked = True
        before, after = split
        if _contains_words(after, name) and not _contains_words(before, name):
            return True
    if marked:
        return False
    # A TABLE ROW WITH NO LEAD-IN SENTENCE (#193). The marker lives in the
    # sentence introducing a table, and the chunker can file that sentence
    # under a different requirement row - SAES-E-014 7.2.4 stores the same
    # MOP -> design-pressure table as D-001 6.2.3 starting at its header, so
    # the rule above never fired and the table's INPUT was paired to it. The
    # structural fact that remains: a lookup table's FIRST header column is
    # its key. A field that is exactly the start of a table row's header,
    # with more header after it, is that key - the input, not the constrained
    # quantity. Only for `table_row`: an ordinary limit whose subject starts
    # with the field ("maximum operating pressure of the vessel") is the case
    # the matcher exists for.
    if requirement.get("requirement_type") != "table_row":
        return False
    header = _normalise(requirement.get("subject") or "")
    # A SENTENCE IS NOT A HEADER. "internal design pressure shall be according
    # to the table" does not match the strict marker, but its first noun is
    # what it constrains - refusing it would silence a correct pairing. Only a
    # verbless subject (a bare column header) has a first column to refuse.
    if _HEADER_VERB.search(header):
        return False
    # `name + " "`: the field must be followed by MORE header. A header that
    # is the field alone names one quantity and has no input column.
    return header.startswith(name + " ")


# ------------------------------------------------------------------ rule 4
#: A word that IS a real datasheet field on this kind of equipment (a pump's
#: "Bearing") but that the SAME word also names, as part of a different
#: compound noun, something in an entirely different domain (a foundation's
#: "soil bearing pressure"). Whole-word containment cannot tell these apart -
#: the word is genuinely present either way - and rule 2 (equipment domain)
#: does not catch it either, because the clause names no equipment at all, so
#: there is no domain mismatch for it to see.
#:
#: FOUND reviewing a real review of EF1975-DAS-M-03 (2026-09-28): a civil
#: clause on allowable SOIL bearing pressure was paired, whole-word, with a
#: pump datasheet's blank "Bearing" field - a foundation-loading comment
#: attached to a mechanical component that has nothing to do with it.
#:
#: Deliberately short and hand-picked, the same shape as DOMAIN_NOUNS above:
#: each entry is a field word mapped to the SPECIFIC OTHER COMPOUND PHRASES
#: that word forms when it does NOT mean the equipment field - not a general
#: synonym or fuzzy-match table. This rule refuses ONLY when one of those
#: exact phrases is present in the requirement's own sentence, never on the
#: bare word alone - a legitimate mechanical sentence like "the pump bearing
#: temperature shall be monitored" contains none of these phrases and is
#: left alone.
AMBIGUOUS_COMPOUND: dict[str, tuple[str, ...]] = {
    "bearing": ("soil bearing", "foundation bearing", "bearing capacity",
               "bearing pressure", "allowable bearing"),
}


def compound_term_conflict(field_name: str, requirement: dict) -> bool:
    """True when `field_name` is one of `AMBIGUOUS_COMPOUND`'s words and the
    requirement's own sentence contains one of that word's OTHER, non-
    equipment compound phrases."""
    name = _normalise(field_name)
    others = AMBIGUOUS_COMPOUND.get(name)
    if not others:
        return False
    text = _normalise(" ".join(str(requirement.get(key) or "") for key in
                               ("requirement_text", "source_text", "subject")))
    if not text:
        return False
    return any(_contains_words(text, phrase) for phrase in others)


# ------------------------------------------------------------------ rule 5
#: The words, as data: `reference/field_qualifiers.json` (see its `_about`).
QUALIFIERS_PATH = Path(__file__).parent / "reference" / "field_qualifiers.json"


def derived_after() -> frozenset[str]:
    """Words that, right after a field's words, make it a different quantity."""
    return frozenset(w.lower() for w in json.loads(
        QUALIFIERS_PATH.read_text(encoding="utf-8")).get("derived_after", []))


def qualifiers() -> frozenset[str]:
    return frozenset(w.lower() for w in json.loads(
        QUALIFIERS_PATH.read_text(encoding="utf-8"))["qualifiers"])


def qualifier_conflict(requirement: dict, field_name: str) -> bool:
    """True when the requirement's SUBJECT puts a side, part or location word
    (`qualifiers()`: external, jacket, inlet...) right AT the field's own words
    and the field name does not carry it: just before them ("the maximum
    EXTERNAL design pressure") or just after, through "of (the)" ("the
    operating pressure OF THE JACKET"). FOUND on the real PSV review
    (2026-10-10): those two were paired with the sheet's plain design and
    operating pressures by whole-word containment and gave seven false
    NON_COMPLIANT findings.

    Next to the field's words only, never anywhere in the subject: in "the
    minimum shell thickness and the maximum allowable working pressure" the
    word "shell" qualifies the thickness, not the pressure. When the field was
    matched through a synonym and its words are not in the subject, there is
    nothing to stand next to, so no conflict."""
    subject = _normalise(str(requirement.get("subject") or "")).split()
    field = _normalise(field_name).split()
    if not subject or not field:
        return False
    # BOTH DIRECTIONS (planner, 2026-10-10): a FIELD that names a side or part
    # the subject does not ("Jacket design pressure" against a plain "design
    # pressure" rule) is a different quantity too. Same qualifier both sides
    # still pairs.
    if (set(field) & qualifiers()) - set(subject):
        return True
    words = qualifiers() - set(field)
    n = len(field)
    for start in range(len(subject) - n + 1):
        if subject[start:start + n] != field:
            continue
        # "set pressure TOLERANCE": the next word makes it another quantity
        nxt = subject[start + n:start + n + 1]
        if nxt and nxt[0] in derived_after() and nxt[0] not in field:
            return True
        before = subject[max(0, start - 2):start]
        after = subject[start + n:start + n + 3]
        if after[:1] == ["of"]:
            after = after[2:3] if after[1:2] == ["the"] else after[1:2]
        else:
            after = []
        if words & set(before) or words & set(after):
            return True
    return False


# ------------------------------------------------------------------ rule 6
# SAME QUANTITY KIND (order 139): a requirement pairs only with a value of the
# same kind of quantity (a flow field was paired with bearing-temperature
# clauses, a pump efficiency with weld-joint rules). The kind is READ: a side's
# own unit (`claims`; no second unit table here), the unit a blank cell
# prints, else the noun naming the quantity (`quantity_nouns`, onto the same
# `claims` dimensions). Two kinds that differ: REFUSED. A kind that cannot be
# told, or another thing's quantity: UNSURE - kept for the engineer, never a
# verdict.
#: Why a pairing that no rule refuses still may not carry a verdict.
QUANTITY_KIND_UNSURE = "quantity_kind_unsure"

_CONJUNCTIONS = frozenset({"and", "or", "nor"})
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*|[^\sa-z0-9]")


def _is_word(token: str) -> bool:
    """A word that can name something: two letters or more, no digit (a
    clause label, a material grade or a number says nothing about whose
    quantity it is)."""
    return len(token) > 1 and token[0].isalpha() and not any(c.isdigit() for c in token)


@lru_cache(maxsize=1)
def _kind_data() -> dict:
    return json.loads(QUALIFIERS_PATH.read_text(encoding="utf-8"))


def _kind_words(key: str):
    return _kind_data().get(key)


@cache
def _word_set(key: str) -> frozenset[str]:
    """`phrase_end`, `determiners`, `generic_heads`: see the data's `_about`."""
    return frozenset(w.lower() for w in _kind_words(key) or [])


def quantity_nouns() -> dict[str, frozenset[str]]:
    """noun -> the `claims.unit_dimension` families of the quantity it names.
    A SET: vibration is stated as a velocity (mm/s) or a displacement (um,
    mils), flow as a volume or a mass per time - a noun never refuses a unit
    that gives one of its kinds."""
    return {
        k.lower(): frozenset([v] if isinstance(v, str) else v)
        for k, v in (_kind_words("quantity_nouns") or {}).items()
    }


def _tokens(text: str | None) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def printed_unit(fact: dict) -> str | None:
    """The unit a fact states: its own unit column, or - for a BLANK cell -
    the unit printed beside the empty slot ("_____ m3/h", "____ (%)",
    "____ bar g @ ____ C": the quantity is the part before "@", what follows
    is the condition it is stated at). None when no unit is printed."""
    own = fact.get("raw_unit") or fact.get("unit")
    if own:
        return own
    if not fact.get("is_blank"):
        return None
    from .datasheets import primary_unit

    text = re.sub("[_*.\u2013\u2014-]+", " ", str(fact.get("field_value") or ""))
    text = text.split("@")[0].strip()
    bracket = re.fullmatch(r"\(\s*([^()]+?)\s*\)", text)
    return primary_unit(bracket.group(1) if bracket else text)


#: PHYSICS, NOT WORDS (order 143(3)). One quantity that `claims` files under
#: two dimension names: a speed in kph IS a velocity, and a mass per volume
#: in g/L IS a density.
_SAME_QUANTITY = {"speed": "velocity", "concentration": "density"}
#: A unit that also states another quantity: a length in m is also a
#: pressure stated as head. A pair that meets only through this is unsure,
#: never refused and never sure.
_ALSO_STATED_AS = {"length": "pressure"}


def _unit_kinds(unit: str | None) -> frozenset[str]:
    """The kinds a unit states, after the physics above; empty when the unit
    is not one `claims` gives a dimension (a unit unknown never refuses)."""
    base = claims.base_unit(unit)
    dim = claims.unit_dimension(base) if base else None
    if not dim:
        return frozenset()
    dim = _SAME_QUANTITY.get(dim, dim)
    return frozenset({dim, _ALSO_STATED_AS[dim]} if dim in _ALSO_STATED_AS else {dim})


def _surely(kinds: frozenset[str], source: str | None) -> frozenset[str]:
    """`kinds` without what a unit only ALSO states (head for a length)."""
    if source != "unit":
        return kinds
    return kinds - {also for dim, also in _ALSO_STATED_AS.items() if dim in kinds}


def _phrase_heads(text: str | None) -> set[str]:
    """The kinds named by the quantity nouns that HEAD the leading noun
    phrases of `text` - "the minimum thickness or the maximum allowable
    working pressure of the shell" -> {length, pressure}. A noun phrase ends
    at a preposition or verb; its head is its last word (trailing letters,
    numbers and generic words such as "factor" or "value" skipped)."""
    nouns = quantity_nouns()
    heads: set[str] = set()
    phrase: list[str] = []
    ended = False

    def close():
        words = [
            w
            for w in phrase
            if len(w) > 1 and not w.isdigit() and w not in _word_set("generic_heads")
        ]
        if words and words[-1] in nouns:
            heads.update(nouns[words[-1]])

    for token in _tokens(text):
        if token in _CONJUNCTIONS or token in ("/", ","):
            # "and", "or", and a list: "design pressure / temperature"
            if not ended:
                close()
            phrase, ended = [], False
        elif ended:
            continue
        elif token in _word_set("phrase_end"):
            close()
            ended = True
        elif token[0].isalnum():
            phrase.append(token)
        elif phrase and token not in ("(", ")", "'", "\u2019"):
            # "(h) Maximum bearing stress": a label in brackets is not a
            # phrase boundary; any other punctuation ends the phrase.
            close()
            ended = True
    if not ended:
        close()
    return heads


def requirement_kinds(requirement: dict) -> tuple[frozenset[str], str | None]:
    """`(kinds, source)` of what a requirement constrains. Its OWN unit wins
    ("unit"); a requirement with none is read from the quantity nouns that
    head its subject ("noun"). Empty when it names no quantity."""
    kinds = _unit_kinds(requirement.get("raw_unit") or requirement.get("unit"))
    if kinds:
        return kinds, "unit"
    heads = _phrase_heads(requirement.get("subject"))
    return frozenset(heads), ("noun" if heads else None)


def _field_words(fact: dict) -> list[str]:
    from . import field_links

    name = str(fact.get("field_name") or "")
    return [
        w for w in _tokens(f"{name} {field_links.field_of(name)[0]}") if w[0].isalnum()
    ]


def fact_kinds(fact: dict) -> tuple[frozenset[str], str | None]:
    """`(kinds, source)` of a datasheet value: its unit (incl. the unit a blank
    prints, "unit"), else the quantity nouns of its field name ("noun").
    When the unit is one of several quantities the name lists, the field
    states all of them: a combined "Design pressure / temperature" in barg is
    a temperature field too. A name that disagrees with its unit does not
    widen it - the unit is what was read."""
    return _fact_kinds(fact, sure=False)


def _fact_kinds(fact: dict, *, sure: bool) -> tuple[frozenset[str], str | None]:
    heads = frozenset(_phrase_heads(fact.get("field_name")))
    kinds = _unit_kinds(printed_unit(fact))
    if not kinds:
        return heads, ("noun" if heads else None)
    stated = _surely(kinds, "unit") if sure else kinds
    return (stated | heads if kinds & heads else stated), "unit"


def quantity_kind_conflict(requirement: dict, fact: dict) -> bool:
    """True when both sides name a quantity kind and no kind is shared - a
    flow against a temperature, a pressure against a duration. A percentage
    is relative to ANY quantity ("110 % of the rated flow"), so a percent
    unit on one side never refuses a kind the other side has only by its
    noun; two units still do (rule 1)."""
    kinds, source = requirement_kinds(requirement)
    fact_side, fact_source = fact_kinds(fact)
    if not kinds or not fact_side or kinds & fact_side:
        return False
    return not ("noun" in (source, fact_source) and "percent" in kinds | fact_side)


def _field_place(requirement: dict, fact: dict) -> dict | None:
    """Where the field's own words stand in the requirement's subject, or None
    when its last word is not there (a synonym or a model pairing on an idea):

      * `modifiers` - nouns naming ANOTHER THING whose quantity it is
        (`subject_nouns`: "weld JOINT efficiency", "the efficiency of the
        LIGAMENTS") that the fact's name, label and section do not share;
        adjectives (rated, design) and parts (shaft, casing) never count;
      * `next_word` - a word right after the field's words in the same
        phrase: the field is then a modifier of something else ("bearing
        TEMPERATURE", "bearing SURFACE", "temperature RISE");
      * `late` - the field's words stand only after a preposition, in a
        phrase that is not what the requirement constrains ("the minimum
        wall thickness FOR fittings")."""
    field = _field_words(fact)
    tokens = _tokens(requirement.get("subject"))
    if not field or field[-1] not in tokens:
        return None
    at = _field_end(tokens, fact, field[-1])
    own = set(field) | set(
        _tokens(
            " ".join(
                str(fact.get(k) or "")
                for k in ("field_label", "section", "section_heading")
            )
        )
    )
    subjects = _word_set("subject_nouns")

    def names_another_thing(word: str) -> bool:
        if word in own or word.rstrip("s") in own:
            return False
        return word in subjects or word.rstrip("s") in subjects

    modifiers: set[str] = set()
    for word in reversed(tokens[max(0, at - 6) : at]):
        if (
            not word[0].isalnum()
            or word in _word_set("phrase_end")
            or word in _word_set("determiners")
            or word in _CONJUNCTIONS
        ):
            break
        if _is_word(word) and names_another_thing(word):
            modifiers.add(word)
    after = tokens[at + 1 : at + 4]
    next_word = None
    if after[:1] == ["of"]:
        rest = [w for w in after[1:] if w not in _word_set("determiners")]
        if rest and _is_word(rest[0]) and names_another_thing(rest[0]):
            modifiers.add(rest[0])
    elif (
        after
        and _is_word(after[0])
        and after[0] not in own
        and after[0] not in _word_set("phrase_end")
        and after[0] not in _CONJUNCTIONS
        and after[0] not in _word_set("generic_heads")
        and not claims.is_unit(after[0])
        and not after[0].endswith("ed")  # "set pressure MARKED on the device"
    ):
        next_word = after[0]
    late = any(w in _word_set("phrase_end") for w in tokens[:at]) and not any(
        w in _CONJUNCTIONS for w in tokens[:at]
    )
    return {"modifiers": modifiers, "next_word": next_word, "late": late}


def _field_end(tokens: list[str], fact: dict, head: str) -> int:
    """Index of the field's last word in the subject: the LAST place the
    field's own name stands whole ("the pressure relief device SET PRESSURE"),
    else the last place its last word does."""
    name = [w for w in _tokens(fact.get("field_name")) if w[0].isalnum()]
    n = len(name)
    whole = [
        i + n - 1 for i in range(len(tokens) - n + 1) if n and tokens[i : i + n] == name
    ]
    if whole:
        return whole[-1]
    return len(tokens) - 1 - tokens[::-1].index(head)


def quantity_kind_doubt(requirement: dict, fact: dict | None) -> str | None:
    """QUANTITY_KIND_UNSURE when the pair cannot be shown to be one quantity,
    else None. It HOLDS the verdict for an engineer, whatever paired it; only
    when a side names a kind (two categorical words are not its question):
    the sides meet only through head in m; the subject names another thing
    whose quantity it is (weld JOINT efficiency vs a pump "Efficiency"); the
    field's words modify another word ("bearing TEMPERATURE" vs "Bearing");
    or a field that states no kind stands only after a preposition ("the wall
    thickness FOR fittings")."""
    if fact is None:
        return None
    kinds, source = requirement_kinds(requirement)
    fact_side, fact_source = fact_kinds(fact)
    if not kinds and not fact_side:
        return None
    sure_fact, _ = _fact_kinds(fact, sure=True)
    if (kinds & fact_side) and not (_surely(kinds, source) & sure_fact):
        return QUANTITY_KIND_UNSURE  # they meet only through head in m
    place = _field_place(requirement, fact)
    if place is None:
        return None
    if place["modifiers"]:
        return QUANTITY_KIND_UNSURE
    nxt = place["next_word"]
    if nxt and (
        nxt in quantity_nouns() or nxt in derived_after() or fact_source == "unit"
    ):
        return QUANTITY_KIND_UNSURE
    if kinds and not fact_side and place["late"]:
        return QUANTITY_KIND_UNSURE
    return None


def quantity_kind_reason(requirement: dict, fact: dict) -> str:
    """The plain words of a QUANTITY_KIND_UNSURE hold, for the finding."""
    what = " ".join(str(requirement.get("subject") or "").split())
    what = (what[:120] + "...") if len(what) > 120 else (what or "this requirement")
    label = fact.get("field_label") or fact.get("field_name") or "the field"
    return (
        f"{QUANTITY_KIND_UNSURE}: the requirement is about '{what}' and the datasheet "
        f"field '{label}' may be a different quantity, so its result is set aside"
    )


# ------------------------------------------------------------------ together
# ------------------------------------------- a model pairing's own doubts
#: Why a MODEL-proposed pairing that no rule refuses is still not sure enough
#: to carry a verdict. Each was a FALSE RESULT on the real-model F1 of
#: 2026-10-11 (three model pairings decided, three wrong):
FIELD_WORD_ABSENT = "field_word_absent"      # a mounting distance vs "Elevation"
RELATIVE_LIMIT = "relative_limit"            # "10 C above the pour point" vs a temperature
SEVERAL_VALUES = "several_values"            # a flattened table band vs a temperature

#: Words that, right after a limit, make it relative to ANOTHER quantity or
#: place ("at least 10 C ABOVE THE pour point", "7.5 m BEYOND THE edge").
_RELATIVE_AFTER = (r"(?:above|below|beyond|over|under|higher\s+than|lower\s+than|more\s+than|"
                   r"less\s+than|greater\s+than|from|outside|inside|within)\s+(?:the|its|that|any|each)\b")
_BRACKETS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_LEADING_CLAUSE_NO = re.compile(r"^\s*\d+(?:\.\d+)+\s+")


def _clause_text(requirement: dict) -> str:
    return str(requirement.get("requirement_text") or requirement.get("source_text") or "")


def model_pairing_doubt(requirement: dict, fact: dict) -> str | None:
    """The first doubt about a model-proposed pairing, by name, or None.

    A doubt does not refuse the pairing - it HOLDS its verdict for an
    engineer (planner decision 2026-10-11: a low-confidence proposal waits).
    It errs towards holding: a held true pairing costs a look, a decided
    false one is a false result.

      * a word of the field's own name is not in the clause (the model
        paired on an idea: "corrosion allowance" with every thickness, the
        "operating" pressure with the "allowable working" one). EVERY word
        of four letters or more must be there - one shared word ("pressure",
        "corrosion") was not enough on F1;
      * the limit is relative to another quantity or place;
      * the clause states several values (a table read as one sentence), so
        which one is the limit is a guess.
    """
    text = _clause_text(requirement)
    folded = _normalise(text)
    name_words = [w for w in _words(fact.get("field_name")) if len(w) >= 4]
    if name_words and not all(re.search(rf"(?<!\w){re.escape(w[:5])}", folded) for w in name_words):
        return FIELD_WORD_ABSENT
    value = str(requirement.get("raw_value") or "").strip()
    if value:
        after = re.search(rf"(?<![\w.]){re.escape(value)}(?![\w.]*\d)(.{{0,40}})", text)
        if after and re.search(_RELATIVE_AFTER, _BRACKETS.sub(" ", after.group(1)), re.IGNORECASE):
            return RELATIVE_LIMIT
    bare = _LEADING_CLAUSE_NO.sub("", _BRACKETS.sub(" ", text))
    # numbers read by the ONE number reader (`numparse`), never a pattern here
    from . import numparse
    if len(numparse.number_keys(bare)) > 1:
        return SEVERAL_VALUES
    return None


def refusal(requirement: dict, fact: dict, *, sheet: str | None) -> str | None:
    """The first rule that refuses this pairing, by name, or None to allow it."""
    if unit_dimension_conflict(requirement, fact):
        return UNIT_DIMENSION
    if quantity_kind_conflict(requirement, fact):
        return QUANTITY_KIND
    if equipment_domain_conflict(requirement, sheet):
        return EQUIPMENT_DOMAIN
    if table_lookup_input_conflict(requirement, fact.get("field_name") or ""):
        return TABLE_LOOKUP_INPUT
    if compound_term_conflict(fact.get("field_name") or "", requirement):
        return COMPOUND_TERM
    if qualifier_conflict(requirement, fact.get("field_name") or ""):
        return QUALIFIER
    return None
