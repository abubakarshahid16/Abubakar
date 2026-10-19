"""AI applicability (#647, #677): the model proposes, code confirms.

For a clause still in a review's scope after the code gates, the model answers
whether it applies to THIS equipment and service: yes / no / unsure, a reason
category, and the words of the clause it rests on. "AI reads, code checks":

  * the quote must be in the clause;
  * a "no" counts only when CODE can confirm its reason from stated facts:
      other_equipment            the equipment vocabulary (`subject_scope`)
                                 reads the quote as about equipment this
                                 submittal is not;
      service_condition_not_met  the quote names a service condition
                                 (`service_scope`) the datasheet declares
                                 absent;
      definition                 the quote is a defining sentence
                                 (`requirement_quality`);
      informative_note           the quote is a note ("NOTE", "Informative",
                                 "Commentary") with no "shall"/"must";
  * anything else - "unsure", an unconfirmed "no", a quote not in the clause,
    a reply that could not be read - leaves the clause a CHECK. Unsure is
    never dropped (#647); the engineer sees what the model suggested.

OFF by default (`settings.ai_applicability_enabled`) and capped per run
(`ai_applicability_max_per_run`); the model is the runner's setting (#683).

#141, per DIVISION of a standard (`division_gate`, below; ON by default,
`settings.ai_division_scope_enabled`): a part or appendix whose own scope
sentence limits it to one construction or material applies only to equipment
of that construction - the model reads the sentence and what the datasheet
states, code verifies both quotes and decides "not that construction" only
from the stated material; what code cannot decide is held for the engineer.
Nothing here names a standard or a datasheet.
"""
from __future__ import annotations

import bisect
import re

from . import ai_task_runner, requirement_quality, scope_ledger, service_scope, subject_scope
from .ai import output_limits

CATEGORIES = ["other_equipment", "service_condition_not_met", "informative_note",
              "definition", "none"]

SCHEMA = {
    "type": "object",
    "required": ["applies", "reason", "quote"],
    "properties": {
        "applies": {"type": "string", "enum": ["yes", "no", "unsure"]},
        "reason": {"type": "string", "enum": CATEGORIES},
        "quote": {"type": ["string", "null"]},
    },
}

INSTRUCTION = """You decide whether one clause of an engineering standard applies
to one submittal. The EQUIPMENT and SERVICE lines describe the submittal; the
CLAUSE line is the clause. Answer:
- applies: "yes", "no" or "unsure";
- reason: when "no", why - "other_equipment" (the clause is about a different
  kind of equipment), "service_condition_not_met" (it applies only in a service
  this submittal is not in), "informative_note" (a note, not a requirement), or
  "definition"; otherwise "none";
- quote: the exact words of the clause your answer rests on.
Say "unsure" whenever the clause and the submittal do not settle it."""

TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="clause_applicability", version="v1", instruction=INSTRUCTION, schema=SCHEMA,
    num_predict=output_limits.max_tokens_for(output_limits.ROUTE_CLAUSE_APPLICABILITY)))

_NOTE = re.compile(r"^\s*(?:note|notes|informative|commentary)\b", re.IGNORECASE)
_MANDATORY = re.compile(r"\b(?:shall|must|is required|are required)\b", re.IGNORECASE)


def _squash(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def context(classification: dict | None, facts: list[dict]) -> str:
    """The EQUIPMENT and SERVICE lines: what the submittal itself states."""
    equipment = (classification or {}).get("equipment_type") or "not stated"
    service = [f"{f.get('field_label')}: {f.get('field_value') or f.get('raw_value')}"
               for f in facts if not f.get("is_blank") and re.search(
                   r"service|fluid|h2s|sour|nace|temperature|pressure",
                   str(f.get("field_label") or ""), re.IGNORECASE)][:8]
    return f"EQUIPMENT: {equipment}\nSERVICE: {'; '.join(service) or 'not stated'}"


def confirm(reason: str, quote: str, *, equipment: set[str], facts: list[dict]) -> bool:
    """Can CODE confirm the model's "does not apply" from stated facts?"""
    if reason == "other_equipment":
        subject, _ = subject_scope.requirement_subject(
            {"requirement_text": quote}, {}, subject_scope.vocabulary())
        return bool(subject) and bool(equipment) and not (subject & equipment)
    if reason == "service_condition_not_met":
        for c in service_scope.conditions():
            d = service_scope.declaration(c, facts)
            if d is not None and d["present"] is False and service_scope.specific_to(
                    c, {"requirement_text": quote}, ""):
                return True
        return False
    if reason == "definition":
        return requirement_quality.is_defining_sentence(quote)
    if reason == "informative_note":
        return bool(_NOTE.match(quote)) and not _MANDATORY.search(quote)
    return False


def gate(requirements: list[dict], *, classification: dict | None, facts: list[dict],
         provider=None, limit: int | None = None) -> dict:
    """{"kept", "items" (confirmed "does not apply", as {"requirement", "code",
    "detail", "decided_by"}), "notes" {requirement id: what the model suggested
    that code did not confirm}, "asked", "not_asked"}."""
    vocab = subject_scope.vocabulary()
    equipment, _ = subject_scope.submittal_equipment(classification, facts, vocab)
    head = context(classification, facts)
    model = getattr(provider, "requested_model", None) or ai_task_runner.settings.ai_task_model
    kept: list[dict] = []
    items: list[dict] = []
    notes: dict = {}
    asked = 0
    for requirement in requirements:
        clause = (requirement.get("source_text") or requirement.get("requirement_text") or "").strip()
        if limit is not None and asked >= limit or not clause:
            kept.append(requirement)
            continue
        asked += 1
        result = ai_task_runner.run_task(TASK, f"{head}\nCLAUSE: {clause}", provider=provider)
        data = result.data if result.state == ai_task_runner.STATE_OK else None
        if not data or data.get("applies") == "yes":
            kept.append(requirement)
            continue
        quote = data.get("quote") or ""
        in_clause = bool(quote.strip()) and _squash(quote) in _squash(clause)
        reason = data.get("reason") or "none"
        if (data.get("applies") == "no" and in_clause and reason in scope_ledger.REASONS
                and confirm(reason, quote, equipment=equipment, facts=facts)):
            items.append({"requirement": requirement, "code": reason,
                          "detail": (f"{scope_ledger.REASONS[reason][1]}: proposed by the "
                                     f"model, confirmed by code; quoted: \"{quote.strip()}\""),
                          "decided_by": f"ai:{model}+code"})
            continue
        kept.append(requirement)
        said = (f'; it quoted: "{quote.strip()}"' if in_clause else "")
        notes[requirement.get("id")] = (
            "the model was unsure whether it applies" if data.get("applies") == "unsure"
            else f"the model said it may not apply ({reason.replace('_', ' ')}); "
                 f"code could not confirm it{said}")
    return {"kept": kept, "items": items, "notes": notes, "asked": asked,
            "not_asked": len(requirements) - asked}


# --------------------------------------- #141: a division's own scope sentence
# Where a standard's DIVISIONS (parts, appendices, annexes, chapters) are, and
# where each requirement sits; the gate is below. No standard or part is named:
# the words are the structural words standards use for a top-level division.

#: A division heading: the structural word, a short id (a number, or one to
#: four capitals with an optional "-A" letter), then the end of the line or a
#: title (`subject_scope._TITLE_REST`). The word is capitalised ("Part",
#: "PART"): a "part" inside a wrapped sentence is not a heading, and neither
#: is "Part 3 of this" (a lower-case word follows the id).
_DIVISION = re.compile(
    r"^(?:(?i:(?:non-?)?mandatory|normative|informative)\s+)?"
    r"(?:P(?i:art)|A(?i:ppendix|nnex)|C(?i:hapter))\s+"
    r"(?P<id>\d{1,3}[A-Z]?|[A-Z]{1,4}(?:-[A-Z]{1,2})?)(?![A-Za-z0-9])"
    + subject_scope._TITLE_REST
)
#: A contents-page entry: a heading with a title that ends in a page number.
_CONTENTS_TAIL = re.compile(r"[A-Za-z)]\s*[.\s]*\s\d{1,4}$")
#: A division heading is among this many first lines of its page.
_DIVISION_TOP = 5
#: How far into a division its scope clause is looked for (lines), and how
#: many words of the division the model reads.
_SCOPE_LOOK = 160
SCOPE_WORDS = 170
_SCOPE_LINE = re.compile(r"\bscope\b", re.IGNORECASE)


def divisions(text: subject_scope.StandardText) -> list[dict]:
    """The divisions of a standard and the lines that end them, in order:
    {"at" (offset in the folded text), "line" (index), "name", "heading"}.

    A division STARTS A PAGE: its heading is among the first lines of a page
    (`_DIVISION_TOP`), and that page holds no other heading-like line. EVERY
    other heading-like line - a wrapped cross-reference ("... see" / "Part
    X"), a heading below the top of a page, a page with two of them, a
    contents entry - ENDS the division it is in: it is a break (name None),
    and what follows it sits in no division until the next start, so it stays
    a check. A missed heading can therefore never lend the division before it
    to the next one's requirements. A running header, and a heading repeated
    for the division it is already in (a "(continued)" title), are neither."""
    out: list[dict] = []
    for lo, hi in text.page_bounds.values():
        first = bisect.bisect_left(text.offsets, lo, hi=len(text.lines))
        heads: list[tuple[int, tuple[str, str], bool]] = []
        for index in range(first, len(text.lines)):
            if text.offsets[index] >= hi:
                break
            line = text.lines[index]
            match = _DIVISION.match(line)
            if match is None or re.sub(r"\d+", "#", line) in text.running:
                continue
            listed = bool(line[match.end("id") :].strip()) and bool(
                _CONTENTS_TAIL.search(line)
            )
            # the division's name: its structural word and id ("appendix 9")
            word = line[: match.start("id")].split()[-1].casefold()
            heads.append((index, (word, match.group("id").upper()), listed))
        if not heads:
            continue
        top, _name, listed = heads[0]
        starts = (
            len({name for _i, name, _l in heads}) == 1
            and not listed
            and top - first < _DIVISION_TOP
        )
        for index, name, _listed in heads:
            if out and out[-1]["name"] == name:
                continue
            out.append(
                {
                    "at": text.offsets[index],
                    "line": index,
                    "name": name if starts and index == top else None,
                    "heading": text.lines[index],
                }
            )
    return out


def division_of(
    requirement: dict, text: subject_scope.StandardText, divs: list[dict]
) -> dict | None:
    """The division a requirement sits in, or None when it sits before the
    first one, after a break, or cannot be placed: where its sentence sits in
    the text first, else its page (a division starts a page) - a page that
    holds a break is in none."""
    at = text.place(requirement)
    if at is None:
        bounds = text.page_bounds.get(subject_scope._page_of(requirement))
        if bounds is None or bounds[1] <= bounds[0]:
            return None
        if any(d["name"] is None and bounds[0] <= d["at"] < bounds[1] for d in divs):
            return None
        at = bounds[1] - 1
    inside = [d for d in divs if d["at"] <= at]
    return inside[-1] if inside and inside[-1]["name"] is not None else None


#: The heading and the lines right after it: always read.
_OPENING = 4


def scope_passage(text: subject_scope.StandardText, div: dict, end: int | None) -> str:
    """What the model reads of a division: its heading and the lines right
    after it, then its OWN scope clause - the first line naming "scope" in the
    division's first clause (before a second sub-clause heading) - up to the
    next sub-clause heading, at most `SCOPE_WORDS` words, never past the
    division's end (`end`: the next start or break). A scope line of a later
    sub-clause is never read as the division's: with none in the first
    clause, only the opening is read."""
    stop = len(text.lines) if end is None else end
    first = div["line"]
    opening = min(first + _OPENING, stop)
    scope_at = None
    subs = 0
    for i in range(first + 1, min(first + _SCOPE_LOOK, stop)):
        # the heading first: a scope line of the SECOND sub-clause is not the
        # division's own
        if subject_scope._heading(text.lines[i]) is not None:
            subs += 1
            if subs > 1:
                break
        if _SCOPE_LINE.search(text.lines[i]):
            scope_at = i
            break
    words: list[str] = " ".join(text.lines[first:opening]).split()
    if scope_at is not None:
        for i in range(max(scope_at, opening), stop):
            if i > scope_at and subject_scope._heading(text.lines[i]) is not None:
                break
            if len(words) >= SCOPE_WORDS:
                break
            words.extend(text.lines[i].split())
    return " ".join(words[:SCOPE_WORDS])


def folded_in(needle: object, haystack: object, *, least: int = 1) -> bool:
    """Is `needle` in `haystack`, compared on letters and digits only (so a
    word hyphenated over a line break still matches)?"""
    key = subject_scope._key(needle)
    return len(key) >= least and key in subject_scope._key(haystack)


# ------------------------------------------- #141: a division's own scope
# A division may limit itself in its own scope sentence to one construction
# (order 141: such a part was checked against an ordinary vessel). Per division
# that holds requirements of this run:
#   1. the model reads the division's heading and scope clause
#      (`scope_passage`) and says whether it is limited, with
#      the construction's words and the scope sentence; CODE checks that the
#      sentence is in the standard's text and the words in the sentence;
#   2. the model reads what the datasheet STATES about the equipment's
#      material and construction and says whether the equipment is of that
#      construction, quoting the stated line; CODE checks the quote is a
#      stated line whose value does not itself name the construction;
#   3. CODE decides "not that construction", never the model alone: only when
#      no stated value anywhere on the datasheet names the construction, and
#      the stated line names ANOTHER member of the same exclusive material
#      family (`conditions`, #920). The model's "yes" keeps it a check.
# Anything code cannot decide is held for the engineer (`applicability_unsure`).
# A model that is off, fails, stops answering or gives a reply code cannot
# verify changes nothing: every requirement stays a check.

SCOPE_SCHEMA = {
    "type": "object",
    "required": ["limited", "construction", "quote"],
    "properties": {
        "limited": {"type": "string", "enum": ["yes", "no", "unsure"]},
        "construction": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"]},
    },
}

SCOPE_INSTRUCTION = """The TEXT is the start of one division (a part, appendix,
annex or chapter) of an engineering standard: its heading, its title and its
scope clause. Answer:
- limited: "yes" when the division's OWN scope says it applies only to
  equipment of one particular construction, material or kind (for example
  "applies to vessels constructed of <a material>"); "no" when it applies to
  all the equipment the standard covers or names no such limit; "unsure" when
  the text does not settle it;
- construction: when "yes", the few words of the scope sentence that name
  that construction, material or kind, copied exactly; otherwise null;
- quote: when "yes", the scope sentence, copied exactly from the TEXT;
  otherwise null."""

#: The least length (letters and digits) of a scope sentence that is checked.
_QUOTE_MIN = 16


def _scope_problems(data: dict, text: str) -> list[str]:
    """Code's check of a "limited" reading: the sentence is in the standard's
    text, and the construction's words are in the sentence."""
    if data.get("limited") != "yes":
        return []
    quote, construction = data.get("quote") or "", data.get("construction") or ""
    if not folded_in(quote, text, least=_QUOTE_MIN):
        return ["the quote is not in the TEXT"]
    if not folded_in(construction, quote, least=3):
        return ["the construction is not in the quote"]
    return []


SCOPE_TASK = ai_task_runner.register(
    ai_task_runner.TaskSpec(
        name="division_scope",
        version="v1",
        instruction=SCOPE_INSTRUCTION,
        schema=SCOPE_SCHEMA,
        check=_scope_problems,
        num_predict=output_limits.max_tokens_for(
            output_limits.ROUTE_CLAUSE_APPLICABILITY
        ),
    )
)

CONSTRUCTION_SCHEMA = {
    "type": "object",
    "required": ["equipment_is", "quote", "is_that"],
    "properties": {
        "equipment_is": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"]},
        "is_that": {"type": "string", "enum": ["yes", "no", "unsure"]},
    },
}

CONSTRUCTION_INSTRUCTION = """The CONSTRUCTION line names the construction,
material or kind of equipment that one division of a standard is limited to.
The STATED lines are what a submittal's datasheet states about its equipment.
Answer:
- equipment_is: what the datasheet says the equipment itself, or one of its
  main parts, is constructed of or made of, in the datasheet's words; null
  when it does not say;
- quote: the STATED line that says it, copied exactly; null when none does;
- is_that: "yes" when the equipment or one of its main parts is of that
  CONSTRUCTION; "no" only when a stated line shows it is of a different one;
  "unsure" when the lines do not settle it. A seal, a fastener, a lining or an
  accessory does not make the equipment of a construction."""


def _stated_lines(text: str) -> list[str]:
    return [line[2:] for line in text.splitlines() if line.startswith("- ")]


def _construction_problems(data: dict, text: str) -> list[str]:
    """Code's check of a "no": the quote is one of the stated lines, and that
    line's value does not itself name the construction."""
    if data.get("is_that") != "no":
        return []
    quote = data.get("quote") or ""
    construction = text.splitlines()[0].partition(":")[2]
    line = next((s for s in _stated_lines(text) if folded_in(quote, s, least=4)), None)
    if line is None:
        return ["the quote is not one of the STATED lines"]
    if _names(line.partition(": ")[2] or line, construction):
        return ["the quoted line names the construction itself"]
    return []


CONSTRUCTION_TASK = ai_task_runner.register(
    ai_task_runner.TaskSpec(
        name="equipment_construction",
        version="v1",
        instruction=CONSTRUCTION_INSTRUCTION,
        schema=CONSTRUCTION_SCHEMA,
        check=_construction_problems,
        num_predict=output_limits.max_tokens_for(
            output_limits.ROUTE_CLAUSE_APPLICABILITY
        ),
    )
)

#: The words of the stated lines the model reads (the task reads ~300).
_STATED_WORDS = 220


def _names(value: object, construction: str) -> bool:
    """Does `value` name any word of `construction` (four letters or more;
    a plural "s" does not count, so "vessel" names "vessels")?"""

    def words(text: object) -> set[str]:
        return {
            w[:-1] if w.endswith("s") else w
            for w in re.findall(r"[a-z]{4,}", subject_scope._fold(text))
        }

    return bool(words(value) & words(construction))


def _named_anywhere(
    construction: str, classification: dict | None, facts: list[dict]
) -> bool:
    """Does ANY stated value of the datasheet (every fact, uncut), or its
    classification, name the construction? A main part or only a seal: not
    for code to say, so such a division is never excluded."""
    values = [
        *(classification or {}).values(),
        *(
            f.get("field_value") or f.get("raw_value")
            for f in facts
            if not f.get("is_blank")
        ),
    ]
    return any(_names(v, construction) for v in values if isinstance(v, str) and v)


def stated_construction(classification: dict | None, facts: list[dict]) -> list[str]:
    """What the datasheet states about what its equipment is and is made of:
    the classification's equipment type and title, then the facts the role
    tests read as a material or an equipment class (`conditions`), one line
    per distinct value, within `_STATED_WORDS` words."""
    from . import conditions

    classification = classification or {}
    lines = [
        f"{label}: {classification[key]}"
        for key, label in (("equipment_type", "equipment type"), ("title", "title"))
        if classification.get(key)
    ]
    seen: set[str] = set()
    for shape in (conditions.SHAPE_MATERIAL, conditions.SHAPE_CLASS):
        for fact in conditions._candidate_facts(shape, facts):
            value = str(fact.get("field_value") or "").strip()
            if (
                fact.get("is_blank")
                or conditions._is_empty(value)
                or value.casefold() in seen
            ):
                continue
            seen.add(value.casefold())
            lines.append(
                f"{fact.get('field_label') or fact.get('field_name')}: {value}"
            )
    out: list[str] = []
    words = 0
    for line in lines:
        words += len(line.split())
        if words > _STATED_WORDS:
            break
        out.append(" ".join(line.split()))
    return out


def _construction_text(construction: str, quote: str, stated: list[str]) -> str:
    return "\n".join(
        [
            f"CONSTRUCTION: {construction}",
            f"SCOPE: {quote}",
            "STATED:",
            *(f"- {s}" for s in stated),
        ]
    )


#: A model that does not answer in time, or cannot be reached: no further
#: division of the run is asked (each would wait `ai_task_timeout_s`).
_MODEL_DOWN = ("the model did not answer in time", "the model could not be reached")
#: A LAYER on a base material (cladding, an overlay, a lining, a coating,
#: galvanising, plating): true of any document, a layer does not change what
#: the base is made of, so a value naming one never excludes - it is held.
_LAYER = re.compile(
    r"\b(?:clad\w*|overlay\w*|lin(?:ed|ing)|coat\w*|galvani[sz]\w*|plat(?:ed|ing))\b"
)


def _read(task, text: str, provider, run: dict) -> dict | None:
    """One task, unless the model already stopped answering in this run."""
    if run.get("stopped"):
        return None
    result = ai_task_runner.run_task(task, text, provider=provider)
    if result.state == ai_task_runner.STATE_OK:
        return result.data
    if (result.reason or "").startswith(_MODEL_DOWN):
        run["stopped"] = result.reason
    return None


def _division_decision(
    scope: dict,
    stated: list[str],
    classification: dict | None,
    facts: list[dict],
    provider,
    run: dict,
) -> tuple[str, str | None]:
    """("does_not_apply" | "unsure" | "applies", the stated line and the
    other material code read) for a division limited to the construction.
    Code decides "does not apply"; a read that fails is "applies" (nothing
    excluded or held on it); what code cannot decide is "unsure"."""
    from . import conditions

    construction = scope["construction"]
    if not stated:
        return "unsure", None
    first = _read(
        CONSTRUCTION_TASK,
        _construction_text(construction, scope["quote"], stated),
        provider,
        run,
    )
    if first is None or first.get("is_that") == "yes":
        return "applies", None
    if first.get("is_that") != "no" or _named_anywhere(
        construction, classification, facts
    ):
        return "unsure", None
    line = next((s for s in stated if folded_in(first.get("quote"), s, least=4)), None)
    if line is None:
        return "applies", None
    value = conditions._fold(line.partition(": ")[2] or line)
    if _LAYER.search(value):
        return "unsure", None
    other = conditions._names_another_of_the_family(
        value,
        [conditions._fold(construction)],
        conditions.SHAPE_MATERIAL,
    )
    return ("does_not_apply", f'{line}" names {other}') if other else ("unsure", None)


def division_gate_for_run(
    requirements: list[dict],
    classification: dict | None,
    facts: list[dict],
    standard_labels: dict[str, str],
) -> dict:
    """`division_gate` for one review run, with the run's settings: with
    `ai_division_scope_enabled` off every requirement stays a check and the
    summary is None."""
    settings = ai_task_runner.settings
    if not settings.ai_division_scope_enabled:
        return {"kept": list(requirements), "items": [], "held": [], "summary": None}
    return division_gate(
        requirements,
        classification=classification,
        facts=facts,
        standard_labels=standard_labels,
        limit=settings.ai_division_scope_max_per_run,
    )


def division_gate(
    requirements: list[dict],
    *,
    classification: dict | None,
    facts: list[dict],
    standard_labels: dict[str, str] | None = None,
    provider=None,
    limit: int | None = None,
    pages_of=None,
) -> dict:
    """#141: requirements of a standard's division whose own scope limits it
    to a construction code finds this equipment is not do not apply; what
    code cannot decide is held for the engineer. Returns {"kept", "items" (does not apply, code
    `outside_division_scope`), "held" (applies, not checked, code
    `applicability_unsure`), "summary"}. Never fails a review: on an error
    nothing changes (every requirement stays a check)."""
    from . import errors

    try:
        return _division_gate(
            requirements,
            classification=classification,
            facts=facts,
            standard_labels=standard_labels or {},
            provider=provider,
            limit=limit,
            pages_of=pages_of or subject_scope.standard_pages,
        )
    except Exception as exc:  # noqa: BLE001 - logged by type; must never fail the review
        return errors.fell_back(
            "ai_applicability: the division scope failed; nothing is narrowed",
            exc,
            {
                "kept": list(requirements),
                "items": [],
                "held": [],
                "summary": {
                    "not_run": f"the division scope could not be read "
                    f"({type(exc).__name__}); nothing was narrowed"
                },
            },
        )


def _place(requirements: list[dict], pages_of) -> tuple[dict, dict, dict]:
    """Where each requirement sits: ({id(requirement): (standard, division)},
    {(standard, division): (division, passage, page)}, {key: requirements})."""
    where: dict[int, tuple[str, int]] = {}
    passages: dict[tuple[str, int], tuple[dict, str, int | None]] = {}
    counts: dict[tuple[str, int], int] = {}
    for sid in dict.fromkeys(r.get("standard_document_id") for r in requirements):
        text = subject_scope.StandardText(pages_of(sid)) if sid else None
        divs = divisions(text) if text is not None else []
        for k, div in enumerate(divs):
            if div["name"] is not None:
                end = divs[k + 1]["line"] if k + 1 < len(divs) else None
                page = next(
                    (
                        p
                        for p, (lo, hi) in text.page_bounds.items()
                        if lo <= div["at"] < hi
                    ),
                    None,
                )
                passages[(sid, k)] = (div, scope_passage(text, div, end), page)
        index = {id(d): k for k, d in enumerate(divs)}
        for r in requirements:
            div = (
                divs
                and r.get("standard_document_id") == sid
                and division_of(r, text, divs)
            )
            if div:
                where[id(r)] = key = (sid, index[id(div)])
                counts[key] = counts.get(key, 0) + 1
    return where, passages, counts


def _item(requirement: dict, found: dict, standard_labels: dict, model: str) -> dict:
    """The ledger item for a requirement of a decided division."""
    sid = requirement.get("standard_document_id")
    scope = found["scope"]
    said = (
        f"{found['div']['heading']} of {standard_labels.get(sid) or sid} applies only to "
        f'{scope["construction"].strip()}: "{scope["quote"].strip()}"'
        + (f" (page {found['page']})" if found["page"] is not None else "")
    )
    if found["verdict"] == "does_not_apply":
        code = "outside_division_scope"
        detail = (
            f'{said}; the datasheet states "{found["line"]}, another material of that '
            "family (the model read the scope sentence and the stated line; code decided)"
        )
    else:
        code = "applicability_unsure"
        detail = (
            f"{said}; the datasheet does not settle whether this equipment is of that "
            "construction - an engineer decides"
        )
    return {
        "requirement": requirement,
        "code": code,
        "detail": detail,
        "decided_by": f"ai:{model}+code",
    }


def _division_gate(
    requirements, *, classification, facts, standard_labels, provider, limit, pages_of
) -> dict:
    model = (
        getattr(provider, "requested_model", None)
        or ai_task_runner.settings.ai_task_model
    )
    where, passages, counts = _place(requirements, pages_of)
    order = sorted(counts, key=lambda key: -counts[key])
    asked = order if limit is None else order[:limit]
    stated = stated_construction(classification, facts)
    decided: dict[tuple[str, int], dict] = {}
    summary = dict.fromkeys(("read", "could_not_read", "limited"), 0)
    summary.update(divisions=len(order), not_read_limit=len(order) - len(asked))
    run: dict = {}
    for key in asked:
        div, passage, page = passages[key]
        scope = _read(SCOPE_TASK, passage, provider, run)
        summary["could_not_read" if scope is None else "read"] += 1
        if scope is None or scope.get("limited") != "yes":
            continue
        summary["limited"] += 1
        verdict, line = _division_decision(
            scope, stated, classification, facts, provider, run
        )
        if verdict != "applies":
            decided[key] = {
                "verdict": verdict,
                "line": line,
                "div": div,
                "page": page,
                "scope": scope,
            }
    if run.get("stopped"):
        summary["stopped"] = f"{run['stopped']}; the divisions after it were not read"
    kept: list[dict] = []
    out: dict[str, list[dict]] = {
        "outside_division_scope": [],
        "applicability_unsure": [],
    }
    for r in requirements:
        found = decided.get(where.get(id(r)))
        if found is None:
            kept.append(r)
        else:
            item = _item(r, found, standard_labels, model)
            out[item["code"]].append(item)
    items, held = out["outside_division_scope"], out["applicability_unsure"]
    summary.update(does_not_apply=len(items), held=len(held))
    return {"kept": kept, "items": items, "held": held, "summary": summary}
