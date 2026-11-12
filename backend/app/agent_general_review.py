"""GENERAL REVIEW mode of the AI reviewer: a procedure or a contract with no rule book to hold it to (#1690, #781).

OWNER, 11 Nov 2026 (STATE 16.4): review them in GENERAL REVIEW mode when we hold no rule book for the paper: list the rule books
the paper cites that we do not hold; ask the completeness checklist of that kind of paper; check the paper against itself; check
it against the project papers we hold; AI engineering comments marked "AI note, no rule book". Never ask equipment rules of a
paper they do not belong to. Silence is a "Query", never "not met". No "Pass" or "Fail". All lines internal only.

This module is the mode's DEFINITION and its ONE EXIT. The run itself is `agent_general_parts`, the prompts are
`agent_general_prompts`, the job and the files are `agent_general_job`.

  * `finalize_line` is the single exit of every line of this mode: the four classes only ("Not checked: rule book not held",
    "AI note, no rule book", "Query for the engineer", "Not reviewed"), each with its own word; every verdict word of the rule
    review (Pass, Fail, AI thinks, Proven by code, ...) is refused. A rule item is never built here.
  * `decide_mode`: the paper's kind first; unknown, a datasheet, or a kind the gate does not name is refused before anything is
    read; a held rule book never refuses the mode, it is recorded (`books_of`): a held book that carries no approved rule for
    this kind of paper is "not used in this general review", a held book that DOES carry approved rules of this kind is named
    in one true line (rule review for this kind is switched off).
  * `check_project_papers`: the project papers a request names are never chosen silently: each must be readable by the
    caller (a filter only narrows, CLAUDE.md rule 5), not the paper, not a rule book, and have page text.

General code (rule 13): no equipment, study or client word. No model call and no network here.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from . import agent_review_gate, claims, numparse
from .reader_api import _fold

# ---------------------------------------------------------------- classes and the single exit

CLASS_NOT_CHECKED = "Not checked: rule book not held"
CLASS_NOTE = "AI note, no rule book"
CLASS_QUERY = "Query for the engineer"
CLASS_NOT_REVIEWED = "Not reviewed"
WORD_OF = {
    CLASS_NOT_CHECKED: "Not checked",
    CLASS_NOTE: "AI note",
    CLASS_QUERY: "Query",
    CLASS_NOT_REVIEWED: "Not reviewed",
}
CLASSES = tuple(WORD_OF)
PART_WORDS = {
    1: "not held",
    2: "checklist",
    3: "paper against itself",
    4: "against project papers",
    5: "engineering comment",
}
PARTS = tuple(PART_WORDS)
TEXT_FROM_MODEL = "the model's words"
TEXT_FROM_QUOTE = "quote"
MODE_WORD = "general review"

SUB_SELF = "paper disagrees with itself"
SUB_REF = "broken reference"
SUB_OPEN = "open action"
SUB_COUNT = "count mismatch"
SUB_ENGINEERING = "engineering comment"
SUB_CHECKLIST = "checklist item"
SUB_CONCERN = "checklist concern"
SUB_UNREAD = "could not be checked"
SUB_SILENT = "silent on a project requirement"
SUB_DISAGREES = "disagrees with {document}"

#: Words that may never be the verdict word, label or class of a line of this mode (the wording of the rule review).
FORBIDDEN = (
    "pass",
    "fail",
    "ai thinks: met",
    "ai thinks: not met",
    "proven by code",
    "ai opinion, engineer to confirm",
    "ai opinion, rule not yet approved",
    "ai thinks",
    "met",
    "not met",
    "compliant",
    "non-compliant",
)
VERDICT_KEYS = (
    "verdict",
    "verdict_label",
    "word",
    "verdict_class",
    "ai_verdict",
    "decided_by",
)
#: A line text that STARTS with a verdict phrase is refused too (a sentence that merely contains "pass" is ordinary prose).
_VERDICT_START = re.compile(
    r"^\s*(pass|fail|ai thinks|proven by code|not met)\b\s*(:|$)", re.I
)
NO_CHECKLIST = "no completeness checklist for this kind of paper"
NO_PROJECT_PAPER = "no project paper was given to check against"
HELD_FIT_LINE = "rule books we hold that fit this paper were not used: rule review for this kind is switched off"
UNREAD_QUERY = "could not be checked: the page holds pictures that were not read"


class GeneralModeViolation(ValueError):
    """A line (or a call) that this mode must never produce."""


class Refused(RuntimeError):
    """The mode refuses the paper or a document: nothing was asked, nothing was sent."""


def finalize_line(line: Mapping) -> dict:
    """THE exit of this mode. A line is one of the four classes with its own word; the verdict words of the rule review are
    refused, so no writer can ever carry one. Every line is internal, and no line is ever a rule item."""
    out = dict(line)
    for key in VERDICT_KEYS:  # what the caller wrote, before this exit sets the word
        val = out.get(key)
        if val is not None and str(val).strip().casefold() in FORBIDDEN:
            raise GeneralModeViolation(
                f"verdict word not allowed in general review: {key}={val!r}"
            )
    cls = out.get("verdict_class")
    if cls not in CLASSES:
        raise GeneralModeViolation(f"class not allowed in general review: {cls!r}")
    if out.get("word") not in (None, WORD_OF[cls]):
        raise GeneralModeViolation(
            f"word {out.get('word')!r} does not belong to class {cls!r}"
        )
    out["word"] = WORD_OF[cls]
    if out.get("part") not in PARTS:
        raise GeneralModeViolation(
            f"part not allowed in general review: {out.get('part')!r}"
        )
    if out.get("source") == "rule" or str(out.get("item_id") or "").startswith("R-"):
        raise GeneralModeViolation("a rule item is never asked in general review")
    if cls == CLASS_NOTE and out.get("subkind") is None:
        raise GeneralModeViolation("an AI note needs its sub-kind")
    if _VERDICT_START.match(str(out.get("text") or "")):
        raise GeneralModeViolation("a line text may not open with a verdict word")
    out["internal_only"] = True
    return out


# ---------------------------------------------------------------- small helpers


def tokens_of(text: str) -> int:
    return len(text) // 4 + 1


def words_cut(text: Any, limit: int) -> str:
    """At most `limit` WORDS (the prompt's own word limit), never a character cut: the text a line stores is whole."""
    w = " ".join(str(text or "").split()).split()
    return " ".join(w[:limit])


def window_pages(
    pages: Mapping[int, str], limit_tokens: int, overlap: int = 1
) -> list[list[int]]:
    """The whole paper in one window when it fits; else windows of consecutive pages, each starting `overlap` page(s) back."""
    numbers = sorted(n for n, t in pages.items() if (t or "").strip())
    cost = {n: tokens_of(pages[n]) + 20 for n in numbers}
    if sum(cost.values()) <= limit_tokens:
        return [numbers] if numbers else []
    out: list[list[int]] = []
    i = 0
    while i < len(numbers):
        window, used, j = [], 0, i
        while j < len(numbers) and (
            not window or used + cost[numbers[j]] <= limit_tokens
        ):
            window.append(numbers[j])
            used += cost[numbers[j]]
            j += 1
        out.append(window)
        if j >= len(numbers):
            break
        i = max(i + 1, j - overlap)
    return out


def figures_label(kind: str, quote_a: str, quote_b: str | None) -> str | None:
    """For a disagreement or a count mismatch: whether code can compare the two figures. Exactly one plain number in each quote
    is compared (project number code, `numparse`), with the same unit word or none on both sides; anything else is "not compared
    by code". Never the model's arithmetic."""
    if kind not in ("disagreement", "count_mismatch") or not quote_b:
        return None

    def one(text: str) -> tuple[float, str | None] | None:
        nums = [
            n
            for n in numparse.find_numbers(text)
            if n.value is not None and not n.joined
        ]
        if (
            len(nums) != 1
            or nums[0].ambiguous
            or numparse.is_three_decimal_dot(nums[0].raw)
        ):
            return None
        m = re.match(r"\s*([^\W\d_]+(?:/[^\W\d_]+)?)", text[nums[0].end :])
        unit = m.group(1) if m and claims.is_unit(m.group(1)) else None
        return nums[0].value, (unit.casefold() if unit else None)

    a, b = one(quote_a), one(quote_b)
    if (
        a is None or b is None or a[1] != b[1]
    ):  # a unit on one side only, or two units: never compared here
        return "not compared by code"
    if a[0] != b[0]:
        return "figures differ: by code"
    return "figures equal: by code (the disagreement is not about the figure)"


# ---------------------------------------------------------------- pictures that were not read as text

LOW_TEXT_CHARS = 100
_MISSING = re.compile(
    r"\b(missing|absent|omitted|undefined|lacks?|lacking|without|"
    r"not (?:shown|given|provided|defined|included|stated|present|listed|read|available)|"
    r"no (?:formula|equation|figure|diagram|table|value|expression|illustration)s?|never defined)\b",
    re.I,
)


def unread_pages(conn: sqlite3.Connection, document_id: str) -> list[int]:
    """Pages of the paper that hold pictures or formulas the text extraction did not read: a page flagged for recognition or
    equation-heavy by the extractor, or a page with very little text. A plain fact about the file, not a judgement."""
    rows = conn.execute(
        "SELECT page_no, char_count, needs_ocr, equation_heavy FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,),
    ).fetchall()
    return [
        int(r[0])
        for r in rows
        if int(r[2] or 0) or int(r[3] or 0) or int(r[1] or 0) < LOW_TEXT_CHARS
    ]


def unread_words(pages: Iterable[int]) -> str:
    """ "page 3 holds" / "pages 3, 5 hold", for a line that could not be checked."""
    numbers = sorted(set(pages))
    which = ", ".join(str(n) for n in numbers)
    return (
        f"page {which} holds pictures that were not read"
        if len(numbers) == 1
        else f"pages {which} hold pictures that were not read"
    )


def claims_missing(flag: Any, *words: Any) -> bool:
    """Does a finding claim that something is MISSING? The model's own flag, or the plain words of its sentence."""
    return flag is True or any(_MISSING.search(str(w or "")) for w in words)


def picture_fact(pages: Iterable[int]) -> str:
    """The plain fact the prompts get, or "" when every page was read as text."""
    numbers = sorted(set(pages))
    if not numbers:
        return ""
    return f"Pages {', '.join(str(n) for n in numbers)} hold pictures or formulas that were not read as text."


# ---------------------------------------------------------------- documents: only what the carrier allows


class Documents:
    """The page texts of the paper and of the project papers. A document that is not in `allowed` (the approved-documents
    carrier of the run) is refused here, so no prompt can ever carry it."""

    def __init__(
        self,
        allowed: Iterable[str],
        paper: str,
        texts: Mapping[str, Mapping[int, str]],
        names: Mapping[str, str] | None = None,
    ) -> None:
        self.allowed, self.paper = frozenset(str(d) for d in allowed), paper
        if paper not in self.allowed:
            raise Refused("the carrier must name the paper")
        self._texts = {
            d: {int(n): str(t or "") for n, t in p.items()} for d, p in texts.items()
        }
        self.names = dict(names or {})

    def pages(self, doc: str) -> dict[int, str]:
        if doc not in self.allowed:
            raise Refused(f"document {doc} is not in the carrier: it is never sent")
        return self._texts.get(doc, {})


def load_documents(
    conn: sqlite3.Connection, paper: str, project: list[str], allowed: Iterable[str]
) -> Documents:
    allowed = list(allowed)
    for d in project:
        if d not in allowed:
            raise Refused(f"project paper {d} is not in the carrier: it is never sent")
    texts: dict[str, dict[int, str]] = {}
    names: dict[str, str] = {}
    for d in [paper, *project]:
        rows = conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (d,)
        ).fetchall()
        texts[d] = {int(r[0]): r[1] or "" for r in rows}
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (d,)
        ).fetchone()
        names[d] = (row[0] if row else "") or ""
    return Documents(allowed, paper, texts, names)


MAX_PROJECT_PAPERS = 10


def _is_rule_book(conn: sqlite3.Connection, document_id: str) -> bool:
    """A document that holds stored rules is a rule book. No rule table yet (nothing was ever extracted): none is."""
    try:
        return (
            conn.execute(
                "SELECT 1 FROM standard_requirements WHERE standard_document_id = ? LIMIT 1",
                (document_id,),
            ).fetchone()
            is not None
        )
    except sqlite3.OperationalError:
        return False


def check_project_papers(
    conn: sqlite3.Connection,
    paper: str,
    ids: Iterable[str],
    allowed: Iterable[str],
) -> tuple[list[dict], list[str]]:
    """(accepted [{document_id, name}], problems). The papers a request NAMES, never chosen silently: each must be readable by
    the caller (`allowed` is the caller's scope: a filter may only narrow, rule 5), not the paper itself, not a rule book, not
    a duplicate, and have page text. One problem makes the whole list refused: the caller decides what to name."""
    from . import claude_approved

    allowed = frozenset(allowed)
    out: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        d = str(raw)
        if d in seen:
            continue
        seen.add(d)
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (d,)
        ).fetchone()
        why = None
        if d == paper:
            why = "the paper itself is not a project paper"
        elif d not in allowed or row is None:
            why = "no such document for this caller"
        elif _is_rule_book(conn, d):
            why = "a rule book is not a project paper"
        elif claude_approved.blocked_by_name(row[0]):
            why = "this document is blocked by its file name or checksum, so it is not sent"
        elif not conn.execute(
            "SELECT 1 FROM pages WHERE document_id = ? AND TRIM(text) <> '' LIMIT 1",
            (d,),
        ).fetchone():
            why = "the document has no stored page text"
        if why:
            problems.append(f"{d}: {why}")
            continue
        out.append({"document_id": d, "name": row[0] or d})
    if len(out) > MAX_PROJECT_PAPERS:
        problems.append(f"more than {MAX_PROJECT_PAPERS} project papers")
    return out, problems


# ---------------------------------------------------------------- the rule books of the paper (decided by code, recorded)


def _kind_rule_books(kind: str) -> list[str]:
    from . import kind_standards

    return list((kind_standards.table().get("method_standards") or {}).get(kind, []))


def books_of(conn: sqlite3.Connection, paper: str, kind: str) -> dict:
    """The rule books the paper cites (or its kind needs), split into HELD and NOT HELD. For each held book whether it carries an
    approved rule (a label `ai_approved`) of THIS paper kind: `fit`; the others are `not_fit`: not used in this general review.
    Names only. Read only."""
    from . import agent_review_rules as rules
    from . import applicability, rule_labels, standard_ids

    text = "\n".join(
        r[0] or ""
        for r in conn.execute(
            "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no", (paper,)
        )
    )
    library = [e for e in rules.library_of(conn) if e["id"] != paper]
    held: dict[str, str] = {}
    not_held: list[dict] = []

    def take(name: str, why: str) -> None:
        entry = applicability.find_standard(library, name)
        if entry is None:
            if not any(
                standard_ids.same_standard(name, x["rule_book"]) for x in not_held
            ):
                not_held.append({"rule_book": name, "why": why})
        else:
            held.setdefault(entry["id"], name)

    for name in standard_ids.cited_standards(text):
        take(name, "cited by the paper")
    for name in _kind_rule_books(kind):
        take(name, "needed by the paper kind")
    for b in rules.missing_rule_books(
        conn, paper
    ):  # the app's own list of cited books the library lacks
        if not any(
            standard_ids.same_standard(b["rule_book"], x["rule_book"]) for x in not_held
        ):
            not_held.append(
                {
                    "rule_book": b["rule_book"],
                    "why": b.get("why") or "cited by the paper",
                }
            )
    fit, not_fit = {}, {}
    for doc_id, name in held.items():
        has = (
            rule_labels._has(conn, "rule_label")
            and conn.execute(
                "SELECT 1 FROM rule_label l JOIN standard_requirements r ON l.source = 'requirement' AND l.rule_ref = r.id"
                " WHERE r.standard_document_id = ? AND l.paper_kind = ? AND l.state = 'ai_approved' LIMIT 1",
                (doc_id, kind),
            ).fetchone()
        )
        (fit if has else not_fit)[doc_id] = name
    return {"not_held": not_held, "held_fit": fit, "held_not_fit": not_fit}


def decide_mode(
    conn: sqlite3.Connection, paper: str, kind: str | None, known: bool = True
) -> dict:
    """{'ok': True, ...} or {'ok': False, 'message': ...}. KIND FIRST: an unknown kind, a datasheet (the rule review's), or a kind
    the gate does not name for general review is refused before the paper is read. A paper with no readable text is refused (code
    could not verify a quote on it). Held rule books never refuse: they are decided and recorded by `books_of`."""
    norm = str(kind or "").strip().lower().replace(" ", "_")
    if not known or not norm:
        return {
            "ok": False,
            "message": "REFUSED | paper kind unknown: the engineer names the kind first; general review asks nothing of a paper of unknown kind",
        }
    if norm == "datasheet":
        return {
            "ok": False,
            "message": "REFUSED | a datasheet is reviewed by the rule review, never by general review",
        }
    if not agent_review_gate.general_kind_enabled(norm):
        return {
            "ok": False,
            "message": f"REFUSED | general review is not enabled for a {norm.replace('_', ' ')}",
        }
    n_text = sum(
        len((r[0] or "").strip())
        for r in conn.execute("SELECT text FROM pages WHERE document_id = ?", (paper,))
    )
    if n_text < 200:
        return {
            "ok": False,
            "message": "REFUSED | the paper has no readable page text: code could not verify a quote on it",
        }
    return {"ok": True, "kind": norm, **books_of(conn, paper, norm)}


# ---------------------------------------------------------------- part 2: the checklist of the paper kind

GENERIC_SUBJECT_WORDS = frozenset(
    {"study", "plan", "review", "general", "procedure", "contract"}
)


def paper_head(conn: sqlite3.Connection, paper: str) -> str:
    """The words that say what the paper is about: its stored title, its file name and the start of its first page."""
    bits: list[str] = []
    for sql in (
        "SELECT title FROM document_classification WHERE document_id = ?",
        "SELECT filename FROM documents WHERE id = ?",
    ):
        try:
            row = conn.execute(sql, (paper,)).fetchone()
        except sqlite3.Error:  # a small copy may lack the table
            row = None
        bits.append(str(row[0] or "") if row else "")
    row = conn.execute(
        "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no LIMIT 1",
        (paper,),
    ).fetchone()
    bits.append((row[0] or "")[:600] if row else "")
    return _fold(" ".join(bits))


def subject_fits(skill_kind: str, paper_kind: str, head: str) -> bool:
    """A checklist is asked only of a paper about ITS subject: the skill kind is "<subject>_<paper kind>" and every subject word (a
    generic one like "study" aside) must stand in the paper's own title words. A skill kind with no subject word is general."""
    k = str(skill_kind)
    tail = "_" + (paper_kind or "").replace(" ", "_")
    subject = k[: -len(tail)] if k.endswith(tail) else ""
    words = [w for w in subject.split("_") if w and w not in GENERIC_SUBJECT_WORDS]
    return all(re.search(rf"\b{re.escape(w)}", head) for w in words)


def checklist_items(
    conn: sqlite3.Connection, kind: str, paper: str, skills: list[dict] | None = None
) -> tuple[list[dict], dict]:
    """(items, info). Skill items of this paper kind that carry no equipment type, or the paper's own (the F2 rule). No rule item.
    Where the kind has no checklist, or none about this paper's subject: ([], {'none': NO_CHECKLIST})."""
    from . import agent_review_items as items_mod
    from . import agent_review_rules as rules

    head = paper_head(conn, paper)
    out: list[dict] = []
    unfit = 0
    for skill in items_mod.load_skills(kind, skills):
        if not subject_fits(skill["kind"], kind, head):
            unfit += 1
            continue
        for item in sorted(skill["items"], key=lambda i: i["order"]):
            q = " ".join(
                f"{label}: {item[k].strip()}"
                for label, k in (
                    ("Topic", "topic"),
                    ("Expected", "expected"),
                    ("Acceptable", "acceptable_range"),
                    ("Ask the engineer when", "escalate_when"),
                )
                if item.get(k)
            )
            out.append(
                {
                    "item_id": f"S-{item['id']}",
                    "source": "skill",
                    "topic": item.get("topic"),
                    "question": q,
                    "clause_refs": [
                        {"standard": r["standard"], "clause": r["clause"]}
                        for r in item.get("clause_refs") or []
                    ],
                    "skill_kind": skill["kind"],
                }
            )
    if not out:
        return [], {
            "none": NO_CHECKLIST,
            "kind": kind,
            "checklists_for_another_subject": unfit,
        }
    kept, dropped = rules.filter_skill_items(
        conn, out, rules.paper_equipment_types(conn, paper), None, None
    )
    return kept, {
        "skill_items_found": len(out),
        "kept": len(kept),
        "dropped_equipment_type": len(dropped),
        "kind": kind,
    }
