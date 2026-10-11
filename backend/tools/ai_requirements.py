"""AI requirement extraction (#645): the model reads, code checks every field.

"AI reads, code checks" (owner decision 2026-10-08; rules on #644). One task
reads one passage of at most `MAX_WORDS` words of a standard and returns the
requirements it states, each with:

  quote     the exact words the requirement stands on;
  subject   what the requirement is about;
  operator  <=, <, >=, >, =, range, or none (a requirement with no figure);
  value     the figure as printed (for a range, its lower end);
  value_to  the upper end of a range, or null;
  unit      the unit as printed, or null;
  condition when it applies, or null;
  standard  a standard the requirement names, or null.

NOTHING THE MODEL SAYS IS KEPT ON ITS WORD. The model LOCATES a requirement
(its quote); CODE READS it (owner decision on #645, "AI reads, code checks"):

  * the quote must be in the passage (whitespace and case aside), else the
    item is `could_not_read` with the reason;
  * the STANDARDS it cites are read by code from the verified quote
    (`standard_ids`); the model's own "standard" field is a hint, and when it
    names something the quote does not cite as a standard the item is kept
    and flagged "model standard disagreed" (a word for nothing - "None",
    "null", "N/A" - is read as no hint);
  * the item's FIGURES are read by code from the verified quote (`read_figures`:
    numparse value, unit through the shared unit reader of #653, and the
    operator its wording states). The model's own value/unit fields are hints
    only: when they disagree with code's reading, code wins and the item is
    flagged "model value disagreed" for an engineer. A quote with no figure is
    a figure-less requirement; two figures are two, each with its unit; a
    bracketed conversion ("16 psi (110 kPa)") is one quantity.

Duplicates (the same figures from the same words, met again in an
overlapping passage) are merged in code. The model is the runner's setting
(`settings.ai_task_model`, qwen3.5:2b by default). No rule here names a
document, a standard or a clause.
"""
from __future__ import annotations

import re

from app import ai_task_runner, numparse, standard_ids

#: Words per task. Under the runner's 300-word limit, so a passage split at a
#: sentence never crosses it (#644 decision b).
MAX_WORDS = 280

OPERATORS = ["<=", "<", ">=", ">", "=", "range", "none"]

SCHEMA = {
    "type": "object",
    "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["quote", "subject", "operator", "value", "unit"],
                "properties": {
                    "quote": {"type": "string"},
                    "subject": {"type": "string"},
                    "operator": {"type": "string", "enum": OPERATORS},
                    "value": {"type": ["string", "null"]},
                    "value_to": {"type": ["string", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "condition": {"type": ["string", "null"]},
                    "standard": {"type": ["string", "null"]},
                },
            },
        },
    },
}

INSTRUCTION = """You read one passage of an engineering standard. List every
requirement it states: a sentence with "shall", "must", "is required", "not
less than", "not more than", "maximum", "minimum", or a table row that sets a
limit. For each one give:
- quote: the exact words from the passage the requirement stands on, copied
  character for character (no paraphrase);
- subject: what it is about, in a few words;
- operator: one of <=, <, >=, >, =, range, none (none when it has no figure);
- value: the figure exactly as printed (for a range, the lower end), or null;
- value_to: the upper end of a range, or null;
- unit: the unit exactly as printed next to the figure, or null;
- condition: when it applies, or null;
- standard: a standard the requirement names, or null.
Worked examples, page numbers, clause numbers and document numbers are not
requirements. If the passage states none, return an empty list."""

TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="requirement_extraction",
    version="v1",
    instruction=INSTRUCTION,
    schema=SCHEMA,
    num_predict=900,
))

#: Why an item was not kept (plain words; shown to an engineer, never the text).
QUOTE_NOT_IN_SOURCE = "the quoted words are not in the passage"


def _squash(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def split_passages(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """`text` cut at sentence ends into passages of at most `max_words`
    words. A single sentence longer than that is cut at the word limit."""
    sentences = re.split(r"(?<=[.;:!?])\s+|\n+", (text or "").strip())
    passages: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        while len(words) > max_words:
            if current:
                passages.append(" ".join(current)); current, count = [], 0
            passages.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if count + len(words) > max_words and current:
            passages.append(" ".join(current)); current, count = [], 0
        current.extend(words)
        count += len(words)
    if current:
        passages.append(" ".join(current))
    return passages


def check_item(item: dict, passage: str) -> str | None:
    """None when the item may be kept, else why not: the quote must be in the
    passage, and a standard it names must parse and be the one the quote
    cites. Its figures are NOT taken from the model - see `read_figures`."""
    quote = item.get("quote") or ""
    if not quote.strip() or _squash(quote) not in _squash(passage):
        return QUOTE_NOT_IN_SOURCE
    return None


#: What a model writes in a text field when it means "nothing" - JSON null
#: spelled as a word. Read as absent, never as a value (#645 diagnosis: the
#: string "None" in the standard field rejected real requirements).
_NOTHING = frozenset({"", "none", "null", "n/a", "na", "nil", "-", "not applicable"})


def hint(value) -> str | None:
    """A model's text field, or None when it is empty or a word for nothing."""
    text = str(value).strip() if value is not None else ""
    return None if text.casefold() in _NOTHING else text


def read_standards(quote: str) -> list[str]:
    """The standards the verified quote cites, read by `standard_ids` (code
    reads; the model's own "standard" field is a hint only)."""
    return standard_ids.cited_standards(quote)


#: Flag on an item whose own "standard" field names something the quote does
#: not cite as a standard (or something that is not a standard identifier).
MODEL_STANDARD_DISAGREED = "model standard disagreed"


def _standard_hint_agrees(item: dict, standards: list[str]) -> bool:
    named = hint(item.get("standard"))
    if named is None:
        return True
    return standard_ids.parse(named) is not None and any(
        standard_ids.same_standard(named, s) for s in standards)


#: Words before a figure that say which way the limit points. Generic English
#: of requirements, longest first; nothing here names a standard.
_OPERATOR_WORDS = (
    ("not more than", "<="), ("not to exceed", "<="), ("not exceed", "<="),
    ("no more than", "<="), ("not greater than", "<="), ("maximum of", "<="),
    ("maximum", "<="), ("max.", "<="), ("max", "<="), ("up to", "<="),
    ("at most", "<="), ("less than or equal to", "<="), ("or less", "<="),
    ("not less than", ">="), ("no less than", ">="), ("minimum of", ">="),
    ("minimum", ">="), ("min.", ">="), ("min", ">="), ("at least", ">="),
    ("greater than or equal to", ">="), ("or more", ">="),
    ("less than", "<"), ("below", "<"), ("under", "<"),
    ("greater than", ">"), ("more than", ">"), ("above", ">"), ("exceeding", ">"),
)
_OPERATOR_BEFORE = re.compile(
    r"(?:" + "|".join(re.escape(w) for w, _ in _OPERATOR_WORDS) + r")\s*$", re.IGNORECASE)
_OPERATOR_AFTER = re.compile(r"^\s*\S*\s*(or less|or more)\b", re.IGNORECASE)


def _operator(quote: str, start: int, end: int) -> str | None:
    before = _OPERATOR_BEFORE.search(quote[max(0, start - 30):start])
    if before:
        word = before.group(0).strip().lower()
        return next(op for w, op in _OPERATOR_WORDS if w == word)
    after = _OPERATOR_AFTER.match(quote[end:end + 25])
    if after:
        return "<=" if after.group(1).lower() == "or less" else ">="
    return None


#: Between the two numbers of a range: a dash or "to" (the sign reader may
#: already have taken the dash as a minus on the second number).
_RANGE_GAP = re.compile(r"\s*(?:[-–—]|to)?\s*", re.IGNORECASE)
#: Between a figure (its number and unit) and a bracketed restatement.
_BRACKET_GAP = re.compile(r"\s*[^\s()]*\s*\(\s*")


def read_figures(quote: str) -> list[dict]:
    """AI LOCATES, CODE READS (owner decision on #645): every figure WITH A
    UNIT in the verified quote, read by numparse - value, unit and the
    operator its wording states. A bracketed figure that is the same quantity
    as the figure before it ("16 psi (110 kPa)") is that figure again, not a
    second limit. A reference numeral (clause, table, page) is not a figure."""
    from app import answer, synthesis

    held = synthesis.strip_reference_numerals(quote)
    every = answer._figure_occurrences(held)
    # A RANGE carries its unit once, after its second number: "25-30 microns",
    # "5 to 10 mm". The first number takes the second's unit.
    for i, f in enumerate(every[:-1]):
        nxt = every[i + 1]
        if f["unit"] is None and nxt["unit"] and _RANGE_GAP.fullmatch(held[f["end"]:nxt["start"]]):
            every[i] = {**f, "unit": nxt["unit"], "sign": "+" if f["sign"] == "?" else f["sign"]}
    found = [f for f in every if f["unit"]]
    out: list[dict] = []
    for f in found:
        previous = out[-1] if out else None
        # "16 psi (110 kPa)": the bracketed figure restates the one before it
        if previous is not None and _BRACKET_GAP.fullmatch(held[previous["_end"]:f["start"]]) \
                and answer._unit_value_matches({**f}, previous["_occ"]):
            continue
        sign = "-" if f["sign"] == "-" else ""
        out.append({"value": sign + f["value"].rstrip("0").rstrip(".") if "." in f["value"]
                    else sign + f["value"], "unit": f["unit"],
                    "operator": _operator(held, f["start"], f["end"]),
                    "_end": f["end"], "_occ": f})
    return [{k: v for k, v in fig.items() if not k.startswith("_")} for fig in out]


#: Flag on an item whose own figure fields disagree with code's reading.
MODEL_VALUE_DISAGREED = "model value disagreed"


def _hints_agree(item: dict, figures: list[dict]) -> bool:
    """Do the model's own value fields (hints) agree with what code read?"""
    from app import answer

    unit = hint(item.get("unit")) or ""
    read = [answer._figure_occurrences(f"{f['value']} {f['unit']}")[0] for f in figures]
    for value in (item.get("value"), item.get("value_to")):
        value = hint(value)
        if value is None:
            continue
        stated = answer._figure_occurrences(f"{value} {unit}".strip())
        if not stated:
            return False
        h = stated[0]

        def same(r: dict) -> bool:
            if (h["sign"] == "-") != (r["sign"] == "-"):
                return False
            if h["unit"] is None:
                return answer._value_matches(h["value"], r["value"])
            return answer._unit_value_matches(h, r)

        if not any(same(r) for r in read):
            return False
    return True


def _key(item: dict) -> tuple:
    """Two items are one requirement when they rest on the same words (an
    overlapping passage reads a sentence twice)."""
    return (_squash(item.get("quote")),)


def extract(text: str, *, provider=None, use_cache: bool = True) -> dict:
    """Read `text` (any length) passage by passage. Returns
    {"requirements": [kept items, each with "passage"], "could_not_read":
    [{"passage", "reason"}], "passages": n, "merged": n}. A passage the model
    could not read, and an item a check rejected, are both listed with the
    reason - neither is guessed at."""
    kept: list[dict] = []
    seen: set[tuple] = set()
    unread: list[dict] = []
    merged = 0
    passages = split_passages(text)
    for index, passage in enumerate(passages):
        result = ai_task_runner.run_task(TASK, passage, provider=provider, use_cache=use_cache)
        if result.state != ai_task_runner.STATE_OK:
            unread.append({"passage": index, "reason": result.reason})
            continue
        for item in result.data.get("requirements") or []:
            reason = check_item(item, passage)
            if reason is not None:
                unread.append({"passage": index, "reason": reason})
                continue
            key = _key(item)
            if key in seen:
                merged += 1
                continue
            seen.add(key)
            figures = read_figures(item["quote"])
            standards = read_standards(item["quote"])
            flags = [] if _hints_agree(item, figures) else [MODEL_VALUE_DISAGREED]
            if not _standard_hint_agrees(item, standards):
                flags.append(MODEL_STANDARD_DISAGREED)
            kept.append({**item, "figures": figures, "standards": standards,
                         "flags": flags, "passage": index})
    return {"requirements": kept, "could_not_read": unread,
            "passages": len(passages), "merged": merged}
