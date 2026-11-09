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
Persistence (the table `rule_finish_step`, reading rules, applying a proposal) is in `rule_finish_store`, which imports this module.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, NamedTuple

from . import rule_finish_figures as ff
from .compiled_rule_proof import quote_verified

COMPARATORS_ALLOWED = (">=", ">", "<=", "<", "=", "!=")
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


def _stored_figures(rule: dict) -> list[tuple[float, str, str | None]]:
    """(value, unit, comparator) of every figure the rule stores: a limit, the two ends of a range, or each of `figures`."""
    unit = rule.get("unit")
    if rule.get("figures"):
        return [
            (float(f["value"]), f.get("unit") or unit, rule.get("comparator"))
            for f in rule["figures"]
        ]
    if _is_number(rule.get("value")):
        return [(float(rule["value"]), unit, rule.get("comparator"))]
    if _is_number(rule.get("value_low")) and _is_number(rule.get("value_high")):
        return [
            (float(rule["value_low"]), unit, ">="),
            (float(rule["value_high"]), unit, "<="),
        ]
    return []


def _same_figures(stored: list, confirmed: list) -> bool:
    """The engineer's confirmed figures equal the stored ones exactly: the same values, units and comparators."""
    left = sorted((round(v, 9), str(u).lower(), c) for v, u, c in stored)
    right = sorted(
        (
            round(float(f.get("value", "nan")), 9),
            str(f.get("unit")).lower(),
            f.get("comparator"),
        )
        for f in confirmed
    )
    return bool(stored) and left == right


def _proposal(reading) -> list[dict]:
    """What the quote implies for the empty fields, ONLY where code can read the comparator (the simple shape or a closed
    range); otherwise the engineer is required. NEVER applied here."""
    if reading.shape == "simple":
        ends = [(reading.figures[0], reading.comparator)]
    elif reading.shape == "range":
        ends = [(reading.figures[0], ">="), (reading.figures[1], "<=")]
    else:
        return []
    return [
        {"value": f.value, "unit": f.unit, "comparator": c, "applied": False}
        for f, c in ends
    ]


def _stands_with_unit(figures, stored: list, evidence: dict):
    """Every stored figure stands in the quote WITH its unit (the repo's unit comparison); the failing verdict or None."""
    for value, unit, _ in stored:
        if not unit or str(unit).lower() == "none":
            return FAIL, "unit_not_filled", evidence
        hits = [f for f in figures if f.value == value and ff.unit_matches(unit, f)]
        if not hits:
            evidence["unit"] = unit
            same_number = any(f.value == value for f in figures)
            return (
                FAIL,
                "unit_not_in_quote" if same_number else "value_not_in_quote",
                evidence,
            )
    return None


def limit_and_unit(rule: dict) -> tuple[str, str, dict]:
    """Step a, simple and closed. PASS only when every stored figure and its unit stand in the quote (numparse, the unit
    table), every unit figure of the quote is stored (or confirmed by the engineer), and the comparator is either decided
    by code in the simple shape (one figure, one table phrase directly governing it) or confirmed by the engineer's
    confirmed_figures for this exact version and content. A quote whose figure or unit cannot be read with certainty is
    INCOMPLETE; NOT_APPLICABLE only where the quote has no figure at all."""
    quote = _quote_of(rule)
    if not quote:
        return FAIL, "no_quote", {}
    reading = ff.read(quote)
    if reading.incomplete:
        return (
            INCOMPLETE,
            reading.incomplete,
            {"figures_in_quote": len(reading.figures)},
        )
    figures, stored = reading.figures, _stored_figures(rule)
    evidence: dict = {"figures_in_quote": len(figures), "shape": reading.shape}
    if not figures and not stored:
        return NOT_APPLICABLE, "no_figure_in_quote", evidence
    if figures and not stored:
        evidence["proposed"] = _proposal(reading)
        evidence["engineer_required"] = reading.shape == "complex"
        return FAIL, "figure_not_filled", evidence
    for value, _, _ in stored:
        if not ff.stands(value, reading.text):
            return FAIL, "value_not_in_quote", evidence
    if not figures:  # a bare number: the engineer reads what it is a limit of
        return _confirmed_or(rule, stored, evidence)
    verdict = _stands_with_unit(figures, stored, evidence)
    if verdict:
        return verdict
    if len(stored) == 2 and rule.get("value") is None and stored[0][0] > stored[1][0]:
        return FAIL, "range_order", evidence
    confirmed = rule.get("confirmed_figures") or []
    lone = [
        f
        for f in figures
        if not any(f.value == v and ff.unit_matches(u, f) for v, u, _ in stored)
    ]
    if any(
        not any(
            f.value == float(c.get("value", "nan"))
            and ff.unit_matches(c.get("unit"), f)
            for c in confirmed
        )
        for f in lone
    ):
        return INCOMPLETE, "unaccounted_figures", evidence
    if reading.shape == "simple" and len(stored) == 1:
        if stored[0][2] != reading.comparator:
            return FAIL, "comparator_mismatch", evidence
        return PASS, "value_and_unit_stand_in_quote", evidence
    if reading.shape == "range" and rule.get("value") is None and len(stored) == 2:
        return PASS, "value_and_unit_stand_in_quote", evidence
    return _confirmed_or(rule, stored, evidence)


def _confirmed_or(rule: dict, stored: list, evidence: dict):
    """The comparator is not decided by code in this shape: it passes only on the engineer's confirmed figures."""
    if _same_figures(stored, rule.get("confirmed_figures") or []):
        return PASS, "comparator_confirmed_by_engineer", evidence
    return INCOMPLETE, "comparator_needs_engineer", evidence


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

#: Words of a rule's field that name a quantity a datasheet field can hold (step b, closed list).
QUANTITY_CUES = (
    "size",
    "dimension",
    "diameter",
    "length",
    "thickness",
    "width",
    "height",
    "rating",
    "setting",
    "pressure",
    "temperature",
    "capacity",
    "clearance",
    "distance",
    "flow",
    "speed",
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
    has_number = (
        _is_number(rule.get("value"))
        or (_is_number(rule.get("value_low")) and _is_number(rule.get("value_high")))
        or bool(rule.get("figures"))
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
    # a size, dimension, rating or setting a datasheet field can hold, with a figure in the quote: closed cue list
    quantity = [
        word
        for word in QUANTITY_CUES
        if re.search(rf"\b{word}s?\b", str(rule.get("field") or "").lower())
    ]
    if quantity and ff.figures(_quote_of(rule)):
        return (
            PASS,
            DATASHEET_VALUE,
            {"source": DATASHEET_VALUE, "cues": [*quantity, "figure_in_quote"]},
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
#: How a connection is made: the closed words a connection-type condition may use (the repo's own vocabulary of
#: end connections: threaded/screwed, flanged, welded, socketweld, buttweld).
CONNECTION_WORDS = {
    "threaded": "threaded",
    "screwed": "threaded",
    "flanged": "flanged",
    "welded": "welded",
    "socket-welded": "socket welded",
    "socket welded": "socket welded",
    "butt-welded": "butt welded",
    "butt welded": "butt welded",
}
_UNCONDITIONAL = frozenset({"in all cases", "always", "at all times", "in every case"})


def equipment_types_in(text: str) -> list[str]:
    lowered = " ".join(str(text or "").lower().split())
    return [label for label, pattern in EQUIPMENT_VOCAB if pattern.search(lowered)]


def _read_condition(text: str):
    from . import conditions  # heavy import, only when a condition row needs it

    return conditions.read_condition(text)


def _connection_types(text: str) -> list[str]:
    folded = " ".join(str(text or "").lower().split())
    return sorted(
        {
            kind
            for word, kind in CONNECTION_WORDS.items()
            if re.search(rf"\b{re.escape(word)}\b", folded)
        }
    )


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
        if key_type in ("equipment_type", "subject"):
            found = equipment_types_in(value)
            if found:
                equipment.extend(found)
            else:
                why = (
                    "equipment_type_not_in_vocabulary"
                    if key_type == "equipment_type"
                    else "subject_not_in_equipment_vocabulary"
                )
                problems.append({"row": key_type, "why": why})
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
            connection = _connection_types(value)
            if connection:
                tests.append({"kind": "connection_type", "values": connection})
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
    for text in rule.get("exceptions") or ():
        text = " ".join(str(text).split())
        kinds = _connection_types(text)
        types = equipment_types_in(text)
        if kinds or types:
            tests.append(
                {"kind": "exception", "equipment_types": types, "connection": kinds}
            )
        else:
            problems.append({"row": "exception", "why": "exception_not_read"})
    evidence = {
        "equipment_types": sorted(set(equipment)),
        "tests": tests,
        "rows": len(rows) + len(rule.get("exceptions") or ()),
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
            # a check bound to another version or quote is stale: it never counts
            return FinishStatus(
                NOT_FINISHED, name, f"{name}_stale" if got == "stale" else got
            )
    return FinishStatus(FINISHED, None, None)


def may_decide(rule_steps: dict) -> bool:
    """Only a finished rule decides. A rule whose quote is not found (g not pass) NEVER decides, nor one with a, b, c or
    d failed or incomplete, nor one whose e (engineer check) or f (owner sample) is missing or not pass."""
    return finish_status(rule_steps).status == FINISHED
