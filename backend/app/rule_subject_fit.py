"""Is a rule about something this paper does not have? (order 14 LPV V1; owner, 17 Nov 2026; the lead's decision after review)

A rule was asked of a steel drum because it shared a word ("design life", "design pressure") with a field of the paper, although
the rule was written for an acrylic window. NOTHING IS DROPPED BY WORDS: such a rule stays in the review, and its point (the rule
check's or the AI reviewer's) moves to the owner's section "AI thinks these do not apply, tick to confirm" with the reason "the
paper names no <thing> on any page"; the engineer confirms it (`to_confirm`, applied when the points are assembled).

What a rule is ABOUT, per sentence of its stored text (a stored rule may hold two sentences: each is read):
  * the sentence's grammatical subject, the words before its "shall" / "must" / ... (`subject_part`);
  * the whole lead-in of the list it is an item of, only when the items between the lead-in and it are that list's own items
    in order (`lead_in`);
  * the title of its section, when that heading is a title (no modal verb) naming no second group (no "and", "or", comma) and
    the thing is the title's head, its last words ("Tests for <things>", never "... with <thing> liners").
The things are DATA (`reference/rule_subject_things.json`), with their spellings. A point moves only when EVERY sentence is about
a thing and the paper names none of the things on any page. In ANY doubt it stays as it is:
  * the rule REQUIRES the thing (it is named after the verb, or "<thing> shall be provided / fitted / used / installed /
    supplied / furnished / required"): a missing required part is a finding, never a reason to set the rule aside;
  * a negation within six words before the thing ("without", "no", "not", "unless", "instead of", "other than", "except",
    "excluding", "non-"), a subject that joins the thing with another group ("for X and for <thing>", a comma), or a subject
    holding a verb (the stored text glued two sentences);
  * a page of the paper not readable as text.
A sentence that only carries on a worked example of the book ("For example, ... 93 psig. The operating pressure must be kept
below 93 psig ...", every measured figure of it in the example: `claims.extract_measurements`, never a list or clause number) moves
to the same section with its own reason. No standard, clause or layout is named in code (rule 13). Reads only; no model."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

from . import subject_scope

THINGS_PATH = Path(__file__).parent / "reference" / "rule_subject_things.json"
EXAMPLE_WORDS = "a worked example in the rule book, not a requirement"
#: the ONE label a moved point carries everywhere (pill, page, both files): code moved it, the engineer confirms
LABEL = "Does not apply? (code, engineer to confirm)"
ACTION = "Engineer to check whether the rule applies to this paper: {reason}."
WHY = "Code, not the AI: {reason} (the engineer confirms)."
#: where the thing was read, in the reason's own words (honesty rule 4: the reason says where it comes from)
SOURCE_WORDS = {
    "own": "its own words are about",
    "list": "the list it sits in is about",
    "title": "its section is about",
}

_ENUM = re.compile(r"^\s*\((\d{1,2}|[a-z]|[ivx]{1,4})\)\s", re.IGNORECASE)
_ITEM = re.compile(r"\((\d{1,2}|[a-z])\)\s")
_LIST_START = re.compile(r":\s*\((1|a)\)\s", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.;]\s")
#: a sentence ends at ". " / "; " before a capital or "(", or where a new clause number starts ("... not allowed 5.2.17 Concrete ...")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])|\s+(?=\d+(?:\.\d+)+\s+[A-Z])")
#: a verb inside the words before "shall": the stored text glued two sentences, so its subject is not one noun phrase (doubt)
_VERB_IN_SUBJECT = re.compile(
    r"\b(?:is|are|was|were|been|does|do|did|has|have|had|requires?|allowed|permitted)\b",
    re.I,
)
LEAD_IN_MAX = 600
_NEGATION = re.compile(
    r"\b(?:without|no|not|nor|unless|instead of|other than|except|exception|excluding|exclusive of|non)\b(?:\s+\S+){0,6}\s*$"
)
#: "flanges such as <thing>", "parts including <thing>": the thing is an example of something else (the rule stays)
_EXAMPLE_OF = re.compile(
    r"\b(?:such as|including|includes|include|e g|eg|like|namely)\b(?:\s+\S+){0,3}\s*$"
)
_JOINED = re.compile(r"\b(?:and|or)\b|,")
_AND_OR = re.compile(r"\b(?:and|or)\b")
#: a subject that opens with a condition on the thing ("Where <thing> is fitted, ...", "If ...", "For <things>, ...")
_CONDITION = re.compile(
    r"^\W*(?:\(\w{1,4}\)\s*)?(?:where|if|when|whenever|for|in the case of|in case of)\b",
    re.I,
)
#: the words that put the thing in a qualifier of the subject ("the design life OF the <thing>", "procedures BY <thing> systems")
_QUALIFIER = re.compile(
    r"\b(?:of|for|in|on|with|by|to|from|within|inside)\b(?:\s+\S+){0,3}\s*$"
)
_EXAMPLE_OPEN = re.compile(
    r"^(?:for example|for instance|e\.\s?g\.)[\s,]", re.IGNORECASE
)


@lru_cache(maxsize=4)
def _things(path: str, mtime: float) -> tuple[tuple, ...]:  # noqa: ARG001 - the file time is the cache key
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for entry in data.get("things") or []:
        words = tuple(
            sorted(
                {
                    subject_scope._fold(w)
                    for w in entry.get("words") or []
                    if subject_scope._fold(w)
                }
            )
        )
        paper = tuple(
            sorted(
                {
                    _compact(w)
                    for w in [*words, *(entry.get("paper_words") or [])]
                    if _compact(w)
                }
            )
        )
        if entry.get("name") and words:
            out.append((str(entry["name"]), words, paper))
    return tuple(out)


def things(path: Path | str | None = None) -> tuple[tuple, ...]:
    """((name, folded spellings, paper spellings), ...) from the data file; a malformed entry is skipped (nothing moves for it).
    The paper spellings (the spellings plus `paper_words`, compacted) are what keeps a rule when the paper names any of them."""
    p = Path(path or THINGS_PATH)
    return _things(str(p), p.stat().st_mtime)


def _compact(text: object) -> str:
    """Letters and digits only, lower case: "G.R.P.", "Fire-Water" and "FIREWATER" read alike."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _entry(entry: tuple) -> tuple[str, tuple, tuple]:
    name, words, *rest = entry
    return name, words, rest[0] if rest else tuple(_compact(w) for w in words)


def _found(text: object, catalogue) -> list[tuple[str, str, bool, int]]:
    """[(name, the spelling found, doubt, position in the folded text)] for every spelling of a thing that stands whole in `text`.
    Doubt: a negation within six words before it, or the thing given as an example of something else ("such as", "including")."""
    folded = subject_scope._fold(text)
    out = []
    for entry in catalogue:
        name, words, _paper = _entry(entry)
        for w in words:
            for m in re.finditer(
                r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", folded
            ):
                before = folded[: m.start()].rstrip()
                out.append(
                    (
                        name,
                        w,
                        bool(_NEGATION.search(before) or _EXAMPLE_OF.search(before)),
                        m.start(),
                    )
                )
    return out


def sentences(text: object) -> list[str]:
    """The sentences of a stored rule (a stored rule may hold two)."""
    return [
        s.strip()
        for s in _SENTENCE_SPLIT.split(" ".join(str(text or "").split()))
        if s.strip()
    ]


_OBLIGATION = re.compile(
    r"\b(?:shall|must|should|will|needs? to|is to|are to|is required|are required|to be)\b",
    re.IGNORECASE,
)


def subject_part(sentence: object) -> str:
    """The sentence's grammatical subject: its words before its obligation ("shall", "must", "is required", "to be" ...); "" with
    none."""
    text = " ".join(str(sentence or "").split())
    verb = _OBLIGATION.search(text) or subject_scope._MODAL.search(text)
    return text[: verb.start()] if verb else ""


def requires(sentence: str, catalogue) -> bool:
    """The sentence's OBLIGATION is on the thing: the thing is its object (named after "shall" / "must" / "is required" / "to be"),
    or the HEAD of its subject ("A sight glass shall be available", "Fire pumps shall comply ..."). Such a rule STAYS asked: on a
    paper without the thing, the missing thing is the finding. It is NOT an obligation on the thing when the subject opens with a
    condition ("Where / If / When <thing> is fitted, ...", "For <things>, ...") or the thing only qualifies the subject ("the design
    life OF the <thing>")."""
    text = " ".join(str(sentence or "").split())
    verb = _OBLIGATION.search(text) or subject_scope._MODAL.search(text)
    if not verb:
        return False
    if any(not doubt for _n, _w, doubt, _at in _found(text[verb.end() :], catalogue)):
        return True
    subject = text[: verb.start()]
    if _CONDITION.search(subject):
        return False
    folded = subject_scope._fold(subject)
    return any(
        not _QUALIFIER.search(folded[:at].rstrip())
        for _n, _w, doubt, at in _found(subject, catalogue)
        if not doubt
    )


def _style(marker: str) -> str:
    return "digit" if marker.isdigit() else "letter"


def _ordinal(marker: str) -> int:
    return int(marker) if marker.isdigit() else ord(marker.lower()) - ord("a") + 1


def lead_in(sentence: object, passage: object) -> str:
    """The lead-in of the list `sentence` is item k of: the sentence ending in ":" right before item (1) / (a) of the same style,
    found in `passage`, ONLY when the items between it and this one are that list's items 1 .. k-1 in order (a lead-in is never
    inherited across lists). "" otherwise."""
    sent = " ".join(str(sentence or "").split())
    text = " ".join(str(passage or "").split())
    own = _ENUM.match(sent)
    at = text.find(sent[:80]) if own else -1
    if at <= 0:
        return ""
    prefix = text[:at]
    starts = [
        m
        for m in _LIST_START.finditer(prefix)
        if _style(m.group(1)) == _style(own.group(1))
    ]
    if not starts:
        return ""
    colon = starts[-1].start() + 1
    between = [
        m.group(1)
        for m in _ITEM.finditer(prefix, colon)
        if _style(m.group(1)) == _style(own.group(1))
    ]
    if [_ordinal(m) for m in between] != list(range(1, _ordinal(own.group(1)))):
        return ""
    ends = [m.end() for m in _SENTENCE_END.finditer(prefix, 0, colon)]
    return prefix[max(ends[-1] if ends else 0, colon - LEAD_IN_MAX) : colon].strip()


def title_of(heading: object) -> str:
    """A section heading only when it is a TITLE (no modal verb) that names no second group (no "and", "or", comma)."""
    text = " ".join(str(heading or "").split())
    if (
        not text
        or subject_scope._MODAL.search(text)
        or _JOINED.search(re.sub(r"^[\d.\-\s]+", "", text))
    ):
        return ""
    return text


def is_example(requirement: Mapping, passage: object) -> bool:
    """The rule sentence carries on a worked example: the sentence right before it opens with "For example" / "For instance" /
    "e.g." and holds every MEASURED figure of the rule sentence (a number with its unit, `claims.extract_measurements`; a list or
    clause number is no figure). A rule with no measured figure is no example."""
    from .claims import extract_measurements

    sentence = " ".join(
        str(
            requirement.get("source_text") or requirement.get("requirement_text") or ""
        ).split()
    )
    text = " ".join(str(passage or "").split())
    at = text.find(sentence[:80]) if sentence else -1
    if at <= 0:
        return False
    ends = [m.end() for m in _SENTENCE_END.finditer(text, 0, max(0, at - 1))]
    before = text[ends[-1] if ends else 0 : at].strip()
    own = {(m.raw_value, m.raw_unit) for m in extract_measurements(sentence)}
    there = {(m.raw_value, m.raw_unit) for m in extract_measurements(before)}
    return bool(_EXAMPLE_OPEN.search(before) and own and own <= there)


def _sources(
    parts: list[str], passage: object, heading: object, catalogue
) -> list[tuple[str, str, str]] | None:
    """[(source, name, spelling)] the rule is about, per sentence (own subject, its list's lead-in, its section's title), or None
    when a sentence is about nothing on the list, or any of it is in doubt (a negation, an example of something else, a subject
    joining another group or holding a verb). The title counts only with the thing as its head (its last words)."""
    title = subject_scope._fold(title_of(heading))
    shared = [("list", h) for h in _found(lead_in(parts[0], passage), catalogue)]
    shared += [("title", h) for h in _found(title, catalogue) if title.endswith(h[1])]
    out: list[tuple[str, str, str]] = []
    for s in parts:
        subject = subject_part(s)
        own = [("own", h) for h in _found(subject, catalogue)]
        hits = own + shared
        if not hits or any(h[2] for _src, h in hits):
            return None
        cond = bool(
            _CONDITION.search(subject)
        )  # "For <things>, the ...": its comma ends the condition, it joins nothing
        joined = (
            _AND_OR.search(subject.lower()) if cond else _JOINED.search(subject.lower())
        )
        if own and (joined or (_VERB_IN_SUBJECT.search(subject) and not cond)):
            return None  # "for X and for <thing>", or two sentences glued: about more than the thing
        out += [(src, h[0], h[1]) for src, h in hits]
    return out


def decide(
    requirement: Mapping,
    passage: object,
    paper_text: str | None,
    catalogue=None,
    heading: object = "",
) -> str | None:
    """The reason the rule's point moves to the tick section, or None (it stays as it is). The reason says where the thing was
    read: its own words, the list it sits in, or its section."""
    if paper_text is None:
        return None
    if is_example(requirement, passage):
        return EXAMPLE_WORDS
    catalogue = catalogue or things()
    parts = sentences(
        requirement.get("source_text") or requirement.get("requirement_text")
    )
    if not parts or any(requires(s, catalogue) for s in parts):
        return None
    found = _sources(parts, passage, heading, catalogue)
    if not found:
        return None
    paper = _compact(paper_text)
    entries = {e[0]: _entry(e) for e in catalogue}
    if any(w and w in paper for _src, n, _sp in found for w in entries[n][2]):
        return None  # the paper names the thing (or a word the data list says keeps it), in any case or punctuation
    source = next(
        src for src in ("own", "list", "title") if any(f[0] == src for f in found)
    )
    spelled = " / ".join(dict.fromkeys(sp for src, _n, sp in found if src == source))
    names = " / ".join(dict.fromkeys(sp for _src, _n, sp in found))
    return f"{SOURCE_WORDS[source]} {spelled}; the paper names no {names} on any page"


# ---- the database side --------------------------------------------------------------------------------------------------------


def paper_text(conn: sqlite3.Connection, document_id: str) -> str | None:
    """Every page of the paper as one text, or None when a page is not readable as text (`agent_review_absence.unreadable_page`)
    or nothing can be read: then nothing moves."""
    from .agent_review_absence import unreadable_page

    try:
        pages = conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
        ).fetchall()
        held = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        ledger_rows = (
            conn.execute(
                "SELECT l.page_no, l.native_status, l.ocr_status, p.needs_ocr FROM page_ledger l LEFT JOIN pages p"
                " ON p.document_id = l.document_id AND p.page_no = l.page_no WHERE l.document_id = ?",
                (document_id,),
            ).fetchall()
            if "page_ledger" in held
            else None
        )
    except sqlite3.Error:
        return None
    texts = {int(p[0]): str(p[1] or "") for p in pages}
    if not texts:
        return None
    ledger = (
        None
        if ledger_rows is None
        else {
            int(r[0]): {
                "native_status": r[1],
                "ocr_status": r[2],
                "needs_ocr": bool(r[3]),
            }
            for r in ledger_rows
        }
    )
    if unreadable_page(texts, max(texts), ledger) is not None:
        return None
    return "\n".join(texts[n] for n in sorted(texts))


def _rules(conn, ids: Iterable[str]) -> dict[str, dict]:
    """id -> the stored rule with its passage's text and section heading (read only)."""
    ids = sorted({i for i in ids if i})
    out: dict[str, dict] = {}
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        try:
            cur = conn.execute(
                "SELECT r.id, r.source_text, r.requirement_text, c.text AS passage, c.section AS heading FROM standard_requirements r"
                f" LEFT JOIN chunks c ON c.id = r.chunk_id WHERE r.id IN ({','.join('?' * len(part))})",
                part,
            )
            names = [d[0] for d in cur.description]
            out.update(
                {str(r[0]): dict(zip(names, r, strict=True)) for r in cur.fetchall()}
            )
        except sqlite3.Error:  # no rule table: nothing moves
            return {}
    return out


def _rule_id(point: Mapping) -> str | None:
    finding = point.get("_finding") or {}
    if finding.get("requirement_id"):
        return str(finding["requirement_id"])
    item = str((point.get("_line") or {}).get("item_id") or "")
    return item[2:] if item.startswith("R-") else None


def to_confirm(conn, points: list[dict], paper_id: str) -> int:
    """Move to the tick section (rank 9, `agent_review_not_applicable`) every point, of the rule check or the AI reviewer, whose
    rule `decide` sets aside, with its reason in the point's own words; an engineer's own point and a "not reviewed" stay. Returns
    how many moved. Nothing is removed: the point is still counted, listed and decided by a tick."""
    from .agent_review_not_applicable import TILE

    movable = [
        p for p in points if p.get("rank") in (1, 2, 3, 4, 5, 6, 7) and _rule_id(p)
    ]
    text = paper_text(conn, paper_id) if movable else None
    if text is None:
        return 0
    catalogue, rules = things(), _rules(conn, (_rule_id(p) for p in movable))
    moved = 0
    for p in movable:
        rule = rules.get(_rule_id(p) or "")
        reason = (
            decide(rule, rule.get("passage"), text, catalogue, rule.get("heading"))
            if rule
            else None
        )
        if reason:
            p.update(
                rank=9,
                tile=TILE,
                firm=None,
                ai_label=LABEL,  # ONE honest label, never the AI's own answer inside the tick section
                action=ACTION.format(reason=reason),
                ai_reasoning=WHY.format(reason=reason),
            )
            p["_subject_fit"] = reason
            moved += 1
    return moved
