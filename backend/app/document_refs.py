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
  holds_document_text  The row stays and holds text taken from the document
                       (a passage, a filename, a quote). Whether a delete must
                       also erase that text is an OWNER DECISION that has not
                       been made, so it is listed here and left alone. When the
                       owner decides, this is the list to change.

Nothing here deletes anything. It only states, and the test enforces it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

FK_CASCADE = "fk_cascade"
FK_SET_NULL = "fk_set_null"
DELETED_BY_ROUTE = "deleted_by_route"
KEPT = "kept_by_design"
HOLDS_TEXT = "holds_document_text"

DISPOSITIONS = frozenset({FK_CASCADE, FK_SET_NULL, DELETED_BY_ROUTE, KEPT, HOLDS_TEXT})

#: (table, column) -> (disposition, reason)
REGISTRY: dict[tuple[str, str], tuple[str, str]] = {
    # ---- removed with the document by the foreign key -------------------
    ("chunk_vectors", "document_id"): (FK_CASCADE, "derived from the document's chunks"),
    ("chunks", "document_id"): (FK_CASCADE, "the document's own text"),
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

    # ---- rows that hold text taken from a document: owner decision ------
    ("messages", "text"): (
        HOLDS_TEXT, "chat answers can quote document passages"),
    ("messages", "payload"): (
        HOLDS_TEXT, "chat answer payload can carry passages and citations"),
    ("reports", "snapshot_json"): (
        HOLDS_TEXT, "report snapshot can carry cited passage text"),
    ("report_documents", "filename"): (
        HOLDS_TEXT, "the filename of the document, copied at report time"),
    ("watch_events", "filename"): (
        HOLDS_TEXT, "the filename seen by the folder watcher"),
    ("crs_comment_numbers", "document_name"): (
        HOLDS_TEXT, "a document name copied beside the comment number"),
    ("canonical_field_names", "quote"): (
        HOLDS_TEXT, "a quote from the document that justified a field name"),
}

#: Columns that name a document. The test finds these by name in the full
#: schema; anything it finds that is not in REGISTRY fails the build.
REFERENCE_COLUMN_PATTERN = r"(^|_)document_ids?$"

#: Tables that are the document itself, not a reference to it.
NOT_REFERENCES = frozenset({"documents"})

#: Files, not rows. `reports.on_document_deleted` unlinks report files and
#: the page-image cache and stored PDF are removed by the route. The review
#: PDF written under `<data_dir>/review_reports` is NOT removed by a delete;
#: whether it should be is the same owner decision as `holds_document_text`.


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
