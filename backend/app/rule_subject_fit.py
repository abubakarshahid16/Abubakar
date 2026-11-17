"""Does a rule fit this paper's equipment? (order 14 LPV V1; owner, 17 Nov 2026; the lead's decision after three review rounds)

A rule was asked of a steel drum because it shared a word ("design life", "design pressure") with a field of the paper, although
the rule was written for a vessel with an acrylic window. NOTHING IS DROPPED, and no grammar is parsed: the decision rests on the
AGREED DATA. A rule's point (the rule check's or the AI reviewer's) moves to the owner's section "does not apply? tick to confirm"
only when BOTH hold:
  1. the rule names a thing of the data list (`reference/rule_subject_things.json`) in its own words, the lead-in of its list or
     its section's title, and the paper names none of that thing's spellings on any page (case, punctuation and spaces ignored);
  2. the rule's AGREED equipment tag (`rule_equipment_label`, decided by `agent_review_equipment.equipment_decision`, the ONE
     function the AI reviewer's own filter uses) names ANOTHER equipment type than the paper's. A rule tagged for this paper's
     equipment stays asked even when the paper lacks the part (that is the finding); an untagged, not agreed or general rule
     never moves; a paper whose equipment type is not known, or read with doubt ("type unsure", the same reading a run
     records), moves nothing: every point stays asked (`TYPE_NOT_CONFIRMED`).
A sentence that only carries on a worked example of the book ("For example, ... 93 psig. The operating pressure must be kept below
93 psig ...", every measured figure of the rule in the example: `claims.extract_measurements`) moves with its own reason. The
engineer confirms each moved point; it is counted and listed, never removed. No standard, clause or layout is named in code (rule
13). Reads only; no model."""

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

_ENUM = re.compile(r"^\s*\((\d{1,2}|[a-z]|[ivx]{1,4})\)\s", re.IGNORECASE)
_ITEM = re.compile(r"\((\d{1,2}|[a-z])\)\s")
_LIST_START = re.compile(r":\s*\((1|a)\)\s", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.;]\s")
LEAD_IN_MAX = 600
_EXAMPLE_OPEN = re.compile(
    r"^(?:for example|for instance|e\.\s?g\.)[\s,]", re.IGNORECASE
)


@lru_cache(maxsize=4)
def _things(path: str, mtime: float) -> tuple[tuple, ...]:  # noqa: ARG001 - the file time is the cache key
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for entry in data.get("things") or []:
        words = tuple(
            sorted({_compact(w) for w in entry.get("words") or [] if _compact(w)})
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
    """((name, compacted spellings, compacted paper spellings), ...) from the data file; a malformed entry is skipped. The paper
    spellings (the spellings plus `paper_words`) are what keeps a rule when the paper names any of them."""
    p = Path(path or THINGS_PATH)
    return _things(str(p), p.stat().st_mtime)


def _compact(text: object) -> str:
    """Letters and digits only, lower case: "G.R.P.", "Fire-Water" and "FIREWATER" read alike."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _entry(entry: tuple) -> tuple[str, tuple, tuple]:
    name, words, *rest = entry
    words = tuple(_compact(w) for w in words)
    return name, words, tuple(_compact(w) for w in rest[0]) if rest else words


def named(text: object, catalogue) -> list[tuple[str, str]]:
    """[(name, spelling)] of every thing `text` names: a spelling standing whole between word boundaries (case, punctuation and
    spaces ignored inside it)."""
    folded = subject_scope._fold(text)
    flat = " " + " ".join(folded.split()) + " "
    out = []
    for entry in catalogue:
        name, words, _paper = _entry(entry)
        for w in words:
            if m := re.search(
                r"(?<![a-z0-9])" + r"\s?".join(map(re.escape, w)) + r"(?![a-z0-9])",
                flat,
            ):
                out.append((name, m.group(0)))  # the rule's own spelling, as it reads
    return out


def _style(marker: str) -> str:
    return "digit" if marker.isdigit() else "letter"


def _ordinal(marker: str) -> int:
    return int(marker) if marker.isdigit() else ord(marker.lower()) - ord("a") + 1


def lead_in(sentence: object, passage: object) -> str:
    """The lead-in of the list `sentence` is item k of: the sentence ending in ":" right before item (1) / (a) of the same style,
    found in `passage`, ONLY when the items between it and this one are that list's items 1 .. k-1 in order. "" otherwise."""
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


def _words(text: object) -> str:
    return str(text or "").replace("_", " ").strip()


def decide(
    requirement: Mapping,
    passage: object,
    paper_text: str | None,
    catalogue=None,
    heading: object = "",
    tag: Mapping | None = None,
) -> str | None:
    """The reason the rule's point moves to the tick section, or None (it stays asked). `tag`: the rule's agreed equipment tag as
    `equipment_decision` judged it against the paper ({"other": True, "rule": <type or family>, "paper": <types>}), None when
    the rule's tag fits the paper, is not agreed, is general, or is missing (then nothing moves for a thing)."""
    if paper_text is None:
        return None
    if is_example(requirement, passage):
        return EXAMPLE_WORDS
    if not (tag and tag.get("other")):
        return None
    catalogue = catalogue or things()
    sentence = (
        requirement.get("source_text") or requirement.get("requirement_text") or ""
    )
    found = named(
        " ".join(str(x or "") for x in (heading, lead_in(sentence, passage), sentence)),
        catalogue,
    )
    if not found:
        return None
    paper = _compact(paper_text)
    entries = {e[0]: _entry(e) for e in catalogue}
    if any(w and w in paper for n, _sp in found for w in entries[n][2]):
        return None  # the paper names the thing (or a word the data list says keeps it), in any case or punctuation
    spelled = " / ".join(dict.fromkeys(sp for _n, sp in found))
    return (
        f"its agreed equipment tag is {_words(tag.get('rule'))}, this paper is {_words(tag.get('paper'))}, and the paper names no "
        f"{spelled} on any page"
    )


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


def tag_against(conn, rule_id: str, ctx) -> dict | None:
    """The rule's agreed equipment tag judged against the paper by the AI reviewer's ONE function (`equipment_decision`, mode
    "type"): {"other": True, "rule", "paper"} only when it answers "another equipment type", which only an AGREED tag naming a type
    or family not the paper's gets; a tag not agreed, general or missing, or a paper whose equipment is not known: None."""
    from . import agent_review_equipment as eqmod
    from . import rule_equipment

    if ctx is None:
        return None
    label = rule_equipment.label_for(conn, "requirement", str(rule_id)) or {}
    try:
        row = conn.execute(
            "SELECT field FROM rule_label WHERE source = 'requirement' AND rule_ref = ?",
            (str(rule_id),),
        ).fetchone()
    except sqlite3.Error:
        row = None
    keep, why, _fam = eqmod.equipment_decision(
        label, ctx.eq, ctx.tax, "type", row[0] if row else None
    )
    if keep or why != eqmod.ANOTHER_EQUIPMENT:
        return None
    return {
        "other": True,
        "rule": label.get("equip_type") or label.get("equip_family"),
        "paper": ", ".join(sorted(ctx.eq.core_types or ctx.eq.types)),
    }


#: why nothing moved on a paper: a move rests on the paper's equipment type, which must be read with no doubt (LPV V4's record)
TYPE_NOT_CONFIRMED = "paper's equipment type not confirmed"


def type_confirmed(paper_id: str) -> bool:
    """The paper's equipment type is read with no doubt by the app's one reader (`subject_scope.read_equipment` over its
    classification and its stated facts: the same reading a run records as its type or as "type unsure: <reason>"). Unsure (the
    paper's own codes say another type), or not recorded: False, and no point moves."""
    from . import classification, datasheets

    try:
        facts = datasheets.list_facts(
            paper_id, allowed_document_ids=frozenset({paper_id})
        )
        record = classification.of_document(paper_id) or {}
        found, _source, _doubt = subject_scope.read_equipment(
            record, facts, subject_scope.vocabulary()
        )
    except Exception:  # noqa: BLE001 - a reading that cannot be made is not a confirmed type: nothing moves
        return False
    return bool(
        found
    )  # an unsure reading gives no type (`read_equipment`: "the equipment is read as UNKNOWN")


def _rule_id(point: Mapping) -> str | None:
    finding = point.get("_finding") or {}
    if finding.get("requirement_id"):
        return str(finding["requirement_id"])
    item = str((point.get("_line") or {}).get("item_id") or "")
    return item[2:] if item.startswith("R-") else None


def to_confirm(conn, points: list[dict], paper_id: str) -> int:
    """Move to the tick section (rank 9, `agent_review_not_applicable`) every point, of the rule check or the AI reviewer, whose
    rule `decide` sets aside, with ONE label and its reason in the point's own words; an engineer's own point and a "not
    reviewed" stay. Returns how many moved. Nothing is removed: the point is still counted, listed and decided by a tick."""
    from . import agent_review_equipment as eqmod
    from .agent_review_not_applicable import TILE

    movable = [
        p for p in points if p.get("rank") in (1, 2, 3, 4, 5, 6, 7) and _rule_id(p)
    ]
    text = paper_text(conn, paper_id) if movable else None
    if text is None:
        return 0
    if not type_confirmed(
        paper_id
    ):  # the paper's equipment type is unsure or not recorded: nothing moves, all stay asked
        for p in movable:
            p["_subject_fit_held"] = TYPE_NOT_CONFIRMED
        return 0
    ctx = eqmod.load_equipment(conn, paper_id, "type")
    catalogue, rules = things(), _rules(conn, (_rule_id(p) for p in movable))
    moved = 0
    for p in movable:
        rid = _rule_id(p) or ""
        rule = rules.get(rid)
        reason = (
            decide(
                rule,
                rule.get("passage"),
                text,
                catalogue,
                rule.get("heading"),
                tag_against(conn, rid, ctx),
            )
            if rule
            else None
        )
        if reason:
            p.update(
                rank=9,
                tile=TILE,
                firm=None,
                ai_label=LABEL,  # ONE honest label, never the AI's own answer inside the tick section
                ai_answer=f"{LABEL}: {reason}.",
                action=ACTION.format(reason=reason),
                ai_reasoning=WHY.format(reason=reason),
            )
            p["_subject_fit"] = reason
            moved += 1
    return moved
