"""Which standard sentences may stand behind a CRS row (orders 180 / 180.1).

Two general rules, true for any standard and any datasheet type; no part, label,
service or document is named here. They run before a sentence is paired with a
datasheet field, so a row never quotes a sentence that cannot support it.

  1. A SENTENCE THAT STATES NO REQUIREMENT IS NEVER A SUPPORTING CLAUSE. A
     statement with no requirement word (shall, must, required, to be, a limit
     word) and no number, written as a list of items, is a description, not a
     check ("the package holds a, b, c, d"). It is HELD for the engineer
     ("applies, not checked: it states no requirement"), never compared and
     never listed as support, so a blank field it was paired with says "no
     clause found" instead of quoting a list. Unsure is held, never excluded.
  2. A SENTENCE THAT NAMES ITS OWN SERVICE, APPLICATION OR SEAL PLAN APPLIES
     ONLY WHEN THE DATASHEET STATES THE SAME ONE. The words that name it are
     read from the sentence's own wording (a "<words> service" or
     "<words> application" phrase, a "Plan <n>" code, a "for <words> pumps"
     duty); when the datasheet's text does not hold them the sentence is HELD
     for the engineer ("applies, not checked"), never compared and never listed
     as support. Unsure is held, never excluded.

Pure functions over dicts. The two short word lists below are last-resort
structure words (orders 143): what is generic in a phrase, not any one service.
"""

from __future__ import annotations

import re

from . import requirements_3b

#: A word that makes a sentence a requirement, or a limit.
_REQUIRES = re.compile(
    r"\b(?:shall|must|should|required?|requires?|requirements?|needs?\s+to|has\s+to|"
    r"have\s+to|will|(?:is|are|be|being)\s+to|to\s+be|"
    r"not\s+(?:less|more|greater|smaller|lower|higher|exceed\w*|permitted|allowed)|"
    r"minimum|maximum|at\s+least|at\s+most|up\s+to|limited|prohibit\w*|only|unless|except|"
    r"provide\w*|suppl(?:y|ied|ies)|furnish\w*|include\w*|install\w*|fit(?:ted)?|equip\w*|"
    r"ensur\w*|comply|complies|conform\w*|perform\w*|test(?:ed)?|inspect\w*|mark(?:ed)?|"
    r"label(?:l?ed)?|use[ds]?|apply|applied)\b",
    re.IGNORECASE,
)

#: Words that do not name a service, application or duty by themselves.
_GENERIC = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "such",
        "any",
        "all",
        "each",
        "every",
        "same",
        "other",
        "another",
        "normal",
        "continuous",
        "intermittent",
        "standby",
        "specified",
        "intended",
        "stated",
        "required",
        "particular",
        "general",
        "special",
        "design",
        "main",
        "primary",
        "secondary",
        "typical",
        "given",
        "which",
        "where",
        "when",
        "for",
        "and",
        "with",
        "without",
        "under",
        "over",
        "their",
        "its",
    }
)

#: Order 228.5: linking words (prepositions, conjunctions, auxiliaries, participles). Only the
#: words AFTER the last one in the phrase before "service" / "application" can name a service:
#: "put into service", "inspected before service", "suitable for service", "maintained during
#: service" name none; "used before lethal service" names "lethal". Without this a sentence was
#: held as "applies only to 'into'" (owner's walk-through: 17 requirements) [found-on].
_BREAK = frozenset(
    {
        "into", "onto", "upon", "before", "after", "prior", "during", "throughout", "within",
        "without", "until", "while", "whilst", "since", "once", "then", "through", "across",
        "around", "between", "among", "against", "about", "above", "below", "from", "following",
        "preceding", "using", "being", "been", "have", "has", "will", "shall", "should", "must",
        "may", "than", "also", "only", "per", "via", "for", "of", "in", "on", "at", "to", "by",
        "as", "is", "are", "was", "were", "be", "it",
    }
)


def _after_last_break(phrase: str) -> str:
    """The words of `phrase` after its last linking word ("" when it ends in one)."""
    words = phrase.split()
    for i in range(len(words) - 1, -1, -1):
        if words[i].casefold() in _BREAK:
            return " ".join(words[i + 1 :])
    return phrase


_PLAN = re.compile(r"\bplan\s+(\d{1,2}[a-z]?)\b", re.IGNORECASE)
_NAMED = re.compile(
    r"\b((?:[a-z][a-z\-]+\s+){1,2})(?:service|application|applications)\b",
    re.IGNORECASE,
)
_DUTY = re.compile(
    r"\bfor\s+(?:the\s+)?((?:[a-z][a-z\-]+\s+){1,3})(?:pump|pumps|compressor|compressors)\b",
    re.IGNORECASE,
)


def _text(requirement: dict) -> str:
    return " ".join(
        str(
            requirement.get("source_text") or requirement.get("requirement_text") or ""
        ).split()
    )


def states_no_requirement(requirement: dict) -> bool:
    """Rule 1: a statement with no requirement word, no number, written as a list."""
    if requirement.get("requirement_type") != requirements_3b.STATEMENT:
        return False
    text = _text(requirement)
    if not text or _REQUIRES.search(text) or re.search(r"\d", text):
        return False
    return len(re.findall(r"[,;]", text)) >= 2


def _significant(phrase: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z][a-z\-]+", phrase.casefold())
        if len(w) >= 4 and w not in _GENERIC
    ]


def named_conditions(requirement: dict) -> list[str]:
    """What the sentence says it applies to, as the words it used ("Plan 32",
    "<words> service"); [] when it names none."""
    text = _text(requirement)
    found = [f"plan {m.group(1)}".casefold() for m in _PLAN.finditer(text)]
    for pattern in (_NAMED, _DUTY):
        for m in pattern.finditer(text):
            phrase = _after_last_break(m.group(1)) if pattern is _NAMED else m.group(1)
            words = _significant(phrase)
            if words:
                found.append(" ".join(words))
    return list(dict.fromkeys(found))


def sheet_text(facts: list[dict]) -> str:
    """Everything the datasheet states, as one folded string."""
    parts: list[str] = []
    for fact in facts:
        if fact.get("is_blank"):
            continue
        for key in ("field_label", "field_name", "field_value", "raw_value"):
            if fact.get(key) not in (None, ""):
                parts.append(str(fact[key]))
    return re.sub(r"\s+", " ", " ".join(parts)).casefold()


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.casefold())) + " "


def _stated(phrase: str, sheet: str) -> bool:
    """Does the sheet state this phrase? Its words, whole and in order, side by
    side (so "water" is not stated by "seawater", nor "sulfur molten" by two
    unrelated fields); a "Plan <n>" code by its code."""
    if phrase.startswith("plan "):
        return re.search(rf"\bplan\s*{re.escape(phrase[5:])}\b", sheet) is not None
    return _words(phrase) in _words(sheet)


def hold_non_requirements(requirements: list[dict]) -> dict:
    """{"kept", "held"}: rule 1. A sentence that states no requirement is held."""
    kept: list[dict] = []
    held: list[dict] = []
    for requirement in requirements:
        if states_no_requirement(requirement):
            held.append(
                {
                    "requirement": requirement,
                    "code": "applicability_unsure",
                    "not_a_requirement": True,
                    "detail": (
                        "it lists items and states no requirement (no must, shall, "
                        "provide or limit); an engineer decides whether it asks for anything"
                    ),
                }
            )
        else:
            kept.append(requirement)
    return {"kept": kept, "held": held}


def hold_unstated_services(
    requirements: list[dict], *, facts: list[dict], known: frozenset[str] = frozenset()
) -> dict:
    """{"kept", "held"}: rule 2. A sentence naming a service the sheet does not
    state is held for the engineer. A sheet with no text holds nothing. `known`
    are the words of the services the service vocabulary already decides
    (`service_scope`): a sentence naming one of those is left to that decision."""
    sheet = sheet_text(facts)
    kept: list[dict] = []
    held: list[dict] = []
    for requirement in requirements:
        missing = [
            p
            for p in named_conditions(requirement)
            if not _stated(p, sheet) and not any(w in known for w in p.split())
        ]
        if not (missing and sheet):
            kept.append(requirement)
            continue
        held.append(
            {
                "requirement": requirement,
                "code": "service_unknown",
                "detail": (
                    "the sentence applies only to "
                    + "; ".join(f'"{p}"' for p in missing)
                    + ", which this datasheet does not state; an engineer decides"
                ),
            }
        )
    return {"kept": kept, "held": held}


def known_words(names: list[str]) -> frozenset[str]:
    """The significant words of service names and markers already decided elsewhere."""
    return frozenset(w for n in names for w in _significant(n))


def gate(requirements: list[dict], *, facts: list[dict]) -> dict:
    """Both rules in order: {"kept", "held"}."""
    first = hold_non_requirements(requirements)
    second = hold_unstated_services(first["kept"], facts=facts)
    return {"kept": second["kept"], "held": first["held"] + second["held"]}
