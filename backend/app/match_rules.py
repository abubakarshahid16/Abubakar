"""Rules that decide WHICH containment hit a requirement may be paired with.

WHY THIS EXISTS. `comparison.match_by_containment` joins a requirement to a
datasheet field by whole-word containment and resolves ties by "longest field
name wins". Measured on `gold/PAIRS-216400C.csv` that made 8 pairings, of which
0 were right and 8 were FALSE - every one a real clause number and a real page
attached to a number the clause was not about:

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

import re

from . import claims

# ------------------------------------------------------------------ reasons
#: Why a containment hit was refused. Every refusal carries one of these so a
#: run can report how many pairings each rule removed, and a rule that removes
#: a correct pairing can be found by its name rather than by reading findings.
UNIT_DIMENSION = "unit_dimension"
EQUIPMENT_DOMAIN = "equipment_domain"
TABLE_LOOKUP_INPUT = "table_lookup_input"

REASONS: tuple[str, ...] = (UNIT_DIMENSION, EQUIPMENT_DOMAIN, TABLE_LOOKUP_INPUT)

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
def _unit_of(row: dict) -> str:
    base, _reference = claims.split_reference(row.get("raw_unit") or row.get("unit"))
    return base or ""


def unit_dimension_conflict(requirement: dict, fact: dict) -> bool:
    """True when the two units cannot be about the same quantity.

    Both dimensions known and different: a pressure against a temperature.
    Exactly one known and the other spelling not a unit at all: `°C` against
    `ohm-cm`. Everything else is left alone - `compare` has the last word on
    whether two numbers can actually be compared.
    """
    left, right = _unit_of(requirement), _unit_of(fact)
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
    return claims._fold_unit(unknown) not in claims._RECOGNISED_UNITS


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
    # `name + " "`: the field must be followed by MORE header. A header that
    # is the field alone names one quantity and has no input column.
    return _normalise(requirement.get("subject") or "").startswith(name + " ")


# ------------------------------------------------------------------ together
def refusal(requirement: dict, fact: dict, *, sheet: str | None) -> str | None:
    """The first rule that refuses this pairing, by name, or None to allow it."""
    if unit_dimension_conflict(requirement, fact):
        return UNIT_DIMENSION
    if equipment_domain_conflict(requirement, sheet):
        return EQUIPMENT_DOMAIN
    if table_lookup_input_conflict(requirement, fact.get("field_name") or ""):
        return TABLE_LOOKUP_INPUT
    return None
