"""Review a written procedure against a playbook (#679, W5b-04).

A PLAYBOOK is a data file (`reference/playbooks/*.json`, format
`review-playbook/1`): the elements a document type is expected to contain, the
standard clause each element comes from, and the cue words that count as the
document stating it. The review reads a document the system already holds (a
Word file through the #668 reader, or a PDF) and reports, per element:

  present              every cue group is found together in one passage, with
                       the passage's locator ("4.2 > para 3") and a quote
  unclear              only part of what the element expects is found
  missing              nothing found, in a document that was read in full
                       (said as "not found in the pages read": about the pages,
                       never about the author)
  could_not_be_checked the document was not read in full, so absence proves
                       nothing, or it has no readable text (shared absence rule)
  standard_not_held    the element's source standard is not in the library.
                       NEVER met: the clause could not be checked against its
                       text. Where the topic appears is listed as a pointer for
                       the engineer, not as a verdict.

RULES THE LOADER ENFORCES (W5b-10, #547): a check without a clause citation is
rejected by name; a playbook is a DRAFT until a named engineer and a date are
recorded, and the report says so. Nothing here is invented by a model: the
cues are data a person edits, and a model's proposal (`proposer`) is kept only
when its quote is found verbatim in the passage it cites.

No network, no model by default. Pure over the chunk rows; the caller says whose
documents may be read.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .db import connect

FORMAT = "review-playbook/1"
PLAYBOOK_DIR = Path(__file__).parent / "reference" / "playbooks"

PRESENT = "present"
UNCLEAR = "unclear"
MISSING = "missing"
COULD_NOT_BE_CHECKED = "could_not_be_checked"
STANDARD_NOT_HELD = "standard_not_held"
STATES = (PRESENT, UNCLEAR, MISSING, COULD_NOT_BE_CHECKED, STANDARD_NOT_HELD)

#: Chunk kinds that are the document's body. A footer, a tracked change, a
#: comment and a table of contents are stored beside the body, never in it.
BODY_KINDS = ("prose", "table", "heading")
QUOTE_MAX = 240


class PlaybookError(ValueError):
    """A playbook file that cannot be used. The message names the element."""


@dataclass(frozen=True)
class Element:
    id: str
    title: str
    expects: str
    standard: str
    clause: str
    groups: tuple[tuple[str, tuple[str, ...]], ...]      # (label, phrases)


@dataclass(frozen=True)
class Playbook:
    id: str
    title: str
    version: str
    document_kind: str
    sign_off: dict
    clauses_verified: bool
    note: str
    elements: tuple[Element, ...]

    @property
    def signed_off(self) -> bool:
        return self.sign_off.get("status") == "signed_off"


# --------------------------------------------------------------------- loading

def parse(data: object, where: str = "playbook") -> Playbook:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise PlaybookError(f"{where}: must be a JSON object with format {FORMAT!r}")
    for field in ("id", "title", "version"):
        if not str(data.get(field) or "").strip():
            raise PlaybookError(f"{where}: {field} is required")
    sign = data.get("sign_off") or {"status": "draft"}
    status = sign.get("status")
    if status not in ("draft", "signed_off"):
        raise PlaybookError(f"{where}: sign_off.status must be draft or signed_off")
    if status == "signed_off" and not (str(sign.get("by") or "").strip() and str(sign.get("date") or "").strip()):
        raise PlaybookError(f"{where}: a signed-off playbook names who signed it (sign_off.by) and when (sign_off.date)")
    raw = data.get("elements")
    if not isinstance(raw, list) or not raw:
        raise PlaybookError(f"{where}: no elements")
    seen: set[str] = set()
    elements = []
    for n, e in enumerate(raw, start=1):
        eid = str((e or {}).get("id") or "").strip()
        if not eid or eid in seen:
            raise PlaybookError(f"{where}: element {n} needs a unique id")
        seen.add(eid)
        source = e.get("source") or {}
        if not str(source.get("standard") or "").strip() or not str(source.get("clause") or "").strip():
            # W5b-10: a check no clause stands behind is an invented check.
            raise PlaybookError(f"{where}: element {eid} has no clause citation (source.standard and source.clause are required)")
        groups = []
        for g in e.get("evidence") or []:
            phrases = tuple(str(p).strip() for p in (g or {}).get("any") or [] if str(p).strip())
            if not phrases or not str((g or {}).get("label") or "").strip():
                raise PlaybookError(f"{where}: element {eid} has an evidence group with no label or no phrases")
            groups.append((str(g["label"]).strip(), phrases))
        if not groups:
            raise PlaybookError(f"{where}: element {eid} has no evidence cues, so nothing can count as present")
        if not str(e.get("title") or "").strip():
            raise PlaybookError(f"{where}: element {eid} has no title")
        elements.append(Element(eid, str(e["title"]).strip(), str(e.get("expects") or "").strip(),
                                str(source["standard"]).strip(), str(source["clause"]).strip(), tuple(groups)))
    return Playbook(str(data["id"]).strip(), str(data["title"]).strip(), str(data["version"]).strip(),
                    str(data.get("document_kind") or "").strip(), dict(sign), bool(data.get("clauses_verified", False)),
                    str(data.get("note") or "").strip(), tuple(elements))


def load_file(path: str | Path) -> Playbook:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlaybookError(f"{p.name}: could not be read ({type(exc).__name__})") from exc
    return parse(data, p.name)


def available(directory: Path | None = None) -> tuple[dict[str, Playbook], list[dict]]:
    """(playbooks by id, files that could not be used with the reason). A bad
    file is reported, never silently dropped."""
    found: dict[str, Playbook] = {}
    broken: list[dict] = []
    for path in sorted((directory or PLAYBOOK_DIR).glob("*.json")):
        try:
            pb = load_file(path)
        except PlaybookError as exc:
            broken.append({"file": path.name, "reason": str(exc)})
            continue
        found[pb.id] = pb
    return found, broken


def notice(pb: Playbook) -> str | None:
    """The sentence a report carries while a playbook is a draft."""
    if pb.signed_off:
        return None
    return ("This playbook has not been signed off by a client discipline engineer (W5b-10): its checks are a draft, "
            "and its clause numbers have not been confirmed against the standards.")


# -------------------------------------------------------------------- matching

def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9&*]+", " ", (text or "").lower()).split())


def _pattern(phrase: str) -> re.Pattern:
    """A cue as a regex: whole words, a trailing * means any word ending
    ("revalidat*"), spaces and hyphens in the cue match either in the text."""
    words = _norm(phrase).split()
    parts = []
    for i, w in enumerate(words):
        stem = w.endswith("*")
        w = w.rstrip("*")
        parts.append(re.escape(w) + (r"[a-z0-9]*" if stem else ""))
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-]+".join(parts) + r"(?![a-z0-9])")


def _hits(phrases: tuple[str, ...], text: str) -> list[re.Match]:
    low = " ".join((text or "").lower().split())
    out = []
    for phrase in phrases:
        m = _pattern(phrase).search(low)
        if m:
            out.append(m)
    return out


def _sentence(text: str, phrases: tuple[str, ...]) -> str | None:
    """The sentence of `text` holding the first cue found: a verbatim slice."""
    flat = " ".join((text or "").split())
    for sentence in re.split(r"(?<=[.!?;:])\s+", flat):
        if _hits(phrases, sentence):
            return sentence[:QUOTE_MAX].rstrip()
    return None


def quote_in(quote: str, text: str) -> bool:
    """Is `quote` really in `text`? Whitespace and case do not matter; nothing else."""
    q = " ".join((quote or "").lower().split())
    return bool(q) and q in " ".join((text or "").lower().split())


def _own_text(chunk: dict) -> str:
    """The passage's own text: a Word chunk's text starts with its heading line,
    which is a title and not a statement, so the heading line is taken off."""
    text = chunk.get("text") or ""
    heading = (chunk.get("section") or "").strip()
    if heading and text.startswith(heading):
        rest = text[len(heading):]
        if rest[:1] in ("\n", " ", ""):
            return rest.lstrip()
    return text


def _where(chunk: dict) -> str:
    if chunk.get("locator"):
        return chunk["locator"]
    page = chunk.get("page_start")
    return f"page {page}" if page else "unlocated"


# ------------------------------------------------------------------ the review

def _chunks(document_id: str) -> list[dict]:
    rows = connect().execute(
        "SELECT ordinal, kind, page_start, section, context, locator, retrievable, text"
        " FROM chunks WHERE document_id = ? ORDER BY ordinal", (document_id,)).fetchall()
    return [dict(r) for r in rows]


def _readiness(document_id: str) -> tuple[bool, str | None, str | None]:
    """(read in full, why not, filename)."""
    doc = connect().execute("SELECT filename, status FROM documents WHERE id = ?", (document_id,)).fetchone()
    if doc is None:
        return False, "the document does not exist", None
    if doc["status"] != "ready":
        return False, f"the document is not fully read (status: {doc['status']})", doc["filename"]
    unread = connect().execute(
        "SELECT COUNT(*) AS n FROM pages WHERE document_id = ? AND needs_ocr = 1", (document_id,)).fetchone()["n"]
    if unread:
        return False, f"{unread} page(s) were not read into text (they need recognition)", doc["filename"]
    return True, None, doc["filename"]


def standard_held(identifier: str, library: list[dict]) -> bool:
    from .applicability import find_standard
    return find_standard(library, identifier) is not None


def review(document_id: str, playbook: Playbook, *, allowed_document_ids: frozenset[str],
           proposer=None) -> dict:
    """Review `document_id` against `playbook`. `proposer(element, passages)` may
    return `[{"chunk": <index into passages>, "quote": "..."}]`; each is kept only
    when the quote is verbatim in the passage it names."""
    from . import standards, submittal_review

    submittal_review.ensure_schema()
    chunks = _chunks(document_id)
    body = [c for c in chunks if c["kind"] in BODY_KINDS and c["retrievable"]]
    read_in_full, why_not, filename = _readiness(document_id)
    if not body and read_in_full:
        read_in_full, why_not = False, "the document has no readable text"
    library = standards.list_standards(allowed_document_ids=allowed_document_ids, include_superseded=True)
    held_cache: dict[str, bool] = {}
    results = []
    ai = {"used": proposer is not None, "proposed": 0, "kept": 0, "rejected": 0}

    for element in playbook.elements:
        held = held_cache.setdefault(element.standard, standard_held(element.standard, library))
        found = _match(element, body)
        entry = {"id": element.id, "title": element.title, "expects": element.expects,
                 "source": {"standard": element.standard, "clause": element.clause},
                 "standard_held": held, "state": None, "reason": None, "evidence": [],
                 "missing_cues": [], "found_at": []}
        if not held:
            entry["state"] = STANDARD_NOT_HELD
            entry["reason"] = (f"{element.standard} is not in the library, so this element cannot be checked "
                               "against it; this is not a finding that it is met")
            entry["found_at"] = [e["locator"] for e in found["evidence"][:3]]
            results.append(entry)
            continue
        if found["state"] == PRESENT:
            entry.update(state=PRESENT, evidence=found["evidence"][:3])
        else:
            entry["missing_cues"] = found["missing_cues"]
            kept = []
            if proposer is not None:
                for p in proposer(element, [{"locator": _where(c), "text": c["text"]} for c in body]) or []:
                    ai["proposed"] += 1
                    c = body[p["chunk"]] if isinstance(p.get("chunk"), int) and 0 <= p["chunk"] < len(body) else None
                    if c is not None and quote_in(p.get("quote", ""), c["text"]):
                        ai["kept"] += 1
                        kept.append({"locator": _where(c), "quote": " ".join(p["quote"].split())[:QUOTE_MAX],
                                     "method": "proposed_and_verified"})
                    else:
                        ai["rejected"] += 1
            if kept:
                entry.update(state=PRESENT, evidence=kept[:3])
            elif found["state"] == UNCLEAR:
                entry.update(state=UNCLEAR, evidence=found["evidence"][:3],
                             reason="only part of what this element expects was found: no passage "
                                    "mentions " + ", ".join(found["missing_cues"]))
            elif not read_in_full:
                entry.update(state=COULD_NOT_BE_CHECKED, reason=f"could not be checked: {why_not}")
            else:
                entry.update(state=MISSING, reason="not found in the pages read")
        results.append(entry)

    counts = {s: sum(1 for r in results if r["state"] == s) for s in STATES}
    counts["total"] = len(results)
    return {"playbook": {"id": playbook.id, "title": playbook.title, "version": playbook.version,
                         "sign_off": playbook.sign_off, "signed_off": playbook.signed_off,
                         "clauses_verified": playbook.clauses_verified, "notice": notice(playbook)},
            "document": {"id": document_id, "filename": filename, "read_in_full": read_in_full,
                         "passages_read": len(body), "not_read_reason": why_not},
            "elements": results, "counts": counts, "ai": ai}


def _match(element: Element, body: list[dict]) -> dict:
    """Deterministic matching. PRESENT when one passage holds a cue of EVERY
    group (and a quote can be cut from its own text); UNCLEAR when cues are
    found but never all together; MISSING when none is found."""
    evidence = []
    for chunk in body:
        text = _own_text(chunk)
        # Cues may sit in the heading too ("4.2 Study team"), but a heading alone
        # is a title, not a statement: at least one cue must be in the passage's
        # own text, and the quote is cut from that text, never from the heading.
        heading = " ".join(filter(None, [chunk.get("context"), chunk.get("section")]))
        hit_groups = [label for label, phrases in element.groups if _hits(phrases, heading + " " + text)]
        if not hit_groups:
            continue
        in_text = [label for label, phrases in element.groups if _hits(phrases, text)]
        quote = next((q for q in (_sentence(text, phrases) for label, phrases in element.groups
                                  if label in in_text) if q), None)
        evidence.append({"locator": _where(chunk), "quote": quote, "method": "cue_words",
                         "groups": hit_groups, "in_text": bool(in_text)})
    all_groups = len(element.groups)
    complete = [e for e in evidence if len(e["groups"]) == all_groups and e["in_text"] and e["quote"]]
    if complete:
        return {"state": PRESENT, "evidence": complete, "missing_cues": []}
    if evidence:
        best = max(evidence, key=lambda e: (len(e["groups"]), e["in_text"]))
        absent = [label for label, _ in element.groups if label not in best["groups"]]
        if not absent:
            absent = ["a statement in the text under the heading"]
        return {"state": UNCLEAR, "evidence": sorted(evidence, key=lambda e: -len(e["groups"]))[:3],
                "missing_cues": absent}
    return {"state": MISSING, "evidence": [], "missing_cues": [label for label, _ in element.groups]}


# --------------------------------------------- a model proposes, code checks

_STOP = frozenset("the a an of to and or for in on at is are be shall must with by as that this it its from "
                  "procedure study document".split())
MAX_CANDIDATES = 4
MAX_WORDS_PER_PASSAGE = 55          # four passages stay under the task runner's word limit


def _content_words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 2 and w not in _STOP}


def task_proposer(provider=None):
    """A `proposer` backed by the AI task runner (#662): for an element whose
    cues did not settle it, the model is shown the few passages that share the
    most words with what the element expects and is asked whether one of them
    states it. Its answer is a quote, nothing more; `review` keeps the quote
    only when it is verbatim in the passage it names. The model name, the word
    limit and the retry are the runner's settings (#683), not this module's."""
    from . import ai_task_runner as runner

    def check(data: dict, text: str) -> list[str]:
        if not data.get("found"):
            return []
        pieces = {int(m.group(1)): m.group(2) for m in re.finditer(r"^\[(\d+)\] (.*)$", text, re.M)}
        passage = pieces.get(data.get("passage"))
        if passage is None:
            return ["the passage number is not one of the passages given"]
        return [] if quote_in(data.get("quote", ""), passage) else ["the quote is not in that passage"]

    spec = runner.register(runner.TaskSpec(
        name="playbook_locate", version="v1",
        instruction=("Decide whether one of the numbered passages states what the document is expected to "
                     "contain. If it does, give its number and ONE exact quote copied from it. If none does, "
                     "answer found false. Never write a quote that is not in the passage."),
        schema={"type": "object", "required": ["found", "passage", "quote"],
                "properties": {"found": {"type": "boolean"}, "passage": {"type": "integer"},
                               "quote": {"type": "string"}}},
        check=check))

    def propose(element: Element, passages: list[dict]) -> list[dict]:
        want = _content_words(element.title + " " + element.expects)
        scored = sorted(((len(want & _content_words(p["text"])), i) for i, p in enumerate(passages)), reverse=True)
        chosen = [i for n, i in scored[:MAX_CANDIDATES] if n > 0]
        if not chosen:
            return []
        lines = [f"Expected: {element.expects or element.title}"]
        for k, i in enumerate(chosen, start=1):
            lines.append(f"[{k}] " + " ".join(passages[i]["text"].split()[:MAX_WORDS_PER_PASSAGE]))
        result = runner.run_task(spec, "\n".join(lines), provider=provider)
        if result.state != runner.STATE_OK or not result.data or not result.data.get("found"):
            return []
        k = result.data.get("passage")
        if not isinstance(k, int) or not 1 <= k <= len(chosen):
            return []
        return [{"chunk": chosen[k - 1], "quote": result.data.get("quote", "")}]

    return propose
