"""Table and formula rules, evaluated in code (owner order 2026-09-26, 2a + 2b).

THE CASE. A standard sets design pressure from the maximum operating pressure
with a range table - "up to X: MOP + c; over X up to Y: the greater of k x MOP
and MOP + c". The comparison engine typed it `table_row`, found no single
limit, and sent it to an engineer as NEEDS_ENGINEER_REVIEW - and paired it
against the MAXIMUM OPERATING PRESSURE field, which is the rule's INPUT, not
the value it judges.

WHAT THIS MODULE IS. Pure: no database, no model, no network.
  * `evaluate(rule, input, output)` - the arithmetic. Find the row the input
    falls in, compute the required output (max/min of linear terms), compare.
    Unknown structure, a unit that does not convert, or an input outside
    every row returns a result that says so - NEVER a guessed verdict.
  * `parse_rule(text)` - a small code grammar for the common row shapes.
    Returns None when the text does not parse (the requirement stays with an
    engineer).
  * `verify_numbers(rule, text)` - the gate for a rule the MODEL parsed: every
    number in it must appear verbatim in the clause or table text on its page
    (the rule the deleted CRS-comment gate used). The arithmetic is always Python.

2b, THE RIGHT FIELD. `judge` pairs the rule's OUTPUT field for the verdict and
records the INPUT used. Output absent -> MISSING_INFORMATION ("design pressure
not stated"); input absent -> the required value cannot be calculated, so an
engineer decides. The input is never compared against the rule. A field the
datasheet states twice with DIFFERENT values is a conflict, not an absence:
NEEDS_ENGINEER_REVIEW, every value named with its page.

A rule is written as data:

    {"output": "design pressure", "input": "operating pressure",
     "input_names": ["mop", "maximum operating pressure", "operating pressure"],
     "unit": "kPa", "comparator": ">=",
     "rows": [{"from": null, "to": 1800, "op": "single", "terms": [{"k": 1, "c": 170}]},
              {"from": 1800, "to": 6900, "op": "max",
               "terms": [{"k": 1.1, "c": 0}, {"k": 1, "c": 170}]}]}

A row covers input in (from, to]; `null` is open.
"""
from __future__ import annotations

import json
import re

from . import claims, numparse

import logging

_log = logging.getLogger(__name__)

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"
MISSING_INFORMATION = "MISSING_INFORMATION"

RULE_REASON = "RULE_EVALUATED"
SOURCE_CODE = "code"
SOURCE_MODEL = "model_parsed_verified"

_CMP = {">=": lambda a, b: a >= b - 1e-9, "<=": lambda a, b: a <= b + 1e-9}


# ------------------------------------------------------------ arithmetic

_BASIS = re.compile(r"^(?P<base>.*?)\s*(?:\(\s*(?P<p>[ga])\s*\)|(?P<s>[ga]))$", re.IGNORECASE)


def _split_basis(unit: str) -> tuple[str, str]:
    """("bar", "g") for "barg" / "bar(g)" / "bar g"; ("kPa", "") when unstated.
    Only a PRESSURE unit carries a gauge/absolute basis."""
    text = (unit or "").strip()
    m = _BASIS.match(text)
    if m and m.group("base") and claims.unit_dimension(m.group("base").strip()) == "pressure":
        return m.group("base").strip(), (m.group("p") or m.group("s")).lower()
    return text, ""


def _to_base(value: float, unit: str) -> tuple[float, str] | None:
    base_unit, _basis = _split_basis(unit)
    m = claims.normalise(repr(value), base_unit)
    if m.normalized_value is None or not m.normalized_unit:
        return None
    return float(m.normalized_value), m.normalized_unit


def _fmt(x: float) -> str:
    return f"{round(x, 6):,.6g}"


def required_for(rule: dict, input_value: float) -> tuple[float, dict] | None:
    """(required output in the rule's unit, the row used), or None if no row."""
    for row in rule["rows"]:
        lo, hi = row.get("from"), row.get("to")
        if (lo is None or input_value > lo) and (hi is None or input_value <= hi):
            values = [t.get("k", 1) * input_value + t.get("c", 0) for t in row["terms"]]
            op = row.get("op", "single")
            if op == "max":
                return max(values), row
            if op == "min":
                return min(values), row
            if len(values) != 1:
                return None
            return values[0], row
    return None


def _row_words(row: dict, unit: str) -> str:
    lo, hi = row.get("from"), row.get("to")
    if lo is None:
        return f"up to {_fmt(hi)} {unit}"
    if hi is None:
        return f"over {_fmt(lo)} {unit}"
    return f"over {_fmt(lo)} up to {_fmt(hi)} {unit}"


def evaluate(rule: dict, input_value: float, input_unit: str,
             output_value: float, output_unit: str) -> dict | None:
    """The verdict of `rule` for these datasheet values. None: structure unknown.

    Both values are converted into the rule's unit through the unit table;
    a unit that does not convert makes no comparison (NEEDS_ENGINEER_REVIEW).
    """
    try:
        unit = rule["unit"]
        rows = rule["rows"]
        comparator = rule.get("comparator", ">=")
    except (KeyError, TypeError):
        return None
    if not rows or comparator not in _CMP:
        return None
    base_rule = _to_base(1.0, unit)
    base_in = _to_base(float(input_value), input_unit)
    base_out = _to_base(float(output_value), output_unit)
    # GAUGE AGAINST ABSOLUTE IS NOT ONE SCALE. The two datasheet values must
    # share a basis; a table that states none is read on the datasheet's
    # gauge basis and the rationale SAYS so (a guess shown as a guess). An
    # absolute datasheet value against an unstated table basis is not read.
    b_rule, b_in, b_out = (_split_basis(u)[1] for u in (unit, input_unit, output_unit))
    basis_note = ""
    if b_in != b_out or (b_rule and b_rule != b_in) or (not b_rule and b_in == "a"):
        return {"status": NEEDS_ENGINEER_REVIEW, "required_value": None,
                "input_used": f"{_fmt(input_value)} {input_unit}",
                "output_checked": f"{_fmt(output_value)} {output_unit}", "rows_used": None,
                "rationale": (f"{RULE_REASON}: gauge and absolute pressures ({input_unit}, "
                              f"{output_unit}, table in {unit}) are not one scale; nothing "
                              "was compared")}
    elif not b_rule and b_in == "g":
        basis_note = f" (the table's {unit} read as gauge, as the datasheet's values are)"
    if base_rule is None or base_in is None or base_out is None \
            or not (base_rule[1] == base_in[1] == base_out[1]):
        return {"status": NEEDS_ENGINEER_REVIEW, "required_value": None,
                "input_used": f"{_fmt(input_value)} {input_unit}",
                "output_checked": f"{_fmt(output_value)} {output_unit}", "rows_used": None,
                "rationale": (f"{RULE_REASON}: the datasheet's units ({input_unit}, {output_unit}) "
                              f"do not convert to the rule's unit ({unit}); nothing was compared")}
    scale = base_rule[0]
    x_in, x_out = base_in[0] / scale, base_out[0] / scale
    found = required_for(rule, x_in)
    if found is None:
        return {"status": NEEDS_ENGINEER_REVIEW, "required_value": None,
                "input_used": f"{_fmt(input_value)} {input_unit}",
                "output_checked": f"{_fmt(output_value)} {output_unit}", "rows_used": None,
                "rationale": (f"{RULE_REASON}: {rule.get('input', 'the input')} "
                              f"{_fmt(input_value)} {input_unit} is outside every row of the "
                              f"rule's table; an engineer decides")}
    required, row = found
    ok = _CMP[comparator](x_out, required)
    word = "at least" if comparator == ">=" else "at most"
    rationale = (
        f"{RULE_REASON}: required {rule.get('output', 'value')} {word} {_fmt(required)} {unit} "
        f"from {rule.get('input', 'the input')} {_fmt(input_value)} {input_unit} "
        f"(table row: {_row_words(row, unit)}); the datasheet says "
        f"{_fmt(output_value)} {output_unit}{basis_note}")
    return {"status": COMPLIANT if ok else NON_COMPLIANT, "required_value": required,
            "input_used": f"{_fmt(input_value)} {input_unit}",
            "output_checked": f"{_fmt(output_value)} {output_unit}",
            "rows_used": [_row_words(row, unit)], "rationale": rationale}


# ---------------------------------------------------------------- parsing

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_UNIT = r"([a-zA-Z°]+[a-zA-Z0-9/°]*)"
_BOUND = re.compile(
    r"^(?:(?:up\s*to|<=|≤|not\s+exceeding)\s*" + _NUM + r"\s*" + _UNIT + r"?"
    r"|(?:over|above|>|exceeding)\s*" + _NUM + r"\s*" + _UNIT + r"?"
    r"(?:\s*(?:up\s*to|to|and\s+up\s+to|-|–|and\s+not\s+exceeding)\s*" + _NUM + r"\s*" + _UNIT + r"?)?)",
    re.IGNORECASE)
_TERM = re.compile(r"(?:" + _NUM + r"\s*(?:x|×|\*|times)\s*)?(?P<sym>[A-Za-z][A-Za-z .]{0,40}?)"
                   r"\s*(?:\+\s*" + _NUM + r"\s*" + _UNIT + r"?)?\s*$", re.IGNORECASE)


def _n(text: str) -> float:
    """A number the bound/term patterns matched, read by the shared parser
    (`numparse`): "3,300" is 3300 and "9,0" is 9.0. A token that is not one
    number ("1,2,3") raises, and `parse_rule` turns that into "no rule"."""
    value = numparse.as_number(text)
    if value is None:
        raise ValueError(f"not one number: {text!r}")
    return value


def _parse_expr(expr: str, symbols: list[str]) -> dict | None:
    text = " ".join(expr.split()).rstrip(".")
    op = "single"
    lowered = text.lower()
    for tail, name in ((r",?\s*whichever\s+is\s+(?:greater|higher|larger)$", "max"),
                       (r",?\s*whichever\s+is\s+(?:less|lower|smaller)$", "min")):
        m = re.search(tail, lowered)
        if m:
            op, text = name, text[:m.start()]
            break
    parts = re.split(r"\s+or\s+|\s*,\s*", text, flags=re.IGNORECASE)
    if op == "single" and len(parts) != 1:
        return None
    terms = []
    for part in parts:
        m = _TERM.match(part.strip())
        if not m:
            return None
        sym = " ".join(m.group("sym").split()).lower()
        if not any(sym == s or sym.endswith(s) for s in symbols):
            return None
        terms.append({"k": _n(m.group(1)) if m.group(1) else 1.0,
                      "c": _n(m.group(3)) if m.group(3) else 0.0})
    return {"op": op, "terms": terms}


def parse_rule(text: str, *, output: str, input_names: list[str]) -> dict | None:
    try:
        return _parse_rule(text, output=output, input_names=input_names)
    except ValueError:
        return None      # a number that is not one number: not a rule


def _parse_rule(text: str, *, output: str, input_names: list[str]) -> dict | None:
    """A range-table rule from the clause/table text, or None if it does not parse.

    Reads rows written `<bound> | <expression>` or `<bound>: <expression>`,
    one per line. Every row must parse and all bounds must share one unit;
    otherwise None - a half-parsed table is not a rule.
    """
    symbols = [s.lower() for s in input_names]
    rows, unit = [], None
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        m = _BOUND.match(line)
        if not m:
            continue
        rest = line[m.end():].lstrip(" |:-–")
        if m.group(1):
            lo, hi, u = None, _n(m.group(1)), m.group(2)
        else:
            lo, u = _n(m.group(3)), m.group(4)
            hi = _n(m.group(5)) if m.group(5) else None
            u = m.group(6) or u
        if u:
            if unit and u.lower() != unit.lower():
                return None
            unit = unit or u
        expr = _parse_expr(rest, symbols)
        if expr is None:
            return None
        rows.append({"from": lo, "to": hi, **expr})
    if not rows or not unit:
        return None
    rows.sort(key=lambda r: (r["from"] is not None, r["from"] or 0))
    return {"output": output, "input": input_names[-1], "input_names": input_names,
            "unit": unit, "comparator": ">=", "rows": rows}


def rule_numbers(rule: dict) -> set[float]:
    out: set[float] = set()
    for row in rule.get("rows", []):
        for key in ("from", "to"):
            if row.get(key) is not None:
                out.add(float(row[key]))
        for term in row.get("terms", []):
            if term.get("k", 1) != 1:
                out.add(float(term["k"]))
            if term.get("c", 0) != 0:
                out.add(float(term["c"]))
    return out


def verify_numbers(rule: dict, text: str) -> bool:
    """Every number the rule uses appears verbatim in the page's text."""
    present = {n for n in numparse.number_keys(text or "") if isinstance(n, float)}
    return rule_numbers(rule) <= present


# ------------------------------------------------------------ pairing (2b)

#: What a pressure-from-operating-pressure rule reads from a datasheet. Field
#: names are matched after `datasheets.normalise_field_name`.
KNOWN_RULES = (
    {"output": "design pressure",
     "input_names": ["mop", "maximum operating pressure", "max operating pressure",
                     "operating pressure"],
     "requirement_words": ("design pressure",)},
    {"output": "design temperature",
     "input_names": ["mot", "maximum operating temperature", "max operating temperature",
                     "operating temperature"],
     "requirement_words": ("design temperature",)},
)


#: The three states a datasheet field can be in for a rule. A CONFLICT is not
#: an absence: two rows for one field with different values is something the
#: sheet SAYS, and the engineer must reconcile it - reporting it as "not
#: stated" hid a real disagreement behind a false absence.
ABSENT = "absent"
SINGLE = "single"
CONFLICT = "conflict"

#: Rationale tag for a field the datasheet states more than once, differently.
CONFLICTING_VALUES = "conflicting_values"


def _value_of(fact: dict) -> str:
    return " ".join((fact.get("field_value") or "").split())


def _same_value_key(fact: dict) -> tuple:
    """What two rows must share to be ONE value. The quantity when it parses
    ("3,300 kPa" = "3300 kPa" = "3.3 MPa"; gauge and absolute kept apart),
    else the written text with spacing and thousands separators folded."""
    raw, unit = fact.get("raw_value"), fact.get("raw_unit") or ""
    if raw not in (None, ""):
        base, basis = _split_basis(unit)
        m = claims.normalise(str(raw), base)
        if m.normalized_value is not None and m.normalized_unit:
            return ("q", round(float(m.normalized_value), 9), m.normalized_unit, basis)
        number = claims.parse_value(str(raw))
        if number is not None:
            return ("n", round(number, 9), " ".join(unit.lower().split()))
    text = _value_of(fact).lower()
    return ("t", re.sub(r"(?<=\d),(?=\d{3}\b)", "", text))


def _read_field(facts: list[dict], names) -> tuple[str, list[dict]]:
    """(state, the fact rows for the field) within ONE equipment scope.
    ABSENT: no row. SINGLE: every row carries the same value (the first row
    is judged). CONFLICT: the rows carry different values - none is chosen.

    THE MOST SPECIFIC NAME WINS. `names` lists synonyms of the quantity the
    rule reads first ("mop", "maximum operating pressure") and the generic,
    less specific name LAST ("operating pressure" - `parse_rule` stores it
    as `rule["input"]`). A normal operating pressure beside a maximum one is
    two quantities, not a disagreement: the generic name is read only when
    no specific name is on the sheet. Specific synonyms that disagree are
    one quantity stated twice - a real conflict."""
    from .datasheets import normalise_field_name
    names = list(names)
    tiers = [names[:-1], names[-1:]] if len(names) > 1 else [names]
    hits: list[dict] = []
    for tier in tiers:
        wanted = {normalise_field_name(n) for n in tier}
        hits = [f for f in facts if normalise_field_name(f.get("field_name") or "") in wanted]
        if hits:
            break
    if not hits:
        return ABSENT, []
    return (SINGLE if len({_same_value_key(f) for f in hits}) == 1 else CONFLICT), hits


def _conflict_words(field: str, hits: list[dict]) -> str:
    """Every distinct value with the page(s) it was read on - the citation
    for each side of the disagreement (CLAUDE.md rule 4)."""
    pages: dict[str, list] = {}
    for f in hits:
        seen = pages.setdefault(_value_of(f), [])
        if f.get("page") is not None and f.get("page") not in seen:
            seen.append(f.get("page"))
    parts = []
    for value, where in pages.items():
        shown = f"'{value}'" if value else "blank"
        cite = (f" (page {', '.join(str(p) for p in where)})" if where
                else " (page not recorded)")
        parts.append(shown + cite)
    return (f"{CONFLICTING_VALUES}: the datasheet states conflicting values for "
            f"{field}: {'; '.join(parts)}")


def _judge_one(rule: dict, facts: list[dict]) -> tuple[dict, dict | None]:
    """(verdict, fact judged) for a parsed rule against ONE equipment scope's facts.

    The OUTPUT field is judged; the INPUT is only used to compute the
    required value, and is named in the rationale. A field the datasheet
    states twice with different values is a CONFLICT: never judged, never
    "not stated" - NEEDS_ENGINEER_REVIEW with every value and its page.
    """
    out_state, out_hits = _read_field(facts, [rule["output"]])
    in_state, in_hits = _read_field(facts, rule.get("input_names") or [rule["input"]])
    output = out_hits[0] if out_state == SINGLE else None
    inp = in_hits[0] if in_state == SINGLE else None
    if out_state == CONFLICT:
        # The first row is returned so the finding cites a real page on the
        # submittal; the rationale names every value and page.
        return ({"status": NEEDS_ENGINEER_REVIEW,
                 "rationale": (f"{RULE_REASON}: {_conflict_words(rule['output'], out_hits)}; "
                               "no value was chosen and the rule was not applied - "
                               "an engineer reconciles the datasheet"),
                 "limit": None, "observed": None, "exception_applied": None}, out_hits[0])
    if output is None or output.get("is_blank"):
        input_note = ""
        if inp:
            input_note = (f" (input {inp.get('field_label') or inp.get('field_name')} "
                          f"{inp.get('field_value')} was found)")
        elif in_state == CONFLICT:
            input_note = f" ({_conflict_words(rule['input'], in_hits)})"
        return ({"status": MISSING_INFORMATION,
                 "rationale": f"{RULE_REASON}: {rule['output']} not stated on the datasheet"
                              + input_note,
                 "limit": None, "observed": None, "exception_applied": None}, output)
    if in_state == CONFLICT:
        return ({"status": NEEDS_ENGINEER_REVIEW,
                 "rationale": (f"{RULE_REASON}: {_conflict_words(rule['input'], in_hits)}; "
                               f"so the required {rule['output']} could not be calculated - "
                               "an engineer reconciles the datasheet"),
                 "limit": None, "observed": None, "exception_applied": None}, output)
    if inp is None or inp.get("is_blank"):
        return ({"status": NEEDS_ENGINEER_REVIEW,
                 "rationale": (f"{RULE_REASON}: {rule['input']} is not stated on the datasheet, "
                               f"so the required {rule['output']} could not be calculated"),
                 "limit": None, "observed": None, "exception_applied": None}, output)
    # claims.parse_value: "3,300" is 3300 (thousands), "9,0" is 9.0; None if not a number.
    x_in, x_out = (claims.parse_value(str(f.get("raw_value") or "")) for f in (inp, output))
    if x_in is None or x_out is None:
        return ({"status": NEEDS_ENGINEER_REVIEW,
                 "rationale": f"{RULE_REASON}: a value is not a single number; not calculated",
                 "limit": None, "observed": None, "exception_applied": None}, output)
    result = evaluate(rule, x_in, inp.get("raw_unit") or "", x_out, output.get("raw_unit") or "")
    if result is None:
        return ({"status": NEEDS_ENGINEER_REVIEW,
                 "rationale": f"{RULE_REASON}: the rule's structure is not one this system evaluates",
                 "limit": None, "observed": None, "exception_applied": None}, output)
    return ({"status": result["status"], "rationale": result["rationale"],
             "limit": result["required_value"], "observed": result["output_checked"],
             "exception_applied": None, "input_used": result["input_used"],
             "rows_used": result["rows_used"]}, output)


#: Which per-tag status decides a multi-tag verdict: a breach anywhere is a
#: breach; COMPLIANT only when EVERY tag was judged and met the rule.
_TAG_PRECEDENCE = (NON_COMPLIANT, NEEDS_ENGINEER_REVIEW, MISSING_INFORMATION, COMPLIANT)


def judge(rule: dict, facts: list[dict]) -> tuple[dict, dict | None]:
    """(verdict, fact judged) for a parsed rule against the datasheet's facts.

    PER EQUIPMENT TAG. A sheet covering P-101A and P-101B states one design
    pressure for each; two different values there are two pumps, not a
    conflict. With two or more tags, each tag is judged on its own rows
    (untagged rows apply to every tag unless the tag states the field
    itself), and the verdicts are combined by `_TAG_PRECEDENCE` with every
    tag's result named in the rationale.
    """
    tags = sorted({f.get("equipment_tag") for f in facts if f.get("equipment_tag")})
    if len(tags) < 2:
        return _judge_one(rule, facts)
    from .datasheets import normalise_field_name
    untagged = [f for f in facts if not f.get("equipment_tag")]
    per_tag = []
    for tag in tags:
        own = [f for f in facts if f.get("equipment_tag") == tag]
        # A tag's own row outranks the sheet-wide one for the same field.
        own_names = {normalise_field_name(f.get("field_name") or "") for f in own}
        scope = own + [f for f in untagged
                       if normalise_field_name(f.get("field_name") or "") not in own_names]
        per_tag.append((tag, *_judge_one(rule, scope)))
    status = next(s for s in _TAG_PRECEDENCE if any(v["status"] == s for _t, v, _f in per_tag))
    tag, verdict, fact = next(x for x in per_tag if x[1]["status"] == status)
    words = "; ".join(f"{t}: {v['status']} - {v['rationale']}" for t, v, _f in per_tag)
    return ({**verdict, "status": status,
             "rationale": f"{RULE_REASON}: judged per equipment tag ({len(per_tag)} tags); "
                          f"{tag} decides. {words}"}, fact)


def known_rule_for(requirement: dict) -> dict | None:
    """Which KNOWN_RULES shape this requirement is about, by its own words."""
    text = " ".join(str(requirement.get(k) or "") for k in
                    ("requirement_text", "source_text", "field", "subject")).lower()
    for known in KNOWN_RULES:
        if any(w in text for w in known["requirement_words"]):
            return known
    return None


def dumps(rule: dict) -> str:
    return json.dumps(rule, sort_keys=True)


# ------------------------------------------------------- store and fetch

MODEL_STEP = "rule_parse"
MODEL_PROMPT = """Turn this engineering table/formula clause into JSON rows. Each row: \
{"from": number|null, "to": number|null, "op": "single"|"max"|"min", \
"terms": [{"k": number, "c": number}]} meaning output = op(k * input + c) for input in (from, to]. \
Also give "unit" (the unit of the table's numbers). Use ONLY numbers printed in the text. \
Answer {"unit": "...", "rows": [...]} and nothing else.

TEXT:
"""


def _page_texts(requirement: dict) -> list[str]:
    """The clause's own text, its chunk, and - for a garbled table - the
    page's ruled table re-read by the table reader, in that order."""
    from .db import connect
    texts = [str(requirement.get("source_text") or requirement.get("requirement_text") or "")]
    chunk = connect().execute("SELECT text FROM chunks WHERE id = ?",
                              (requirement.get("chunk_id"),)).fetchone()
    if chunk and chunk["text"]:
        texts.append(chunk["text"])
    doc = connect().execute("SELECT stored_path FROM documents WHERE id = ?",
                            (requirement.get("standard_document_id"),)).fetchone()
    page = requirement.get("page") or requirement.get("chunk_page")
    if doc and doc["stored_path"] and page:
        try:
            from . import tables
            for shape in tables.parse_page_tables(doc["stored_path"], int(page)):
                texts.append("\n".join(" | ".join(c or "" for c in row) for row in shape))
        except Exception as exc:  # noqa: BLE001 - an unreadable page leaves the text sources
            # The caller then reports "the table ... could not be read" when no
            # rule results; the cause is logged so it is not lost.
            _log.warning("the ruled table on page %s of %s could not be re-read (%s)",
                         page, requirement.get("standard_document_id"), type(exc).__name__)
    return texts


def _model_parse(text: str, known: dict, provider) -> dict | None:
    """The model's parse, kept only if every number in it is on the page."""
    from . import reasoning_provider as rp
    from .config import settings
    response = provider.reason(rp.Packet(
        prompt=MODEL_PROMPT + text[:6000], num_ctx=settings.num_ctx, num_predict=800,
        step=MODEL_STEP, prompt_version="rule-parse-v1", timeout_s=120))
    try:
        body = json.loads(response.text.strip().strip("`").removeprefix("json").strip())
        rule = {"output": known["output"], "input": known["input_names"][-1],
                "input_names": known["input_names"], "unit": str(body["unit"]),
                "comparator": ">=", "rows": list(body["rows"])}
    except (ValueError, KeyError, TypeError):
        return None
    # REJECT, NEVER REPAIR: a number that is not on the page is an invention.
    return rule if rule["rows"] and verify_numbers(rule, text) else None


def rule_for(requirement: dict, *, provider=None) -> tuple[dict | None, str | None]:
    """(rule, source) for a table/relative requirement - parsed once and
    stored on the requirement, or (None, why) when it stays with an engineer."""
    from .config import settings
    from .db import connect
    if requirement.get("rule_json"):
        try:
            return json.loads(requirement["rule_json"]), requirement.get("rule_source")
        except ValueError:
            pass
    known = known_rule_for(requirement)
    if known is None:
        return None, None
    texts = _page_texts(requirement)
    rule, source = None, None
    for text in texts:
        rule = parse_rule(text, output=known["output"], input_names=known["input_names"])
        if rule is not None and verify_numbers(rule, text):
            source = SOURCE_CODE
            break
        rule = None
    if rule is None and settings.rule_parse_model_enabled:
        from . import reasoning_provider as rp
        if provider is not None or rp.claude_available()[0]:
            try:
                engine = provider or rp.get_provider("reasoning", step=MODEL_STEP)
                for text in texts:
                    rule = _model_parse(text, known, engine)
                    if rule is not None:
                        source = SOURCE_MODEL
                        break
            except Exception:  # noqa: BLE001 - budget or refusal: stays with an engineer
                rule = None
    if rule is None:
        page = requirement.get("page") or requirement.get("chunk_page")
        return None, (f"the table on page {page} could not be read" if page
                      else "the table could not be read")
    if requirement.get("id"):
        with connect() as conn:
            conn.execute("UPDATE standard_requirements SET rule_json = ?, rule_source = ?"
                         " WHERE id = ?", (dumps(rule), source, requirement["id"]))
    return rule, source
