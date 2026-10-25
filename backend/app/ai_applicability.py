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

import re

from . import ai_task_runner, requirement_quality, scope_ledger, service_scope, subject_scope
from .ai import output_limits
from .division_text import (  # noqa: F401 - re-exported: the names tests and callers use
    NOT_READ_COUNTS,
    SCOPE_WORDS,
    crashed_item,
    division_of,
    divisions,
    ledger_item,
    not_read_rec,
    place,
    scope_passage,
    sub_of,
    sub_units,
    unscreened,
)

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
    # one provider: the model named in the ledger is the model that ran
    provider = provider or ai_task_runner.make_provider()
    model = getattr(provider, "requested_model", None) or ai_task_runner.model_in_use()
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
# A part whose scope was NOT READ (the model fails, stops answering, gives a
# reply code cannot verify, or the run's limit is reached) is never a pass: its
# requirements are HELD for the engineer (order 173.2). Switched off
# (`ai_division_scope_enabled`), nothing changes.

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
        *datasheet_heading(classification),
        *(
            f.get("field_value") or f.get("raw_value")
            for f in facts
            if not f.get("is_blank")
        ),
    ]
    return any(_names(v, construction) for v in values if isinstance(v, str) and v)


_HEADING_LINES, _HEADING_WORDS = 2, 8


def datasheet_heading(classification: dict | None) -> list[str]:
    """The first short lines of the datasheet's first page: a sheet says what
    it is in its heading even when no equipment type or title was stored for
    it. Empty when the document or its text is not known. Its own words, never
    a word list: whether a line names the construction is decided by
    `_names`, as for every stated line."""
    from .db import connect

    doc = (classification or {}).get("document_id")
    if not doc:
        return []
    row = connect().execute(
        "SELECT text FROM chunks WHERE document_id = ? AND page_start = 1"
        " ORDER BY ordinal LIMIT 1",
        (doc,),
    ).fetchone()
    lines = [" ".join(ln.split()) for ln in (row["text"] if row else "").splitlines()]
    heads = [ln for ln in lines if ln and len(ln.split()) <= _HEADING_WORDS]
    return heads[:_HEADING_LINES]


def stated_construction(classification: dict | None, facts: list[dict]) -> list[str]:
    """What the datasheet states about what its equipment is and is made of:
    the classification's equipment type and title, the sheet's own first-page
    heading, then the facts the role tests read as a material or an equipment
    class (`conditions`), one line per distinct value, within `_STATED_WORDS`
    words."""
    from . import conditions

    classification = classification or {}
    lines = [
        f"{label}: {classification[key]}"
        for key, label in (("equipment_type", "equipment type"), ("title", "title"))
        if classification.get(key)
    ]
    lines += [f"heading: {head}" for head in datasheet_heading(classification)]
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


def _yes_is_stated(reply: dict, stated: list[str], construction: str) -> bool:
    """Is the model's "yes" backed by a STATED line that names the
    construction and is the line it quoted?"""
    line = next((s for s in stated if folded_in(reply.get("quote"), s, least=4)), None)
    return line is not None and _names(line.partition(": ")[2] or line, construction)


def _division_decision(
    scope: dict,
    stated: list[str],
    classification: dict | None,
    facts: list[dict],
    provider,
    run: dict,
) -> tuple[str, str | None]:
    """("does_not_apply" | "unsure" | "applies" | "unread", the stated line
    and the other material code read) for a division limited to the
    construction. Code decides "does not apply"; a read that fails is
    "unread" (nothing excluded or held on it, but the gate counts it); a
    "yes" counts as "applies" only when a stated line names the construction
    and the model's quote is that line, else it is "unsure"; what code cannot
    decide is "unsure"."""
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
    if first is None:
        return "unread", None
    if first.get("is_that") == "yes":
        return (
            "applies" if _yes_is_stated(first, stated, construction) else "unsure"
        ), None
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
    code cannot decide, and a part the model did not read, is held for the
    engineer. Returns {"kept", "items" (does not apply, code
    `outside_division_scope`), "held" (applies, not checked, code
    `applicability_unsure`), "summary"}. Never fails a review: on an
    unexpected error every requirement is HELD (the step did not run)."""
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
        name = type(exc).__name__
        summary = {"not_run": f"the division scope could not be read ({name})"}
        if requirements:
            # order 173.2: a step that did not run never lets a clause through
            summary["not_run"] += "; its requirements are held for the engineer"
            summary["requirements_gated"] = len(requirements)
            summary["requirements_held_scope_not_read"] = len(requirements)
        else:
            summary["not_run"] += "; nothing was narrowed"
        held = [crashed_item(r, name) for r in requirements]
        return errors.fell_back(
            "ai_applicability: the division scope failed; its requirements are held",
            exc,
            {"kept": [], "items": [], "held": held, "summary": summary},
        )


def _decide_unit(unit: dict, ctx: dict) -> dict:
    """Read one unit (spends one read of the run's budget) and decide:
    {"status": "read" | "unread" | "beyond", "verdict": "kept" | "held" |
    "does_not_apply", "scope", "unit", ...}. "unsure" is held for the engineer;
    so is a unit the model could not be read for or the limit left unread
    (`not_read`: never compared, the gate counts it). A candidate start (found by shape or break) can only be held, never
    excluded, even when the model confirms it: nothing checks it is a real
    start of a part."""
    from . import clause_scope

    summary = ctx["summary"]
    if ctx["budget"] is not None and ctx["budget"] <= 0:
        summary["not_read_limit"] += 1
        return not_read_rec(unit, "beyond")
    if ctx["budget"] is not None:
        ctx["budget"] -= 1
    passage = scope_passage(unit["text"], unit["div"], unit["end"])
    scope = _read(SCOPE_TASK, passage, ctx["provider"], ctx["run"])
    summary["could_not_read" if scope is None else "read"] += 1
    rec = {"status": "read", "verdict": "kept", "scope": scope, "unit": unit}
    if scope is None:
        return not_read_rec(unit, "scope")
    if scope.get("limited") == "unsure":
        return {**rec, "verdict": "held", "unsure": True}
    if scope.get("limited") != "yes":
        return rec
    summary["limited"] += 1
    verdict, line = _division_decision(
        scope,
        ctx["stated"],
        ctx["classification"],
        ctx["facts"],
        ctx["provider"],
        ctx["run"],
    )
    if verdict == "unread":
        return not_read_rec(unit, "construction", scope)
    rec["own"] = True
    if verdict == "applies":
        return rec
    verdict = "held" if verdict == "unsure" else verdict
    if unit["kind"] == "candidate":  # found by shape: nothing checks it is a start
        verdict = clause_scope.downgrade(verdict)
    return {**rec, "verdict": verdict, "line": line}


def _subparts(unit: dict, wanted: set, ctx: dict) -> tuple[list[dict], list | None]:
    """(flagged, skipped): the sub-headings of a division the model flags as
    limited to a material, form, construction or grade (each verified by
    `clause_scope`), and the sub-headings that were NOT screened - None when
    none of them was (the run's budget is spent or the model stopped), else the
    ones past the titles one read can carry. A screen that fails (a reply that
    does not fit, a model error) is not a screen with none flagged: None."""
    from . import clause_scope

    found = clause_scope.subclause_units(
        unit["text"], unit["div"], unit["end"], wanted, limit=None
    )
    if not found:
        return [], []
    if ctx["run"].get("stopped") or (ctx["budget"] is not None and ctx["budget"] <= 0):
        return [], None
    if ctx["budget"] is not None:
        ctx["budget"] -= 1
    head = found[: clause_scope.MAX_TITLES]
    flagged = clause_scope.screen_titles(head, ctx["provider"], ctx["run"])
    if flagged is None or ctx["run"].get("stopped"):  # the screen failed
        return [], None
    return flagged, found[clause_scope.MAX_TITLES :]


def _read_all(units: dict, where: dict, ctx: dict) -> tuple[dict, dict]:
    """Read the divisions and candidate starts the largest first, then the
    flagged sub-parts (also those holding no requirement of their own but an
    inner sub-part's) the largest first, all within the run's budget.
    Returns ({key: decision}, {id(requirement): [sub-part keys, outer first]});
    `ctx["screen_failed"]` gets the requirements whose sub-headings the screen
    did not carry (it failed, was not run or left them out): they are HELD.
    `ctx["by_page"]` gets those kept but counted: no line, or in a kept
    candidate start (never screened)."""
    recs: dict[tuple, dict] = {}
    subs: list[dict] = []
    ctx["screen_failed"], ctx["by_page"] = set(), set()
    todo = sorted(
        (u for u in units.values() if u["weight"]), key=lambda u: -u["weight"]
    )
    for unit in todo:
        recs[unit["key"]] = rec = _decide_unit(unit, ctx)
        open_part = rec["status"] == "read" and rec["verdict"] == "kept"
        if unit["kind"] == "division" and open_part:
            lines = {ln for key, ln in where.values() if key == unit["key"]}
            flagged, skipped = _subparts(unit, lines - {None}, ctx)
            failed, by_page = unscreened(unit, where, skipped)
            ctx["screen_failed"] |= failed
            ctx["by_page"] |= by_page
            subs += sub_units(unit, flagged)
        elif unit["kind"] == "candidate" and open_part:  # never sub-screened
            ctx["by_page"] |= unscreened(unit, where, [], screened=False)[1]
    subs_of = sub_of(subs, where)
    for sub in sorted(subs, key=lambda s: -s["count"]):
        if sub["count"]:
            recs[sub["key"]] = _decide_unit(sub, ctx)
    if subs:
        ctx["summary"]["subparts_flagged"] = len(subs)
    return recs, subs_of


#: How restrictive a verdict is: a requirement takes the highest of its parts.
_RANK = {"kept": 0, "held": 1, "does_not_apply": 2}


def _effective(requirement: dict, where, sub_map, recs, units) -> dict | None:
    """The decision that holds for a requirement: the most restrictive of its
    part's and of EVERY flagged sub-part that contains it (an outer one is read
    even when only an inner one holds the requirement); a part or sub-part
    that was not read is held (`not_read`), so it outranks a kept one. A
    candidate start the model read and did not confirm as a new part inherits the part before it
    DOWNGRADED (excluded -> held), unless the model was unsure of it, which
    holds: a false break never rescues a clause from a limited part, and code
    never excludes on inheritance or on a candidate's own reading (a start
    found by shape or break can only hold; `_decide_unit` caps it)."""
    from . import clause_scope

    placed = where.get(id(requirement))
    if placed is None:
        return None
    unit = units[placed[0]]
    rec = recs[unit["key"]]
    if (
        rec["status"] == "read"
        and unit["kind"] == "candidate"
        and not (rec.get("own") or rec.get("unsure"))
    ):
        prev = recs.get(unit["prev"]["key"]) if unit["prev"] else None
        if prev and clause_scope.downgrade(prev["verdict"]) == "held":
            rec = {**prev, "verdict": "held", "via": unit["div"]["heading"]}
        else:
            rec = {**rec, "verdict": "kept"}
    subs = [recs[k] for k in sub_map.get(id(requirement), []) if k in recs]
    return max([rec, *subs], key=lambda r: _RANK[r["verdict"]])


def _sort_out(requirements, where, marks, sub_map, recs, units, labels, model):
    """(kept, items, held, counts): every requirement with the decision that
    holds for it. `marks`: the ids of the requirements "unplaced", whose
    sub-headings the screen did not carry ("screen_failed", held) and which
    were placed "by_page" only or sit in a candidate start (kept, counted).
    Counts are of requirements; a count of none is left out."""
    kept: list[dict] = []
    out: dict[str, list[dict]] = {
        "outside_division_scope": [],
        "applicability_unsure": [],
    }
    counts: dict[str, int] = {}

    def count(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for r in requirements:
        rec = _effective(r, where, sub_map, recs, units)
        if id(r) in marks["unplaced"]:
            count("requirements_unplaced")
        if rec and rec["verdict"] == "kept" and id(r) in marks["screen_failed"]:
            rec = not_read_rec(units[where[id(r)][0]], "screen")
        if rec is None or rec["verdict"] == "kept":
            kept.append(r)
            if id(r) in marks["by_page"]:
                count("requirements_kept_sub_headings_not_screened")
            continue
        item = ledger_item(r, rec, labels, model)
        out[item["code"]].append(item)
        if rec.get("not_read"):
            count(NOT_READ_COUNTS[rec["not_read"]])
        elif rec.get("unsure") and not rec.get("via"):
            count("requirements_held_unsure")
    return kept, out["outside_division_scope"], out["applicability_unsure"], counts


def _division_gate(
    requirements, *, classification, facts, standard_labels, provider, limit, pages_of
) -> dict:
    # one provider for the whole run: the model recorded is the model that read
    provider = provider or ai_task_runner.make_provider()
    model = getattr(provider, "requested_model", None) or ai_task_runner.model_in_use()
    units, where, unplaced = place(requirements, pages_of)
    divisions_read = [
        u for u in units.values() if u["weight"] and u["kind"] == "division"
    ]
    summary: dict = dict.fromkeys(("read", "could_not_read", "limited"), 0)
    summary.update(divisions=len(divisions_read), not_read_limit=0)
    ctx = {
        "summary": summary,
        "budget": limit,
        "provider": provider,
        "run": {},
        "classification": classification,
        "facts": facts,
        "stated": stated_construction(classification, facts),
    }
    recs, subs_of = _read_all(units, where, ctx)
    if stopped := ctx["run"].get("stopped"):
        summary["stopped"] = f"{stopped}; the divisions after it were not read"
        summary["model_unavailable"] = stopped
    marks = {
        "unplaced": unplaced,
        "screen_failed": ctx["screen_failed"],
        "by_page": ctx["by_page"],
    }
    kept, items, held, counts = _sort_out(
        requirements, where, marks, subs_of, recs, units, standard_labels, model
    )
    candidates = sum(
        1
        for key, rec in recs.items()
        if units.get(key, {}).get("kind") == "candidate" and rec["status"] == "read"
    )
    # the denominator of every requirement count: the requirements of the
    # standards in this review, and nothing else
    summary.update(does_not_apply=len(items), held=len(held), **counts)
    summary["requirements_gated"] = len(requirements)
    if candidates:
        summary["candidates_read"] = candidates
    model_status = ai_task_runner.model_status()
    if model_status["fallback"] and model == model_status["used"]:
        summary["model_fallback"] = (
            f"{model_status['reason']}; {model_status['used']} read the scopes"
        )
    return {"kept": kept, "items": items, "held": held, "summary": summary}
