"""An 'absent' Fail CHECKED by code (ported from the experiment's exp11/absence.py).

Before: every AI 'absent' Fail became a Query ("code cannot prove an absence"). Here code tries to PROVE the absence
from what the product already stores; the Fail stands only when every step below holds, else the line stays a Query
with one plain why code (ABSENCE_WHY). Pure functions over plain data; no model, no network, no paper text written.

  1 REQUIRED. The item is a rule (a skill item has no stored obligation), its kind is not advice, its type is not a
    recommendation, its own requirement sentence binds ('shall' / 'must': compiled_rule_proof.strength_of), the rule
    has no stored exception, no stored condition (a numeric_limit row's `condition`; on table rows that column is the
    row label, conditions.py), and the sentence has no condition opener (CONDITION_WORDS: general English, no layout).
  2 FIELD KNOWN. The rule's OWN field (item field_roles, the rule data's field, or the requirement's stored
    closed-vocabulary name) maps to the product's field registry: a role of reference/datasheet_checks.json
    (datasheet_roles.roles_of) or a group of reference/field_synonyms.json (field_links). Its words are the registry's
    label patterns and synonym spellings, never words written for one paper.
  2b CARRIED BY THIS PAPER KIND (lead, 11 Nov: "really absent" is not "a real problem"; most absent items belong in
    other papers). The field list is the registry's list for the paper's equipment type (datasheet_roles.wanted_roles:
    the type's mandatory list and checklist) and exists only for a datasheet paper kind (step 2's kind). A role that
    list does not carry, or a paper kind with no field list (a procedure), stays a Query: never a Fail.
  3 EVERY PAGE READABLE. Pages 1..N all present, each with a native text layer (ledger 'text', not needing OCR, no
    OCR pending or failed) and at least MIN_PAGE_CHARS characters. One unreadable or near-empty page: no proof.
  4 NOT READ. No field read from the paper (submittal_facts, every reader run, superseded rows too) names the role.
  5 NOT ON ANY PAGE. No line of any page carries a registry label pattern, a synonym spelling of the field, or ANY
    content word of the field's registry names (agent_bind.content_words). The last part is strict on purpose: the
    11 Nov hand check found the registry spellings narrower than real labels (an area stated as 'effective area', a
    speed as 'rpm' with a blank), so a missing spelling proved nothing; one shared word now keeps it a Query.
  6 NOT DEFERRED. No line carries the field's words with a deferral mark (run.deferred_mark: "By Contractor", "TBA").
The runner adds: the clause quote verified and strong, and the second opinion asked on the ABSENCE claim agrees.
Rule 4: 'not mentioned' is never compliant: this path gives Fail or Query, never Pass.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .agent_review_verdict import BY_ABSENCE  # noqa: F401  the label lives with the other labels

MIN_PAGE_CHARS = 100
#: Condition openers: a sentence that binds only under a condition the paper may not show is not provably required.
CONDITION_WORDS = ("if", "when", "where", "whenever", "unless", "in case", "provided that", "specified", "purchaser",
                   "agreed", "applicable", "optional", "option", "otherwise")
_CONDITION = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in CONDITION_WORDS) + r")\b")

#: why code -> the plain why written on the Query line
ABSENCE_WHY = {
    "absence_not_a_rule": "not a held rule: code cannot tell the item is required",
    "absence_rule_not_found": "the rule's stored requirement row was not found: code cannot tell it binds",
    "absence_advice": "the rule is advice, not a requirement: an absence is not a Fail",
    "absence_not_binding": "the requirement does not say shall or must: an absence is not a Fail",
    "absence_conditional": "the requirement holds only under a condition: code cannot prove it applies",
    "absence_exception": "the rule has a stored exception: code cannot prove it applies",
    "absence_field_unknown": "the rule names no field of the field registry: code cannot prove an absence",
    "absence_field_ambiguous": "the requirement names several registry fields: code cannot tell which is absent",
    "absence_no_field_list": "this paper kind has no field list: code cannot tell the item belongs on this paper",
    "absence_not_carried": "this paper kind's field list does not carry the field: the item may belong in another paper",
    "absence_page_unreadable": "a page has no readable text: code cannot prove an absence",
    "absence_field_read": "a field read from the paper names this item",
    "absence_field_words_on_page": "the field's registry words stand on a page of the paper",
    "absence_value_deferred": "the sheet marks this value as not final",
    "absence_clause_weak": "clause quote not verified or too short: an absence Fail needs a strong clause quote",
    "absence_no_second_opinion": "no second opinion on the absence",
    "absence_second_disagreed": "the second opinion did not agree the item is absent",
    "absence_second_same_model": "second opinion model is the same or unknown",
}


@dataclass(frozen=True)
class Proof:
    """`proven`: code proved the absence (steps 1-6). Else `code` (an ABSENCE_WHY key) and `page` where it broke."""

    proven: bool
    code: str | None = None
    page: int | None = None
    role: str | None = None
    role_source: str | None = None
    field_words: tuple[str, ...] = ()
    pages_checked: int = 0
    facts_checked: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def why(self) -> str | None:
        if self.proven:
            return None
        text = ABSENCE_WHY.get(str(self.code), str(self.code))
        return f"{text} (page {self.page})" if self.page else text

    def to_json(self) -> dict:
        return {"proven": self.proven, "code": self.code, "page": self.page, "role": self.role,
                "role_source": self.role_source, "pages_checked": self.pages_checked,
                "facts_checked": self.facts_checked}


def fold(text: Any) -> str:
    """The role matcher's fold (datasheet_checks._fold) plus punctuation to spaces, so a label is read the same way."""
    return " ".join(re.sub(r"[^\w\s.]", " ", str(text or "").lower().replace(":", " ")).split())


# ---------------------------------------------------------------- 1 required


def required(item: Mapping, requirement: str | None) -> str | None:
    """None when the item is provably required, else its why code."""
    from .compiled_rule_proof import strength_of

    if item.get("source") != "rule":
        return "absence_not_a_rule"
    if item.get("rule_row_found") is not True:  # review 4: no stored requirement row read: the rule cannot bind
        return "absence_rule_not_found"
    if item.get("rule_kind") == "advice" or item.get("requirement_type") == "recommendation":
        return "absence_advice"
    sentence = " ".join(str(requirement or "").lower().split())
    if not sentence or strength_of(sentence) != "shall":
        return "absence_not_binding"
    if str(item.get("rule_exceptions") or "").strip() not in ("", "[]", "{}", "null"):
        return "absence_exception"
    if item.get("requirement_type") == "numeric_limit" and str(item.get("rule_condition") or "").strip():
        return "absence_conditional"
    if _CONDITION.search(sentence):
        return "absence_conditional"
    return None


# ---------------------------------------------------------------- 2 the field in the registry


@lru_cache(maxsize=2)
def registry() -> dict:
    from . import datasheet_checks

    return datasheet_checks.load_rules()


def _deanchor(pattern: str) -> re.Pattern:
    """A whole-label pattern ('^design press(ure)?$') made a search inside a line."""
    p = re.sub(r"(?:(?<=^)|(?<=[(|]))\^", "", pattern)
    p = re.sub(r"\$(?=$|[)|])", "", p)
    return re.compile(p)


def _synonym_groups() -> dict[str, list[str]]:
    """{canonical phrase: [its spellings, itself included]} from field_synonyms.json (field_links' table)."""
    from . import field_links

    _pattern, to_canonical, _attrs = field_links._table()
    out: dict[str, list[str]] = {}
    for spelling, canon in to_canonical.items():
        out.setdefault(canon, []).append(spelling)
    return out


@dataclass(frozen=True)
class FieldWords:
    role: str | None  # the registry role, or None when only a synonym group knows the field
    canonical: str | None  # the synonym group, or None
    patterns: tuple[re.Pattern, ...]
    spellings: tuple[str, ...]
    source: str

    def names(self) -> tuple[str, ...]:
        """Plain names for the comment and the second opinion: the registry's words, never the paper's."""
        out = [s for s in (self.canonical, (self.role or "").replace("_", " ")) if s]
        return tuple(dict.fromkeys(out))


def field_words(candidates: Iterable[tuple[str, str]], rules: Mapping | None = None) -> FieldWords | None:
    """The first candidate field (name, source) the registry knows, with its words; None when none is known."""
    from . import datasheet_roles, field_links

    rules = rules or registry()
    groups = _synonym_groups()
    for name, source in candidates:
        name = str(name or "").strip()
        if not name:
            continue
        roles = datasheet_roles.roles_of(name, rules) or datasheet_roles.roles_of(name.replace("_", " "), rules)
        if not roles and name in rules["roles"]:
            roles = [name]
        canon = field_links.canonical(name.replace("_", " "))
        group = canon if canon in groups else None
        if not roles and group is None:
            continue
        role = roles[0] if roles else None
        patterns: list[re.Pattern] = []
        for r in roles:
            for p in rules["roles"][r]["names"]:
                patterns.append(_deanchor(p))  # a bad pattern raises: never a silently smaller search
        if role and group is None:
            rc = field_links.canonical(role.replace("_", " "))
            group = rc if rc in groups else None
        spellings = sorted(set(groups.get(group, [])) | ({fold(name.replace("_", " "))} if roles or group else set()))
        return FieldWords(role, group, tuple(patterns), tuple(s for s in spellings if s), source)
    return None


def candidates_of(item: Mapping) -> list[tuple[str, str]]:
    """The rule's OWN field names, in order: its field roles (H3's, or the rule data's), then the requirement's stored
    closed-vocabulary name. Never the AI's label: that names the paper words nearest to where the item should be."""
    out = [(str(r), str(item.get("field_roles_source") or "items")) for r in item.get("field_roles") or []]
    out += [(str(n), "stored requirement name") for n in item.get("requirement_names") or []]
    return out


def roles_named_in(sentence: str | None, carried: Iterable[str], rules: Mapping | None = None) -> list[str]:
    """The carried registry roles whose label pattern stands in the requirement sentence itself (code, registry
    words): the field the rule's own words name when the rule data stores none."""
    rules = rules or registry()
    folded = fold(sentence)
    out = []
    for role in sorted(carried):
        spec = rules["roles"].get(role)
        if spec and any(_deanchor(p).search(folded) for p in spec["names"]):
            out.append(role)
    return out


def carried_roles(paper_kind: str | None, equipment_type: str | None, rules: Mapping | None = None) -> frozenset | None:
    """The roles this paper kind carries: the registry's field list for the equipment type, for a datasheet only.
    None: no field list (another paper kind, or no list for the type)."""
    from . import datasheet_roles

    from . import datasheet_checks

    if paper_kind != "datasheet":
        return None
    rules = rules or registry()
    # review 5: an unknown type falls back to the GENERIC list in the product; that is no field list of THIS paper
    if not equipment_type or datasheet_checks.mandatory_list_key(equipment_type, rules) == "_generic":
        return None
    roles = datasheet_roles.wanted_roles(equipment_type, rules)
    return roles or None


# ---------------------------------------------------------------- 3 readable pages


def unreadable_page(texts: Mapping[int, str], total: int, ledger: Mapping[int, Mapping] | None) -> int | None:
    """The first page 1..total that is not readable as text, else None. `ledger` None: text checks only (fixtures)."""
    if total <= 0:
        return 1
    for n in range(1, total + 1):
        text = texts.get(n)
        if not text or len(text.strip()) < MIN_PAGE_CHARS:
            return n
        if ledger is not None:
            row = ledger.get(n)
            if not row or row.get("native_status") != "text" or row.get("needs_ocr"):
                return n
            if row.get("ocr_status") in ("pending", "failed"):
                return n
    return None


# ---------------------------------------------------------------- 4, 5 and 6: not read, not on a page, not deferred


def _line_has(line: str, words: FieldWords, any_word: bool = False) -> bool:
    folded = fold(line)
    if any(p.search(folded) for p in words.patterns):
        return True
    if any(re.search(rf"(?<!\w){re.escape(s)}(?!\w)", folded) for s in words.spellings):
        return True
    if any_word:
        from .agent_bind import content_words

        want = content_words(" ".join([*words.names(), *words.spellings]))
        return bool(want & content_words(folded))
    return False


def fact_naming(facts: Iterable[Mapping], words: FieldWords, rules: Mapping | None = None) -> int | None:
    """The page of the first fact read from the paper that names the field (its role, its words), else None.
    A fact with no page counts as page 0 (still a hit)."""
    from . import datasheet_roles

    rules = rules or registry()
    for f in facts:
        for name in (f.get("field_name"), f.get("field_label")):
            if not name:
                continue
            if words.role and words.role in datasheet_roles.roles_of(str(name), rules):
                return int(f.get("page") or 0)
            if _line_has(str(name), words, any_word=True):
                return int(f.get("page") or 0)
    return None


def page_naming(texts: Mapping[int, str], total: int, words: FieldWords) -> int | None:
    for n in range(1, total + 1):
        for line in (texts.get(n) or "").splitlines():
            if _line_has(line, words, any_word=True):
                return n
    return None


def prove(item: Mapping, requirement: str | None, texts: Mapping[int, str], total: int,
          ledger: Mapping[int, Mapping] | None, facts: list[Mapping], carried: frozenset | None,
          deferred: Callable[[str], int | None] | None = None, rules: Mapping | None = None) -> Proof:
    """Steps 1-6 in order; the first that fails names the why code. `carried`: `carried_roles` of this paper."""
    code = required(item, requirement)
    if code:
        return Proof(False, code)
    if carried is None:
        return Proof(False, "absence_no_field_list")
    candidates = candidates_of(item)
    if not candidates:
        named = roles_named_in(requirement, carried, rules)
        if len(named) > 1:
            return Proof(False, "absence_field_ambiguous", extra={"roles": named})
        candidates = [(r, "named in the requirement") for r in named]
    # review 8: EVERY known field of the rule must be proven absent, not only the first
    known = [w for w in (field_words([c], rules) for c in candidates) if w is not None]
    if not known:
        return Proof(False, "absence_field_unknown")
    first = known[0]
    base = {"role": first.role or first.canonical, "role_source": first.source, "field_words": first.names()}
    for words in known:
        if words.role is None or words.role not in carried:
            return Proof(False, "absence_not_carried", **base)
    bad = unreadable_page(texts, total, ledger)
    if bad is not None:
        return Proof(False, "absence_page_unreadable", bad, **base)
    for words in known:
        page = fact_naming(facts, words, rules)
        if page is not None:
            return Proof(False, "absence_field_read", page or None, facts_checked=len(facts), **base)
        page = page_naming(texts, total, words)
        if page is not None:
            return Proof(False, "absence_field_words_on_page", page, pages_checked=total, facts_checked=len(facts),
                         **base)
        if deferred is not None:
            for name in words.names():
                page = deferred(name)
                if page is not None:
                    return Proof(False, "absence_value_deferred", page, pages_checked=total, **base)
    return Proof(True, None, None, pages_checked=total, facts_checked=len(facts), **base)


def comment(words: tuple[str, ...], standard: Any, clause: Any) -> str:
    """The contractor sentence for a checked absence: the registry's field name, no number, no paper words."""
    name = words[0] if words else "this item"
    where = " ".join(str(x) for x in (standard, f"clause {clause}" if clause else "") if x)
    return f"The {name} is not stated on the paper; please state it{f' as {where} requires' if where else ''}."


# ---------------------------------------------------------------- the deferral guard of a Pass (owner rule 10 Nov)


def deferred_mark(field_text: str, texts: Mapping[int, str]) -> int | None:
    """The first page where ONE line carries all the field's content words AND a deferral mark from the existing vocabulary
    (`blank_markers.names_a_marker`: "By Contractor", "TBA", "vendor to advise", ...), else None. A figure followed by 'By
    Contractor' is not a confirmed value. General: words, no layout. `texts` is {page number: page text}."""
    from .agent_bind import content_words
    from .blank_markers import names_a_marker

    want = content_words(field_text)
    if not want:
        return None
    for n in sorted(texts):
        for raw in (texts.get(n) or "").splitlines():
            if names_a_marker(raw) and want <= content_words(raw):
                return n
    return None


def pass_guard(item: Mapping, label: str, texts: Mapping[int, str]) -> tuple[dict, str, int | None] | None:
    """(decision, reason code, deferred page) when a Pass must become a Query, else None. Field words: the item's roles, else
    the field label code found on the page. Unknown field words: Query on the safe side; the field marked deferred on any
    page: Query. A guard that only makes a Pass less confident."""
    from .agent_bind import content_words

    field_text = " ".join(str(r).replace("_", " ") for r in item.get("field_roles") or []) or label
    if not content_words(field_text):
        return (
            {
                "verdict": "Query",
                "decided_by": "engineer",
                "why": "field words unknown: code cannot check the sheet for a deferral mark",
            },
            "field_unknown_cannot_check_deferral",
            None,
        )
    page = deferred_mark(field_text, texts)
    if page is None:
        return None
    return (
        {"verdict": "Query", "decided_by": "engineer", "why": f"the sheet marks this value as not final on page {page}"},
        "value_deferred",
        page,
    )
