"""Single-answer evidence reports, rendered from a frozen snapshot.

WHAT THIS IS, on its own face and on page 1 of every PDF: one question, the
quoted evidence, and the documents it came from, frozen at generation. It is
NOT the plan's §7.2 analysis report - no coverage ledger, no gap analysis, no
recommendation, no market findings - and the PDF names each of those as not
included in a bordered box beside the watermark. An absent section is visible
as absent; nothing is rendered empty and nothing is rendered with zeros.

THE RENDERER'S ONLY INPUT IS THE SNAPSHOT. `render()` performs no query
against `documents`, `chunks` or `pages`. Rename a document, re-ingest it,
change its timestamps - regenerating produces the same body, and `verify()`
reports the divergence as `evidence_drift` rather than silently using the new
state. That is what "regenerating an old report must not silently use newer
documents" means mechanically.

THE FILE IS CLIENT CONTENT. A report quotes documents, so reading one requires
being the owner AND still holding every cited document in scope. Owner-alone
is the `list_conversations` defect already on record. If a cited document
leaves the reader's scope the report is gone immediately and completely -
404, never 403, because a 403 confirms the report exists and which documents
it cites. The listing carries `suppressed_count` so a user can see THAT
something is hidden without seeing WHAT.

THE SPIKE (CHANGELOG, 2026-09-05) decided three things here:

  * `<thead>` does NOT repeat across page breaks in PyMuPDF Story. The
    evidence table is at most three rows and does not span; anything that
    could span is a stated limitation, not a hope.
  * Arabic goes through Story only. It shaped there (Naskh, presentation
    forms, no .notdef). `insert_textbox` and `insert_text` perform no shaping
    and produce unjoined Arabic that still looks like Arabic to a non-reader -
    the worst failure mode - so they are confined to ASCII furniture in
    `_draw_furniture`, and a test greps for it.
  * A TOC is built by hand from element positions; the PDF outline is empty.
    This report is short enough not to need one.

`report_sha256` is a hash of the PDF bytes and NOT a reproducibility hash:
PyMuPDF embeds a producer string and an ID array, so a re-render on a
different build produces a different file with identical content. Compare
`snapshot_sha256` for content; `report_sha256` proves the stored file is the
one that was issued.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

import fitz

from . import access, chat
from .config import config_version, settings
from .db import connect

TEMPLATE_VERSION = "1"
RENDERER = f"pymupdf-{fitz.VersionBind}"

#: What a single-answer evidence report does not contain, named on page 1.
NOT_INCLUDED = ["coverage ledger", "gap analysis", "recommendation",
                "public-market findings"]

APPROVAL = ("This report is generated from indexed documents by an automated "
            "system. It is not engineering advice and requires review and "
            "approval by a qualified engineer before any use.")

WATERMARK = "PROTOTYPE - NOT FOR CONSTRUCTION"


class ReportNotFound(Exception):
    pass


class NotReportable(Exception):
    """The message cannot be reported on, and the reason is client-safe."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- snapshot


def _passages_of(payload: dict, answer_type: str) -> list[dict]:
    """The evidence, in citation order, each marked as cited or not."""
    if answer_type == "extract":
        primary = payload.get("passage")
        answers = payload.get("answer_passages") or ([primary] if primary else [])
        seen = {p["chunk_id"] for p in answers}
        rest = [p for p in payload.get("supporting") or [] if p["chunk_id"] not in seen]
        return ([{**p, "cited": True} for p in answers]
                + [{**p, "cited": False} for p in rest])
    cited = set(payload.get("cited") or [])
    return [{**p, "cited": (i + 1) in cited}
            for i, p in enumerate(payload.get("passages") or [])]


def build_snapshot(message_id: str, scope: access.AccessScope) -> dict:
    """Freeze everything the renderer will ever be allowed to see.

    Raises NotReportable for a message that is not an answered assistant turn,
    and ReportNotFound when the message - or any document it cites - is outside
    the caller's scope. The same 404 for both, deliberately: "you may not see
    this" must be indistinguishable from "this does not exist".
    """
    conn = connect()
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None or row["role"] != "assistant":
        raise ReportNotFound(message_id)
    message = chat._row_to_message(row)
    if message["answer_type"] not in ("extract", "generated"):
        raise NotReportable("only an answered question can be reported on")
    payload = message["payload"] or {}

    asked = conn.execute(
        """SELECT * FROM messages WHERE conversation_id = ? AND role = 'user'
           AND ordinal < ? ORDER BY ordinal DESC LIMIT 1""",
        (message["conversation_id"], message["ordinal"]),
    ).fetchone()
    question = asked["text"] if asked else None
    resolved = (asked["resolved_question"] if asked else None) or question

    passages = _passages_of(payload, message["answer_type"])
    document_ids = sorted({p["document_id"] for p in passages})
    if not document_ids:
        raise NotReportable("the answer cites no document")
    # Every cited document must be readable NOW by the person asking for the
    # report. Filtering the passages instead would print a partial report that
    # looks whole.
    if not scope.unrestricted and any(not scope.may_read(d) for d in document_ids):
        raise ReportNotFound(message_id)

    documents = []
    for doc_id in document_ids:
        d = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if d is None:
            raise NotReportable("a cited document no longer exists")
        # Sources read off a page image are provenance the report has to keep.
        sources = {p.get("text_source") or "extracted" for p in passages
                   if p["document_id"] == doc_id}
        documents.append({
            "document_id": doc_id,
            "filename": d["filename"],
            "sha256": d["sha256"],
            "page_count": d["page_count"],
            "chunk_signature": d["chunk_signature"],
            "indexed_at": d["indexed_at"],
            # These columns do not exist. NULL, rendered as "not recorded" -
            # inventing a value would be a false record.
            "revision": None,
            "approval_status": None,
            "passages_cited": sum(1 for p in passages
                                  if p["document_id"] == doc_id and p["cited"]),
            "text_source": (sources.pop() if len(sources) == 1 else "mixed"),
        })

    return {
        "template_version": TEMPLATE_VERSION,
        "renderer": RENDERER,
        "config_version": config_version(),
        "generated_at": _now(),
        "auth_mode": settings.auth_mode,
        # null under `disabled`: there is no user, and a placeholder name on a
        # report is a false attribution
        "owner_user_id": scope.user_id,
        "scope_unrestricted": scope.unrestricted,
        "scope_document_ids": sorted(scope.allowed_document_ids),
        "conversation_id": message["conversation_id"],
        "message_id": message_id,
        "question": question,
        "resolved_question": resolved,
        "answer_type": message["answer_type"],
        "answer": message["text"],
        "reason": message["reason"],
        "passages": passages,
        "documents": documents,
        "model": payload.get("model"),
        "answer_model": settings.answer_model,
        "embed_model": getattr(settings, "embed_model_name", None),
        "retrieval_mode": payload.get("retrieval_mode"),
        "reranked": payload.get("reranked"),
        "candidates_considered": payload.get("candidates_considered"),
        "seconds": payload.get("seconds"),
        "prompt_tokens": payload.get("prompt_tokens"),
        "output_tokens": payload.get("output_tokens"),
        "truncated": bool(payload.get("truncated")),
        "evidence_removed": payload.get("evidence_removed") or [],
        "not_included": list(NOT_INCLUDED),
    }


# ------------------------------------------------------------------ render


def _esc(text) -> str:
    return html.escape("" if text is None else str(text))


def _fmt(value, unit: str = "") -> str:
    """Unmeasured is 'not measured', never 0 and never blank."""
    if value is None:
        return "not measured"
    return f"{value}{unit}"


CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #111; }
h1 { font-size: 18pt; margin-bottom: 2pt; }
h2 { font-size: 12pt; margin-top: 14pt; border-bottom: 1px solid #999; }
p { overflow-wrap: anywhere; }
.box { border: 1.5px solid #333; padding: 6pt; margin: 8pt 0; }
.approval { border: 1px solid #b45309; background: #fff7ed; padding: 6pt;
            margin: 8pt 0; font-size: 9.5pt; }
.meta { font-size: 8.5pt; color: #444; }
table { table-layout: fixed; width: 100%; border-collapse: collapse; font-size: 8.5pt; }
th, td { border: 1px solid #999; padding: 3pt; text-align: left;
         overflow-wrap: anywhere; word-break: break-all; vertical-align: top; }
th { background: #eee; }
.quote { font-family: serif; font-size: 10.5pt; border-left: 3px solid #333;
         padding-left: 8pt; margin: 6pt 0; }
.generated { font-family: sans-serif; background: #fff4e0;
             border: 1px solid #f59e0b; padding: 6pt; margin: 6pt 0; }
.provenance { font-size: 8.5pt; color: #92400e; font-style: italic; }
.label { font-size: 8pt; color: #555; text-transform: uppercase; }
.warn { border: 1px solid #f59e0b; background: #fff4e0; padding: 5pt; font-size: 9pt; }
.audit { border: 1px solid #94a3b8; background: #f8fafc; padding: 6pt; margin: 6pt 0;
         font-size: 9pt; }
.audit p { margin: 3pt 0; }
.ok { border: 1px solid #16a34a; background: #f0fdf4; padding: 5pt; font-size: 9pt; }
"""


def _passage_html(p: dict, n: int) -> str:
    where = (f"{_esc(p['filename'])}, page {p['page_start']}"
             if p.get("page_start") == p.get("page_end")
             else f"{_esc(p['filename'])}, pages {p.get('page_start')}-{p.get('page_end')}")
    section = f" · {_esc(p['section'])}" if p.get("section") else ""
    status = "cited by answer" if p.get("cited") else "supplied, not cited"
    out = [f'<p class="label">[S{n}] {where}{section} ({status})</p>']
    if (p.get("text_source") or "extracted") == "recognised":
        # ON EVERY recognised passage, never once at the top: the reader may
        # open the report at this page.
        conf = p.get("ocr_min_conf")
        viol = p.get("ocr_alphabet_violations") or 0
        line = ("Read by OCR from a scanned page - not the document's own text. "
                f"Lowest confidence {conf:.2f}." if conf is not None else
                "Read by OCR from a scanned page - not the document's own text. "
                "Confidence not recorded.")
        if viol:
            line += (f" {viol} character(s) this document cannot contain"
                     f" (sample: {_esc(p.get('ocr_alphabet_sample'))}).")
        out.append(f'<p class="provenance">{line}</p>')
    out.append(f'<p class="quote">{_esc(p.get("text"))}</p>')
    return "".join(out)


def _has_uncited_extract_evidence(s: dict) -> bool:
    return (
        s["answer_type"] == "extract"
        and any(not p.get("cited") for p in s.get("passages") or [])
    )


def _answer_citation_numbers(answer: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[S(\d+)\]", answer or "")})


def _citation_audit_html(s: dict) -> str:
    passages = s.get("passages") or []
    answer_markers = _answer_citation_numbers(s.get("answer") or "")
    cited_passages = [i for i, p in enumerate(passages, start=1) if p.get("cited")]
    supplied_count = sum(1 for p in passages if not p.get("cited"))
    valid = set(range(1, len(passages) + 1))
    missing = [n for n in answer_markers if n not in valid]

    answer_label = ", ".join(f"S{n}" for n in answer_markers) or "none"
    cited_label = ", ".join(f"S{n}" for n in cited_passages) or "none"
    status: str
    if missing:
        status = (
            '<p class="warn">Citation audit failed: the answer names missing '
            'evidence marker(s) '
            f'{_esc(", ".join("S" + str(n) for n in missing))}.</p>'
        )
    elif s["answer_type"] == "generated" and not answer_markers:
        status = (
            '<p class="warn">Citation audit failed: generated answer has no '
            'inline [S#] evidence marker.</p>'
        )
    else:
        status = (
            '<p class="ok">Citation audit passed: every inline [S#] marker '
            'resolves to evidence frozen in this report.</p>'
        )

    return (
        '<div class="audit"><b>Citation audit</b>'
        f'<p>Answer markers: {_esc(answer_label)}. '
        f'Evidence marked cited: {_esc(cited_label)}. '
        f'Supporting passages not cited by the answer: {supplied_count}.</p>'
        f'{status}</div>'
    )


def to_html(s: dict) -> str:
    who = (_esc(s["owner_user_id"]) if s["owner_user_id"]
           else "authentication disabled - no user identity recorded")
    parts = [
        "<h1>Evidence report</h1>",
        f'<p class="meta">Generated {_esc(s["generated_at"])} · generated by: {who}'
        f' · config {_esc(s["config_version"])} · template {TEMPLATE_VERSION}'
        f' · {_esc(s["renderer"])}</p>',
        # The box: what this report is, and what it is not.
        '<div class="box"><b>This is a single-answer evidence report.</b> It '
        'contains one question, the passages retrieved for it, and the documents '
        'they came from, frozen when the report was generated.<br/>'
        '<b>Not included in this report:</b> '
        + ", ".join(_esc(x) for x in s["not_included"]) + ".</div>",
        f'<div class="approval">{_esc(APPROVAL)}</div>',
        "<h2>1. Question</h2>",
        f"<p>{_esc(s['question'])}</p>",
    ]
    if s["resolved_question"] and s["resolved_question"] != s["question"]:
        parts.append(f'<p class="meta">Retrieval ran on the resolved question: '
                     f'{_esc(s["resolved_question"])}</p>')

    parts.append("<h2>2. Answer</h2>")
    parts.append(_citation_audit_html(s))
    if s["answer_type"] == "extract":
        parts.append('<p class="label">Quoted verbatim from the document</p>')
        parts.append(f'<p class="quote">{_esc(s["answer"])}</p>')
        if _has_uncited_extract_evidence(s):
            parts.append(
                '<p class="warn">This quoted answer is the cited extract only. '
                'Other matched passages are preserved in the Evidence section as '
                'supplied, not cited, and are not merged into the quoted answer.</p>'
            )
    else:
        parts.append(f'<p class="label">Generated by {_esc(s["model"] or s["answer_model"])}'
                     ' from the passages below - the model\'s words, not the document\'s</p>')
        parts.append(f'<div class="generated">{_esc(s["answer"])}</div>')
        if s["truncated"]:
            parts.append('<p class="warn">This answer reached its length limit and '
                         'stops early.</p>')
    if s["evidence_removed"]:
        items = "".join(
            f"<li>{_esc(e.get('filename'))} p{_esc(e.get('page_start'))} - "
            + ("not used at all" if e.get("action") == "dropped"
               else f"shortened, {e.get('characters_dropped')} characters left out")
            + "</li>" for e in s["evidence_removed"])
        parts.append(f'<div class="warn">Sources that did not fit the model\'s '
                     f'context window:<ul>{items}</ul></div>')

    parts.append("<h2>3. Evidence</h2>")
    for i, p in enumerate(s["passages"], start=1):
        parts.append(_passage_html(p, i))

    parts.append("<h2>4. Documents</h2>")
    rows = "".join(
        f"<tr><td>{_esc(d['filename'])}</td><td>{_esc(d['sha256'])}</td>"
        f"<td>{_fmt(d['page_count'])}</td>"
        f"<td>{'not recorded' if d['revision'] is None else _esc(d['revision'])}</td>"
        f"<td>{'not recorded' if d['approval_status'] is None else _esc(d['approval_status'])}</td>"
        f"<td>{_esc(d['text_source'])}</td></tr>"
        for d in s["documents"])
    parts.append("<table><thead><tr><th>File</th><th>SHA-256 at generation</th>"
                 "<th>Pages</th><th>Revision</th><th>Approval</th><th>Text source</th>"
                 f"</tr></thead><tbody>{rows}</tbody></table>")

    parts.append("<h2>5. How this answer was produced</h2>")
    parts.append(
        '<p class="meta">'
        f"Answer model {_esc(s['answer_model'])} · retrieval {_esc(s['retrieval_mode'])}"
        f" · reranked {_esc(s['reranked'])} · candidates {_fmt(s['candidates_considered'])}"
        f" · time {_fmt(s['seconds'], ' s')} · prompt tokens {_fmt(s['prompt_tokens'])}"
        f" · output tokens {_fmt(s['output_tokens'])}"
        f" · auth mode {_esc(s['auth_mode'])}</p>")
    # The approval sentence TWICE: once where a reader starts and once where
    # they stop.
    parts.append(f'<div class="approval">{_esc(APPROVAL)}</div>')
    return "\n".join(parts)


MEDIABOX = fitz.paper_rect("a4")
#: Room at the bottom for the footer furniture.
BODY = MEDIABOX + (40, 40, -40, -52)


def _draw_furniture(doc: fitz.Document) -> None:
    """Watermark and page numbers, on EVERY page, as an overlay.

    ASCII ONLY. These two calls are the only place `insert_text` is permitted
    in this module: it performs no Arabic shaping, so any body text through it
    would render unjoined Arabic that still looks like Arabic to a non-reader.
    """
    total = doc.page_count
    for page in doc:
        # Overlay, so it cannot sit behind body content and be cropped away.
        centre = page.rect.width / 2, page.rect.height / 2
        page.insert_text(
            fitz.Point(centre[0] - 210, centre[1] + 20), WATERMARK,
            fontsize=30, fontname="helv", color=(0.72, 0.72, 0.72),
            morph=(fitz.Point(*centre), fitz.Matrix(45)), overlay=True,
        )
        page.insert_text(
            fitz.Point(40, page.rect.height - 24),
            f"Page {page.number + 1} of {total}  |  {WATERMARK}  |  Nabaa evidence report",
            fontsize=8, fontname="helv", color=(0.3, 0.3, 0.3), overlay=True,
        )


def render(snapshot: dict) -> bytes:
    """The PDF, from the snapshot and nothing else."""
    def rectfn(rect_num, filled):
        return MEDIABOX, BODY, None

    story = fitz.Story(html=to_html(snapshot), user_css=CSS)
    doc = story.write_with_links(rectfn)
    _draw_furniture(doc)
    doc.set_metadata({
        "title": "Nabaa evidence report",
        "subject": "Single-answer evidence report - prototype, not for construction",
        "creator": "Nabaa",
    })
    try:
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


# ----------------------------------------------------------------- storage


def _report_dir() -> Path:
    return settings.data_dir / "reports"


def _path_for(sha: str) -> Path:
    # Content-addressed: no question text, no document name, no username in
    # the filename. A filename leaks past every access check into backup
    # indexes, Referer headers and browser history.
    return _report_dir() / sha[:2] / f"{sha}.pdf"


def generate(message_id: str, scope: access.AccessScope) -> dict:
    snapshot = build_snapshot(message_id, scope)
    snapshot_json = _canonical(snapshot)
    pdf = render(snapshot)
    report_sha = _sha(pdf)
    path = _path_for(report_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)

    with fitz.open("pdf", pdf) as doc:
        page_count = doc.page_count

    report_id = f"rpt_{secrets.token_hex(6)}"
    owner_username = None
    if scope.user_id:
        u = connect().execute("SELECT email FROM users WHERE id = ?",
                              (scope.user_id,)).fetchone()
        owner_username = u["email"] if u else None

    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO reports (id, created_at, message_id, conversation_id,
                   owner_user_id, owner_username, auth_mode, scope_unrestricted,
                   scope_document_ids, question, resolved_question, snapshot_json,
                   snapshot_sha256, config_version, renderer, template_version,
                   stored_path, report_sha256, size_bytes, page_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report_id, snapshot["generated_at"], message_id,
             snapshot["conversation_id"], scope.user_id, owner_username,
             settings.auth_mode, int(scope.unrestricted),
             json.dumps(snapshot["scope_document_ids"]),
             snapshot["question"], snapshot["resolved_question"],
             snapshot_json.decode("utf-8"), _sha(snapshot_json),
             snapshot["config_version"], RENDERER, TEMPLATE_VERSION,
             str(path), report_sha, len(pdf), page_count),
        )
        for d in snapshot["documents"]:
            conn.execute(
                """INSERT INTO report_documents (report_id, document_id, filename,
                       sha256, page_count, chunk_signature, indexed_at, revision,
                       approval_status, passages_cited, text_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (report_id, d["document_id"], d["filename"], d["sha256"],
                 d["page_count"], d["chunk_signature"], d["indexed_at"],
                 d["revision"], d["approval_status"], d["passages_cited"],
                 d["text_source"]),
            )
    return describe(report_id, scope)


# ------------------------------------------------------------------ access


def _visible(report_row, scope: access.AccessScope) -> bool:
    """Owner AND still authorised for every cited document."""
    if settings.auth_mode != access.AUTH_DISABLED:
        if report_row["owner_user_id"] != scope.user_id:
            return False
    if scope.unrestricted:
        return True
    cited = [r["document_id"] for r in connect().execute(
        "SELECT document_id FROM report_documents WHERE report_id = ?",
        (report_row["id"],)).fetchall()]
    return all(scope.may_read(d) for d in cited)


def _row_to_record(row) -> dict:
    docs = connect().execute(
        "SELECT * FROM report_documents WHERE report_id = ? ORDER BY filename",
        (row["id"],)).fetchall()
    return {
        "id": row["id"],
        "question": row["question"],
        "resolved_question": row["resolved_question"],
        "created_at": row["created_at"],
        "page_count": row["page_count"],
        "size_bytes": row["size_bytes"],
        "report_sha256": row["report_sha256"],
        "owner_username": row["owner_username"],
        "documents": [{
            "document_id": d["document_id"],
            "filename": d["filename"],
            "sha256_prefix": d["sha256"][:12],
            "revision": d["revision"],
            "approval_status": d["approval_status"],
            "passages_cited": d["passages_cited"],
            "text_source": d["text_source"],
        } for d in docs],
        "not_implemented_sections": list(NOT_INCLUDED),
        # stored_path is NEVER here
    }


def _require(report_id: str, scope: access.AccessScope):
    row = connect().execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if row is None or not _visible(row, scope):
        raise ReportNotFound(report_id)
    return row


def describe(report_id: str, scope: access.AccessScope) -> dict:
    return _row_to_record(_require(report_id, scope))


def list_reports(scope: access.AccessScope) -> dict:
    rows = connect().execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
    visible = [r for r in rows if _visible(r, scope)]
    owned = rows if settings.auth_mode == access.AUTH_DISABLED else [
        r for r in rows if r["owner_user_id"] == scope.user_id]
    return {
        "reports": [_row_to_record(r) for r in visible],
        # THAT something is hidden, never WHAT.
        "suppressed_count": len(owned) - len(visible),
    }


def stored_path(report_id: str, scope: access.AccessScope) -> Path:
    row = _require(report_id, scope)
    if not row["stored_path"]:
        raise ReportNotFound(report_id)
    return Path(row["stored_path"])


def verify(report_id: str, scope: access.AccessScope) -> dict:
    """Is the file the one issued, is the snapshot intact, did the evidence move?

    Drift is REPORTED, never resolved: the report keeps saying what the
    documents said when it was generated, and this says whether they still do.
    """
    row = _require(report_id, scope)
    snapshot_intact = _sha(row["snapshot_json"].encode("utf-8")) == row["snapshot_sha256"]
    path = Path(row["stored_path"]) if row["stored_path"] else None
    file_intact = bool(path and path.exists() and _sha(path.read_bytes()) == row["report_sha256"])

    drift: list[str] = []
    conn = connect()
    for d in conn.execute("SELECT * FROM report_documents WHERE report_id = ?",
                          (report_id,)).fetchall():
        live = conn.execute("SELECT * FROM documents WHERE id = ?",
                            (d["document_id"],)).fetchone()
        name = d["filename"]
        if live is None:
            drift.append(f"{name}: no longer in the corpus")
            continue
        if live["sha256"] != d["sha256"]:
            drift.append(f"{name}: file content changed")
        if live["filename"] != d["filename"]:
            drift.append(f"{name}: renamed to {live['filename']}")
        if (live["chunk_signature"] or "") != (d["chunk_signature"] or ""):
            drift.append(f"{name}: re-chunked since the report was generated")
        if (live["indexed_at"] or "") != (d["indexed_at"] or ""):
            drift.append(f"{name}: re-indexed since the report was generated")
    return {
        "report_id": report_id,
        "snapshot_intact": snapshot_intact,
        "file_intact": file_intact,
        "evidence_drift": drift,
    }


def on_document_deleted(document_id: str) -> None:
    """Unlink every report that cites the document. Keep the rows.

    The record that a report was issued survives; the file, which quotes the
    document, does not.
    """
    conn = connect()
    ids = [r["report_id"] for r in conn.execute(
        "SELECT report_id FROM report_documents WHERE document_id = ?",
        (document_id,)).fetchall()]
    for rid in ids:
        row = conn.execute("SELECT stored_path FROM reports WHERE id = ?", (rid,)).fetchone()
        if row and row["stored_path"]:
            Path(row["stored_path"]).unlink(missing_ok=True)
        with conn:
            conn.execute(
                "UPDATE reports SET stored_path = NULL, suppressed_reason = ? WHERE id = ?",
                ("a cited document was deleted", rid))
