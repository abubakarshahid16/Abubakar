"""Which equipment a rule is for, from the scope clause of the Part or Appendix it sits in (owner's order, 2 Nov 2026).

A CLAUSE OF A STANDARD CAN BE TRUE AND STILL NOT BE ABOUT THIS EQUIPMENT. A review or a checklist asks here before it
pairs a rule with a value. Only with RULEBOOK_V2_REVIEW_ENABLED on; the callers keep the door.

AI READ IT, CODE VERIFIES IT, NOTHING IS GUESSED. There is no second reader: the division gate's model already reads each
Part's scope clause (`ai_applicability.SCOPE_TASK`, on `division_text.scope_passage`) and keeps the answer in
`ai_task_cache`. This reads that stored answer, read only, and sends nothing. The answer's key holds the passage, so a
changed text is no answer. Code verifies the sentence is on the Part's page and a real sentence (`scope_quote`).
`scripts/read_part_scopes.py` is the one explicit step that may add a Claude answer to the same store (`CLAUDE_READ_TASK`). It is one
more reading, checked the same way: two readings that disagree leave the rule UNKNOWN, whoever gave them.

  STANDARD  the standard has no Part or Appendix, or the rule stands before its first: the standard's own scope holds,
            which is who chose it for this kind and who signed the rule. Unchanged.
  GENERAL   a model read no limit AND the Part's own text says it applies to all of something (`says_all`, read from the
            passage whatever the reading quoted), and that something is all equipment, or this type, or the rule's own
            sentence names this type. A Part general for its own subject is general only for that subject.
  NAMED     the model read a limit and the sentence, verified in the passage, names this equipment type (one of its own
            spellings in the vocabulary; a phrase in a negated or excluded part of the sentence does not count). In scope.
  OUTSIDE   the model read a limit, the verified sentence names other equipment the vocabulary knows, the vocabulary puts
            that equipment in another family than this type, and the rule's own sentence does not name this type. Never
            paired, never decided, counted on the run by Part and rule id.
  UNKNOWN   anything else, and always when code cannot tell: no reading a scope-setting model gave, "unsure", readings that
            disagree, a sentence not in the passage, a sentence that names no equipment the vocabulary knows, a word shared
            with other types ("valve"), a wider kind (a type with no family, or in the family of what the sentence names),
            a "no" whose text does not say "all", no type, no page text, or a rule that cannot be placed. Never treated
            as in scope: the checklist says it is not paired, a review writes a Query with the reason.

A READING SETS SCOPE ONLY FROM THE READER MODEL (`settings.answer_model`) OR THE CLAUDE READ. Another model's stored answer
can only hold one back by disagreeing. A stored row that is not a reading is no reading.

A rule's Part is where its sentence stands (`division_text.division_of`). A cross-reference inside a Part breaks that
reading, so past a break the rule's own clause number places it, only when the Part it names spans the rule's page.

Nothing here names a standard, a Part, a layout or a kind of equipment (rule 13). What is apart from what is data, the
`family` of a type in `reference/equipment_vocabulary.json`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace

from . import (
    ai_applicability,
    ai_task_runner,
    compiled_rule_proof,
    division_text,
    rule_equipment_scope,
    scope_quote,
    subject_scope,
)
from .config import settings

STANDARD, GENERAL, NAMED, OUTSIDE, UNKNOWN = (
    "standard",
    "general",
    "named",
    "outside",
    "unknown",
)
# The reasons a checklist and a review name.
OUTSIDE_EQUIPMENT_SCOPE = "outside_equipment_scope"
SCOPE_NOT_ESTABLISHED = "scope_not_established"
_MEMO_SIZE = 8
#: A footnote's number printed right after a sentence's full stop: the sentence is whole.
_FOOTNOTE_MARK = re.compile(r"(?<=[.;!?])\d{1,3}$")
#: A clause that says it applies to all of something: its own verb, then the word for all, to the end of the sentence.
_SAYS_ALL = re.compile(
    r"\b(?:applicable|appl(?:y|ies)|covers?|intended)\b[^.;]{0,40}?\b(?:all|every|any)\b[^.;]*",
    re.IGNORECASE,
)
_ALL_EQUIPMENT = re.compile(
    r"\b(?:all|every|any)\b(?:\s+[\w-]+){0,3}?\s+equipment\b", re.IGNORECASE
)


def says_all(text: str) -> str | None:
    """The part of this text that says it applies to all of something, or None. Negated phrases do not count."""
    shown = rule_equipment_scope.masked(compiled_rule_proof.join_hyphens(text))
    found = _SAYS_ALL.search(shown)
    return found.group(0) if found else None


def _claude_read_problems(data: dict, text: str) -> list[str]:
    """Code's check of a Claude reading, before it is stored. The prompt asks for the sentence; this is the other half."""
    found = ai_applicability._scope_problems(data, text)
    sentence = sentence_of(data)
    if data.get("limited") == "no" and not says_all(sentence):
        found.append("no needs the sentence that says it applies to all of something")
    if not sentence:
        return found
    if not ai_applicability.folded_in(
        sentence, text, least=ai_applicability._QUOTE_MIN
    ):
        found.append("the scope sentence is not in the TEXT")
    elif not whole_sentence(sentence):
        found.append("the scope sentence is not a whole sentence")
    return found


#: The question asked for the sentence whatever it says, so a "no" can be checked. A reply goes in the one store under its
#: own version: the local path is not touched. Short on purpose: every character is paid for on every Part.
CLAUDE_READ_TASK = replace(
    ai_applicability.SCOPE_TASK,
    version="part-scope-claude-v2",
    instruction="""The TEXT is the start of one division of an engineering standard. Answer:
- limited: "yes" if its own scope sentence limits it to one construction, material or kind of equipment; "no" only if that
  sentence says it applies to all of something; "unsure" otherwise, and when there is no scope sentence;
- construction: when "yes", those words copied exactly; else null;
- quote: when "yes", the sentence copied exactly; else null;
- scope_sentence: the scope sentence copied exactly, whatever it says; null if none.""",
    schema={
        **ai_applicability.SCOPE_SCHEMA,
        "required": [*ai_applicability.SCOPE_SCHEMA["required"], "scope_sentence"],
        "properties": {
            **ai_applicability.SCOPE_SCHEMA["properties"],
            "scope_sentence": {"type": ["string", "null"]},
        },
    },
    check=_claude_read_problems,
    claude_retries=1,
)


def sentence_of(reading: dict) -> str:
    """The scope sentence a reading shows: its quote, or the sentence a Claude reading names."""
    return str(reading.get("quote") or reading.get("scope_sentence") or "")


def whole_sentence(sentence: str) -> bool:
    """A real sentence, by the one shape test; a footnote's number after the full stop leaves it whole."""
    shown = _FOOTNOTE_MARK.sub("", sentence.strip())
    return not scope_quote.problems(
        {"limited": "yes", "quote": shown, "construction": "named"}
    )


@dataclass(frozen=True)
class Scope:
    state: str
    reason: str | None
    #: Plain words for the engineer. Names the Part and its page; never quotes the standard.
    words: str
    division: str | None = None
    #: Two readings of this Part's scope clause disagree. A person's question, and counted on a read.
    disagreement: bool = False


@dataclass(frozen=True)
class _Standard:
    text: subject_scope.StandardText
    divs: list[dict]
    tops: list[dict]
    pages: dict[int, str]


_MEMO: dict[tuple, _Standard] = {}


def _standard_of(conn, document_id: str) -> _Standard | None:
    """A standard's text and divisions, read once per version of its stored text. None: no page text."""
    try:
        stored = conn.execute(
            "SELECT COUNT(*), SUM(LENGTH(text)) FROM pages WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not stored[0]:
        return None
    key = (document_id, stored[0], stored[1])
    if key not in _MEMO:
        pages = [
            (r[0], r[1] or "")
            for r in conn.execute(
                "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
                (document_id,),
            )
        ]
        text = subject_scope.StandardText(pages)
        divs = division_text.divisions(text)
        while len(_MEMO) >= _MEMO_SIZE:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[key] = _Standard(text, divs, division_text._tops(text, divs), dict(pages))
    return _MEMO[key]


def _label(top: dict) -> str:
    word, ident = top["name"]
    return f"{word.capitalize()} {ident}"


def _start_page(std: _Standard, top: dict) -> int | None:
    return division_text._page_at(std.text, top["at"])


def _named_by_clause(std: _Standard, named: list[dict], rule: dict) -> dict | None:
    """The named division the rule's own clause number starts with, when that division spans the rule's page."""
    parts = re.split(r"[-.(\s]", str(rule.get("clause") or "").upper())
    wanted = ["-".join(parts[:2]), parts[0]]
    page = rule.get("page")
    if page is None:
        return None
    for ident in wanted:
        for k, top in enumerate(named):
            following = _start_page(std, named[k + 1]) if k + 1 < len(named) else None
            start = _start_page(std, top)
            if (
                top["name"][1] == ident
                and start is not None
                and start <= page
                and (following is None or page < following)
            ):
                return top
    return None


def _placed(std: _Standard, rule: dict) -> tuple[dict | None, bool]:
    """(the named division the rule sits in or None, is the rule outside every division by standing before them all)."""
    named = [t for t in std.tops if t.get("name")]
    if not named:
        return None, True
    requirement = {"requirement_text": rule.get("quote"), "page": rule.get("page")}
    here = division_text.division_of(requirement, std.text, std.divs)
    if here is not None:
        return here, False
    page, first = rule.get("page"), _start_page(std, named[0])
    if page is not None and first is not None and page < first:
        return None, True
    return _named_by_clause(std, named, rule), False


def parts_of(conn, document_id: str) -> list[dict]:
    """A standard's named Parts and Appendices: {"label", "passage", "page"}, in order. Empty with no page text."""
    std = _standard_of(conn, document_id)
    if std is None:
        return []
    return [
        {
            "label": _label(t),
            "passage": _passage(std, t),
            "page": _start_page(std, t),
        }
        for t in std.tops
        if t.get("name")
    ]


def _passage(std: _Standard, top: dict) -> str:
    following = [t["line"] for t in std.tops if t["line"] > top["line"]]
    end = following[0] if following else None
    return division_text.scope_passage(std.text, top, end).strip()


def _reading(row, sets_scope: bool) -> dict | None:
    """A stored row as a reading, or None: a row that is not one must not stop a review."""
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return {**data, "_sets_scope": sets_scope} if isinstance(data, dict) else None


def _readings(conn, passage: str) -> list[dict]:
    """Every stored answer on this passage, and whether it may set scope: only the reader model's or the Claude read's. A
    Claude answer is the only thing in the store under its version, as `read_part_scopes` is the only thing that writes
    it. Nothing is asked."""
    found = []
    try:
        for spec in (ai_applicability.SCOPE_TASK, CLAUDE_READ_TASK):
            models = conn.execute(
                "SELECT DISTINCT model FROM ai_task_cache WHERE task = ? AND version = ? ORDER BY model",
                (spec.name, spec.version),
            ).fetchall()
            for model in models:
                row = conn.execute(
                    "SELECT result_json FROM ai_task_cache WHERE key = ?",
                    (ai_task_runner.cache_key(spec, model[0], passage),),
                ).fetchone()
                sets_scope = (
                    spec is CLAUDE_READ_TASK or model[0] == settings.answer_model
                )
                if row and (reading := _reading(row, sets_scope)):
                    found.append(reading)
    except sqlite3.OperationalError:
        return []
    return found


def _in_passage(sentence: str, passage: str) -> bool:
    """On the Part's own text: its passage stops where the Part does, so the next Part's sentence is not its sentence."""
    return compiled_rule_proof.quote_verified(sentence, passage)


def _apart(others: set[str], ours: set[str], vocab) -> bool:
    """Does the vocabulary put every one of these in another family than this type? A type with no family: it cannot say."""
    theirs = {vocab.family.get(t) for t in others}
    mine = {vocab.family.get(t) for t in ours}
    return None not in theirs and None not in mine and not theirs & mine


def _names_type(sentence: str, equipment_type: str) -> bool | None:
    """Does the sentence name this type? True: a spelling of this type alone. False: only when it names other equipment the
    vocabulary knows, in another family. None, a question for a person, for all else: a word shared with other types, a
    possibly wider kind, no equipment the vocabulary knows, or a type it does not know."""
    vocab = subject_scope.vocabulary()
    ours = vocab.equipment_in(equipment_type)
    if not ours or vocab.pattern is None:
        return None
    shown = rule_equipment_scope.masked(compiled_rule_proof.join_hyphens(sentence))
    shared = False
    others: set[str] = set()
    for match in vocab.pattern.finditer(subject_scope._fold(shown)):
        types = {
            t
            for t in vocab.phrases[match.group(0)]
            if vocab.kind.get(t) == subject_scope.EQUIPMENT
        }
        if types and types == ours:
            return True
        shared = shared or bool(types & ours)
        others |= types - ours
    if shared or not others:
        return None
    return False if _apart(others, ours, vocab) else None


def _unknown(words: str, division: str | None = None) -> Scope:
    return Scope(UNKNOWN, SCOPE_NOT_ESTABLISHED, words, division)


def _disagree(label: str) -> Scope:
    return Scope(
        UNKNOWN,
        SCOPE_NOT_ESTABLISHED,
        f"two readings of the scope clause of {label} disagree",
        label,
        True,
    )


def _general(
    passage: str, label: str, page, rule: dict, equipment_type: str | None
) -> Scope:
    """A reading of no limit, whatever it quoted: the Part's own text must say "all", and it is general for what it says."""
    span = says_all(passage)
    if span is None:
        return _unknown(
            f"{label} was read as no limit, and its text does not say so", label
        )
    if _ALL_EQUIPMENT.search(span):
        return Scope(
            GENERAL, None, f"{label} covers all equipment (page {page})", label
        )
    if not equipment_type:
        return _unknown(f"this sheet's equipment type is not known, for {label}", label)
    if _names_type(span, equipment_type) is True:
        return Scope(
            GENERAL, None, f"{label} covers {equipment_type} (page {page})", label
        )
    if _names_type(str(rule.get("quote") or ""), equipment_type) is True:
        return Scope(
            GENERAL, None, f"this rule of {label} names {equipment_type}", label
        )
    return _unknown(
        f"{label} is general for its own subject; neither its scope clause nor this rule names {equipment_type}",
        label,
    )


def _limited(
    shown: list[str], label: str, page, rule: dict, equipment_type: str | None
) -> Scope:
    if not all(whole_sentence(s) for s in shown):
        return _unknown(f"the scope reading of {label} is not a whole sentence", label)
    if not equipment_type:
        return _unknown(
            f"{label} is limited and this sheet's equipment type is not known", label
        )
    named = {_names_type(s, equipment_type) for s in shown}
    if len(named) > 1:
        return _disagree(label)
    named = named.pop()
    if named is None:
        return _unknown(
            f"code cannot tell whether {label} covers {equipment_type}", label
        )
    if named:
        return Scope(
            NAMED, None, f"{label} is for {equipment_type} (page {page})", label
        )
    if _names_type(str(rule.get("quote") or ""), equipment_type) is True:
        return _unknown(
            f"the scope clause of {label} names other equipment and this rule names {equipment_type}",
            label,
        )
    return Scope(
        OUTSIDE,
        OUTSIDE_EQUIPMENT_SCOPE,
        f"the scope clause of {label} (page {page}) names other equipment, not {equipment_type}",
        label,
    )


def _read_part(
    conn, std: _Standard, top: dict, rule: dict, equipment_type: str | None
) -> Scope:
    label = _label(top)
    passage = _passage(std, top)
    readings = _readings(conn, passage)
    if not readings:
        return _unknown(f"the scope clause of {label} has not been read", label)
    if len({r.get("limited") for r in readings}) > 1:
        return _disagree(label)
    if not any(r["_sets_scope"] for r in readings):
        return _unknown(
            f"the scope clause of {label} was read only by a model that does not set scope",
            label,
        )
    limited = readings[0].get("limited")
    if limited not in ("yes", "no"):
        return _unknown(f"the scope clause of {label} leaves its limit open", label)
    page = _start_page(std, top)
    if limited == "no":
        return _general(passage, label, page, rule, equipment_type)
    said = {sentence_of(r) for r in readings if r["_sets_scope"] and sentence_of(r)}
    if not said:
        return _unknown(f"no scope sentence of {label} was shown", label)
    if not all(_in_passage(s, passage) for s in said):
        return _unknown(
            f"the scope sentence read for {label} is not in its own text", label
        )
    return _limited(sorted(said), label, page, rule, equipment_type)


def of_rule(conn, rule: dict, equipment_type: str | None) -> Scope:
    """This rule's scope against this equipment type. `rule` names its standard, clause, page and quote. Read only."""
    document_id = rule.get("standard_document_id") or rule.get("document_id")
    if not document_id:
        return _unknown("the rule does not say which standard it comes from")
    std = _standard_of(conn, document_id)
    if std is None:
        return _unknown("no page text of its standard is stored")
    top, before_every_part = _placed(std, rule)
    if before_every_part:
        return Scope(STANDARD, None, "the standard's own scope")
    if top is None:
        return _unknown("code cannot place the rule in a Part or Appendix")
    return _read_part(conn, std, top, rule, equipment_type)
