"""One figure against one clause figure, decided by CODE (Part of #805, step 3: the AI senior review).

The AI senior review (`ai_senior_review`, later PRs) reads a document and a clause and quotes both. It may SAY a value meets a limit; it
never decides it. This module is the only place that turns two verified quotes into True / False / "cannot compare":

  * the clause's figure and unit come from the CLAUSE QUOTE, the document's figure from the DOCUMENT QUOTE, both through the comparison
    module's own readers (`claims.extract_measurements`, `comparators.direction_of`). A figure the model gives separately is never used;
  * the direction ("not more than", "at least") is read by `comparators.direction_of`, which holds a negated phrase it cannot read
    (both directions -> None). No direction -> no verdict;
  * units are converted by `claims` (decimal commas, kPa / bar / psi, gauge and absolute kept apart); a different kind of quantity, or
    gauge against absolute, is not compared;
  * the DOCUMENT quote must be one plain value: a range, a tolerance, a comparator-qualified value ("max 10 bar"), several figures, a
    placeholder ("By Contractor", "TBA", "n/a", "not ...") or a negation is refused;
  * a value equal to a STRICT limit ("less than 10 bar", 10 bar printed) is not decided: the verdict is None;
  * more than one clause figure of the same kind, or more than one kind of clause figure, is not decided.

SUBJECT: this module does NOT match subjects. The caller must guarantee that the clause and the document figure are about the SAME
quantity (the same pressure, the same temperature, the same item); a verdict says only that two figures stand in the stated relation.
A `None` or a "cannot decide" result is "engineer to check", never a pass.

READING IS A WHITELIST: the clause decides only with a requirement marker (shall, must, at least ...) and no permission or option
wording (may, allowed, need not ...); the document quote decides only as a bare value or a short label with a delimiter (or "is / are /
of") before the figure, and with no status word (draft, superseded, estimated ...). Anything else is "cannot decide".

CLOSED VOCABULARY: after every other guard, each word of the clause sentence and each word of the document LABEL must belong to the closed
vocabulary below (function words, comparator and requirement words, plain physical-quantity and equipment-property nouns, unit words). A
word outside it ("suggested", "advised", "rejected", "alternative", "option", ...) means "cannot decide": the pair goes to the engineer. The
older blacklists stay as an extra net. A gap in the vocabulary costs a decision, never a wrong one.

KNOWN LIMITS (stated plainly): the subject pairing is the CALLER'S job. Labels such as operating, startup, upset, trip, alarm, setpoint,
test, hydrotest, shutoff, standby, another unit's value, "Test pressure" against a design figure, and "%" of WHAT, are NOT distinguished
here. This module compares two figures; it does not know which quantity each one is. "Cannot decide" and None are engineer-to-check.

Pure: no model, no database, no network. `None` from `compare` means "the clause quote asks no figure": the caller decides whether a text
requirement applies. A verdict of None inside a result means "asked a figure, could not decide": the row stays unclear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import blank_markers, claims, comparators

_NEGATED = re.compile(
    r"\b(?:not|no|none|nil|without|excluded|exclud\w*|omitted|deleted|void|spare|by\s+others|n/?a)\b",
    re.IGNORECASE,
)
_STRICT = re.compile(
    r"[<>]|less than|greater than|more than|higher than|lower than|below|above|under|over|exceed",
    re.IGNORECASE,
)
_NOT_STRICT = re.compile(
    r"or equal|at least|at most|not (?:more|less|greater|higher|lower|exceed)|no (?:more|less|greater)|minimum|maximum|≤|≥",
    re.IGNORECASE,
)
_EQUAL_TOLERANCE = 0.005

# --- refusals of anything the code cannot read with certainty (#1689 review): each returns "cannot decide", never a verdict ---
# A negated COMPARATOR ("not more than") is a direction the comparison module reads; these are removed before looking for any other negation.
_NEGATED_COMPARATOR = re.compile(
    r"\b(?:not|no)\s+(?:to\s+)?(?:be\s+)?(?:more|less|greater|higher|lower|smaller|larger|fewer|below|above|under|over|exceed\w*)\b",
    re.IGNORECASE,
)
_ANY_NEGATION = re.compile(
    r"\b(?:not|no|nor|never|neither|none|without|cannot|prohibit\w*|forbid\w*|forbidden|unacceptable|inadmissible|disallow\w*|reject\w*|banned)\b|n't\b",
    re.IGNORECASE,
)
# a single separator followed by exactly three digits ("1.500", "1,500") may be a thousands separator or a decimal: not read.
_AMBIGUOUS_SEPARATOR = re.compile(r"(?<![\d.,])[1-9]\d{0,2}[.,]\d{3}(?!\d)")
_QUALIFIER = re.compile(
    r"\b(?:min|minimum|max|maximum|approx\w*|about|around|circa|ca|abt|typ|typical\w*|nominal|nom|up\s+to|at\s+least|at\s+most|"
    r"less|more|greater|higher|lower|above|below|over|under|exceed\w*|limit|rated|average|mean)\b|[~\u2248\u00b1<>\u2264\u2265]",
    re.IGNORECASE,
)
_EXCEPTION = re.compile(
    r"\b(?:as\s+agreed|agreed|except\w*|unless|where|wherever|when|whenever|whereas|while|if|provided|subject\s+to|otherwise|other\s+than|"
    r"apart\s+from|excluding|only\s+for|in\s+case|in\s+which\s+case|depending|according\s+to|as\s+per|per\s+\w+\s+approval|by\s+agreement|approved\s+by)\b",
    re.IGNORECASE,
)
_CONDITION_FIGURE = re.compile(
    r"\b(?:for|at|with|in|on|from|beyond)\b[^,;.]{0,60}?\b(?:above|below|over|under|exceeding|greater\s+than|more\s+than|less\s+than|higher\s+than|lower\s+than)\b",
    re.IGNORECASE,
)
_REQUIREMENT_VERB = re.compile(
    r"\b(?:is|are|shall|must|should|required|be|to\s+be|will)\b", re.IGNORECASE
)
_DIRECTION_WORD = re.compile(
    r"(?P<le>\bnot\s+(?:to\s+)?(?:be\s+)?(?:exceed\w*|more|greater|higher|larger|above|over)\b|\bno\s+(?:more|greater|higher|larger)\b|"
    r"\bat\s+most\b|\bmost\b|\bor\s+(?:less|lower)\b|\bmax(?:imum)?\b|\bup\s+to\b|\bless\s+than\b|\blower\s+than\b|\bsmaller\s+than\b|\bbelow\b|\bunder\b|<=|\u2264|<)"
    r"|(?P<ge>\bnot\s+(?:to\s+)?(?:be\s+)?(?:less|lower|smaller|below|under)\b|\bno\s+(?:less|lower|smaller)\b|\bat\s+least\b|\bleast\b|\bor\s+(?:more|greater|higher)\b|\bmin(?:imum)?\b|"
    r"\bgreater\s+than\b|\bmore\s+than\b|\bhigher\s+than\b|\babove\b|\bover\b|\bexceed\w*|>=|\u2265|>)",
    re.IGNORECASE,
)
_REF_UNIT = r"(?:bar|mbar|psi|kpa|mpa|pa|atm|torr|kgf?/cm2|kg/cm\u00b2)"
_REF_AFTER_UNIT = re.compile(
    rf"\b{_REF_UNIT}\s*[(\[]?\s*(?P<r>g|ga|gage|gauge|a|abs|absolute)\b", re.IGNORECASE
)
_REF_GLUED = re.compile(r"\b(?:bar|psi|kpa|mpa|pa|mbar)(?P<r>g|a)\b", re.IGNORECASE)
_REF_WORD = re.compile(r"\b(?P<r>gauge|gage|absolute|abs)\b", re.IGNORECASE)
_REF_PAREN = re.compile(r"\((?P<r>g|a)\)", re.IGNORECASE)


def _pressure_references(text: str) -> set[str]:
    """Which pressure references ('g', 'a') the text states, in any spelling."""
    found: set[str] = set()
    for rx in (_REF_AFTER_UNIT, _REF_GLUED, _REF_WORD, _REF_PAREN):
        for m in rx.finditer(text):
            found.add("g" if m.group("r").lower().startswith("g") else "a")
    return found


# --- whitelist reading (#1689 second review): the figure is decided only when NOTHING unread stands beside it ---
_FIGURE_UNIT = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?P<unit>[A-Za-z\u00b5\u00b0%\u03a9][A-Za-z\u00b5\u00b0%\u03a9\u00b2\u00b3/\d]*)"
)
_SIGN_WORD = re.compile(
    r"\b(?:minus|negative|plus|sub-?zero|(?:below|under)\s+zero)\b", re.IGNORECASE
)
_REFERENCE_TOKEN = re.compile(
    r"^\s*\(?\s*\b(?:g|ga|gage|gauge|a|abs|absolute)\b\s*\)?", re.IGNORECASE
)
# structural guard: a sign character glued to the figure or one token before it ("+10", "- 10", "\u00b110") is an offset or a sign the code does
# not read. (A digit group beside the figure, "1 000", is caught by the one-number rule.)
_SIGN_BEFORE = re.compile(r"[+\-\u2212\u2013\u2014\u00b1]\s*$")
_MEGA_OK = re.compile(r"^MPa[ga]?$")
# an approximation word before or after the CLAUSE figure (the document side has its own, wider, list)
_APPROXIMATION = re.compile(
    r"\b(?:approx\w*|about|around|circa|ca|abt|typ|typical\w*|nominal|nom|average|mean)\b|[~\u2248\u00b1]",
    re.IGNORECASE,
)
_CLOSER = re.compile(
    r"\b(?:or\s+(?:more|less|greater|higher|lower)|minimum|maximum|min|max|(?:is\s+|are\s+)?required)\b",
    re.IGNORECASE,
)
_OR_CLOSER = re.compile(r"or\s+(?:more|less|greater|higher|lower)$", re.IGNORECASE)
# one-number rule: the clause and the document quote each hold exactly ONE number (digit run, or number word); a second number
# anywhere is a condition, a class, a count, a product or a power the code does not read. Superscript digits and ^ x * are never read.
_NUMBER_TOKEN = re.compile(r"[\d\u00bc-\u00be\u2150-\u218f\u2460-\u24ff]+(?:[.,]\d+)?")
_NUMBER_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|half|twice|double|triple|dozen|pair)\b",
    re.IGNORECASE,
)
_OPERATOR_OR_POWER = re.compile(
    r"[\^\u00d7*\u00b2\u00b3\u00b9\u2070-\u2079\u2080-\u2089]"
)
# advisory and hedge words: a recommendation is not a requirement, an estimate is not a figure
_HEDGE = re.compile(
    r"\b(?:should|preferably|prefer\w*|recommend\w*|may|might|can|could|would|typically|normally|generally|usually|ordinarily|ideally|"
    r"desirable|about|around|circa|approx\w*|nominal|typical\w*|up\s+to)\b|\bc\.",
    re.IGNORECASE,
)
# lead-in rule: what stands before the comparator is a plain subject phrase, not a condition
_STARTS_WITH_CONDITION = re.compile(
    r"^\W*(?:for|in|on|at|with|during|when|where|whenever|if|under|upon|after|before|while|unless|until|as|by|from|of|without|per|"
    r"within|between|among|except|provided|subject)\b",
    re.IGNORECASE,
)
_LEAD_IN_BREAK = re.compile(r"[,;:()\[\]{}]|\.\s")
_LEAD_IN_WORDS = 6
# document side: a bare value, or a short plain label then a delimiter (or a copula) then the figure; never a status word
_DOCUMENT_DELIMITER = re.compile(
    r"\s*[:=|\t]\s*"
)  # a dash is not one: before a figure it may be a minus sign
_LABEL_WORDS = 4
_PLAIN_LABEL = re.compile(r"^[^\W\d_]+(?: [^\W\d_]+)*$")
_COPULA_LABEL = re.compile(
    r"^(?P<label>[^\W\d_]+(?: [^\W\d_]+)*) (?:is|are|of)$", re.IGNORECASE
)
_STATUS_WORD = re.compile(
    r"\b(?:superseded|previous\w*|former\w*|old|obsolete|void\w*|cancel\w*|estimat\w*|draft|proposed|target|was|were|expected|"
    r"assumed|pending|likely|planned|provisional|tentative|preliminary|future|revised\s+from)\b",
    re.IGNORECASE,
)
# clause side: a requirement marker is needed, option and permission wording is refused
_REQUIREMENT_MARKER = re.compile(
    r"\b(?:shall|must|required|requires|is\s+to\s+be|are\s+to\s+be|maximum|minimum|at\s+least|at\s+most|not\s+more\s+than|"
    r"not\s+less\s+than|no\s+more\s+than|no\s+less\s+than|not\s+(?:higher|lower|greater|smaller|larger)\s+than|not\s+(?:to\s+)?exceed\w*|"
    r"not\s+be\s+(?:less|more)\s+than|limited\s+to)\b",
    re.IGNORECASE,
)
_PERMISSION_OR_OPTION = re.compile(
    r"\b(?:allowed|permitted|permissible|optional|may|can|could|need\s+not|needs\s+not|does\s+not\s+need|not\s+required|"
    r"not\s+necessary|unnecessary|expected|intended|assumed|anticipated|was|were|would|preferably|unless\s+otherwise)\b",
    re.IGNORECASE,
)
_FUNCTION_WORDS = (
    "the a an of to be is are shall must not no than or and at in for on per by with as any each all every it its this that such being "
    "been have has equal equals same"
)
_COMPARATOR_WORDS = (
    "least most more less greater lower higher larger smaller exceed exceeds exceeding exceeded above below under over maximum minimum "
    "max min required requires require requirement limited limit limits upper"
)
_QUANTITY_WORDS = (
    "pressure pressures temperature temperatures design designed operating working set rated allowable test hydrostatic hydrotest relief "
    "valve valves vessel vessels pipe pipes piping wall thickness corrosion allowance diameter size sizes flow rate capacity speed power "
    "head level length width height depth mass weight density viscosity material class rating stress load torque voltage current frequency "
    "time period interval number value values body bonnet seat stem disc plug ball gate globe check butterfly flange flanges bolt bolts bolting "
    "gasket nut stud washer face facing rating ratings nozzle nozzles shell tube tubes tubing plate plates sheet pump pumps motor motors "
    "compressor fan blower turbine engine generator transformer cable cables wire wires conductor insulation cooling heating heater heaters "
    "cooler coolers exchanger exchangers tank tanks drum drums column columns tower towers line lines duct ducts hose hoses nominal bore "
    "internal external inside outside inner outer minimum maximum average total net gross overall effective actual process service fluid "
    "fluids liquid liquids gas gases steam water air oil fuel medium media product capacity volume volumes area areas surface surfaces "
    "roughness hardness strength yield tensile impact energy force forces resistance conductivity capacitance inductance impedance "
    "noise vibration sound level levels leakage leak leaks tightness seal seals sealing gland packing bearing bearings shaft shafts coupling "
    "couplings gear gears brake brakes clutch spring springs actuator actuators positioner positioners signal signals loop loops range "
    "ranges span accuracy repeatability response stroke travel opening closing closure shutoff cycle cycles life service duty rate rates "
    "efficiency losses loss drop differential delta rise increase change distance spacing clearance gap pitch thread threads depth "
    "coating coatings paint thick film layer layers lining liners liner weld welds welding joint joints connection connections size "
    "rated working operating maximum allowable pressure point points position positions angle angles slope grade grades grade "
    "composition content contents concentration chloride chlorides sulphur sulfur carbon ph table humidity moisture dew ambient site "
    "elevation altitude wind snow seismic zone area rating protection ingress enclosure degree degrees ip velocity finish dry duration supply output throat bend radius flush runout tolerance acceleration "
    "displacement amplitude lift gap flow discharge suction inlet outlet vent drain stress strain elongation reduction fatigue creep "
    "hole holes thread engagement"
)
_UNIT_WORDS = (
    "bar mbar psi kpa mpa pa atm mm cm m km kg g gram grams tonne tonnes degc degf celsius fahrenheit kelvin percent hz khz kw w mw v kv a "
    "ma ka ohm ohms litre litres liter liters hour hours minute minutes second seconds day days year years rpm gauge gage absolute abs ga "
    "barg bara psig psia metre metres meter meters inch inches foot feet newton newtons joule joules watt watts volt volts amp amps"
)
_VOCABULARY = frozenset(
    (
        _FUNCTION_WORDS
        + " "
        + _COMPARATOR_WORDS
        + " "
        + _QUANTITY_WORDS
        + " "
        + _UNIT_WORDS
    ).split()
)
_WORD = re.compile(r"[^\W\d_]+")


def _in_vocabulary(word: str) -> bool:
    word = word.lower()
    return (
        word in _VOCABULARY
        or (word.endswith("s") and word[:-1] in _VOCABULARY)
        or (word.endswith("es") and word[:-2] in _VOCABULARY)
    )


def unknown_words(text: str) -> list[str]:
    """The words of `text` (its figure and unit left out) that are not in the closed vocabulary."""
    return [
        w for w in _WORD.findall(_FIGURE_UNIT.sub(" ", text)) if not _in_vocabulary(w)
    ]


_PUNCTUATION_ONLY = re.compile(r"^[\s)\]\[(.,;:]*$")


def _tail_after_figure(text: str, closers: bool) -> str | None:
    """What stands after the LAST figure+unit, once the unit's reference and (for a clause) a closed set of closers are removed.
    None when there is no figure+unit; anything but punctuation left over means unread text sits beside the figure."""
    found = list(_FIGURE_UNIT.finditer(text))
    if not found:
        return None
    tail = text[found[-1].end() :]
    if closers:
        tail = _CLOSER.sub(" ", tail)
    if claims.unit_dimension(found[-1].group("unit")) == "pressure":
        tail = _REFERENCE_TOKEN.sub(" ", tail, count=1)
    return tail


def _figure_token_refusal(text: str) -> str | None:
    """The figure is not one clean token (a digit group or a sign beside it) or its unit is spelled in a case that changes its meaning."""
    for m in _FIGURE_UNIT.finditer(text):
        before = text[: m.start()]
        if _SIGN_BEFORE.search(before):
            return "a sign stands beside the figure (an offset or a negative value)"
        unit = m.group("unit")
        if ("M" in unit or unit.lower().startswith("mpa")) and not _MEGA_OK.match(unit):
            return "the unit's letter case may change its meaning (m / M)"
    return None


def _structure_refusal(text: str) -> str | None:
    """More than one number, a power or product mark, or an advisory word anywhere in the quote."""
    rest = _FIGURE_UNIT.sub(" N ", text)
    if _OPERATOR_OR_POWER.search(rest):
        return "a power, a product mark or a superscript digit stands near the figure"
    numbers = len(_NUMBER_TOKEN.findall(rest)) + len(_NUMBER_WORD.findall(rest))
    numbers += rest.count(" N ")
    if numbers != 1:
        return "the quote holds no figure or more than one number (a class, a count, a product or a condition)"
    if _HEDGE.search(text):
        return "the quote holds an advisory or hedge word (should, may, about ...)"
    return None


def _lead_in_refusal(clause: str) -> str | None:
    figure_start = _FIGURE_UNIT.search(clause).start()
    word = _DIRECTION_WORD.search(clause)
    lead = clause[: min(figure_start, word.start()) if word else figure_start]
    if (
        _LEAD_IN_BREAK.search(lead)
        or len(lead.split()) > _LEAD_IN_WORDS
        or _STARTS_WITH_CONDITION.match(lead)
    ):
        return "the clause starts with a condition or a long or split lead-in"
    return None


def _whitelist_refusal(text: str, clause: bool) -> str | None:
    refusal = _structure_refusal(text)
    if refusal:
        return refusal
    refusal = _figure_token_refusal(text)
    if refusal:
        return refusal
    if _SIGN_WORD.search(text):
        return "a sign is written in words (minus, negative, plus): not read"
    tail = _tail_after_figure(text, closers=clause)
    if tail is None or not _PUNCTUATION_ONLY.match(tail):
        return "text or a mark stands after the figure and its unit that the code does not read"
    if clause:
        return _lead_in_refusal(text)
    return None


def _clause_refusal(clause: str) -> str | None:
    """Why the CLAUSE quote cannot be read with certainty, or None."""
    if _PERMISSION_OR_OPTION.search(clause):
        return "the clause is worded as a permission or an option, not a requirement"
    if not _REQUIREMENT_MARKER.search(clause):
        return "the clause has no requirement marker (shall, must, at least ...)"
    if _ANY_NEGATION.search(_NEGATED_COMPARATOR.sub(" ", clause)):
        return "the clause holds a negation or a prohibition the code does not read"
    if _AMBIGUOUS_SEPARATOR.search(clause):
        return (
            "a clause figure has a separator that may be a thousands mark or a decimal"
        )
    stripped = _NEGATED_COMPARATOR.sub(" ", clause)
    if _EXCEPTION.search(clause) or _CONDITION_FIGURE.search(stripped):
        return "the clause holds an exception or a condition the figure may belong to"
    head, sep, tail = clause.partition(",") if "," in clause else clause.partition(";")
    if sep and re.search(r"\d", head) and _REQUIREMENT_VERB.search(tail):
        return "the figure may belong to a condition before a separate requirement"
    if _APPROXIMATION.search(clause):
        return "the clause figure carries an approximation word"
    refusal = _whitelist_refusal(clause, clause=True)
    if refusal:
        return refusal
    figure_end = list(_FIGURE_UNIT.finditer(clause))[-1].end()
    phrases = [
        m
        for m in _DIRECTION_WORD.finditer(clause)
        if not (m.start() >= figure_end and _OR_CLOSER.match(m.group(0)))
    ]
    kinds = {
        k for m in _DIRECTION_WORD.finditer(clause) for k in ("le", "ge") if m.group(k)
    }
    if len(kinds) > 1 or len(phrases) > 1:
        return "the clause holds two directions or a split comparator phrase"
    if unknown_words(clause):
        return "the clause holds a word outside the closed vocabulary"
    return None


def _document_lead_in_refusal(text: str) -> str | None:
    """The document figure decides only as a bare value, or after a short plain label and a delimiter or a copula."""
    found = _FIGURE_UNIT.search(text)
    if found is None:
        return None
    lead = text[: found.start()].strip()
    if not lead:
        return None
    parts = _DOCUMENT_DELIMITER.split(text[: found.start()])
    if len(parts) > 1 and parts[-1] == "":
        cells = parts[:-1]
        if all(_PLAIN_LABEL.match(c) and len(c.split()) <= _LABEL_WORDS for c in cells):
            return None
    copula = _COPULA_LABEL.match(lead)
    if copula and len(copula.group("label").split()) <= _LABEL_WORDS:
        return None
    return (
        "a word stands before the document figure that is not a label with a delimiter"
    )


def _document_refusal(text: str) -> str | None:
    """Why the DOCUMENT quote is not one plain, certain value, or None."""
    if _AMBIGUOUS_SEPARATOR.search(text):
        return "the document figure has a separator that may be a thousands mark or a decimal"
    if _QUALIFIER.search(text):
        return "the document figure carries a qualifier (min, max, approx, typical ...)"
    if _STATUS_WORD.search(text):
        return (
            "the document quote holds a status word (draft, superseded, estimated ...)"
        )
    refusal = _document_lead_in_refusal(text)
    if refusal:
        return refusal
    refusal = _whitelist_refusal(text, clause=False)
    if refusal:
        return refusal
    if unknown_words(text):
        return "the document label holds a word outside the closed vocabulary"
    return None


@dataclass(frozen=True)
class FigureResult:
    """`verdict` True: the document figure satisfies the clause; False: it breaks it; None: asked a figure, cannot decide (`reason` says why)."""

    verdict: bool | None
    reason: str
    direction: str | None = None


def _undecided(reason: str, direction: str | None = None) -> FigureResult:
    return FigureResult(None, reason, direction)


def compare(document_quote: str, clause_quote: str) -> FigureResult | None:
    """Decide the document quote against the clause quote, or None when the clause quote asks no figure."""
    clause_figures = [
        m
        for m in claims.extract_measurements(clause_quote or "")
        if m.normalized_value is not None
    ]
    if not clause_figures:
        return None
    if len({m.dimension for m in clause_figures}) != 1:
        return _undecided("the clause asks more than one kind of figure")
    if len({round(m.normalized_value, 9) for m in clause_figures}) != 1:
        return _undecided("the clause holds more than one figure of that kind")
    asked = clause_figures[0]
    direction = comparators.direction_of(clause_quote) or next(
        (m.comparator for m in clause_figures if m.comparator in (">=", "<=", "=")),
        None,
    )
    if direction not in (">=", "<=", "="):
        return _undecided("the clause gives no readable comparator", None)
    refusal = _clause_refusal(clause_quote)
    if refusal:
        return _undecided(refusal, direction)
    text = document_quote or ""
    refusal = _document_refusal(text)
    if refusal:
        return _undecided(refusal, direction)
    if asked.dimension == "pressure":
        stated = (_pressure_references(text), _pressure_references(clause_quote))
        if (stated[0] or stated[1]) and (stated[0] != stated[1] or len(stated[0]) != 1):
            return _undecided("gauge and absolute pressure are not compared", direction)
    if blank_markers.names_a_marker(text) or _NEGATED.search(text):
        return _undecided(
            "the document quote is a placeholder or a negation", direction
        )
    printed = [
        m
        for m in claims.extract_measurements(text)
        if m.normalized_value is not None and m.dimension == asked.dimension
    ]
    if len(printed) != 1:
        return _undecided(
            "the document figure is not the same kind of quantity as the clause figure",
            direction,
        )
    value = printed[0]
    if value.comparator:
        return _undecided(
            "the document figure is itself a limit or a range, not a plain value",
            direction,
        )
    a, b = value.normalized_value, asked.normalized_value
    tolerance = 1e-6 * max(abs(b), 1.0)
    if (
        abs(a - b) <= tolerance
        and _STRICT.search(clause_quote)
        and not _NOT_STRICT.search(clause_quote)
    ):
        return _undecided("equal to a strict limit: not decided by code", direction)
    ok = {
        ">=": a >= b - tolerance,
        "<=": a <= b + tolerance,
        "=": abs(a - b) <= max(tolerance, _EQUAL_TOLERANCE * abs(b)),
    }[direction]
    return FigureResult(
        ok,
        f"{value.raw_value} {value.raw_unit} against {direction} {asked.raw_value} {asked.raw_unit}",
        direction,
    )
