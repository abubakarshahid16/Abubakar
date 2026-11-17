"""Does the thing a rule is about fit the paper? (order 14 LPV, V1; owner, 17 Nov 2026)

A rule was asked of a steel drum because it shared a word ("design life", "design pressure") with a field of the paper, although
the rule was written for an acrylic window. The rule now: a rule is asked only when the thing its OWN SCOPE is about fits the
paper, never by a shared word alone.

  * What a rule is ABOUT (its own scope) is its sentence's grammatical subject, the words before its "shall" / "must"
    (`subject_part`), plus, when it is an item of a list ("(3) The maximum ... shall not exceed ..."), the whole sentence that
    introduces that list: the one ending in ":" right before the list's first item, in the same passage of the rule book
    (`lead_in`). A list item inherits what its list is about. A thing named after the verb is what the rule ASKS FOR ("the
    following shall be installed: ... a sight glass"), so it never makes the rule unfit.
  * The things are DATA (`reference/rule_subject_things.json`): constructions, material classes and parts that only some
    equipment has. No standard, clause, document or layout is named in code (rule 13).
  * A rule whose own scope names a thing is NOT asked of a paper that names none of that thing's words on any page. Positive
    evidence only; in any doubt the rule is asked: a page of the paper is not readable as text, the paper names the thing
    anywhere, or the rule names it only after a negation ("other than", "except", "excluding", "non-").

Used by both reviewers: the rule check (`comparison`, reason `rule_subject_not_on_paper`, does not apply) and the AI reviewer's
rule choice (`agent_review_items.build_items`, the same reason, left out and listed). Reads only; no model; no network."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

from . import subject_scope

THINGS_PATH = Path(__file__).parent / "reference" / "rule_subject_things.json"
#: the reason code a rule left out by this check carries (scope ledger and the AI reviewer's left-out list)
REASON = "rule_subject_not_on_paper"
REASON_WORDS = "its own words are about a part or material this paper does not have"
#: a sentence that only carries on a worked example of the rule book ("For example, if ... it will close at 93 psig. The operating
#: pressure must be maintained below 93 psig ...") is not a requirement (order 14 LPV V1, widened)
EXAMPLE = "rule_book_example"
EXAMPLE_WORDS = "a worked example in the rule book, not a requirement"
#: the sentence that opens a worked example
_EXAMPLE_OPEN = re.compile(
    r"^(?:for example|for instance|e\.\s?g\.)[\s,]", re.IGNORECASE
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

#: a list item's own marker at the start of its sentence: "(3)", "(c)", "(iv)"
_ENUM = re.compile(r"^\s*\((\d{1,2}|[a-z]|[ivx]{1,4})\)\s", re.IGNORECASE)
#: a lead-in ends in ":" and the list's first item follows it: ": (1) ", ": (a) "
_LIST_START = re.compile(r":\s*\((1|a|i)\)\s", re.IGNORECASE)
#: the start of the sentence that holds a lead-in: after the last full stop or semicolon before it
_SENTENCE_END = re.compile(r"[.;]\s")
#: the longest lead-in read (letters), so a long passage never becomes one "sentence"
LEAD_IN_MAX = 600
#: words shortly before a thing that make it NOT the rule's subject ("other than acrylic", "non-acrylic", "with the exception of
#: main <things>"): a negation within the four words before it
_NEGATION = re.compile(
    r"\b(?:other than|except|exception|excluding|exclusive of|non)\b(?:\s+\S+){0,4}\s*$"
)
#: a subject that joins the thing with another group ("for <others> and for <things>") is about more than the thing
_JOINED = re.compile(r"\b(?:and|or)\b")


@lru_cache(maxsize=4)
def _things(path: str, mtime: float) -> tuple[tuple[str, tuple[str, ...]], ...]:  # noqa: ARG001 - the file time is the cache key
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
        if entry.get("name") and words:
            out.append((str(entry["name"]), words))
    return tuple(out)


def things(path: Path | str | None = None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """((name, folded words), ...) from the data file; a malformed entry is skipped (nothing is left out for it)."""
    p = Path(path or THINGS_PATH)
    return _things(str(p), p.stat().st_mtime)


def _style(marker: str) -> str:
    return "digit" if marker.isdigit() else "letter"


def lead_in(sentence: object, passage: object) -> str:
    """The sentence that introduces the list `sentence` is an item of, found in `passage` (the rule book's text around it), or
    "" when the sentence is not a list item, is not found in the passage, or no lead-in ending in ":" right before the list's
    first item (of the same marker style) comes before it."""
    sent = " ".join(str(sentence or "").split())
    text = " ".join(str(passage or "").split())
    own = _ENUM.match(sent)
    if not own or not text:
        return ""
    at = text.find(sent[:80])
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
    ends = [m.end() for m in _SENTENCE_END.finditer(prefix, 0, colon)]
    begin = max(ends[-1] if ends else 0, colon - LEAD_IN_MAX)
    return prefix[begin:colon].strip()


def _named(folded: str, word: str) -> bool:
    """`word` stands whole in `folded`, at least once NOT right after a negation."""
    for m in re.finditer(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", folded):
        if not _NEGATION.search(folded[: m.start()].rstrip()):
            return True
    return False


def named_things(scope: object, catalogue=None) -> list[str]:
    """The names of the things `scope` names (in the data's order)."""
    folded = subject_scope._fold(scope)
    return [
        name
        for name, words in (catalogue or things())
        if any(_named(folded, w) for w in words)
    ]


def subject_part(sentence: object) -> str:
    """The rule sentence's grammatical subject: its words before the first "shall" / "must" / ... (`subject_scope._MODAL`). A
    thing named AFTER the verb is what the rule asks for ("... shall be installed: a sight glass"), never what it is about, so it
    does not count; a sentence with no such verb (a table line, a bare list item) names no subject here (the rule is asked)."""
    text = " ".join(str(sentence or "").split())
    verb = subject_scope._MODAL.search(text)
    return text[: verb.start()] if verb else ""


def _joined(text: str, catalogue) -> bool:
    """The text names a thing AND joins another group with "and" / "or": the rule is about more than that thing (asked)."""
    return bool(named_things(text, catalogue)) and bool(
        _JOINED.search(subject_scope._fold(text))
    )


def own_scope(requirement: Mapping, passage: object = "", heading: object = "") -> str:
    """What the rule is about: its sentence's subject (`subject_part`), when it is a list item the whole lead-in of its list (the
    lead-in says what every item of the list is about), and the heading of the section its passage sits in when that heading is a
    title (`title_of`: it says what the section is about, "Additional tests for <one kind of equipment>")."""
    sentence = str(
        requirement.get("source_text") or requirement.get("requirement_text") or ""
    )
    return " ".join(
        str(x)
        for x in (title_of(heading), lead_in(sentence, passage), subject_part(sentence))
        if x
    )


def title_of(heading: object) -> str:
    """A section heading only when it is a TITLE: no "shall" / "must" / ... in it. A stored section that is the first words of a
    sentence ("4.6.1 Bearings shall be ...") is not what the section is about, so it is not read."""
    text = " ".join(str(heading or "").split())
    return "" if not text or subject_scope._MODAL.search(text) else text


def _sentence_before(sentence: str, passage: object) -> str:
    text = " ".join(str(passage or "").split())
    at = text.find(sentence[:80]) if sentence else -1
    if at <= 0:
        return ""
    ends = [m.end() for m in _SENTENCE_END.finditer(text, 0, max(0, at - 1))]
    return text[ends[-1] if ends else 0 : at].strip()


def is_example(requirement: Mapping, passage: object) -> bool:
    """The rule sentence carries on a worked example: the sentence right before it in its passage opens with "For example" /
    "For instance" / "e.g." and holds every figure of the rule sentence. Anything else is a requirement (asked)."""
    sentence = " ".join(
        str(
            requirement.get("source_text") or requirement.get("requirement_text") or ""
        ).split()
    )
    before = _sentence_before(sentence, passage)
    figures = _NUMBER.findall(sentence)
    return bool(
        before
        and figures
        and _EXAMPLE_OPEN.search(before)
        and all(f in _NUMBER.findall(before) for f in figures)
    )


def decide(
    requirement: Mapping,
    passage: object,
    paper_text: str | None,
    catalogue=None,
    heading: object = "",
) -> dict | None:
    """{"thing", "detail"} when the rule is NOT asked of this paper, else None (asked). `paper_text` None: the paper's text is
    not readable on every page, so nothing is left out."""
    if paper_text is None:
        return None
    catalogue = catalogue or things()
    sentence = str(
        requirement.get("source_text") or requirement.get("requirement_text") or ""
    )
    if _joined(
        subject_part(sentence), catalogue
    ):  # "for <others> and for <things>, ...": about more than the thing
        return None
    named = named_things(own_scope(requirement, passage, heading), catalogue)
    if not named:
        return None
    paper = subject_scope._fold(paper_text)
    words = dict(catalogue)
    missing = [n for n in named if not any(_named(paper, w) for w in words[n])]
    if len(missing) != len(
        named
    ):  # the paper names one of the things the rule is about: asked
        return None
    thing = "; ".join(missing)
    return {
        "thing": thing,
        "detail": f"its own words are about {thing}; this paper names none on any page",
    }


# ---- the database side: the passages of the rules and the paper's text ----------------------------------------------------


def passages(
    conn: sqlite3.Connection, requirements: Iterable[Mapping]
) -> dict[str, tuple[str, str]]:
    """chunk id -> (text, section heading) of the rule-book passages the requirements came from (read only)."""
    ids = sorted({str(r.get("chunk_id")) for r in requirements if r.get("chunk_id")})
    out: dict[str, tuple[str, str]] = {}
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        try:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE id IN ({','.join('?' * len(part))})", part
            )
            names = [c[0] for c in rows.description]
            found = [dict(zip(names, r, strict=True)) for r in rows.fetchall()]
        except sqlite3.Error:  # no passage table: the rule's own sentence alone is read
            return out
        out.update(
            {
                str(r["id"]): (str(r.get("text") or ""), str(r.get("section") or ""))
                for r in found
            }
        )
    return out


def paper_text(conn: sqlite3.Connection, document_id: str) -> str | None:
    """Every page of the paper as one text, or None when a page is not readable as text (the AI reviewer's own notion,
    `agent_review_absence.unreadable_page`) or nothing can be read: then nothing is left out."""
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


def split(
    conn: sqlite3.Connection, requirements: list[dict], document_id: str
) -> tuple[list[dict], list[dict]]:
    """(kept, left) for one paper: `left` holds {"requirement", "code", "detail", "thing"} per rule not asked: a worked example
    (`EXAMPLE`, whatever the paper) or a rule about a thing the paper does not have (`REASON`). Order kept."""
    if not requirements:
        return [], []
    text = paper_text(conn, document_id)
    catalogue = things()
    chunks = passages(conn, requirements)
    kept, left = [], []
    for r in requirements:
        passage, heading = chunks.get(str(r.get("chunk_id")), ("", ""))
        heading = heading or str(r.get("chunk_section") or "")
        if is_example(r, passage):
            left.append(
                {
                    "requirement": r,
                    "code": EXAMPLE,
                    "detail": EXAMPLE_WORDS,
                    "thing": None,
                }
            )
        elif (got := decide(r, passage, text, catalogue, heading)) is not None:
            left.append(
                {
                    "requirement": r,
                    "code": REASON,
                    "detail": got["detail"],
                    "thing": got["thing"],
                }
            )
        else:
            kept.append(r)
    return kept, left


def gate_for_run(
    requirements: list[dict], submittal_id: str
) -> tuple[list[dict], list[dict]]:
    """The rule check's gate: (kept, items); each item {"requirement", "code", "detail"} is a does-not-apply decision with its
    reason (`rule_subject_not_on_paper` or `rule_book_example`, both in `scope_ledger.REASONS`)."""
    from .db import connect

    kept, left = split(connect(), requirements, submittal_id)
    return kept, [{k: v for k, v in i.items() if k != "thing"} for i in left]
