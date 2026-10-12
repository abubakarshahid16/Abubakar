"""OKF v1: the project's knowledge format (#513, first step of R29 #833).

ONE CONCEPT, ONE FILE. A concept is a standard, a clause, a requirement or an
equipment type. Each is a Markdown file with a small frontmatter block: who
it is, where it comes from, and its LINKS to other concepts. The files are
what a reference graph (#514), its queries (#515) and the "no uncited answer"
check (#516) are built on.

THE RULE OF THE FORMAT: NO LINK WITHOUT A RESOLVING CITATION. A link says
"this clause is part of that standard", "this requirement applies to that
equipment type". Each one carries a citation - a document, a page and a
stored chunk - and it is written only when that citation RESOLVES: the chunk
exists, it belongs to that document, the page is one the chunk spans, and for
a requirement the quoted words are in the chunk's text. A concept whose
source does not resolve is still written, with a NAMED state
(`citation_unresolved`) and no links, and it is counted in the build report:
never dropped silently and never linked on trust.

BUILT FROM STORED FACTS ONLY. `build` reads the tables the ingestion and the
extraction already wrote (documents, classification, chunks, requirements).
No model is called, no socket is opened, nothing is inferred. Access is the
caller's: a document the caller may not read gives no concept at all.

WHERE THE FILES LIVE. They hold document text, so `write` puts them under the
local data folder (`<data_dir>/okf/v1/`), which is outside git, and refuses
any other place. Counts and ids only are reported.

Not in v1 (named, not forgotten): concepts for a datasheet, a revision and a
finding; cross-reference links between standards (R8 #772); engineer approval
and versions of the map (R29 #833). Each concept does carry a content hash,
which is what a version will be made of.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .config import settings
from .db import connect

VERSION = 1

STANDARD, CLAUSE, REQUIREMENT, EQUIPMENT_TYPE = "standard", "clause", "requirement", "equipment_type"
KINDS = (STANDARD, CLAUSE, REQUIREMENT, EQUIPMENT_TYPE)

#: Link relations. Each is written from the more specific concept to the
#: more general one, so a file can be read on its own.
PART_OF = "part_of"            # clause -> standard
IN_CLAUSE = "in_clause"        # requirement -> clause
APPLIES_TO = "applies_to"      # requirement -> equipment type
RELATIONS = (PART_OF, IN_CLAUSE, APPLIES_TO)

#: Concept states. `ok`, or the named reason it carries no links.
OK = "ok"
CITATION_UNRESOLVED = "citation_unresolved"

#: Why a citation does not resolve (closed words, counted in the report).
NO_CHUNK = "no_chunk_recorded"
CHUNK_MISSING = "chunk_not_found"
WRONG_DOCUMENT = "chunk_of_another_document"
PAGE_OUTSIDE = "page_outside_the_chunk"
QUOTE_ABSENT = "quote_not_in_the_chunk"
CELL_ABSENT = "table_cell_not_in_the_chunk"

#: Requirement types read from a TABLE. Their stored sentence is composed by
#: the extractor from a row label, a column and a cell - it is not a quote of
#: the page - so the proof is that the row label and the value are both in
#: the cited chunk.
TABLE_TYPES = frozenset({"table_value", "table_row"})

_ID_PART = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text) -> str:
    return _ID_PART.sub("-", str(text or "").strip()).strip("-").lower() or "none"


def concept_id(kind: str, *parts) -> str:
    """`okf:<kind>:<part>:<part>` - stable for the same stored fact."""
    return "okf:" + ":".join([kind, *(_slug(p) for p in parts)])


def _fold(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


# ---------------------------------------------------------------- citations

def resolve(citation: dict | None, *, conn=None) -> str | None:
    """None when the citation resolves, else the closed reason it does not.

    A citation is `{"document_id", "page", "chunk_id", "quote"?, "cells"?}`.
    It resolves when the chunk exists, belongs to that document, spans that
    page, and contains the quote when one is given - or, for a table reading,
    every one of its `cells` (the row label and the value). Whitespace and
    case are folded, nothing else."""
    citation = citation or {}
    chunk_id = citation.get("chunk_id")
    if not chunk_id:
        return NO_CHUNK
    conn = conn or connect()
    chunk = conn.execute("SELECT document_id, page_start, page_end, text FROM chunks WHERE id = ?",
                         (chunk_id,)).fetchone()
    if chunk is None:
        return CHUNK_MISSING
    if chunk["document_id"] != citation.get("document_id"):
        return WRONG_DOCUMENT
    page = citation.get("page")
    first = chunk["page_start"] or 1
    last = chunk["page_end"] or first
    if page is not None and not (first <= int(page) <= last):
        return PAGE_OUTSIDE
    text = _fold(chunk["text"])
    quote = _fold(citation.get("quote"))
    if quote and quote not in text:
        return QUOTE_ABSENT
    cells = [_fold(cell) for cell in citation.get("cells") or []]
    if any(not cell or cell not in text for cell in cells):
        return CELL_ABSENT
    return None


# -------------------------------------------------------------------- build

def build(standard_document_ids, *, allowed_document_ids: frozenset[str]) -> dict:
    """The concepts of these standards, from stored facts only.

    Returns `{"concepts": [...], "report": {...}}`. A standard the caller may
    not read, or that the library does not hold, gives no concept and is
    named in the report (`not_readable`, `not_held`). Counts only in the
    report - never a title or a sentence."""
    conn = connect()
    wanted = [str(d) for d in dict.fromkeys(standard_document_ids or ())]
    report = {"version": VERSION, "standards_asked": len(wanted), "not_readable": [], "not_held": [],
              "concepts": {kind: 0 for kind in KINDS}, "links": {rel: 0 for rel in RELATIONS},
              "unresolved": {}, "requirements_without_a_clause": 0}
    concepts: dict[str, dict] = {}

    def add(concept: dict) -> dict:
        concepts[concept["id"]] = concept
        return concept

    for doc_id in wanted:
        if doc_id not in allowed_document_ids:
            report["not_readable"].append(doc_id)
            continue
        doc = conn.execute("SELECT id, page_count FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if doc is None:
            report["not_held"].append(doc_id)
            continue
        meta = _classification(conn, doc_id)
        standard = add({
            "okf": VERSION, "kind": STANDARD, "id": concept_id(STANDARD, doc_id), "state": OK,
            "title": meta.get("title") or meta.get("document_number") or doc_id,
            "facts": {"document_id": doc_id, "document_number": meta.get("document_number"),
                      "revision": meta.get("revision"), "pages": doc["page_count"]},
            "source": None, "links": [], "body": ""})
        rows = conn.execute(
            "SELECT id, clause, page, chunk_id, requirement_text, source_text, requirement_type,"
            " equipment_type, confirmed_by, raw_value, table_row FROM standard_requirements"
            " WHERE standard_document_id = ? AND superseded_at IS NULL ORDER BY page, clause, id",
            (doc_id,)).fetchall()
        for row in rows:
            citation = {"document_id": doc_id, "page": row["page"], "chunk_id": row["chunk_id"]}
            if row["requirement_type"] in TABLE_TYPES:
                citation["cells"] = [row["table_row"], row["raw_value"]]
            else:
                citation["quote"] = row["source_text"] or row["requirement_text"]
            why = resolve(citation, conn=conn)
            concept = add({
                "okf": VERSION, "kind": REQUIREMENT, "id": concept_id(REQUIREMENT, row["id"]),
                "state": OK if why is None else CITATION_UNRESOLVED, "unresolved": why,
                "title": f"{meta.get('document_number') or doc_id} {row['clause'] or '(no clause)'}",
                "facts": {"requirement_id": row["id"], "requirement_type": row["requirement_type"],
                          "confirmed": bool(row["confirmed_by"])},
                "source": {k: citation[k] for k in ("document_id", "page", "chunk_id")},
                "links": [], "body": str(row["source_text"] or row["requirement_text"] or "").strip()})
            if why is not None:
                report["unresolved"][why] = report["unresolved"].get(why, 0) + 1
                continue
            cite = dict(concept["source"])
            if row["clause"]:
                clause_id = concept_id(CLAUSE, doc_id, row["clause"])
                clause = concepts.get(clause_id) or add({
                    "okf": VERSION, "kind": CLAUSE, "id": clause_id, "state": OK,
                    "title": f"{meta.get('document_number') or doc_id} {row['clause']}",
                    "facts": {"document_id": doc_id, "clause": row["clause"]},
                    "source": cite, "body": "",
                    "links": [{"rel": PART_OF, "to": standard["id"], "cite": cite}]})
                concept["links"].append({"rel": IN_CLAUSE, "to": clause["id"], "cite": cite})
            else:
                report["requirements_without_a_clause"] += 1
            if _fold(row["equipment_type"]):
                kind_id = concept_id(EQUIPMENT_TYPE, row["equipment_type"])
                concepts.get(kind_id) or add({
                    "okf": VERSION, "kind": EQUIPMENT_TYPE, "id": kind_id, "state": OK,
                    "title": str(row["equipment_type"]).strip(), "facts": {}, "source": None,
                    "links": [], "body": ""})
                concept["links"].append({"rel": APPLIES_TO, "to": kind_id, "cite": cite})
    for concept in concepts.values():
        concept["content_sha256"] = _content_hash(concept)
        report["concepts"][concept["kind"]] += 1
        for link in concept["links"]:
            report["links"][link["rel"]] += 1
    return {"concepts": sorted(concepts.values(), key=lambda c: c["id"]), "report": report}


def _classification(conn, document_id: str) -> dict:
    try:
        row = conn.execute("SELECT document_number, revision, title FROM document_classification"
                           " WHERE document_id = ?", (document_id,)).fetchone()
    except Exception:  # noqa: BLE001 - a library with no classification table yet
        return {}
    return dict(row) if row else {}


def _content_hash(concept: dict) -> str:
    """What a version of the map will be made of: the concept without its hash."""
    plain = {k: v for k, v in concept.items() if k != "content_sha256"}
    return hashlib.sha256(json.dumps(plain, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# -------------------------------------------------------------------- check

def problems(concepts: list[dict], *, conn=None) -> list[str]:
    """Everything that breaks the format's rule, as plain lines (ids only).
    Empty means: every link points at a concept in the set and carries a
    citation that resolves, and no concept in an unresolved state has links."""
    conn = conn or connect()
    known = {c["id"] for c in concepts}
    out: list[str] = []
    for concept in concepts:
        if concept.get("kind") not in KINDS:
            out.append(f"{concept.get('id')}: unknown kind")
        if concept.get("state") != OK and concept.get("links"):
            out.append(f"{concept['id']}: is {concept.get('state')} and still carries links")
        for link in concept.get("links") or []:
            if link.get("rel") not in RELATIONS:
                out.append(f"{concept['id']}: unknown relation {link.get('rel')!r}")
            if link.get("to") not in known:
                out.append(f"{concept['id']}: links to {link.get('to')}, which is not in the set")
            why = resolve(link.get("cite"), conn=conn)
            if why is not None:
                out.append(f"{concept['id']}: link {link.get('rel')} has no resolving citation ({why})")
    return out


# ------------------------------------------------------------ file format

_FRONT = "---"


def render(concept: dict) -> str:
    """The concept as a Markdown file: frontmatter (one `key: JSON` per
    line, keys sorted), a blank line, then the body."""
    front = {k: v for k, v in concept.items() if k != "body"}
    lines = [_FRONT] + [f"{key}: {json.dumps(front[key], ensure_ascii=False, sort_keys=True)}"
                        for key in sorted(front)] + [_FRONT, ""]
    return "\n".join(lines) + (concept.get("body") or "") + "\n"


def parse(text: str) -> dict:
    """The concept a file holds. Raises ValueError on a file that is not OKF
    (no frontmatter, a line that is not `key: JSON`): an unreadable file is
    an error, never an empty concept."""
    lines = str(text).split("\n")
    if not lines or lines[0].strip() != _FRONT:
        raise ValueError("not an OKF file: no frontmatter")
    try:
        end = lines.index(_FRONT, 1)
    except ValueError:
        raise ValueError("not an OKF file: the frontmatter does not close") from None
    concept: dict = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(": ")
        if not sep or not key.strip():
            raise ValueError(f"not an OKF file: bad frontmatter line {line[:40]!r}")
        concept[key.strip()] = json.loads(value)
    body = "\n".join(lines[end + 1:])
    concept["body"] = body.strip("\n")
    return concept


def file_name(concept: dict) -> str:
    """`<kind>/<id without its prefix>.md` - one file per concept."""
    return f"{concept['kind']}/{_slug(concept['id'].split(':', 2)[2])}.md"


def root() -> Path:
    return Path(settings.data_dir) / "okf" / f"v{VERSION}"


def write(concepts: list[dict], out_dir: Path | None = None) -> dict:
    """Write one file per concept under the LOCAL data folder and nowhere
    else (the files hold document text; the data folder is outside git).
    Returns counts. Refuses a set that breaks the format's rule."""
    out = Path(out_dir) if out_dir is not None else root()
    data = Path(settings.data_dir).resolve()
    if data not in [out.resolve(), *out.resolve().parents]:
        raise ValueError("OKF files hold document text and are written only under the local data folder")
    found = problems(concepts)
    if found:
        raise ValueError(f"the set breaks the OKF rule in {len(found)} place(s); nothing was written")
    written = 0
    for concept in concepts:
        path = out / file_name(concept)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(concept), encoding="utf-8")
        written += 1
    return {"written": written, "kinds": {k: sum(1 for c in concepts if c["kind"] == k) for k in KINDS}}
