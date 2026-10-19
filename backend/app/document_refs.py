"""W1: the registry of everything that points at a document, and what a delete does.

`DELETE /api/documents/{id}` used to rely on whoever wrote each table having
remembered it. Tables added later (reports, deliverables, field names, chat
filing, acquisitions) each made their own choice, and nothing checked that a
choice had been made. A new table with a `document_id` column was invisible to
the delete route.

This module is the one list. Every column that names a document, and every
column known to hold text taken from a document, has a row here with a
disposition and a reason. `tests/test_w1_document_refs_registry.py` builds the
full schema, finds every such column, and fails if one is missing from this
list or if a declared foreign-key action no longer matches the database.

Dispositions:

  fk_cascade           The foreign key deletes the row with the document.
  deleted_by_route     No foreign key exists (a virtual table), so the delete
                       route removes the rows itself.
  fk_set_null          The row stays, its document link becomes NULL. Access
                       code must not read NULL as "visible to everyone"
                       (`deliverables.org_wide` is the explicit flag for that).
  kept_by_design      The row stays on purpose. Holds ids or counts only, and
                       the reason says why it must outlive the document.
  erased_on_delete     The row stays and its text taken from the document
                       (a passage, an answer quoting it, a filename) is
                       replaced by `ERASED` inside the delete's transaction
                       (`erase_document_text`, #436; owner decision 8 Oct).
  holds_document_text  The row stays and still holds text taken from the
                       document. Listed so it is not forgotten; each one names
                       the issue that decides it.

Nothing here deletes a row. `erase_document_text` rewrites text in place.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

FK_CASCADE = "fk_cascade"
FK_SET_NULL = "fk_set_null"
DELETED_BY_ROUTE = "deleted_by_route"
KEPT = "kept_by_design"
HOLDS_TEXT = "holds_document_text"
ERASED_ON_DELETE = "erased_on_delete"

DISPOSITIONS = frozenset({FK_CASCADE, FK_SET_NULL, DELETED_BY_ROUTE, KEPT, HOLDS_TEXT,
                          ERASED_ON_DELETE})

#: What erased text reads as. Says what happened, names nothing.
ERASED = "[removed: the document was deleted]"

#: (table, column) -> (disposition, reason)
REGISTRY: dict[tuple[str, str], tuple[str, str]] = {
    # ---- removed with the document by the foreign key -------------------
    ("chunk_vectors", "document_id"): (FK_CASCADE, "derived from the document's chunks"),
    ("chunks", "document_id"): (FK_CASCADE, "the document's own text"),
    ("company_standard_confirmations", "document_id"): (
        FK_CASCADE,
        "an administrator's confirmation of this Company standard (#620)",
    ),
    ("document_classification", "document_id"): (FK_CASCADE, "metadata about this document"),
    ("document_kinds", "document_id"): (FK_CASCADE, "the document-type router's suggestion or a person's confirmed kind"),
    ("document_role_access", "document_id"): (FK_CASCADE, "grants on a document that is gone"),
    ("document_subjects", "document_id"): (FK_CASCADE, "metadata about this document"),
    ("exclusions", "document_id"): (FK_CASCADE, "records of this document's dropped text"),
    ("jobs", "document_id"): (FK_CASCADE, "processing state of this document"),
    ("page_ledger", "document_id"): (FK_CASCADE, "per-page account of this document"),
    ("page_ocr", "document_id"): (FK_CASCADE, "OCR text of this document"),
    ("pages", "document_id"): (FK_CASCADE, "the document's own pages"),
    ("review_runs", "submittal_document_id"): (
        FK_CASCADE, "reviews of this submittal; the delete is refused by "
                    "orphan_guard unless the caller acknowledges the loss"),
    ("submittal_facts", "submittal_document_id"): (
        FK_CASCADE, "facts read from this submittal"),
    ("review_findings", "document_id"): (
        FK_CASCADE, "findings about this submittal; guarded by "
                    "orphan_guard.check_submittal_delete"),
    ("standard_requirements", "standard_document_id"): (
        FK_CASCADE, "requirements of this standard; guarded by orphan_guard.check"),
    ("standard_scope_records", "standard_document_id"): (
        FK_CASCADE, "scope reading of this standard"),
    ("review_applicable_standards", "standard_document_id"): (
        FK_CASCADE, "applicability choice naming this standard"),
    ("applicability_scope_decision_cache", "standard_document_id"): (
        FK_CASCADE, "cache of decisions about this standard"),

    # ---- removed by the delete route itself ------------------------------
    ("chunks_fts", "document_id"): (
        DELETED_BY_ROUTE, "keyword index rows; a virtual table has no foreign key"),

    # ---- row stays, link becomes NULL -----------------------------------
    ("conversations", "document_id"): (
        FK_SET_NULL, "a chat is not deleted because a document was"),
    ("deliverables", "document_id"): (
        FK_SET_NULL, "the register entry outlives the file; org_wide stays 0, "
                     "so the row is not shown to everyone"),
    ("review_findings", "baseline_document_id"): (
        FK_SET_NULL, "a finding keeps existing if its comparison baseline goes"),

    # ---- kept on purpose, ids or counts only ----------------------------
    ("review_findings", "standard_document_id"): (
        KEPT, "id of the standard a finding cited; the finding is the CRS record"),
    ("chat_filed_comments", "document_id"): (
        KEPT, "id only; record that a chat answer was filed as a comment"),
    ("crs_comment_numbers", "first_document_id"): (
        KEPT, "id only; comment numbers are never reused (CRS rule)"),
    ("deliverable_expectations", "source_document_id"): (
        KEPT, "id only; where an expectation was inferred from"),
    ("document_provenance", "document_id"): (
        KEPT, "record of where a standard was obtained; no document text"),
    ("reports", "scope_document_ids"): (
        KEPT, "ids only; the record that a report was issued must survive"),
    ("report_documents", "document_id"): (
        KEPT, "id only; the record of which documents a report covered"),
    ("risks", "document_id"): (
        KEPT, "id only; hidden from non-admin lists because the document is "
              "in nobody's scope any more"),
    ("stage_runs", "document_id"): (KEPT, "id and timing only; a speed log"),
    ("standard_acquisitions", "obtained_document_id"): (
        KEPT, "id only; the record that a standard was obtained"),
    ("vector_generation", "document_id"): (
        KEPT, "a random cache token; triggers rewrite it, holds no content"),
    ("watch_events", "document_id"): (
        KEPT, "id only; the intake log row stays"),
    ("crs_document_scope", "document_id"): (
        KEPT, "id and a scope key; numbering scopes must not be reused. "
              "NOT CHECKED: whether its `label` can carry a document name"),

    # ---- text taken from a document, erased by the delete (#436) ---------
    ("messages", "text"): (
        ERASED_ON_DELETE, "an answer citing the document is replaced; its filename "
                          "is removed from every other message"),
    ("messages", "payload"): (
        ERASED_ON_DELETE, "every passage or citation of the document loses its text "
                          "and filename; ids and page numbers stay"),
    ("reports", "snapshot_json"): (
        ERASED_ON_DELETE, "the snapshot is redacted the same way and its hash "
                          "recomputed; an audit row holds the old and new hash"),
    ("report_documents", "filename"): (
        ERASED_ON_DELETE, "the filename copied at report time; the row stays as the "
                          "record of what the report covered"),
    ("watch_events", "filename"): (
        ERASED_ON_DELETE, "the filename seen by the folder watcher; the intake row stays"),

    # ---- rows that still hold text taken from a document -----------------
    ("crs_comment_numbers", "document_name"): (
        HOLDS_TEXT, "a document name copied beside the comment number; CRS output "
                    "is the review path, left to s2 (#436 lane note)"),
    # #437: removed by the delete route (`field_naming.forget_document`), so a
    # quote no longer outlives its document. Its own section because it is a
    # side table with no foreign key, like the keyword rows.
    ("canonical_field_names", "quote"): (
        DELETED_BY_ROUTE, "a quote from the document that justified a field name;"
        " the delete route removes the rows drawn from the document (#437)"),
}

#: Columns that name a document. The test finds these by name in the full
#: schema; anything it finds that is not in REGISTRY fails the build.
REFERENCE_COLUMN_PATTERN = r"(^|_)document_ids?$"

#: Tables that are the document itself, not a reference to it.
NOT_REFERENCES = frozenset({"documents"})

#: Files, not rows. `reports.on_document_deleted` unlinks report files and
#: the page-image cache and stored PDF are removed by the route. The review
#: PDFs under `<data_dir>/review_reports` are removed by the route too (#437,
#: `review.remove_report_files`) - those rendered since the file name carries
#: the document id; older files cannot be tied to a document and stay until
#: the owner clears them. A deleted STANDARD also takes the review PDFs of the
#: submittals whose findings cite it (#1053, `review.submittals_citing`): they
#: print its requirement wording. `canonical_field_names.quote` rows drawn from the
#: document go with it (`field_naming.forget_document`).


def _scrub(value, document_id: str, filename: str):
    """`value` with the document's text gone: in every object whose
    `document_id` is this document, every string except the ids becomes
    `ERASED` (numbers such as page numbers stay); anywhere else, the
    filename is cut out of strings."""
    if isinstance(value, dict):
        if value.get("document_id") == document_id:
            return {k: (v if k in ("document_id", "chunk_id")
                        else _erase_all(v)) for k, v in value.items()}
        return {k: _scrub(v, document_id, filename) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, document_id, filename) for v in value]
    if isinstance(value, str) and filename and filename in value:
        return value.replace(filename, ERASED)
    return value


def _erase_all(value):
    if isinstance(value, str):
        return ERASED
    if isinstance(value, dict):
        return {k: _erase_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_erase_all(v) for v in value]
    return value


def _cites(value, document_id: str) -> bool:
    if isinstance(value, dict):
        return value.get("document_id") == document_id or any(
            _cites(v, document_id) for v in value.values())
    if isinstance(value, list):
        return any(_cites(v, document_id) for v in value)
    return False


def erase_document_text(conn: sqlite3.Connection, document_id: str, filename: str, *,
                        actor: dict | None = None) -> dict[str, int]:
    """#436 (owner decision 8 Oct): erase the document's text and filename
    from the rows that outlive it. Inside the delete's transaction, so the
    document and its copies go together or not at all.

    * a chat answer whose payload cites the document is replaced by `ERASED`,
      and so is every passage of it in the payload (ids and pages stay);
    * the filename is cut out of every other message, question, conversation
      title and watched-file path;
    * each report snapshot covering it is redacted the same way, its
      `snapshot_sha256` recomputed, and one `report.redacted` audit row
      records the old and new hash; the report row stays;
    * `report_documents.filename` and `watch_events.filename` become `ERASED`.

    Returns counts per kind of row changed.
    """
    import json

    from . import reports  # the snapshot's canonical form and hash have one home

    counts = {"erased_messages": 0, "erased_reports": 0, "erased_filenames": 0}
    like = f"%{document_id}%"
    for row in conn.execute(
            "SELECT id, text, payload FROM messages WHERE payload LIKE ?", (like,)).fetchall():
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
        if not _cites(payload, document_id):
            continue
        conn.execute("UPDATE messages SET text = ?, payload = ? WHERE id = ?",
                     (ERASED if row["text"] is not None else None,
                      json.dumps(_scrub(payload, document_id, filename)), row["id"]))
        counts["erased_messages"] += 1
    if filename:
        # A filename typed into a question, a conversation title made from
        # it, or a watched file's full path: cut out wherever it appears.
        for table, column, key in (("messages", "text", "erased_messages"),
                                   ("messages", "resolved_question", "erased_messages"),
                                   ("conversations", "title", "erased_filenames"),
                                   ("watch_events", "source_path", "erased_filenames")):
            cur = conn.execute(
                f"UPDATE {table} SET {column} = replace({column}, ?, ?)"
                f" WHERE instr({column}, ?) > 0", (filename, ERASED, filename))
            counts[key] += cur.rowcount

    report_ids = [r[0] for r in conn.execute(
        "SELECT report_id FROM report_documents WHERE document_id = ?", (document_id,))]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for report_id in report_ids:
        row = conn.execute("SELECT snapshot_json, snapshot_sha256, question,"
                           " resolved_question FROM reports WHERE id = ?",
                           (report_id,)).fetchone()
        if row is None or not row["snapshot_json"]:
            continue
        snapshot = _scrub(json.loads(row["snapshot_json"]), document_id, filename)
        snapshot["answer"] = ERASED
        body = reports._canonical(snapshot)
        new_sha = reports._sha(body)
        conn.execute(
            "UPDATE reports SET snapshot_json = ?, snapshot_sha256 = ?,"
            " question = ?, resolved_question = ? WHERE id = ?",
            (body.decode("utf-8"), new_sha,
             _scrub(row["question"], document_id, filename),
             _scrub(row["resolved_question"], document_id, filename), report_id))
        conn.execute(
            """INSERT INTO audit_events
                   (at, actor_user_id, actor_username, action,
                    resource_type, resource_id, outcome, detail)
               VALUES (?, ?, ?, 'report.redacted', 'report', ?, 'ok', ?)""",
            (now, (actor or {}).get("id"),
             ((actor or {}).get("email") or "unauthenticated")[:200], report_id,
             f"document {document_id} deleted; snapshot_sha256 "
             f"old={row['snapshot_sha256']} new={new_sha}"))
        counts["erased_reports"] += 1

    for table in ("report_documents", "watch_events"):
        cur = conn.execute(f"UPDATE {table} SET filename = ? WHERE document_id = ?",
                           (ERASED, document_id))
        counts["erased_filenames"] += cur.rowcount
    return counts


def record_document_deleted(conn: sqlite3.Connection, document_id: str,
                            rows_removed: dict[str, int], *,
                            actor: dict | None = None) -> None:
    """One audit row for a delete, written inside the delete's transaction.

    The row and the delete commit together or not at all, so a deleted document
    always has a record and a record never describes a delete that did not
    happen. Ids and counts only: never a filename, never document text,
    because the audit table is the one most likely to be exported.
    """
    counts = " ".join(f"{t}={n}" for t, n in sorted(rows_removed.items()))
    conn.execute(
        """INSERT INTO audit_events
               (at, actor_user_id, actor_username, action,
                resource_type, resource_id, outcome, detail)
           VALUES (?, ?, ?, 'document.deleted', 'document', ?, 'ok', ?)""",
        (datetime.now(UTC).isoformat(timespec="seconds"),
         (actor or {}).get("id"),
         ((actor or {}).get("email") or "unauthenticated")[:200],
         document_id, f"rows_removed: {counts}"))


def forget_quotes(conn: sqlite3.Connection, document_id: str) -> int:
    """#437: the `canonical_field_names.quote` rows drawn from this document
    go with it (the registry files the column as DELETED_BY_ROUTE; it was the
    one text column a delete left behind). Inside the delete's transaction;
    returns the rows removed."""
    from .field_naming import forget_document
    return forget_document(conn, document_id)


def submittals_citing(standard_document_id: str) -> list[str]:
    """#1053: the submittals whose findings cite this standard. Their review
    PDFs print the standard's requirement wording (`review.render_report`), so
    when the standard is deleted those files go too - the quote must not
    outlive the document. Read BEFORE the delete: the cascade nulls the
    citation. A library that never ran a review has no findings table yet; it
    cites nothing, and the delete must not fail on it."""
    from . import review
    from .db import connect
    review.ensure_schema()
    return [r[0] for r in connect().execute(
        "SELECT DISTINCT document_id FROM review_findings"
        " WHERE standard_document_id = ? AND document_id != ? ORDER BY document_id",
        (standard_document_id, standard_document_id))]


def remove_citing_report_files(standard_document_id: str) -> int:
    """#1053: delete the review PDFs of every submittal that cites this
    standard; returns how many went. The findings stay (the record survives,
    its citation nulled by the cascade) and can be exported again."""
    from . import review
    return sum(review.remove_report_files(s) for s in submittals_citing(standard_document_id))
