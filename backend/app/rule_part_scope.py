"""Which equipment a rule is for, from the scope clause of the Part or Appendix it sits in (owner's order, 2 Nov 2026).

A CLAUSE OF A STANDARD CAN BE TRUE AND STILL NOT BE ABOUT THIS EQUIPMENT. A review or a checklist asks here before it
pairs a rule with a value. Only with RULEBOOK_V2_REVIEW_ENABLED on; the callers keep the door.

AI READ IT, CODE VERIFIES IT, NOTHING IS GUESSED. There is no second reader: the division gate's model already reads each
Part's scope clause (`ai_applicability.SCOPE_TASK`, on `division_text.scope_passage`) and keeps the answer in
`ai_task_cache`. This reads that stored answer, read only, and sends nothing. The answer's key holds the passage, so a
changed text is no answer. Code verifies the sentence is on the Part's page and a real sentence (`scope_quote`).

  STANDARD  the standard has no Part or Appendix, or the rule stands before its first: the standard's own scope holds,
            which is who chose it for this kind and who signed the rule. Unchanged.
  GENERAL   the model read no limit AND showed the sentence that says so, verified on the page. In scope for any type.
  NAMED     the model read a limit and the verified sentence names this equipment type (one of its own spellings in the
            equipment vocabulary; a phrase in a negated or excluded part of the sentence does not count). In scope.
  OUTSIDE   the model read a limit and the verified sentence does not name this type, not even by a word it shares with
            others. Never paired, never decided, counted on the run with a named reason.
  UNKNOWN   anything else: no stored reading, "unsure", two readings that disagree, a sentence not on the page, a "no" with
            no sentence shown, only a shared word ("valve"), no type, no page text, or a rule that cannot be placed. It is
            never treated as in scope: the checklist says it is not paired, a review writes a Query with the reason.

A rule's Part is where its sentence stands (`division_text.division_of`). A cross-reference inside a Part breaks that
reading, so past a break the rule's own clause number places it, only when the Part it names spans the rule's page.

Nothing here names a standard, a Part, a layout or a kind of equipment (rule 13). A type that is a kind of another is not
known here: a Part limited to the wider kind reads as OUTSIDE for it until the vocabulary says otherwise.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from . import (
    ai_applicability,
    ai_task_runner,
    compiled_rule_proof,
    division_text,
    rule_equipment_scope,
    scope_quote,
    subject_scope,
)

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


@dataclass(frozen=True)
class Scope:
    state: str
    reason: str | None
    #: Plain words for the engineer. Names the Part and its page; never quotes the standard.
    words: str
    division: str | None = None


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


def _passage(std: _Standard, top: dict) -> str:
    following = [t["line"] for t in std.tops if t["line"] > top["line"]]
    end = following[0] if following else None
    return division_text.scope_passage(std.text, top, end).strip()


def _readings(conn, passage: str) -> list[dict]:
    """Every stored answer of the division gate's scope task on this passage, from any model. Nothing is asked."""
    spec = ai_applicability.SCOPE_TASK
    try:
        models = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT model FROM ai_task_cache WHERE task = ? AND version = ? ORDER BY model",
                (spec.name, spec.version),
            )
        ]
        found = [
            conn.execute(
                "SELECT result_json FROM ai_task_cache WHERE key = ?",
                (ai_task_runner.cache_key(spec, model, passage),),
            ).fetchone()
            for model in models
        ]
    except sqlite3.OperationalError:
        return []
    return [json.loads(r[0]) for r in found if r]


def _on_its_page(std: _Standard, top: dict, sentence: str) -> int | None:
    """The page the sentence stands on: the Part's first page or the one after, where a sentence may run on to."""
    start = _start_page(std, top)
    if start is None:
        return None
    if compiled_rule_proof.quote_verified(sentence, std.pages.get(start)):
        return start
    together = f"{std.pages.get(start, '')}\n{std.pages.get(start + 1, '')}"
    return start if compiled_rule_proof.quote_verified(sentence, together) else None


def _names_type(sentence: str, equipment_type: str) -> bool | None:
    """Does the sentence name this type? True: a spelling of this type alone. None: only a word it shares with other
    types, or a type the vocabulary does not know. False: it does not."""
    vocab = subject_scope.vocabulary()
    ours = vocab.equipment_in(equipment_type)
    if not ours or vocab.pattern is None:
        return None
    shown = rule_equipment_scope.masked(compiled_rule_proof.join_hyphens(sentence))
    shared = False
    for match in vocab.pattern.finditer(subject_scope._fold(shown)):
        types = vocab.phrases[match.group(0)]
        if types == ours:
            return True
        shared = shared or bool(types & ours)
    return None if shared else False


def _unknown(words: str, division: str | None = None) -> Scope:
    return Scope(UNKNOWN, SCOPE_NOT_ESTABLISHED, words, division)


def _read_part(conn, std: _Standard, top: dict, equipment_type: str | None) -> Scope:
    label = _label(top)
    readings = _readings(conn, _passage(std, top))
    if not readings:
        return _unknown(f"the scope clause of {label} has not been read", label)
    said = {r.get("limited") for r in readings}
    if len(said) > 1:
        return _unknown(f"two readings of the scope clause of {label} disagree", label)
    limited = said.pop()
    if limited not in ("yes", "no"):
        return _unknown(f"the scope clause of {label} leaves its limit open", label)
    sentence = str(next((r["quote"] for r in readings if r.get("quote")), "") or "")
    if not sentence:
        return _unknown(f"no scope sentence of {label} was shown", label)
    page = _on_its_page(std, top, sentence)
    if page is None:
        return _unknown(
            f"the scope sentence read for {label} is not on its page", label
        )
    if limited == "no":
        return Scope(
            GENERAL, None, f"{label} sets no limit on equipment (page {page})", label
        )
    if scope_quote.problems(
        {**readings[0], "quote": _FOOTNOTE_MARK.sub("", sentence.strip())}
    ):
        return _unknown(f"the scope reading of {label} is not a whole sentence", label)
    if not equipment_type:
        return _unknown(
            f"{label} is limited and this sheet's equipment type is not known", label
        )
    named = _names_type(sentence, equipment_type)
    if named is None:
        return _unknown(
            f"code cannot tell whether {label} covers {equipment_type}", label
        )
    if named:
        return Scope(
            NAMED, None, f"{label} is for {equipment_type} (page {page})", label
        )
    return Scope(
        OUTSIDE,
        OUTSIDE_EQUIPMENT_SCOPE,
        f"the scope clause of {label} (page {page}) covers other equipment, not {equipment_type}",
        label,
    )


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
    return _read_part(conn, std, top, equipment_type)
