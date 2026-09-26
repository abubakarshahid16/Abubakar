"""What an answer says about itself, in the words the Chat screen shows.

OWNER ORDER 2026-09-26 (chat redesign, section 2f): every assistant turn
carries - additively; every older field stays - what kind of answer it is, the
one grey line saying what was used and how long it took, its sources as
numbered chips, how many of its points were found on the page, the steps it
went through, and which engine wrote it at what cost.

EVERY FIELD IS DERIVED FROM WHAT HAPPENED, never asserted. The used-line names
the documents the answer actually drew on, counted by their recorded role (a
role not recorded is counted as a document, never guessed). `verification` is
reported only where it is literally true: a verbatim quotation IS on its page,
so an extract answer's points are its passages; generated prose gets a count
only once its claims are checked against the page, and until then it gets
none - a count of citation numbers that exist is not a count of points found.

No document TEXT is added here: sources carry ids, names, pages and clauses,
all of which the passages already hold, so `chat.referenced_document_ids`
withholds a turn exactly as before when access is revoked.
"""
from __future__ import annotations

from pathlib import PurePath

from .db import connect

DOCUMENT = "document"
GENERAL = "general"
WEB = "web"
MIXED = "mixed"
REWRITE = "rewrite"
ACTION = "action"
RECORDS = "records"
ANSWER_KINDS = (GENERAL, DOCUMENT, WEB, MIXED, REWRITE, ACTION, RECORDS)

_SUBMITTAL = "CONTRACTOR_SUBMITTAL"
_STANDARD = "COMPANY_STANDARD"


def _seconds(value) -> str:
    try:
        s = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{s:.0f} s" if s >= 1 else "under 1 s"


def _roles(document_ids: list[str]) -> dict[str, dict]:
    if not document_ids:
        return {}
    marks = ",".join("?" * len(document_ids))
    rows = connect().execute(
        f"""SELECT d.id, d.filename, c.document_role, c.document_number, c.title
            FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id
            WHERE d.id IN ({marks})""", list(document_ids)).fetchall()
    return {r["id"]: dict(r) for r in rows}


def display_name(meta: dict) -> str:
    """The document's recorded title, else its filename without the extension."""
    title = (meta.get("title") or "").strip()
    if title:
        return title
    return PurePath(meta.get("filename") or "document").stem


def _what_was_checked(document_ids: list[str], meta: dict[str, dict]) -> str:
    submittals = sum(1 for d in document_ids if (meta.get(d) or {}).get("document_role") == _SUBMITTAL)
    standards = sum(1 for d in document_ids if (meta.get(d) or {}).get("document_role") == _STANDARD)
    other = len(document_ids) - submittals - standards
    parts = []
    if submittals:
        parts.append("your submittal" if submittals == 1 else f"{submittals} submittals")
    if standards:
        parts.append("1 standard" if standards == 1 else f"{standards} standards")
    if other:
        parts.append(("1 document" if other == 1 else f"{other} documents")
                     if parts else ("your document" if other == 1 else f"{other} documents"))
    if not parts:
        return "your documents"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _answer_passages(result: dict) -> list[dict]:
    """The passages the answer USED, in the order its source numbers refer to."""
    kind = result.get("answer_type")
    if kind == "generated":
        return list(result.get("passages") or [])
    if kind == "extract":
        return list(result.get("answer_passages") or
                    ([result["passage"]] if result.get("passage") else []))
    return []


def sources(result: dict) -> list[dict]:
    """Numbered source chips. For generated prose the numbers are the [S#]
    the model cited against; for a quotation, the passages quoted."""
    used = _answer_passages(result)
    if not used:
        return []
    meta = _roles(sorted({p["document_id"] for p in used}))
    cited = set(result.get("cited") or [])
    out = []
    for n, p in enumerate(used, start=1):
        m = meta.get(p["document_id"], {})
        out.append({
            "n": n,
            "kind": DOCUMENT,
            "document_id": p["document_id"],
            "display_name": display_name({**m, "filename": m.get("filename") or p.get("filename")}),
            "document_number": m.get("document_number"),
            "page": p.get("page_start"),
            "page_end": p.get("page_end"),
            "clause": p.get("section"),
            "text_source": p.get("text_source"),
            "ocr_min_conf": p.get("ocr_min_conf"),
            "url": None,
            # extract: every quoted passage is the answer; generated: the ones
            # the model actually cited, the rest were supplied and left unused
            "cited": result.get("answer_type") == "extract" or n in cited,
            # Claude lane: the exact words each verified point stood on
            "quotes": [c["quote"] for c in (result.get("claims") or []) if c.get("n") == n],
            "rows": [],
        })
    return out


def verification(result: dict) -> dict | None:
    """{verified, total} only where it is literally true - see module doc.
    Generated prose carries one only when its claims were quote-checked
    (`answer.verify_claims`, the Claude lane)."""
    if result.get("verification") is not None:
        return result["verification"]
    if result.get("answer_type") == "extract":
        n = len(_answer_passages(result))
        return {"verified": n, "total": n, "method": "verbatim quotation"} if n else None
    return None


def steps(result: dict) -> list[dict]:
    """What the answer went through, in plain words, as it actually happened."""
    kind = result.get("answer_type")
    if kind in (None, "guidance"):
        return []
    if kind == "metadata":
        return [{"label": "Counted from your library", "count": None, "done": True}]
    out = [{"label": "Searched your documents",
            "count": result.get("candidates_considered"), "done": True}]
    if result.get("reranked"):
        out.append({"label": "Ranked the closest passages", "count": None, "done": True})
    read = len(result.get("passages") or []) or len(_answer_passages(result))
    if read:
        out.append({"label": "Read the best sources", "count": read, "done": True})
    if kind == "generated":
        out.append({"label": "Wrote the answer from them", "count": None, "done": True})
    return out


def answer_kind(result: dict) -> str:
    route = result.get("route")
    if route in (REWRITE, ACTION, RECORDS):
        return route
    if result.get("answer_type") in ("guidance", "general"):
        return GENERAL
    return DOCUMENT


def _engine(result: dict) -> str:
    return "Claude" if result.get("provider") == "claude" else "Local model"


def used_line(result: dict) -> str:
    """The one grey line above the answer: what was used, and how long it took."""
    kind = result.get("answer_type")
    route = result.get("route")
    took = _seconds(result.get("seconds"))
    tail = f" · {took}" if took else ""
    if kind == "guidance":
        return ""   # small talk needs no header
    if kind == "cancelled":
        return "Stopped" + tail
    if route == RECORDS:
        n = len(result.get("records") or [])
        return f"Searched your workflow records · {n} found" + tail
    if route == ACTION and kind in ("general", "generated"):
        return "Drafted from the previous answer" + tail
    if route == REWRITE and kind == "generated":
        return "Rewrote the answer from the same sources" + tail
    if kind == "general":
        prefix = ("General knowledge" if route == REWRITE
                  else "General knowledge, not from your documents")
        return f"{prefix} · {_engine(result)}" + tail
    if kind == "metadata":
        return "Counted from your library, not from document text" + tail
    used = _answer_passages(result)
    if used:
        ids = list(dict.fromkeys(p["document_id"] for p in used))
        line = f"Checked {_what_was_checked(ids, _roles(ids))}"
        if kind == "generated" and result.get("provider") == "claude":
            line += " · Claude"
        return line + tail
    if kind == "model_unavailable":
        return "Searched your documents · the answer model could not answer" + tail
    return "Searched your documents · nothing found that answers this" + tail


def suggestions(result: dict) -> list[str]:
    """Two or three next questions. Plain, honest, never a claim."""
    kind, route = result.get("answer_type"), result.get("route")
    if kind == "guidance":
        return list(result.get("examples") or [])[:3]
    if route in (REWRITE, ACTION, RECORDS):
        return []
    if kind in ("extract", "generated"):
        return ["Write that as a comment", "What else is missing?", "Explain simply"]
    if kind == "general":
        return ["Give me that in points", "Check against my documents"]
    return []


def draft(result: dict) -> dict | None:
    """An action answer's draft, for the reader to confirm (section 2g).
    Nothing is written anywhere until they do."""
    if result.get("route") != ACTION or not result.get("answer"):
        return None
    return {"type": "comment", "text": result["answer"], "status": "draft",
            "source_ids": [s["document_id"] for s in sources(result) if s.get("document_id")]}


def present(result: dict) -> dict:
    """The additive fields, ready to merge into the answer and its payload."""
    return {
        "answer_kind": answer_kind(result),
        "used_line": used_line(result),
        "sources": sources(result),
        "verification": verification(result),
        "steps": steps(result),
        "suggestions": suggestions(result),
        "draft": draft(result),
        "notices": list(result.get("notices") or []),
        "cost_usd": result.get("cost_usd"),
    }
