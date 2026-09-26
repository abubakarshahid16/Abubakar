"""Claude-first chat (2026-09-27): the tools Claude may call.

Claude is the conversation brain; these are its hands. Every tool here is
CALLER-PERMISSION-SCOPED FIRST, before anything else runs - a tool never
returns a document the caller may not read, the same "not found" a direct
request for it would get (CLAUDE.md rule 5: intersection, never union).

Nothing here talks to the network except `web_search`, and that one never
sends anything either: calling it only opens the SAME consent turn
`chat_web.consent` already builds for the router path (`chat_web.py`,
`chat_claude_first.py`'s docstring explains why a tool call cannot bypass
consent). `look_at_page` renders a page image locally and hands it back as
part of the tool result; nothing about calling it costs money by itself,
only the Claude turn that reads the image does, exactly like any other
Claude call, and it is charged the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import applicability, datasheets, standards
from . import search as search_mod
from .db import connect

#: Anthropic tool-use definitions. `web_search` and `look_at_page` are added
#: by the caller only when that lane is actually usable this turn
#: (`chat_claude_first.available_tools`).
SEARCH_DOCUMENTS = {
    "name": "search_documents",
    "description": (
        "Search the user's own documents for passages relevant to a query. "
        "Use this for any question about what a document, standard or "
        "submittal says. Returns numbered passages with page numbers; quote "
        "them exactly when you cite one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "document_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Optional: restrict the search to these document ids.",
            },
        },
        "required": ["query"],
    },
}

READ_DOCUMENT = {
    "name": "read_document",
    "description": (
        "Read a document's title, revision and headings, plus the text of "
        "specific pages (or, with no pages given, the first few pages and "
        "every heading) - for questions like 'tell me about this document' "
        "or 'what does this cover'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "pages": {"type": "array", "items": {"type": "integer"},
                     "description": "Optional: specific page numbers, 1-based."},
        },
        "required": ["document_id"],
    },
}

GET_DATASHEET_FIELDS = {
    "name": "get_datasheet_fields",
    "description": (
        "The extracted submittal facts (field, value, unit, page) already "
        "read from a contractor datasheet, with page numbers - use this "
        "before re-reading pages by hand."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"document_id": {"type": "string"}},
        "required": ["document_id"],
    },
}

LIST_CITED_STANDARDS = {
    "name": "list_cited_standards",
    "description": (
        "The standards a submittal cites, and for each: whether it is held "
        "in this library (and can be quoted) or missing (cited but not "
        "available here)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"document_id": {"type": "string"}},
        "required": ["document_id"],
    },
}

WEB_SEARCH = {
    "name": "web_search",
    "description": (
        "Search the public web for background information NOT in the "
        "user's documents (e.g. whether a standard has a newer edition). "
        "Calling this ALWAYS asks the user to approve the exact phrase "
        "first; it never sends anything itself. Only call it when the user "
        "turned the Web switch on and asked something the documents cannot "
        "answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}

LOOK_AT_PAGE = {
    "name": "look_at_page",
    "description": (
        "See the rendered IMAGE of one page - use this for a drawing, a "
        "stamp, a table whose layout matters, or anything read_document's "
        "text did not capture cleanly. Expensive: use it only when the text "
        "is not enough, and only for pages you specifically need."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "page": {"type": "integer"},
        },
        "required": ["document_id", "page"],
    },
}

#: Every source the toolset can offer, before any per-turn filtering.
ALL_TOOLS = (SEARCH_DOCUMENTS, READ_DOCUMENT, GET_DATASHEET_FIELDS, LIST_CITED_STANDARDS)


class ConsentRequired(Exception):
    """`web_search` was called: stop the loop and ask the user first."""

    def __init__(self, query: str) -> None:
        super().__init__(query)
        self.query = query


@dataclass
class ToolRun:
    """One call, what it returned, and the numbered sources it added -
    exactly what "How I got this" shows, in plain words, never raw JSON."""

    name: str
    input: dict
    label: str
    ok: bool
    sources_added: list[dict] = field(default_factory=list)
    note: str = ""


def _readable(document_id: str, *, allowed_document_ids: frozenset[str]) -> dict | None:
    """The document row, or None - a document outside the caller's grants is
    indistinguishable from one that does not exist."""
    if document_id not in allowed_document_ids:
        return None
    row = connect().execute(
        "SELECT d.*, c.title, c.revision, c.document_number, c.doc_class, c.document_role "
        "FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id "
        "WHERE d.id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


def _display_name(doc: dict) -> str:
    """The document's title if it has one, else its filename stem - never
    the raw filename with its extension in front of an engineer."""
    title = (doc.get("title") or "").strip()
    if title:
        return title
    stem = (doc.get("filename") or doc["id"]).rsplit(".", 1)[0]
    return stem


def run_search_documents(input: dict, *, allowed_document_ids: frozenset[str]) -> ToolRun:
    query = str(input.get("query") or "").strip()
    picked = input.get("document_ids") or None
    scope = (allowed_document_ids & frozenset(picked)) if picked else allowed_document_ids
    if not query:
        return ToolRun("search_documents", input, "Searched your documents", False,
                       note="no query given")
    result = search_mod.search(query, limit=6, allowed_document_ids=scope)
    hits = result.get("hits") or []
    sources = [{
        "chunk_id": h["chunk_id"], "document_id": h["document_id"], "filename": h["filename"],
        "page_start": h["page_start"], "page_end": h["page_end"], "section": h.get("section"),
        "text": h["text"], "score": h.get("score") or 0.0,
    } for h in hits]
    return ToolRun("search_documents", input, "Searched your documents", True, sources)


def run_read_document(input: dict, *, allowed_document_ids: frozenset[str]) -> ToolRun:
    document_id = str(input.get("document_id") or "")
    doc = _readable(document_id, allowed_document_ids=allowed_document_ids)
    if doc is None:
        return ToolRun("read_document", input, "Read the document", False, note="not found")
    pages = input.get("pages") or None
    rows = connect().execute(
        "SELECT id, ordinal, page_start, page_end, section, text FROM chunks "
        "WHERE document_id = ? AND retrievable = 1 ORDER BY ordinal", (document_id,)).fetchall()
    headings = []
    seen = set()
    for r in rows:
        if r["section"] and r["section"] not in seen:
            seen.add(r["section"])
            headings.append(r["section"])
    if pages:
        wanted = {int(p) for p in pages}
        chosen = [r for r in rows if any(
            r["page_start"] <= p <= (r["page_end"] or r["page_start"]) for p in wanted)]
        label = f"Read pages {sorted(wanted)} of {doc['page_count'] or '?'}"
    else:
        chosen = rows[:8]
        label = f"Read the whole document · {doc['page_count'] or len(rows)} pages" \
            if len(rows) <= 8 else f"Read the first pages · {doc['page_count']} pages"
    sources = [{
        "chunk_id": r["id"], "document_id": document_id, "filename": doc["filename"],
        "page_start": r["page_start"], "page_end": r["page_end"], "section": r["section"],
        "text": r["text"], "score": 1.0,
    } for r in chosen]
    note = (f"title={_display_name(doc)!r} revision={doc.get('revision')!r} "
           f"headings={headings[:20]!r}")
    return ToolRun("read_document", input, label, True, sources, note=note)


def run_get_datasheet_fields(input: dict, *, allowed_document_ids: frozenset[str]) -> ToolRun:
    document_id = str(input.get("document_id") or "")
    doc = _readable(document_id, allowed_document_ids=allowed_document_ids)
    if doc is None:
        return ToolRun("get_datasheet_fields", input, "Read the extracted fields", False,
                       note="not found")
    facts = datasheets.list_facts(document_id, allowed_document_ids=allowed_document_ids)
    sources = [{
        "chunk_id": f.get("chunk_id") or f"fact_{f['id']}",
        "document_id": document_id, "filename": doc["filename"],
        "page_start": f["page"], "page_end": f["page"], "section": f.get("field_label"),
        "score": 1.0,
        "text": f"{f.get('field_label') or f.get('field_name')}: "
                f"{f.get('raw_value') or f.get('field_value') or '(blank)'} "
                f"{f.get('raw_unit') or f.get('unit') or ''}".strip(),
    } for f in facts if not f.get("is_blank") and f.get("page") is not None]
    return ToolRun("get_datasheet_fields", input, "Read the extracted fields", True, sources,
                  note=f"{len(sources)} of {len(facts)} fields have a value")


def run_list_cited_standards(input: dict, *, allowed_document_ids: frozenset[str]) -> ToolRun:
    document_id = str(input.get("document_id") or "")
    doc = _readable(document_id, allowed_document_ids=allowed_document_ids)
    if doc is None:
        return ToolRun("list_cited_standards", input, "Checked cited standards", False,
                       note="not found")
    rows = connect().execute(
        "SELECT text FROM chunks WHERE document_id = ? AND retrievable = 1", (document_id,)
    ).fetchall()
    text = " ".join((r["text"] or "") for r in rows)
    cited = datasheets.referenced_standards(text)
    library = standards.list_standards(allowed_document_ids=allowed_document_ids,
                                       include_superseded=True)
    matched = applicability._match_referenced(library, cited)
    held, missing = [], []
    for identifier in cited:
        key = applicability.normalise_identifier(identifier)
        entry = matched.get(key)
        if entry:
            held.append({"identifier": identifier, "held": True,
                        "standard_document_id": entry.get("id"), "filename": entry.get("filename")})
        else:
            missing.append({"identifier": identifier, "held": False})
    lines = [f"{h['identifier']}: held ({h['filename']})" for h in held]
    lines += [f"{m['identifier']}: cited but not held in this library" for m in missing]
    return ToolRun("list_cited_standards", input, "Checked cited standards", True,
                  note="\n".join(lines) or "no standards cited")


def run_look_at_page(input: dict, *, allowed_document_ids: frozenset[str],
                     pages_used: list) -> tuple[ToolRun, object | None]:
    """Returns (ToolRun, PageImage|None). The image rides back to the caller
    so it can be embedded in the tool_result Claude actually sees; the
    ToolRun's `sources_added` carries the SAME entry text-only, for
    "How I got this" and for `verify_claims` (an image citation is labelled
    differently there - see `chat_claude_first.CITED_FROM_IMAGE`)."""
    from . import vision_reader
    from .config import settings

    document_id = str(input.get("document_id") or "")
    page_no = input.get("page")
    doc = _readable(document_id, allowed_document_ids=allowed_document_ids)
    if doc is None or not isinstance(page_no, int) or page_no < 1:
        return ToolRun("look_at_page", input, "Looked at a page", False, note="not found"), None
    if len(pages_used) >= settings.chat_vision_max_pages_per_answer:
        return ToolRun("look_at_page", input, "Looked at a page", False,
                       note=f"page limit reached ({settings.chat_vision_max_pages_per_answer} "
                            "per answer)"), None
    try:
        import pymupdf
        with pymupdf.open(doc["stored_path"]) as pdf:
            if not (1 <= page_no <= pdf.page_count):
                return ToolRun("look_at_page", input, "Looked at a page", False,
                               note="page out of range"), None
            image = vision_reader.render(pdf[page_no - 1])
    except Exception as exc:  # noqa: BLE001 - a page that cannot render is reported, not raised
        return ToolRun("look_at_page", input, "Looked at a page", False,
                       note=f"could not render this page: {type(exc).__name__}"), None
    pages_used.append((document_id, page_no))
    text_rows = connect().execute(
        "SELECT text FROM chunks WHERE document_id = ? AND retrievable = 1 "
        "AND page_start <= ? AND page_end >= ? ORDER BY ordinal",
        (document_id, page_no, page_no)).fetchall()
    real_text = " ".join(r["text"] for r in text_rows if r["text"]).strip() or None
    source = {"chunk_id": f"image_{document_id}_{page_no}", "document_id": document_id,
             "filename": doc["filename"],
             "page_start": page_no, "page_end": page_no, "section": "(image)",
             "text": real_text or f"[page {page_no} of {_display_name(doc)}, read from image - "
                                  "no text layer, describe what you see]",
             "read_from_image": True, "has_text_layer": bool(real_text), "score": 1.0}
    return ToolRun("look_at_page", input, f"Looked at page {page_no}", True, [source]), image


def dispatch(name: str, input: dict, *, allowed_document_ids: frozenset[str],
             pages_used: list) -> tuple[ToolRun, object | None]:
    """One tool call, permission-checked, to (ToolRun, image|None)."""
    if name == "search_documents":
        return run_search_documents(input, allowed_document_ids=allowed_document_ids), None
    if name == "read_document":
        return run_read_document(input, allowed_document_ids=allowed_document_ids), None
    if name == "get_datasheet_fields":
        return run_get_datasheet_fields(input, allowed_document_ids=allowed_document_ids), None
    if name == "list_cited_standards":
        return run_list_cited_standards(input, allowed_document_ids=allowed_document_ids), None
    if name == "web_search":
        raise ConsentRequired(str(input.get("query") or ""))
    if name == "look_at_page":
        return run_look_at_page(input, allowed_document_ids=allowed_document_ids,
                               pages_used=pages_used)
    return ToolRun(name, input, "Used a tool", False, note="unknown tool"), None
