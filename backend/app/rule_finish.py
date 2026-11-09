"""The rule finishing line (Cycle 2, #805 plan one; Lane 1): steps a, b, c, d and g, by code, for any standard.

Every step is a pure function of one rule (a plain dict, see `load_rules`) and, where it needs the standard's text, of
that standard's page text. It returns `(result, reason, evidence)`; `result` is one of PASS, FAIL, NOT_APPLICABLE,
INCOMPLETE. No model, no network, no database in the step functions.

  a  limit_and_unit    a number with a unit in the quote must be filled as value + unit, and both must stand in the quote
  b  evidence_source   exactly one of EVIDENCE_SOURCES, by closed word rules; the cue words are the evidence
  c  fragments         "the following ..." with no list: rejoined from the standard's own page text, or incomplete
  d  conditions        applicability rows as closed-vocabulary, testable conditions, or incomplete
  g  quote_found       the quote stands on its cited page of the standard; a rule that fails g NEVER decides
  e  engineer check    written by a separate process (`record_step`), never here
  f  owner sample      written by a separate process (`record_step`), never here

Numbers are `numparse` and the unit table of `claims` (no second number reader); a quote is checked by
`compiled_rule_proof.quote_verified` (no second fold). Generic only (rule 13): nothing here knows a layout or a standard.
Persistence is the table `rule_finish_step` (`ensure_table`), created only in a COPY of a database, never in the live one.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any, NamedTuple

from . import claims, numparse
from .compiled_rule_proof import quote_verified

PASS, FAIL, NOT_APPLICABLE, INCOMPLETE = "pass", "fail", "not_applicable", "incomplete"
RESULTS = (PASS, FAIL, NOT_APPLICABLE, INCOMPLETE)
STEPS = ("a", "b", "c", "d", "e", "f", "g")
CODE_STEPS = ("a", "b", "c", "d", "g")
STEP_NAMES = {
    "a": "limit_and_unit",
    "b": "evidence_source",
    "c": "fragments",
    "d": "conditions",
    "e": "engineer_check",
    "f": "owner_sample",
    "g": "quote_found",
}
MODEL_NONE = "none: code"

# --------------------------------------------------------------------------- the rule as a plain dict


def _quote_of(rule: dict) -> str:
    return " ".join(str(rule.get("quote") or "").split())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------- step a: limit and unit

_COMPARATOR_WORDS = (
    (
        re.compile(
            r"\b(?:maximum|max\.?|not\s+(?:to\s+)?exceed|no\s+more\s+than|not\s+more\s+than|at\s+most|up\s+to)\b"
        ),
        "<=",
    ),
    (
        re.compile(
            r"\b(?:minimum|min\.?|not\s+less\s+than|no\s+less\s+than|at\s+least)\b"
        ),
        ">=",
    ),
)


_LONE_UNIT = re.compile(r"\s+([A-Za-z])(?![A-Za-z0-9])")


def _figures(quote: str) -> tuple[claims.Measurement, ...]:
    """Numbers with a unit in the unit table: a bare number, a date or a part-number-like token is not a figure.

    `claims.extract_measurements` reads the unit written after a number; it sets aside a lone letter that follows a space
    ("15 m"), because "3 a coat" is a word. Here such a letter is read as a unit when `claims.is_unit` knows it and it is
    not the word "a". The numbers are numparse's; the unit table is claims'."""
    found = list(claims.extract_measurements(quote))
    have = {(numparse.as_limit(m.raw_value), m.raw_unit) for m in found}
    taken = {numparse.as_limit(m.raw_value) for m in found}
    for number in numparse.find_numbers(quote):
        if number.value is None or number.joined or number.value in taken:
            continue
        hit = _LONE_UNIT.match(quote, number.end)
        if (
            hit
            and hit.group(1) != "a"
            and claims.is_unit(hit.group(1))
            and (number.value, hit.group(1)) not in have
        ):
            found.append(
                claims.normalise(quote[number.start : number.end], hit.group(1))
            )
    return tuple(found)


def _number_of(m: claims.Measurement) -> float | None:
    return numparse.as_limit(m.raw_value) if m.raw_value is not None else None


def _unit_matches(rule_unit: str | None, m: claims.Measurement) -> bool:
    if not rule_unit or not m.raw_unit:
        return False
    return claims.same_unit(claims.Measurement("", rule_unit, None, None, None), m)


def _proposal(quote: str, figures: tuple[claims.Measurement, ...]) -> list[dict]:
    """What the quote implies for the empty fields. NEVER applied here: a person or a later reviewed step applies it."""
    lowered = quote.lower()
    out = []
    for m in figures:
        comparator, source = m.comparator, "stated_in_quote" if m.comparator else None
        if comparator is None:
            before = (
                lowered[: lowered.find(m.raw_value.lower())]
                if m.raw_value.lower() in lowered
                else lowered
            )
            for pattern, symbol in _COMPARATOR_WORDS:
                hit = list(pattern.finditer(before[-60:]))
                if hit:
                    comparator, source = symbol, "cue_word_before_figure"
                    break
        out.append(
            {
                "value": _number_of(m),
                "unit": m.raw_unit,
                "comparator": comparator,
                "comparator_source": source,
                "applied": False,
            }
        )
    return out


def limit_and_unit(rule: dict) -> tuple[str, str, dict]:
    """Step a. A figure (number + unit of the unit table) in the quote must be filled as value (or value_low and
    value_high) AND unit, and code verifies both stand inside the quote. No figure in the quote: not_applicable."""
    quote = _quote_of(rule)
    if not quote:
        return FAIL, "no_quote", {}
    figures = _figures(quote)
    value, low, high, unit = (
        rule.get("value"),
        rule.get("value_low"),
        rule.get("value_high"),
        rule.get("unit"),
    )
    filled = [v for v in (value, low, high) if _is_number(v)]
    evidence: dict = {"figures_in_quote": len(figures)}
    if not figures and not filled:
        return NOT_APPLICABLE, "no_figure_in_quote", evidence
    if figures and not filled:
        evidence["proposed"] = _proposal(quote, figures)
        return FAIL, "figure_not_filled", evidence
    # a value is filled: it must stand in the quote, and where the quote has a figure, so must its unit
    wanted = (
        [("value", value)]
        if _is_number(value)
        else [("value_low", low), ("value_high", high)]
    )
    if any(not _is_number(v) for _, v in wanted):
        return FAIL, "range_end_missing", evidence
    for name, v in wanted:
        if not numparse.value_in_text(v, quote):
            evidence["missing"] = name
            return FAIL, "value_not_in_quote", evidence
    if not figures:
        # the number stands in the quote with no unit of the table: a count or a ratio, which must say so
        if unit in (None, "", "none"):
            return PASS, "value_stands_no_unit_in_quote", evidence
        evidence["unit"] = unit
        return FAIL, "unit_not_in_quote", evidence
    if not unit or str(unit).lower() == "none":
        return FAIL, "unit_not_filled", evidence
    # each filled number stands in the quote (above); the unit stands beside at least one of them: "between 10 and 40 C"
    # prints it once, after the last number
    matched = [
        name
        for name, v in wanted
        if any(_number_of(m) == float(v) and _unit_matches(unit, m) for m in figures)
    ]
    if not matched:
        evidence["unit"] = unit
        same_number = any(_number_of(m) == float(v) for _, v in wanted for m in figures)
        return (
            FAIL,
            "unit_not_in_quote" if same_number else "value_not_in_quote",
            evidence,
        )
    return PASS, "value_and_unit_stand_in_quote", evidence


# --------------------------------------------------------------------------- step b: evidence source

DATASHEET_VALUE = "datasheet value"
DATASHEET_PRESENCE = "datasheet presence"
DRAWING, CALCULATION, TEST, PROCEDURE = "drawing", "calculation", "test", "procedure"
OWNER_DUTY, SOURCE_INCOMPLETE = "owner duty", "incomplete"
EVIDENCE_SOURCES = (
    DATASHEET_VALUE,
    DATASHEET_PRESENCE,
    DRAWING,
    CALCULATION,
    TEST,
    PROCEDURE,
    OWNER_DUTY,
    SOURCE_INCOMPLETE,
)

_SHEET = r"(?:data\s?sheets?|specification\s+sheets?|spec\.?\s+sheets?)"
_PRESENCE = (
    (
        "on the data sheet",
        re.compile(
            r"\b(?:shown|indicated|stated|specified|given|listed|reported|recorded|included|identified|marked|entered|"
            r"provided|noted)\b[^.;]{0,50}\b(?:on|in)\s+(?:the\s+|each\s+|every\s+|a\s+)?"
            + _SHEET
        ),
    ),
    (
        "data sheet shall show",
        re.compile(
            r"\b"
            + _SHEET
            + r"\b[^.;]{0,40}\b(?:shall|must|should)\s+(?:show|state|indicate|list|include|give|record)"
        ),
    ),
)
_CUES = (
    (
        DRAWING,
        (
            ("drawing", re.compile(r"\bdrawings?\b")),
            ("layout", re.compile(r"\blayouts?\b")),
            ("plot plan", re.compile(r"\bplot\s+plans?\b")),
            ("p&id", re.compile(r"\bp\s?&\s?ids?\b")),
            ("isometric", re.compile(r"\bisometrics?\b")),
        ),
    ),
    (
        CALCULATION,
        (
            ("calculat", re.compile(r"\bcalculat\w*")),
            ("sizing", re.compile(r"\bsizing\b|\bsized\b")),
            ("computed", re.compile(r"\bcomputed?\b|\bcomputation\b")),
        ),
    ),
    (
        TEST,
        (
            ("test", re.compile(r"\btest(?:s|ed|ing)?\b")),
            ("inspect", re.compile(r"\binspect\w*")),
            ("examination", re.compile(r"\bexamin(?:ation|ed)\b")),
            ("witness", re.compile(r"\bwitness\w*")),
        ),
    ),
    (
        PROCEDURE,
        (
            ("procedure", re.compile(r"\bprocedures?\b")),
            ("method", re.compile(r"\bmethods?\b(?!\s+of\s+(?:calculat|sizing))")),
        ),
    ),
    (
        OWNER_DUTY,
        (
            (
                "contractor shall",
                re.compile(
                    r"\b(?:contractor|vendor|supplier|manufacturer|subcontractor|purchaser)\b[^.;]{0,60}\b(?:shall|must)\b"
                ),
            ),
            (
                "shall be provided by",
                re.compile(
                    r"\b(?:shall|must)\b[^.;]{0,40}\b(?:by|from)\s+(?:the\s+)?(?:contractor|vendor|supplier|manufacturer|owner|company)\b"
                ),
            ),
        ),
    ),
)


def evidence_source(rule: dict) -> tuple[str, str, dict]:
    """Step b. Exactly one source of EVIDENCE_SOURCES by closed word rules on the rule's field and quote. The reason is
    the source; the evidence is the cue words that decided it (never the quote)."""
    text = (
        " ".join(str(rule.get("field") or "").split()) + " | " + _quote_of(rule)
    ).lower()
    has_number = _is_number(rule.get("value")) or (
        _is_number(rule.get("value_low")) and _is_number(rule.get("value_high"))
    )
    presence = [label for label, pattern in _PRESENCE if pattern.search(text)]
    if presence:
        return (
            PASS,
            DATASHEET_PRESENCE,
            {"source": DATASHEET_PRESENCE, "cues": presence, "has_limit": has_number},
        )
    for source, cues in _CUES:
        found = [label for label, pattern in cues if pattern.search(text)]
        if found:
            return PASS, source, {"source": source, "cues": found}
    if has_number and rule.get("field"):
        return (
            PASS,
            DATASHEET_VALUE,
            {"source": DATASHEET_VALUE, "cues": ["limit_on_field"]},
        )
    return INCOMPLETE, SOURCE_INCOMPLETE, {"source": SOURCE_INCOMPLETE, "cues": []}


# --------------------------------------------------------------------------- step c: fragments

_POINTER = (
    ("the following", re.compile(r"\bthe\s+following\b")),
    ("as follows", re.compile(r"\bas\s+follows\b")),
    ("below", re.compile(r"\bbelow\s*(?:[:.;,)]|$)")),
    (
        "listed",
        re.compile(
            r"\b(?:is|are|as|be)\s+listed\b|\blisted\s+(?:below|here|hereafter)\b"
        ),
    ),
    ("this data", re.compile(r"\b(?:this|these)\s+(?:data|information)\b")),
)
_MARKER = re.compile(
    r"(?:^|\s)(?:\(?[a-z]\)|\(?\d{1,2}\)|[a-z]\.(?=\s)|\d{1,2}\.(?=\s))\s"
)
_LINE_MARKER = re.compile(
    r"^\s*(?:[\u2022\u25cf\u25aa\u2013\u2014*-]|\(?[a-z]\)|\(?\d{1,2}\)|[a-z]\.|\d{1,2}\.)\s+\S"
)
_CLAUSE_HEAD = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s+\S")
_PAGE_FOOTER = re.compile(r"^\s*page\s+\d+", re.IGNORECASE)
_MAX_LIST_LINES = 60


def _pointers(quote: str) -> list[tuple[str, int]]:
    lowered = quote.lower()
    found = []
    for label, pattern in _POINTER:
        last = None
        for match in pattern.finditer(lowered):
            last = match
        if last is not None:
            found.append((label, last.end()))
    return found


def _holds_list(quote: str, after: int) -> bool:
    """The quote itself carries the list its pointer words point at: two or more list markers after the pointer, or a
    colon followed by a run of items separated by ; or , long enough to be a list."""
    tail = quote[after:]
    if len(_MARKER.findall(" " + tail)) >= 2:
        return True
    if ":" in tail:
        body = tail.split(":", 1)[1].strip()
        return len(body.split()) >= 6 and (";" in body or "," in body)
    return False


def _locate(quote: str, page: str) -> tuple[int, int] | None:
    words = quote.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, page, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def _list_after(text: str, start: int) -> tuple[int, int] | None:
    """(end offset, items) of the list that follows `start` in `text`, or None when no list follows."""
    rest = text[start:]
    if "\n" not in rest:
        return None
    first_break = rest.index("\n")
    pos = start + first_break + 1  # skip the rest of the quote's own line
    items, end, lines_seen, closed = 0, None, 0, False
    for line in text[pos:].splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            if items:
                break
            pos += len(line)
            continue
        if _PAGE_FOOTER.match(stripped) or _CLAUSE_HEAD.match(line):
            break
        if _LINE_MARKER.match(line):
            items += 1
        elif not items or closed:
            break  # not a list item, and not the wrapped end of one: a line that closed its item ends the list
        closed = stripped[-1] in ".;:"
        lines_seen += 1
        pos += len(line)
        end = pos
        if lines_seen >= _MAX_LIST_LINES:
            break
    if end is None or items < 2:
        return None
    return end, items


def _norm(text: str) -> str:
    return " ".join(text.split())


def rejoin(rule: dict, pages: dict[int, str] | None) -> tuple[str | None, dict]:
    """(joined text, info) with the quote followed by the list the standard prints after it (same page, then the next
    page), verified by code to be contiguous in the page text; or (None, {"reason": ...})."""
    quote = _quote_of(rule)
    page_no = rule.get("page")
    if not pages or page_no not in pages:
        return None, {"reason": "page_text_missing"}
    here = pages[page_no] or ""
    spot = _locate(quote, here)
    if spot is None:
        return None, {"reason": "quote_not_located"}
    following = pages.get(page_no + 1) or ""
    text = here + "\n" + following
    boundary = len(here) + 1
    found = _list_after(
        text, spot[1]
    )  # a quote that closes its page: the list opens the next page
    if found is None:
        return None, {"reason": "list_not_found"}
    end, items = found
    joined = text[spot[0] : end]
    if not _norm(joined).lower().startswith(_norm(quote).lower()):
        return None, {"reason": "join_not_contiguous"}
    if not quote_verified(joined, text):
        return None, {"reason": "join_not_contiguous"}
    pages_used = [page_no] + ([page_no + 1] if end > boundary else [])
    return joined, {
        "pages": pages_used,
        "items": items,
        "start": spot[0],
        "end": end,
        "joined_chars": len(joined),
        "joined_sha256": hashlib.sha256(_norm(joined).encode("utf-8")).hexdigest(),
    }


def fragments(rule: dict, pages: dict[int, str] | None = None) -> tuple[str, str, dict]:
    """Step c. A quote that points at a list it does not contain is rejoined with the list from the standard's own page
    text (verified contiguous) or is incomplete. No pointer words: not_applicable."""
    quote = _quote_of(rule)
    pointers = _pointers(quote)
    if not pointers:
        return NOT_APPLICABLE, "no_list_pointer", {"cues": []}
    cues = [label for label, _ in pointers]
    if all(_holds_list(quote, after) for _, after in pointers):
        return PASS, "list_in_quote", {"cues": cues}
    joined, info = rejoin(rule, pages)
    if joined is None:
        return INCOMPLETE, info["reason"], {"cues": cues}
    return PASS, "rejoined_with_list", {"cues": cues, **info}


# --------------------------------------------------------------------------- step d: conditions

#: Equipment types as the rulebook applicability names them, as a CLOSED list. Interim: Lane 2 replaces it with the
#: cleaned list of about 71 types; `EQUIPMENT_VOCAB` is the one place to change.
EQUIPMENT_VOCAB: tuple[tuple[str, re.Pattern], ...] = (
    (
        "pressure safety valve",
        re.compile(
            r"\b(?:pzvs?|psvs?|prvs?|relief\s+valves?|safety\s+valves?|pressure\s+(?:relief|safety)\s+valves?|pressure\s+relief\s+devices?|relief\s+devices?)\b"
        ),
    ),
    ("pump", re.compile(r"\bpumps?\b")),
    ("compressor", re.compile(r"\bcompressors?\b")),
    (
        "pressure vessel",
        re.compile(r"\b(?:pressure\s+vessels?|vessels?|separators?|drums?|columns?)\b"),
    ),
    ("tank", re.compile(r"\btanks?\b")),
    ("heat exchanger", re.compile(r"\b(?:heat\s+)?exchangers?\b")),
    ("piping", re.compile(r"\b(?:piping|pipelines?|pipes?)\b")),
    ("furnace", re.compile(r"\bfurnaces?\b|\bfired\s+heaters?\b")),
    ("motor", re.compile(r"\bmotors?\b")),
    ("transformer", re.compile(r"\btransformers?\b")),
    ("control valve", re.compile(r"\bcontrol\s+valves?\b")),
    ("valve", re.compile(r"\bvalves?\b")),
)
_UNCONDITIONAL = frozenset({"in all cases", "always", "at all times", "in every case"})
CONDITION_KINDS = (
    "size",
    "temperature",
    "pressure",
    "material",
    "service",
    "class",
    "pn",
)


def equipment_types_in(text: str) -> list[str]:
    lowered = " ".join(str(text or "").lower().split())
    return [label for label, pattern in EQUIPMENT_VOCAB if pattern.search(lowered)]


def _read_condition(text: str):
    from . import conditions  # heavy import, only when a condition row needs it

    return conditions.read_condition(text)


def conditions_of(rule: dict) -> tuple[str, str, dict]:
    """Step d. Every applicability row becomes a testable condition of a closed vocabulary, or the rule is incomplete.
    A `subject` row must name a type of the equipment vocabulary; a `condition` row must be read whole by the repo's
    condition reader (kinds: size, temperature, pressure, material, service, class, pn); numbers by numparse."""
    rows = [
        (str(k), " ".join(str(v).split())) for k, v in (rule.get("applicability") or ())
    ]
    equipment: list[str] = []
    tests: list[dict] = []
    problems: list[dict] = []
    for key_type, value in rows:
        if key_type == "equipment_type":
            found = equipment_types_in(value) or [value.lower()]
            equipment.extend(found)
        elif key_type == "subject":
            found = equipment_types_in(value)
            if found:
                equipment.extend(found)
            else:
                problems.append(
                    {"row": key_type, "why": "subject_not_in_equipment_vocabulary"}
                )
        elif key_type in (
            "condition",
            "service",
            "pressure_class",
            "size_range",
            "material_group",
        ):
            if value.lower().strip(" .") in _UNCONDITIONAL:
                tests.append({"kind": "always", "text": None})
                continue
            reading = _read_condition(value)
            if reading is None:
                problems.append({"row": key_type, "why": "condition_not_read"})
            elif reading.problem:
                problems.append({"row": key_type, "why": "condition_part_not_read"})
            else:
                for need in reading.needs:
                    tests.append(
                        {
                            "kind": need.kind,
                            "low": need.low,
                            "high": need.high,
                            "low_open": need.low_open,
                            "high_open": need.high_open,
                            "value": need.value,
                        }
                    )
        else:
            problems.append({"row": key_type, "why": "row_type_not_in_vocabulary"})
    evidence = {
        "equipment_types": sorted(set(equipment)),
        "tests": tests,
        "rows": len(rows),
    }
    if problems:
        evidence["problems"] = problems
        return INCOMPLETE, problems[0]["why"], evidence
    if not rows:
        return INCOMPLETE, "no_applicability_rows", evidence
    return PASS, "conditions_testable", evidence


# --------------------------------------------------------------------------- step g: quote found


def quote_found(rule: dict, pages: dict[int, str] | None) -> tuple[str, str, dict]:
    """Step g. The rule's quote stands on its cited page of the standard (the repo's one quote check). Not found: fail
    `quote_not_found`; and a rule whose g is not pass never decides (`may_decide`)."""
    quote = _quote_of(rule)
    page_no = rule.get("page")
    evidence = {"page": page_no, "document": rule.get("standard_document_id")}
    if not quote:
        return FAIL, "no_quote", evidence
    if not pages or page_no not in pages or not (pages.get(page_no) or "").strip():
        return FAIL, "page_text_missing", evidence
    if quote_verified(quote, pages[page_no]):
        return PASS, "quote_found", evidence
    return FAIL, "quote_not_found", evidence


# --------------------------------------------------------------------------- one rule, all code steps


def run_steps(
    rule: dict, pages: dict[int, str] | None
) -> dict[str, tuple[str, str, dict]]:
    """Steps a, b, c, d and g for one rule. Never swallows an error: an exception goes to the caller."""
    return {
        "a": limit_and_unit(rule),
        "b": evidence_source(rule),
        "c": fragments(rule, pages),
        "d": conditions_of(rule),
        "g": quote_found(rule, pages),
    }


# --------------------------------------------------------------------------- may decide, finished


def _result_of(step: Any) -> str | None:
    if step is None:
        return None
    if isinstance(step, str):
        return step
    if isinstance(step, dict):
        return step.get("result")
    if isinstance(step, (tuple, list)) and step:
        return step[0]
    return getattr(step, "result", None)


class FinishStatus(NamedTuple):
    status: str  # FINISHED | NOT_FINISHED
    blocking: str | None  # the first blocking step, None when finished
    reason: str | None


FINISHED, NOT_FINISHED = "FINISHED", "NOT_FINISHED"
_ALLOWED = {
    "a": (PASS, NOT_APPLICABLE),
    "b": (PASS, NOT_APPLICABLE),
    "c": (PASS, NOT_APPLICABLE),
    "d": (PASS, NOT_APPLICABLE),
    "e": (PASS,),
    "f": (PASS,),
    "g": (PASS,),
}
#: g first: nothing stands without its quote. Then a to f.
_ORDER = ("g", "a", "b", "c", "d", "e", "f")


def finish_status(rule_steps: dict) -> FinishStatus:
    """FINISHED only when a, b, c, d, g are pass or not_applicable (g only pass), e (the AI engineer check) is pass and
    f (the owner sample of its folder) is pass; else NOT_FINISHED with the first blocking step."""
    steps = rule_steps or {}
    for name in _ORDER:
        got = _result_of(steps.get(name))
        if got is None:
            return FinishStatus(NOT_FINISHED, name, "missing")
        if got not in _ALLOWED[name]:
            return FinishStatus(NOT_FINISHED, name, got)
    return FinishStatus(FINISHED, None, None)


def may_decide(rule_steps: dict) -> bool:
    """Only a finished rule decides. A rule whose quote is not found (g not pass) NEVER decides, nor one with a, b, c or
    d failed or incomplete, nor one whose e (engineer check) or f (owner sample) is missing or not pass."""
    return finish_status(rule_steps).status == FINISHED


# --------------------------------------------------------------------------- persistence (a COPY of a database only)

_TABLE = """CREATE TABLE IF NOT EXISTS rule_finish_step (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version_id TEXT NOT NULL,
    step TEXT NOT NULL CHECK (step IN ('a','b','c','d','e','f','g')),
    result TEXT NOT NULL CHECK (result IN ('pass','fail','not_applicable','incomplete')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    checker TEXT NOT NULL,
    model TEXT NOT NULL,
    run_id TEXT NOT NULL,
    at TEXT NOT NULL)"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_rule_finish_step ON rule_finish_step(rule_version_id, step, id)"


def ensure_table(conn: sqlite3.Connection) -> None:
    """Create `rule_finish_step` (append-only history; the latest row per rule version and step is the current one)."""
    conn.execute(_TABLE)
    conn.execute(_INDEX)
    conn.commit()


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_step(
    conn: sqlite3.Connection,
    rule_version_id: str,
    step: str,
    result: str,
    reason: str,
    evidence: dict | None = None,
    *,
    checker: str,
    model: str,
    run_id: str,
    at: str | None = None,
) -> int:
    """Append one step result. Steps e (AI engineer check) and f (owner sample) are written here by their own processes;
    both must name who checked."""
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}")
    if result not in RESULTS:
        raise ValueError(f"unknown result {result!r}")
    if step in ("e", "f") and not (checker or "").strip():
        raise ValueError(f"step {step} needs a named checker")
    if (
        not (reason or "").strip()
        or not (run_id or "").strip()
        or not (model or "").strip()
    ):
        raise ValueError("reason, model and run_id are required")
    ensure_table(conn)
    cur = conn.execute(
        "INSERT INTO rule_finish_step (rule_version_id, step, result, reason, evidence_json, checker, model, run_id, at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            rule_version_id,
            step,
            result,
            reason,
            json.dumps(evidence or {}, sort_keys=True),
            checker or "",
            model,
            run_id,
            at or now_utc(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_steps(conn: sqlite3.Connection, rule_version_id: str) -> dict[str, dict]:
    """The current row per step for one rule version ({} when none, or when the table does not exist)."""
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT s.* FROM rule_finish_step s WHERE s.rule_version_id = ? AND s.id = "
            "(SELECT MAX(id) FROM rule_finish_step t WHERE t.rule_version_id = s.rule_version_id AND t.step = s.step)",
            (rule_version_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {}
        raise
    out = {}
    for row in rows:
        r = dict(row)
        r["evidence"] = json.loads(r.pop("evidence_json") or "{}")
        out[r["step"]] = r
    return out


# --------------------------------------------------------------------------- reading rules (any rulebook copy)


def load_rules(
    conn: sqlite3.Connection,
    *,
    standard: str | None = None,
    key_prefix: str | None = None,
) -> list[dict]:
    """The latest version of every rule of `standard` (or whose rule_key starts with `key_prefix`), with its first
    provenance and its applicability rows, as plain dicts. Read only."""
    conn.row_factory = sqlite3.Row
    where, args = [], []
    if standard:
        where.append("r.standard = ?")
        args.append(standard)
    if key_prefix:
        where.append("r.rule_key LIKE ? ESCAPE '\\'")
        args.append(
            key_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
    if not where:
        raise ValueError("give a standard or a rule key prefix")
    sql = (
        "SELECT r.id AS rule_id, r.rule_key, r.standard, v.id AS version_id, v.version_no, v.kind, v.field, v.comparator, "
        "v.value, v.value_low, v.value_high, v.value_text, v.unit, v.unit_dimension, v.strength, v.sentence_strength, "
        "v.context_flag FROM rulebook_rule r JOIN rulebook_version v ON v.rule_id = r.id "
        "WHERE "
        + " AND ".join(where)
        + " AND v.version_no = (SELECT MAX(version_no) FROM rulebook_version x WHERE x.rule_id = r.id) "
        "ORDER BY r.rule_key"
    )
    rules = []
    for row in conn.execute(sql, args).fetchall():
        rule = dict(row)
        prov = conn.execute(
            "SELECT standard_document_id, edition, clause, page, quote, quote_start, quote_end, page_source "
            "FROM rulebook_provenance WHERE rule_version_id = ? ORDER BY id LIMIT 1",
            (rule["version_id"],),
        ).fetchone()
        if prov is not None:
            rule.update(dict(prov))
        rule["applicability"] = [
            (a["key_type"], a["value"])
            for a in conn.execute(
                "SELECT key_type, value FROM rulebook_applicability WHERE rule_version_id = ? ORDER BY id",
                (rule["version_id"],),
            )
        ]
        rules.append(rule)
    return rules
