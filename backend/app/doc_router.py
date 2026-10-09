"""The document-type router (W5b-02, #526).

WHAT A DOCUMENT IS decides how it is read and reviewed. Only datasheet-shaped
documents were routed; a procedure, a study, a report, a FEED document or a
letter was treated as if it were one, or not at all (275 of 283 documents of
the live library showed "Awaiting a type").

The router scores each kind from cues in the FILE NAME, the TITLE lines, the
BODY of the first three pages and the SHAPE of the text (label/value rows,
numbered steps, a salutation and a sign-off...), using the generic cues in
`reference/document_kinds.json`. Then it does the thing this project insists
on:

  * ONE KIND CLEARLY LEADS (score at least `min_score`, ahead of the runner-up
    by at least `min_margin`): the kind is stored as a SUGGESTION. It is a
    guess, shown as a guess, and confirmed by a person before anything may rely
    on it (rule 4).
  * OTHERWISE the kind is left EMPTY and the document is marked
    `needs_engineer`: "an unknown type asks the engineer instead of guessing".
    The two best candidates and their scores are kept as evidence so the
    engineer sees what the router saw. No kind is invented, and no default is
    stored as if it were a finding.
  * A kind a person CONFIRMED is never overwritten by a later routing run.

The evidence is cue ids and locations ("title: cue 1"), never document text, so
it can be shown and logged. Nothing here opens a socket or calls a model.
Classification is not access control (rule 5): this changes what a document is
called, never who may read it.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from .db import connect

log = logging.getLogger(__name__)

CUES_PATH = Path(__file__).parent / "reference" / "document_kinds.json"

STATE_SUGGESTED = "suggested"
STATE_NEEDS_ENGINEER = "needs_engineer"
STATE_CONFIRMED = "confirmed"
STATES = (STATE_SUGGESTED, STATE_NEEDS_ENGINEER, STATE_CONFIRMED)

#: Lines of page 1 read as the title area; pages read for body cues.
TITLE_LINES = 12
BODY_PAGES = 3
#: Lines examined for the structural features (a long document is not scanned whole).
FEATURE_LINES = 400


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def vocabulary() -> dict:
    """The cue file. Re-read when it changes on disk."""
    return _load(str(CUES_PATH), CUES_PATH.stat().st_mtime)


def kinds() -> list[dict]:
    """The kinds a person may choose, in file order: [{"id", "label"}]."""
    return [{"id": k, "label": v.get("label", k)} for k, v in vocabulary()["kinds"].items()]


# ------------------------------------------------------------------ features

_LABEL_VALUE = re.compile(r"^[A-Za-z][\w /().%,&-]{1,45}\s*(?::|\s\|\s)\s*\S")
_NUMBERED = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[a-z]\)|\(\d+\))\s+\S")
_MODAL = re.compile(r"\b(?:shall|must|should)\b", re.I)
_SALUTATION = re.compile(r"^\s*(?:dear\b|to whom it may concern)", re.I | re.M)
_SIGNOFF = re.compile(
    r"^\s*(?:yours\s+(?:sincerely|faithfully|truly)|kind regards|best regards|regards|sincerely)\b",
    re.I | re.M)
_SUBJECT = re.compile(r"^\s*(?:subject|re)\s*:", re.I | re.M)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def features(pages: list[str]) -> dict[str, float]:
    """Measured shapes of the first pages. All numbers, no text."""
    text = "\n".join(pages[:BODY_PAGES])
    lines = [ln for ln in text.splitlines() if ln.strip()][:FEATURE_LINES]
    n = len(lines) or 1
    return {
        "label_value_ratio": sum(1 for ln in lines if _LABEL_VALUE.match(ln.strip())) / n,
        "numbered_steps": float(sum(1 for ln in lines if _NUMBERED.match(ln))),
        "modal_verbs": float(len(_MODAL.findall(text))),
        "salutation": float(bool(_SALUTATION.search(text))),
        "signoff": float(bool(_SIGNOFF.search(text))),
        "subject_line": float(bool(_SUBJECT.search(text))),
        "table_rows": float(sum(1 for ln in lines if _TABLE_ROW.match(ln))),
    }


# --------------------------------------------------------------------- score


@dataclass
class Routing:
    kind: str | None
    state: str
    #: {kind: score}, best first - kept so an engineer sees what the router saw.
    scores: dict[str, int] = field(default_factory=dict)
    #: cue locations that fired for the leading kinds: "datasheet: title (3)".
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    def as_json(self) -> str:
        return json.dumps({"scores": self.scores, "evidence": self.evidence,
                           "reason": self.reason}, sort_keys=True)


def _title_text(pages: list[str]) -> str:
    first = pages[0] if pages else ""
    return "\n".join([ln for ln in first.splitlines() if ln.strip()][:TITLE_LINES])


def score(filename: str, pages: list[str]) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Per-kind score and the cues that fired. Body cues are capped per kind so
    a long document that merely mentions many words does not outvote a title."""
    vocab = vocabulary()
    cap = int(vocab.get("body_cue_cap", 3))
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "")
    title = _title_text(pages)
    body = "\n".join(pages[:BODY_PAGES])
    feats = features(pages)
    scores: dict[str, int] = {}
    fired: dict[str, list[str]] = {}
    for kind, spec in vocab["kinds"].items():
        total, body_total, notes = 0, 0, []
        for i, cue in enumerate(spec.get("cues", []), start=1):
            where, weight = cue["where"], int(cue.get("weight", 1))
            hit = False
            if where == "feature":
                hit = feats.get(cue["feature"], 0.0) >= float(cue.get("min", 1))
            else:
                subject = {"filename": stem, "title": title, "body": body}[where]
                hit = re.search(cue["pattern"], subject, re.I) is not None
            if not hit:
                continue
            if where == "body":
                if body_total >= cap:
                    continue
                weight = min(weight, cap - body_total)
                body_total += weight
            total += weight
            notes.append(f"{kind}: {where} cue {i} ({weight})")
        scores[kind], fired[kind] = total, notes
    return scores, fired


def route(filename: str, pages: list[str]) -> Routing:
    """Decide a kind, or ask. `pages` are the page texts in order (page 1 first)."""
    vocab = vocabulary()
    min_score, min_margin = int(vocab.get("min_score", 4)), int(vocab.get("min_margin", 2))
    if not any((p or "").strip() for p in pages):
        return Routing(None, STATE_NEEDS_ENGINEER, {}, [],
                       "no text could be read, so the router has nothing to go on")
    scores, fired = score(filename, [p or "" for p in pages])
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    (best, best_score), (second, second_score) = ranked[0], ranked[1]
    shown = dict(ranked[:3])
    if best_score >= min_score and best_score - second_score >= min_margin:
        return Routing(best, STATE_SUGGESTED, shown, fired[best],
                       f"{best} leads ({best_score} against {second_score})")
    why = (f"nothing is clear enough: best is {best} at {best_score}"
           if best_score < min_score else
           f"{best} ({best_score}) and {second} ({second_score}) are too close")
    return Routing(None, STATE_NEEDS_ENGINEER, shown, fired[best] + fired[second], why)


# ------------------------------------------------------------------- storage


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pages_of(document_id: str) -> list[str]:
    rows = connect().execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? AND page_no <= ? ORDER BY page_no",
        (document_id, BODY_PAGES)).fetchall()
    return [r["text"] or "" for r in rows]


def route_document(document_id: str) -> Routing | None:
    """Route one document and store the result. A CONFIRMED kind is left alone
    (None is returned). Idempotent."""
    conn = connect()
    existing = conn.execute("SELECT state, router_version FROM document_kinds WHERE document_id = ?",
                            (document_id,)).fetchone()
    if existing is not None and existing["state"] == STATE_CONFIRMED:
        return None
    doc = conn.execute("SELECT filename FROM documents WHERE id = ?", (document_id,)).fetchone()
    if doc is None:
        return None
    routing = route(doc["filename"], _pages_of(document_id))
    version = str(vocabulary().get("router_version", "1"))
    with conn:
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, evidence, router_version, routed_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(document_id) DO UPDATE SET kind = excluded.kind, state = excluded.state,"
            " evidence = excluded.evidence, router_version = excluded.router_version,"
            " routed_at = excluded.routed_at WHERE document_kinds.state != 'confirmed'",
            (document_id, routing.kind, routing.state, routing.as_json(), version, _now()))
    return routing


def route_unrouted(limit: int = 500) -> dict:
    """Route every document that has no routing yet, or whose routing was made
    by an older router version. Returns counts only."""
    version = str(vocabulary().get("router_version", "1"))
    rows = connect().execute(
        "SELECT d.id FROM documents d LEFT JOIN document_kinds k ON k.document_id = d.id"
        " WHERE d.status IN ('ready', 'partially_searchable', 'no_searchable_content')"
        " AND (k.document_id IS NULL OR (k.state != 'confirmed' AND k.router_version != ?))"
        " LIMIT ?", (version, limit)).fetchall()
    counts = {STATE_SUGGESTED: 0, STATE_NEEDS_ENGINEER: 0}
    for r in rows:
        routing = route_document(r["id"])
        if routing is not None:
            counts[routing.state] += 1
    return {"routed": sum(counts.values()), **counts}


class UnknownKind(ValueError):
    pass


def confirm(document_id: str, kind: str, confirmed_by: str | None) -> dict:
    """A person's decision. Sets the kind and `confirmed`. A kind not in the
    vocabulary is refused by name."""
    if kind not in vocabulary()["kinds"]:
        raise UnknownKind(f"unknown document kind {kind!r}")
    conn = connect()
    now = _now()
    with conn:
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, evidence, router_version,"
            " routed_at, confirmed_by, confirmed_at) VALUES (?, ?, 'confirmed', NULL, ?, ?, ?, ?)"
            " ON CONFLICT(document_id) DO UPDATE SET kind = excluded.kind, state = 'confirmed',"
            " confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at",
            (document_id, kind, str(vocabulary().get("router_version", "1")), now, confirmed_by, now))
    return of_documents([document_id])[document_id]


def of_documents(document_ids: list[str]) -> dict[str, dict]:
    """The stored routing of each given document that has one: {document_kind,
    document_kind_state, document_kind_evidence}. No scope check - callers pass
    ids they have already scoped."""
    ids = list(dict.fromkeys(document_ids))
    out: dict[str, dict] = {}
    conn = connect()
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT document_id, kind, state, evidence FROM document_kinds"
                f" WHERE document_id IN ({marks})", chunk):
            try:
                evidence = json.loads(r["evidence"] or "null")
            except ValueError:
                evidence = None
            out[r["document_id"]] = {
                "document_kind": r["kind"], "document_kind_state": r["state"],
                "document_kind_evidence": evidence if isinstance(evidence, dict) else None}
    return out


def counts(allowed: frozenset[str] | None) -> dict:
    """How many documents, among those a caller may read, have each routing
    state (and how many have none). `allowed` None means every document."""
    conn = connect()
    where, args = "", ()
    if allowed is not None:
        if not allowed:
            return {"total": 0, STATE_SUGGESTED: 0, STATE_NEEDS_ENGINEER: 0, STATE_CONFIRMED: 0,
                    "not_routed": 0}
        where = f" WHERE d.id IN ({','.join('?' * len(allowed))})"
        args = tuple(allowed)
    rows = conn.execute(
        f"SELECT k.state AS state, COUNT(*) AS n FROM documents d"
        f" LEFT JOIN document_kinds k ON k.document_id = d.id{where} GROUP BY k.state", args)
    by = {r["state"]: r["n"] for r in rows}
    total = sum(by.values())
    return {"total": total, STATE_SUGGESTED: by.get(STATE_SUGGESTED, 0),
            STATE_NEEDS_ENGINEER: by.get(STATE_NEEDS_ENGINEER, 0),
            STATE_CONFIRMED: by.get(STATE_CONFIRMED, 0), "not_routed": by.get(None, 0)}
