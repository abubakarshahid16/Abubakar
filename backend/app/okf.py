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


# ------------------------------------------------------- #514: the graph
#
# A REFERENCE GRAPH BUILT ONLY FROM STORED FACTS, EVERY EDGE CITED. The nodes
# are concepts; an edge is one concept's link, and it becomes an edge only if
# its target is a node and its citation resolves AT THE TIME THE GRAPH IS
# BUILT - a file written last week may cite a chunk that has since been
# re-read. A link that fails is not an edge; it is counted under its reason.
# Nothing is inferred: two nodes that "obviously" belong together and have no
# cited link between them are not connected.

#: Why a link did not become an edge (closed words).
TARGET_MISSING = "target_not_in_the_graph"
NOT_OK = "concept_not_ok"


def graph(concepts: list[dict], *, conn=None) -> dict:
    """`{"nodes": {id: {...}}, "edges": [...], "report": {...}}`.

    A node per concept (`kind`, `title`, `state`). An edge
    `{"from", "rel", "to", "cite"}` per link whose target is a node and whose
    citation resolves now. Counts only in the report."""
    conn = conn or connect()
    nodes = {c["id"]: {"kind": c.get("kind"), "title": c.get("title"), "state": c.get("state")}
             for c in concepts}
    edges: list[dict] = []
    refused: dict[str, int] = {}

    def refuse(why: str) -> None:
        refused[why] = refused.get(why, 0) + 1

    for concept in concepts:
        for link in concept.get("links") or []:
            if concept.get("state") != OK:
                refuse(NOT_OK)
            elif link.get("rel") not in RELATIONS or link.get("to") not in nodes:
                refuse(TARGET_MISSING)
            else:
                why = resolve(link.get("cite"), conn=conn)
                if why is not None:
                    refuse(why)
                else:
                    edges.append({"from": concept["id"], "rel": link["rel"], "to": link["to"],
                                  "cite": dict(link["cite"])})
    edges.sort(key=lambda e: (e["from"], e["rel"], e["to"]))
    # The same edges by the node they leave and the node they arrive at: a
    # walk asks for one node's edges, and scanning every edge per step made a
    # question over a whole library take minutes (#515, measured).
    leaving: dict[str, list[dict]] = {}
    arriving: dict[str, list[dict]] = {}
    for edge in edges:
        leaving.setdefault(edge["from"], []).append(edge)
        arriving.setdefault(edge["to"], []).append(edge)
    return {"nodes": nodes, "edges": edges, "leaving": leaving, "arriving": arriving,
            "report": {"nodes": len(nodes), "edges": len(edges), "links_refused": refused,
                       "nodes_by_kind": {k: sum(1 for n in nodes.values() if n["kind"] == k) for k in KINDS},
                       "edges_by_relation": {r: sum(1 for e in edges if e["rel"] == r) for r in RELATIONS}}}


def neighbours(built: dict, concept_id_: str, *, relation: str | None = None,
               incoming: bool = False) -> list[dict]:
    """The edges that leave a node (or, with `incoming`, arrive at it),
    optionally of one relation. Each carries its citation: a step along the
    graph is never taken without one."""
    at_node = built["arriving" if incoming else "leaving"].get(concept_id_, ())
    return [e for e in at_node if relation is None or e["rel"] == relation]


def load(directory: Path | None = None) -> dict:
    """The concepts stored as files under `directory` (default: the local
    OKF folder): `{"concepts": [...], "unreadable": [file names]}`. A file
    that is not OKF is NAMED, never skipped silently and never read as an
    empty concept; a folder that does not exist gives no concepts."""
    base = Path(directory) if directory is not None else root()
    concepts, unreadable = [], []
    for path in sorted(base.rglob("*.md")) if base.is_dir() else []:
        try:
            concept = parse(path.read_text(encoding="utf-8"))
            if concept.get("kind") not in KINDS or not concept.get("id"):
                raise ValueError("not a concept")
            concepts.append(concept)
        except (ValueError, OSError):
            unreadable.append(path.relative_to(base).as_posix())
    return {"concepts": concepts, "unreadable": unreadable}


# ------------------------------------ #516: no uncited answer from the graph
#
# AN ANSWER MADE FROM THE GRAPH IS A LIST OF SENTENCES, EACH WITH WHAT IT
# RESTS ON. A summary across a standard ("these clauses limit noise") is the
# kind of sentence that sounds right and cites nothing. So the check is per
# sentence, in code, and it is the only way such an answer is released: a
# sentence is kept only when it names at least one thing it rests on and
# EVERY thing it names resolves. One bad citation refuses the sentence - a
# half-supported sentence is not shown with its good half.
#
# What a sentence may rest on:
#   {"concept": "<id>"}                    a node that is in the graph, is ok,
#                                          and whose own source resolves;
#   {"edge": {"from", "rel", "to"}}        an edge that is in the graph (its
#                                          citation was checked when built);
#   {"cite": {"document_id", ...}}         a raw citation that resolves.

#: Why a sentence was refused (closed words).
UNCITED = "no_citation"
CONCEPT_MISSING = "concept_not_in_the_graph"
CONCEPT_NOT_OK = "concept_not_ok"
EDGE_MISSING = "edge_not_in_the_graph"
BAD_REFERENCE = "not_a_citation"


def _support(ref, built: dict, sources: dict[str, dict | None], conn) -> str | None:
    """None when `ref` holds, else the closed reason."""
    if not isinstance(ref, dict):
        return BAD_REFERENCE
    if "concept" in ref:
        node = built["nodes"].get(ref["concept"])
        if node is None:
            return CONCEPT_MISSING
        if node.get("state") != OK:
            return CONCEPT_NOT_OK
        source = sources.get(ref["concept"])
        # A standard or an equipment type has no page of its own: it holds
        # through an edge that reaches it, which was cited when built.
        if source is None:
            reached = any(e["to"] == ref["concept"] or e["from"] == ref["concept"] for e in built["edges"])
            return None if reached else UNCITED
        return resolve(source, conn=conn)
    if "edge" in ref:
        wanted = ref["edge"] if isinstance(ref["edge"], dict) else {}
        key = (wanted.get("from"), wanted.get("rel"), wanted.get("to"))
        return None if any((e["from"], e["rel"], e["to"]) == key for e in built["edges"]) else EDGE_MISSING
    if "cite" in ref:
        return resolve(ref["cite"] if isinstance(ref["cite"], dict) else None, conn=conn)
    return BAD_REFERENCE


def check_answer(sentences: list[dict], built: dict, concepts: list[dict], *, conn=None) -> dict:
    """Release only the sentences of a graph answer that are fully cited.

    `sentences` are `{"text", "cites": [...]}`. Returns `{"kept": [...],
    "refused": [{"index", "reason"}], "counts": {reason: n}}`. A refused
    sentence's TEXT is not returned: it is not shown, and it is not logged."""
    conn = conn or connect()
    sources = {c["id"]: c.get("source") for c in concepts}
    kept: list[dict] = []
    refused: list[dict] = []
    counts: dict[str, int] = {}
    for index, sentence in enumerate(sentences or []):
        cites = sentence.get("cites") if isinstance(sentence, dict) else None
        text = str(sentence.get("text") or "").strip() if isinstance(sentence, dict) else ""
        reason = None
        if not text or not isinstance(cites, list) or not cites:
            reason = UNCITED
        else:
            reason = next((why for why in (_support(ref, built, sources, conn) for ref in cites)
                           if why is not None), None)
        if reason is None:
            kept.append({"text": text, "cites": cites})
        else:
            refused.append({"index": index, "reason": reason})
            counts[reason] = counts.get(reason, 0) + 1
    return {"kept": kept, "refused": refused, "counts": counts}


# ------------------------------------------------- #515: three graph queries
#
# WHICH STANDARDS APPLY, IS THIS THE LATEST REVISION, WHAT ELSE IS AFFECTED.
# Each answer is made of steps, and a step is an edge of the graph with its
# citation - or, for a revision, the stored classification record, re-read at
# the time of asking. A question the graph cannot answer gets a NAMED state,
# never an empty list that reads as "none": "no standard applies" and "this
# equipment type is not in the graph" are different answers.

#: The states of a query (closed words).
ANSWERED = "answered"
EQUIPMENT_UNKNOWN = "equipment_type_not_in_the_graph"
NO_CITED_PATH = "no_cited_path_to_a_standard"
NOTHING_AFFECTED = "nothing_reaches_it"
SUPERSEDED = "superseded"
ONLY_ONE_HELD = "only_revision_held"
LATEST_HELD = "latest_of_the_revisions_held"
ORDER_NOT_RECORDED = "order_of_the_revisions_held_is_not_recorded"
NO_NUMBER = "no_document_number_recorded"


def applicable(built: dict, equipment_type: str) -> dict:
    """Which standards apply to an equipment type: every standard a cited
    path reaches from it (requirement applies_to it, in_clause a clause,
    part_of the standard). `{"state", "standards": [{"standard", "paths"}],
    "requirements_reaching_no_standard": n}`; a path is its three edges."""
    target = concept_id(EQUIPMENT_TYPE, equipment_type)
    if target not in built["nodes"]:
        return {"state": EQUIPMENT_UNKNOWN, "standards": [], "requirements_reaching_no_standard": 0}
    reached: dict[str, list[list[dict]]] = {}
    stranded = 0
    for applies in neighbours(built, target, relation=APPLIES_TO, incoming=True):
        paths = [[applies, in_clause, part]
                 for in_clause in neighbours(built, applies["from"], relation=IN_CLAUSE)
                 for part in neighbours(built, in_clause["to"], relation=PART_OF)]
        for path in paths:
            reached.setdefault(path[-1]["to"], []).append(path)
        stranded += not paths
    return {"state": ANSWERED if reached else NO_CITED_PATH,
            "standards": [{"standard": standard, "paths": reached[standard]} for standard in sorted(reached)],
            "requirements_reaching_no_standard": stranded}


def impact(built: dict, concept_id_: str) -> dict:
    """What else is affected when a concept changes: everything that reaches
    it along cited edges (a standard's clauses, their requirements), and the
    equipment types those requirements apply to. `{"state", "affected":
    [{"concept", "kind", "path"}]}`; the path is the edges from the concept.
    An equipment type that is reached is an end: the walk does not go on from
    it to every other requirement of that type."""
    nodes = built["nodes"]
    if concept_id_ not in nodes:
        return {"state": CONCEPT_MISSING, "affected": []}
    paths: dict[str, list[dict]] = {}
    queue: list[tuple[str, list[dict]]] = [(concept_id_, [])]
    while queue:
        node, path = queue.pop(0)
        if node != concept_id_ and nodes[node]["kind"] == EQUIPMENT_TYPE:
            continue
        steps = [(e["from"], e) for e in neighbours(built, node, incoming=True)]
        if nodes[node]["kind"] == REQUIREMENT:
            steps += [(e["to"], e) for e in neighbours(built, node, relation=APPLIES_TO)]
        for other, edge in steps:
            if other != concept_id_ and other not in paths:
                paths[other] = path + [edge]
                queue.append((other, paths[other]))
    return {"state": ANSWERED if paths else NOTHING_AFFECTED,
            "affected": [{"concept": other, "kind": nodes[other]["kind"], "path": paths[other]}
                         for other in sorted(paths)]}


def _superseded_by(conn, document_id) -> str | None:
    row = conn.execute("SELECT superseded_by FROM document_classification WHERE document_id = ?",
                       (document_id,)).fetchone()
    return (row["superseded_by"] or None) if row is not None else None


def latest_revision(built: dict, concepts: list[dict], standard_id: str, *, conn=None) -> dict:
    """Is this standard the latest revision - OF THE REVISIONS THIS LIBRARY
    HOLDS, which is all the graph can know. It rests on the stored record
    that one document supersedes another (set by a person), re-read now; a
    revision label is never compared to guess an order. `{"state", "basis",
    ...}`: `superseded` names the document that replaced it; with several
    revisions held and no record that orders them, the answer is that the
    order is not recorded."""
    conn = conn or connect()
    facts = {c["id"]: c.get("facts") or {} for c in concepts if c.get("kind") == STANDARD}
    if standard_id not in built["nodes"] or standard_id not in facts:
        return {"state": CONCEPT_MISSING}
    document_id = facts[standard_id].get("document_id")
    basis = {"record": "document_classification.superseded_by", "document_id": document_id,
             "boundary": "the revisions this library holds"}
    replaced_by = _superseded_by(conn, document_id)
    if replaced_by:
        return {"state": SUPERSEDED, "superseded_by": replaced_by,
                "superseding_standard_in_the_graph": concept_id(STANDARD, replaced_by) in built["nodes"],
                "basis": basis}
    number = _fold(facts[standard_id].get("document_number"))
    if not number:
        return {"state": NO_NUMBER, "basis": basis}
    others = sorted(other for other, f in facts.items()
                    if other != standard_id and other in built["nodes"] and _fold(f.get("document_number")) == number)
    unordered = []
    for other in others:
        at, seen = facts[other].get("document_id"), set()
        while at and at != document_id and at not in seen:        # follow the record to its end
            seen.add(at)
            at = _superseded_by(conn, at)
        if at != document_id:
            unordered.append(other)
    if unordered:
        return {"state": ORDER_NOT_RECORDED, "also_held": unordered, "basis": basis}
    return {"state": LATEST_HELD if others else ONLY_ONE_HELD, "replaces": others, "basis": basis}
