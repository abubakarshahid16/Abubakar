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
overlapping passage) are merged in code.

CLAUSE TO CHECK (#645 in the review, Stage C, planner 12 Oct). A clause
sentence the requirement parser stored with no limit (`requirement_type`
"statement") that the review then could not decide is given to the model
ONE SENTENCE AT A TIME, and the model proposes a check: field, operator,
value, unit, condition and the exact words. CODE VERIFIES EVERY PART against
the sentence (`verify_proposal`): the quote is in the sentence; the value is
in the quote, read as a number with its sign (`numparse.value_in_text`); a
unit is a unit and stands whole in the quote; code's own reading of the
quote's figures agrees; a condition is in the sentence, and a sentence that
is conditional with no condition proposed is refused (the #858 lesson). What
passes is stored as a DRAFT for the engineer (`clause_check_drafts`), never as
a requirement: no verdict is ever decided on an unapproved proposal. The
model is the runner's local model - standards text never leaves the machine. The model is the runner's setting
(`settings.ai_task_model`, qwen3.5:2b by default). No rule here names a
document, a standard or a clause.
"""
from __future__ import annotations

import re
import uuid

from . import ai_task_runner, numparse, standard_ids

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
    # "shall not be less than 3 mm" is a minimum: without these the shorter
    # "less than" below read it as "<", the opposite (#645).
    ("not be more than", "<="), ("not be greater than", "<="), ("not be higher than", "<="),
    ("not be above", "<="), ("not be less than", ">="), ("not be lower than", ">="),
    ("not be below", ">="),
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
    from . import answer, synthesis

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
    from . import answer

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


# ------------------------------------------------------------ clause to check

CLAUSE_SCHEMA = {
    "type": "object",
    "required": ["has_limit", "field", "operator", "value", "unit", "condition", "quote"],
    "properties": {
        "has_limit": {"type": "boolean"},
        "field": {"type": ["string", "null"]},
        "operator": {"type": ["string", "null"], "enum": [*OPERATORS, None]},
        "value": {"type": ["string", "null"]},
        "unit": {"type": ["string", "null"]},
        "condition": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"]},
    },
}

CLAUSE_INSTRUCTION = """You read ONE sentence of an engineering standard. Say
whether it sets a limit a datasheet value can be checked against. If it does:
- field: the datasheet quantity it limits, in a few words;
- operator: one of <=, <, >=, >, =;
- value: the figure exactly as printed;
- unit: the unit exactly as printed next to the figure, or null;
- condition: the words saying when the limit applies, copied exactly, or null;
- quote: the exact words of the sentence the limit stands on, copied
  character for character.
If it sets no limit, answer has_limit false and null for the rest. Clause,
table and page numbers are not limits."""

CLAUSE_TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="clause_check_proposal",
    version="v1",
    instruction=CLAUSE_INSTRUCTION,
    schema=CLAUSE_SCHEMA,
    num_predict=300,
))

#: Why a proposed check was refused - plain words for the run report; never
#: the clause text.
NO_LIMIT = "the model found no limit in the sentence"
FIELD_MISSING = "no field was proposed"
VALUE_MISSING = "no value was proposed"
VALUE_NOT_IN_QUOTE = "the value is not in the quoted words"
UNIT_UNRECOGNISED = "the unit is not a unit"
UNIT_NOT_IN_QUOTE = "the unit is not in the quoted words"
OPERATOR_DISAGREED = "the operator is not the one the words state"
CONDITION_MISSING = "the sentence is conditional and no condition was proposed"
CONDITION_NOT_IN_SOURCE = "the condition is not in the sentence"
#: A sentence the review could not decide and the model was asked about.
STATEMENT = "statement"


def _whole(needle: str, text: str) -> bool:
    """`needle` stands whole in `text`: no LETTER either side, so "m3/h" is
    not found inside "Nm3/h", while "10%" and "50mm" still hold their unit."""
    needle = _squash(needle)
    return bool(needle) and re.search(
        r"(?<![^\W\d_])" + re.escape(needle) + r"(?![^\W\d_])", _squash(text)) is not None


def _is_conditional(sentence: str) -> bool:
    """Does the sentence hold only under a circumstance? Errs towards YES: a
    refused proposal costs a look; a condition dropped decides a case the
    clause does not cover."""
    from . import field_links, requirements_3b

    return bool(requirements_3b.parse_condition(sentence)
                or field_links._CONDITION.search(sentence or ""))


def verify_proposal(proposal: dict, sentence: str) -> tuple[dict | None, str | None]:
    """(check, None) when CODE confirms every part of the model's proposal
    against the sentence, else (None, why). A check is
    {field, operator, value, unit, condition, quote}; its value, unit and
    operator are the ones code read from the quote."""
    from . import claims

    if not proposal.get("has_limit"):
        return None, NO_LIMIT
    field, value = hint(proposal.get("field")), hint(proposal.get("value"))
    unit, condition = hint(proposal.get("unit")), hint(proposal.get("condition"))
    quote = proposal.get("quote") or ""
    if not quote.strip() or _squash(quote) not in _squash(sentence):
        return None, QUOTE_NOT_IN_SOURCE
    if field is None:
        return None, FIELD_MISSING
    if value is None:
        return None, VALUE_MISSING
    if not numparse.value_in_text(value, quote):
        return None, VALUE_NOT_IN_QUOTE
    if unit is not None:
        if claims.unit_dimension(unit) is None and not claims.is_unit(unit):
            return None, UNIT_UNRECOGNISED
        if not _whole(unit, quote):
            return None, UNIT_NOT_IN_QUOTE
    figures = read_figures(quote)
    if figures and not _hints_agree({"value": value, "unit": unit}, figures):
        return None, MODEL_VALUE_DISAGREED
    read = next((f for f in figures if numparse.value_in_text(value, f"{f['value']} {f['unit']}")), None)
    operator = hint(proposal.get("operator"))
    if read is not None and read["operator"] and operator and operator != read["operator"]:
        return None, OPERATOR_DISAGREED
    if condition is not None and _squash(condition) not in _squash(sentence):
        return None, CONDITION_NOT_IN_SOURCE
    if condition is None and _is_conditional(sentence):
        return None, CONDITION_MISSING
    return {"field": field, "operator": (read or {}).get("operator") or operator,
            "value": (read or {}).get("value") or value, "unit": (read or {}).get("unit") or unit,
            "condition": condition, "quote": quote.strip()}, None


def undecided_statements(requirements: list[dict], status_of: dict) -> list[dict]:
    """The clause sentences of this run the review could not turn into a
    decision: stored with no limit (`statement`) and left with no finding, or
    with one that only says no field matched or an engineer must look."""
    from . import comparison

    open_states = {None, comparison.NOT_IN_DOCUMENT_SCOPE, comparison.NEEDS_ENGINEER_REVIEW}
    return [r for r in requirements
            if r.get("requirement_type") == STATEMENT and status_of.get(r.get("id")) in open_states]


def ensure_schema() -> None:
    """Drafts only. A proposed check is never a requirement: the engineer
    approves it into one, or rejects it (#645)."""
    from .db import connect

    conn = connect()
    with conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS clause_check_drafts (
            requirement_id TEXT NOT NULL,
            field TEXT NOT NULL,
            operator TEXT,
            value TEXT NOT NULL,
            unit TEXT,
            condition TEXT,
            quote TEXT NOT NULL,
            model TEXT,
            review_run_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (requirement_id, field, value, unit))""")
    # #645 part 2: the engineer's decision on a draft. `id` names a draft in
    # a URL; `new_requirement_id` is the confirmed row an accepted draft became.
    from .db import add_column_if_missing
    for column, kind in (("id", "TEXT"), ("decided_by", "TEXT"), ("decided_at", "TEXT"),
                         ("new_requirement_id", "TEXT")):
        add_column_if_missing(conn, "clause_check_drafts", column, kind)
    with conn:
        conn.execute("UPDATE clause_check_drafts SET id = lower(hex(randomblob(16)))"
                     " WHERE id IS NULL")


def propose_checks(requirements: list[dict], *, review_run_id: str | None = None,
                   limit: int, provider=None) -> dict:
    """Ask the local model for a check per undecided clause sentence (at most
    `limit` per run), verify each in code, store what passes as a draft.
    Returns the run report's counts: {sentences, asked, proposed, refused
    {why: n}, could_not_read, not_asked_budget}. Every count is out of
    `sentences`."""
    from .db import connect

    asked = proposed = unread = 0
    model = None
    refused: dict[str, int] = {}
    drafts = []
    for requirement in requirements[:max(limit, 0)]:
        sentence = requirement.get("source_text") or requirement.get("requirement_text") or ""
        asked += 1
        result = ai_task_runner.run_task(CLAUSE_TASK, sentence, provider=provider)
        if result.state != ai_task_runner.STATE_OK:
            unread += 1
            continue
        check, why = verify_proposal(result.data, sentence)
        if check is None:
            refused[why] = refused.get(why, 0) + 1
            continue
        proposed += 1
        drafts.append((requirement["id"], check, result.model))
        model = model or result.model
    if drafts:
        ensure_schema()
        conn = connect()
        with conn:
            # INSERT OR IGNORE: a proposal the engineer already rejected (or
            # accepted) for the same words is not offered again.
            conn.executemany(
                "INSERT OR IGNORE INTO clause_check_drafts (id, requirement_id, field, operator,"
                " value, unit, condition, quote, model, review_run_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(uuid.uuid4().hex, rid, c["field"], c["operator"], c["value"], c["unit"] or "",
                  c["condition"], c["quote"], model, review_run_id)
                 for rid, c, model in drafts])
    return {"sentences": len(requirements), "asked": asked, "proposed": proposed,
            "refused": refused, "could_not_read": unread,
            "not_asked_budget": max(len(requirements) - max(limit, 0), 0),
            # the local runner's model (`ai_task_runner`); None when none answered
            "model": model}


def report_line(counts: dict | None) -> str | None:
    """"N of M sentence requirements now have a proposed check", with what
    happened to the rest - or None when the step did not run."""
    if not counts:
        return None
    refused = sum(counts.get("refused", {}).values())
    line = (f"{counts['proposed']} of {counts['sentences']} sentence requirement(s) now have a "
            f"proposed check (drafts for the engineer); {refused} proposal(s) refused by code, "
            f"{counts['could_not_read']} not read by the model")
    if counts.get("not_asked_budget"):
        line += f", {counts['not_asked_budget']} not asked (the per-run cap)"
    return line + "."


# ------------------------------------------- the engineer decides (part 2)

ACCEPTED, REJECTED, DRAFT, REPLACED = "accepted", "rejected", "draft", "replaced"


class DraftError(ValueError):
    """A draft that cannot be decided, with why (plain words, no clause text)."""


def list_drafts(*, allowed_document_ids: frozenset[str], status: str = DRAFT,
                limit: int = 200) -> list[dict]:
    """Drafts of the standards the caller may read, with the clause sentence
    they stand on and where it is. Read only."""
    from .db import connect

    # READ ONLY (a GET): no schema work here. Before the first draft is
    # written - or before part 2's columns exist - there is nothing to list.
    columns = {r["name"] for r in connect().execute("PRAGMA table_info(clause_check_drafts)")}
    if not allowed_document_ids or "id" not in columns:
        return []
    marks = ",".join("?" * len(allowed_document_ids))
    rows = connect().execute(
        "SELECT d.id, d.requirement_id, d.field, d.operator, d.value, d.unit, d.condition,"
        " d.quote, d.model, d.status, d.decided_at, d.new_requirement_id,"
        " r.standard_document_id, r.clause, r.page, r.source_text"
        " FROM clause_check_drafts d JOIN standard_requirements r ON r.id = d.requirement_id"
        f" WHERE r.standard_document_id IN ({marks}) AND d.status = ?"
        " ORDER BY r.standard_document_id, r.clause, d.created_at LIMIT ?",
        [*sorted(allowed_document_ids), status, limit]).fetchall()
    return [{**dict(r), "unit": r["unit"] or None} for r in rows]


def _draft(conn, draft_id: str, allowed_document_ids: frozenset[str]):
    row = conn.execute(
        "SELECT d.*, r.standard_document_id, r.chunk_id, r.clause, r.page, r.requirement_text,"
        " r.source_text, r.requirement_type, r.superseded_at"
        " FROM clause_check_drafts d JOIN standard_requirements r ON r.id = d.requirement_id"
        " WHERE d.id = ?", (draft_id,)).fetchone()
    # "not found" is the same answer as "not yours"
    if row is None or row["standard_document_id"] not in allowed_document_ids:
        raise DraftError("no clause-check draft with that id")
    return row


def decide_draft(draft_id: str, *, decision: str, allowed_document_ids: frozenset[str],
                 actor: dict | None = None) -> dict:
    """The engineer accepts or rejects one draft (#645 part 2).

    ACCEPT IS CHECKED BY CODE AGAIN, then VERSIONED, never edited in place:
    the proposal is verified against the sentence once more
    (`verify_proposal`), its operator must not point the opposite way to the
    sentence (`requirements_3b.contradicts_source`), and its value and unit
    are normalised by the parser's own `measure`. A NEW requirement row is
    written - a numeric limit, `extraction_method='human'`, confirmed by the
    engineer - and the sentence row it came from is SUPERSEDED, not deleted:
    findings that cited it keep their citation. Reviews use the new row from
    the next run. The draft keeps the decision, who made it and the new row.

    REJECT keeps the draft, marked rejected with the engineer's name, so the
    same proposal for the same words is not offered again.
    """
    from . import requirements_3b, standards
    from .db import connect

    if decision not in {"accept", "reject"}:
        raise DraftError(f"unknown decision {decision!r}")
    ensure_schema()
    conn = connect()
    row = _draft(conn, draft_id, allowed_document_ids)
    if row["status"] != DRAFT:
        raise DraftError(f"this draft was already {row['status']}")
    now = standards._now()
    who = (actor or {}).get("id")
    if decision == "reject":
        with conn:
            conn.execute("UPDATE clause_check_drafts SET status = ?, decided_by = ?, decided_at = ?"
                         " WHERE id = ?", (REJECTED, who, now, draft_id))
        standards._audit("standard.clause_check_rejected", actor, row["standard_document_id"],
                         detail=f"draft={draft_id} requirement={row['requirement_id']}"
                                f" clause={row['clause']}")
        return {"id": draft_id, "decision": "reject", "status": REJECTED,
                "new_requirement_id": None}

    if row["superseded_at"] or row["requirement_type"] != STATEMENT:
        raise DraftError("the clause sentence has changed since this draft was proposed")
    sentence = row["source_text"] or row["requirement_text"] or ""
    check, why = verify_proposal(
        {"has_limit": True, "field": row["field"], "operator": row["operator"],
         "value": row["value"], "unit": row["unit"] or None, "condition": row["condition"],
         "quote": row["quote"]}, sentence)
    if check is None:
        raise DraftError(f"code refused the draft: {why}")
    if check["operator"] is None:
        raise DraftError("code refused the draft: no operator could be read")
    raw_unit = requirements_3b.unit_token(check["unit"]) if check["unit"] else None
    measured = requirements_3b.measure(check["value"], raw_unit)
    limit = {"operator": check["operator"], "raw_value": check["value"], "raw_unit": raw_unit,
             "value": measured.normalized_value, "unit": measured.normalized_unit}
    if limit["value"] is None:
        raise DraftError("code refused the draft: the value is not a number")
    if requirements_3b.contradicts_source(limit, sentence):
        raise DraftError("code refused the draft: the operator points the opposite way to "
                         "the sentence")
    new = standards.create_requirement(
        standard_document_id=row["standard_document_id"], chunk_id=row["chunk_id"],
        requirement_text=row["requirement_text"], source_text=row["source_text"] or sentence,
        clause=row["clause"], page=row["page"], extraction_method="human",
        structured={"requirement_type": "numeric_limit", "field": check["field"],
                    "subject": check["field"], "condition": check["condition"], **limit})
    with conn:
        conn.execute("UPDATE standard_requirements SET confirmed_by = ?, confirmed_at = ?,"
                     " updated_at = ? WHERE id = ?", (who, now, now, new["id"]))
        conn.execute("UPDATE standard_requirements SET superseded_at = ?, updated_at = ?"
                     " WHERE id = ?", (now, now, row["requirement_id"]))
        conn.execute("UPDATE clause_check_drafts SET status = ?, decided_by = ?, decided_at = ?,"
                     " new_requirement_id = ? WHERE id = ?",
                     (ACCEPTED, who, now, new["id"], draft_id))
        # the sentence has its check now: its other drafts are moot
        conn.execute("UPDATE clause_check_drafts SET status = ?, decided_at = ?"
                     " WHERE requirement_id = ? AND status = ?",
                     (REPLACED, now, row["requirement_id"], DRAFT))
    standards._audit("standard.clause_check_accepted", actor, row["standard_document_id"],
                     detail=f"draft={draft_id} requirement={row['requirement_id']}"
                            f" new={new['id']} clause={row['clause']}")
    return {"id": draft_id, "decision": "accept", "status": ACCEPTED,
            "new_requirement_id": new["id"]}
