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
states, code verifies both quotes, unsure is held for the engineer.
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
#
# A standard is built of DIVISIONS - parts, appendices, annexes, chapters -
# and a division may open with its own scope sentence that limits it to one
# construction, material or kind of equipment ("The rules of this Part apply
# to vessels constructed of ..."). Its requirements apply only to that
# equipment. This section only finds the divisions in the standard's own
# text and where each requirement sits; reading the scope sentence and
# deciding is `division_gate` below (the model reads, code verifies).
# Nothing here names a standard or one of its divisions: the words are the
# structural words standards use for a top-level division.

#: A division heading: the structural word, a short id (a number, or one to
#: four capitals with an optional "-A" letter), then the end of the line or a
#: title (`subject_scope._TITLE_REST`). The word is capitalised ("Part",
#: "PART"): a "part" inside a wrapped sentence is not a heading, and neither
#: is "Part 3 of this" (a lower-case word follows the id).
_DIVISION = re.compile(
    r"^(?:(?i:(?:non-?)?mandatory|normative|informative)\s+)?"
    r"(?:P(?i:art)|A(?i:ppendix|nnex)|C(?i:hapter))\s+"
    r"(?P<id>\d{1,3}[A-Z]?|[A-Z]{1,4}(?:-[A-Z]{1,2})?)(?![A-Za-z0-9])" + subject_scope._TITLE_REST
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
    """The divisions of a standard, in order: {"at" (offset in the folded
    text), "line" (index), "name", "heading" (the heading line)}.

    A division STARTS A PAGE: its heading is among the first lines of a page
    (`_DIVISION_TOP`), and that page opens no other division. So a reference
    that a wrapped sentence leaves at the start of a line ("... see" / "Part
    X"), a contents or list page (many headings on one page), a running header
    and a heading repeated for the division it is already in (a "(continued)"
    title) open nothing. A missed heading only leaves its requirements in the
    division before it, whose own scope is then read for them."""
    out: list[dict] = []
    for lo, hi in text.page_bounds.values():
        first = bisect.bisect_left(text.offsets, lo, hi=len(text.lines))
        heads: list[tuple[int, tuple[str, str]]] = []
        for index in range(first, len(text.lines)):
            if text.offsets[index] >= hi:
                break
            line = text.lines[index]
            match = _DIVISION.match(line)
            if match is None or re.sub(r"\d+", "#", line) in text.running:
                continue
            if line[match.end("id") :].strip() and _CONTENTS_TAIL.search(line):
                continue
            # the division's name: its structural word and id ("appendix 9")
            word = line[: match.start("id")].split()[-1].casefold()
            heads.append((index, (word, match.group("id").upper())))
        if not heads or len({name for _i, name in heads}) != 1:
            continue
        index, name = heads[0]
        if index - first < _DIVISION_TOP and not (out and out[-1]["name"] == name):
            out.append(
                {"at": text.offsets[index], "line": index, "name": name,
                 "heading": text.lines[index]}
            )
    return out


def division_of(requirement: dict, text: subject_scope.StandardText, divs: list[dict]) -> dict | None:
    """The division a requirement sits in, or None when it sits before the
    first one or cannot be placed: where its sentence sits in the text first,
    else its page (a division starts a page, so a page lies in one)."""
    at = text.place(requirement)
    if at is None:
        bounds = text.page_bounds.get(subject_scope._page_of(requirement))
        if bounds is None or bounds[1] <= bounds[0]:
            return None
        at = bounds[1] - 1
    inside = [d for d in divs if d["at"] <= at]
    return inside[-1] if inside else None


def scope_passage(text: subject_scope.StandardText, div: dict, end: int | None) -> str:
    """What the model reads of a division: its heading and title lines, then
    its own scope clause (the first line naming "scope" near its start) or,
    with none, the lines that follow - at most `SCOPE_WORDS` words, never past
    the division's end (`end`: the next division's first line)."""
    stop = len(text.lines) if end is None else end
    first = div["line"]
    body = first + 3
    start = next(
        (
            i
            for i in range(body, min(first + _SCOPE_LOOK, stop))
            if _SCOPE_LINE.search(text.lines[i])
        ),
        body,
    )
    words: list[str] = " ".join(text.lines[first : min(body, stop)]).split()
    for line in text.lines[start:stop]:
        if len(words) >= SCOPE_WORDS:
            break
        words.extend(line.split())
    return " ".join(words[:SCOPE_WORDS])


def folded_in(needle: object, haystack: object, *, least: int = 1) -> bool:
    """Is `needle` in `haystack`, compared on letters and digits only (so a
    word hyphenated over a line break still matches)?"""
    key = subject_scope._key(needle)
    return len(key) >= least and key in subject_scope._key(haystack)


# ------------------------------------------- #141: a division's own scope
#
# A division of a standard (a part, an appendix, an annex) may limit itself in
# its own scope sentence to one construction, material or kind of equipment.
# Its requirements were applied to every submittal the standard applies to:
# a special-construction part of a pressure-vessel code was checked against
# an ordinary vessel (order 141). Now, per division that holds requirements of
# this run:
#   1. the model reads the division's heading and scope clause
#      (`scope_passage`) and says whether it is limited, with
#      the construction's words and the scope sentence; CODE checks that the
#      sentence is in the standard's text and the words in the sentence;
#   2. the model reads what the datasheet STATES about the equipment's
#      material and construction and says whether the equipment is of that
#      construction, quoting the stated line; CODE checks the quote is a
#      stated line whose value does not itself name the construction;
#   3. a "no" stands only when a second, differently framed read agrees.
# Then: does not apply (with the quoted scope sentence and the stated line),
# applies (kept a check), or unsure -> held for the engineer (applies, not
# checked: `applicability_unsure`, with the scope sentence). A model that is
# off, fails or gives a reply code cannot verify changes nothing: every
# requirement stays a check. Nothing here names a standard or its parts.

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


SCOPE_TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="division_scope", version="v1", instruction=SCOPE_INSTRUCTION, schema=SCOPE_SCHEMA,
    check=_scope_problems,
    num_predict=output_limits.max_tokens_for(output_limits.ROUTE_CLAUSE_APPLICABILITY)))

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
    line = next((s for s in _stated_lines(text)
                 if folded_in(quote, s, least=4)), None)
    if line is None:
        return ["the quote is not one of the STATED lines"]
    if _names(line.partition(": ")[2] or line, construction):
        return ["the quoted line names the construction itself"]
    return []


CONSTRUCTION_TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="equipment_construction", version="v1", instruction=CONSTRUCTION_INSTRUCTION,
    schema=CONSTRUCTION_SCHEMA, check=_construction_problems,
    num_predict=output_limits.max_tokens_for(output_limits.ROUTE_CLAUSE_APPLICABILITY)))

CONFIRM_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "enum": ["yes", "no", "unsure"]}},
}

CONFIRM_INSTRUCTION = """The STATED line is what a datasheet says its
equipment is constructed of or made of. Is it of the CONSTRUCTION (the same
construction or material, or a kind of it)? Answer "yes", "no", or "unsure"
when you cannot tell."""

CONFIRM_TASK = ai_task_runner.register(ai_task_runner.TaskSpec(
    name="equipment_construction_confirm", version="v1", instruction=CONFIRM_INSTRUCTION,
    schema=CONFIRM_SCHEMA,
    num_predict=output_limits.max_tokens_for(output_limits.ROUTE_CLAUSE_APPLICABILITY)))

#: The words of the stated lines the model reads (the task reads ~300).
_STATED_WORDS = 220


def _names(value: str, construction: str) -> bool:
    """Does `value` name any word of `construction` (four letters or more,
    compared on its stem, so "vessel" names "vessels")?"""
    words = re.findall(r"[a-z]{4,}", subject_scope._fold(value))
    for word in re.findall(r"[a-z]{4,}", subject_scope._fold(construction)):
        stem = word[: max(4, len(word) - 2)]
        if any(w.startswith(stem) for w in words):
            return True
    return False


def stated_construction(classification: dict | None, facts: list[dict]) -> list[str]:
    """What the datasheet states about what its equipment is and is made of:
    the classification's equipment type and title, then the facts the role
    tests read as a material or an equipment class (`conditions`), one line
    per distinct value, within `_STATED_WORDS` words."""
    from . import conditions

    classification = classification or {}
    lines = [f"{label}: {classification[key]}" for key, label in
             (("equipment_type", "equipment type"), ("title", "title"))
             if classification.get(key)]
    seen: set[str] = set()
    for shape in (conditions.SHAPE_MATERIAL, conditions.SHAPE_CLASS):
        for fact in conditions._candidate_facts(shape, facts):
            value = str(fact.get("field_value") or "").strip()
            if fact.get("is_blank") or conditions._is_empty(value) or value.casefold() in seen:
                continue
            seen.add(value.casefold())
            lines.append(f"{fact.get('field_label') or fact.get('field_name')}: {value}")
    out: list[str] = []
    words = 0
    for line in lines:
        words += len(line.split())
        if words > _STATED_WORDS:
            break
        out.append(" ".join(line.split()))
    return out


def _construction_text(construction: str, quote: str, stated: list[str]) -> str:
    return "\n".join([f"CONSTRUCTION: {construction}", f"SCOPE: {quote}", "STATED:",
                      *(f"- {s}" for s in stated)])


def _read(task, text: str, provider) -> dict | None:
    result = ai_task_runner.run_task(task, text, provider=provider)
    return result.data if result.state == ai_task_runner.STATE_OK else None


def _division_decision(scope: dict, stated: list[str], provider) -> tuple[str, str | None]:
    """("does_not_apply" | "unsure" | "applies", the stated line a "no" rests
    on) for a division limited to `scope["construction"]`. A read that fails
    or cannot be verified is "applies": nothing is excluded or held on it."""
    if not stated:
        return "unsure", None
    first = _read(CONSTRUCTION_TASK, _construction_text(
        scope["construction"], scope["quote"], stated), provider)
    if first is None or first.get("is_that") == "yes":
        return "applies", None
    if first.get("is_that") != "no":
        return "unsure", None
    line = next((s for s in stated if folded_in(first.get("quote"), s, least=4)),
                None)
    if line is None:
        return "applies", None
    # Another stated line naming the construction ("<part>: <that material>")
    # may be a main part of it or only a seal: not for code to say - unsure.
    if any(_names(s.partition(": ")[2] or s, scope["construction"]) for s in stated):
        return "unsure", None
    confirm = _read(CONFIRM_TASK, f"CONSTRUCTION: {scope['construction']}\nSTATED: {line}",
                    provider)
    answer = (confirm or {}).get("answer")
    if answer == "no":
        return "does_not_apply", line
    return ("applies", None) if answer in ("yes", None) else ("unsure", None)


def division_gate_for_run(requirements: list[dict], classification: dict | None,
                          facts: list[dict], standard_labels: dict[str, str]) -> dict:
    """`division_gate` for one review run, with the run's settings: with
    `ai_division_scope_enabled` off every requirement stays a check and the
    summary is None."""
    settings = ai_task_runner.settings
    if not settings.ai_division_scope_enabled:
        return {"kept": list(requirements), "items": [], "held": [], "summary": None}
    return division_gate(requirements, classification=classification, facts=facts,
                         standard_labels=standard_labels,
                         limit=settings.ai_division_scope_max_per_run)


def division_gate(requirements: list[dict], *, classification: dict | None, facts: list[dict],
                 standard_labels: dict[str, str] | None = None, provider=None,
                 limit: int | None = None, pages_of=None) -> dict:
    """#141: requirements of a standard's division whose own scope limits it
    to a construction this equipment is not do not apply; unsure ones are
    held for the engineer. Returns {"kept", "items" (does not apply, code
    `outside_division_scope`), "held" (applies, not checked, code
    `applicability_unsure`), "summary"}. Never fails a review: on an error
    nothing changes (every requirement stays a check)."""
    from . import errors

    try:
        return _division_gate(requirements, classification=classification, facts=facts,
                             standard_labels=standard_labels or {}, provider=provider,
                             limit=limit, pages_of=pages_of or subject_scope.standard_pages)
    except Exception as exc:  # noqa: BLE001 - logged by type; must never fail the review
        return errors.fell_back(
            "ai_applicability: the division scope failed; nothing is narrowed", exc,
            {"kept": list(requirements), "items": [], "held": [],
             "summary": {"not_run": f"the division scope could not be read "
                                    f"({type(exc).__name__}); nothing was narrowed"}})


def _division_gate(requirements, *, classification, facts, standard_labels, provider, limit,
                  pages_of) -> dict:
    model = getattr(provider, "requested_model", None) or ai_task_runner.settings.ai_task_model
    where: dict[int, tuple[str, int]] = {}  # id(requirement) -> (standard, division)
    passages: dict[tuple[str, int], tuple[dict, str, int | None]] = {}
    counts: dict[tuple[str, int], int] = {}
    for sid in dict.fromkeys(r.get("standard_document_id") for r in requirements):
        if not sid:
            continue
        text = subject_scope.StandardText(pages_of(sid))
        divs = divisions(text)
        if not divs:
            continue
        for k, div in enumerate(divs):
            end = divs[k + 1]["line"] if k + 1 < len(divs) else None
            page = next((p for p, (lo, hi) in text.page_bounds.items() if lo <= div["at"] < hi),
                        None)
            passages[(sid, k)] = (div, scope_passage(text, div, end), page)
        index = {id(d): k for k, d in enumerate(divs)}
        for r in requirements:
            if r.get("standard_document_id") == sid:
                div = division_of(r, text, divs)
                if div is not None:
                    where[id(r)] = (sid, index[id(div)])
                    counts[(sid, index[id(div)])] = counts.get((sid, index[id(div)]), 0) + 1
    order = sorted(counts, key=lambda key: -counts[key])
    asked = order if limit is None else order[:limit]
    stated = stated_construction(classification, facts)
    decided: dict[tuple[str, int], dict] = {}
    summary = {"divisions": len(order), "read": 0, "not_read_limit": len(order) - len(asked),
               "could_not_read": 0, "limited": 0, "does_not_apply": 0, "held": 0}
    for key in asked:
        div, passage, page = passages[key]
        scope = _read(SCOPE_TASK, passage, provider)
        if scope is None:
            summary["could_not_read"] += 1
            continue
        summary["read"] += 1
        if scope.get("limited") != "yes":
            continue
        summary["limited"] += 1
        verdict, line = _division_decision(scope, stated, provider)
        if verdict != "applies":
            decided[key] = {"verdict": verdict, "line": line, "div": div, "page": page,
                            "scope": scope}
    kept: list[dict] = []
    items: list[dict] = []
    held: list[dict] = []
    for r in requirements:
        found = decided.get(where.get(id(r)))
        if found is None:
            kept.append(r)
            continue
        name = standard_labels.get(r.get("standard_document_id")) or r.get("standard_document_id")
        said = (f"{found['div']['heading']} of {name} applies only to "
                f"{found['scope']['construction'].strip()}: \"{found['scope']['quote'].strip()}\""
                + (f" (page {found['page']})" if found["page"] is not None else ""))
        if found["verdict"] == "does_not_apply":
            items.append({"requirement": r, "code": "outside_division_scope",
                          "detail": f"{said}; the datasheet states \"{found['line']}\" "
                                    "(proposed by the model, confirmed by code)",
                          "decided_by": f"ai:{model}+code"})
        else:
            held.append({"requirement": r, "code": "applicability_unsure",
                         "detail": f"{said}; the datasheet does not settle whether this "
                                   "equipment is of that construction - an engineer decides",
                         "decided_by": f"ai:{model}+code"})
    summary["does_not_apply"] = len(items)
    summary["held"] = len(held)
    return {"kept": kept, "items": items, "held": held, "summary": summary}
