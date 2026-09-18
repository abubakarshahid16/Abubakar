/**
 * Technical metadata and processing information for one document.
 *
 * Master-plan section 7: chunks, passages, excluded pages, embeddings and the
 * internal processing detail move OFF the card and into an expandable drawer,
 * so the card can carry what an engineer reads (role, number, revision,
 * status) and this can carry what an operator reads.
 *
 * NULL RENDERS AS NOTHING. `Field` returns null for an unset value rather than
 * "Unknown", "-" or 0. Most of these fields are unset on every document
 * classified before the submittal-review workflow existed, and a dash in a
 * table is indistinguishable from a recorded one.
 *
 * COUNTS STATE THEIR BOUNDARY. `chunk_count` is retrievable chunks and
 * `chunk_count_total` is every chunk row; publishing one alone is how "19% of
 * pages vanished" stayed invisible, so they are always shown together.
 */
import type { DocumentRecord, DocumentReviewStatus } from "../types/api";
import { ROLE_OPTIONS } from "./classification/MetadataEditor";

/** The words for a derived review status. `not_reviewed` is a real answer and
 *  says so plainly - it is not an absence to be rendered as nothing. */
const REVIEW_STATUS_LABEL: Record<DocumentReviewStatus, string> = {
  not_reviewed: "Not reviewed",
  pending: "Review queued",
  running: "Review running",
  completed: "Review complete",
  failed: "Review failed",
};

function roleLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return ROLE_OPTIONS.find((r) => r.value === value)?.label ?? value;
}

/** One labelled value, or NOTHING AT ALL when it is not recorded. */
function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex flex-col">
      <dt className="text-[11px] uppercase tracking-wide opacity-60">{label}</dt>
      <dd className="text-xs">{value}</dd>
    </div>
  );
}

export function DocumentTechnicalDetails({ doc }: { doc: DocumentRecord }) {
  const recorded = [
    doc.document_role, doc.document_number, doc.title, doc.revision,
    doc.equipment_type, doc.project,
  ].some((v) => v !== null && v !== undefined && v !== "");

  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Document metadata">
        <h4 className="mb-2 text-xs font-medium opacity-80">Document metadata</h4>
        {!recorded && (
          <p className="text-xs opacity-70">
            No submittal-review metadata has been recorded for this document yet.
          </p>
        )}
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Field label="Role" value={roleLabel(doc.document_role)} />
          <Field label="Document number" value={doc.document_number} />
          <Field label="Title" value={doc.title} />
          <Field label="Revision" value={doc.revision} />
          <Field label="Equipment type" value={doc.equipment_type} />
          <Field label="Project" value={doc.project} />
        </dl>
        {doc.superseded_by && (
          // An alert, not a field: quoting a superseded revision is the
          // mistake this whole product exists to prevent.
          <p role="status" className="mt-2 text-xs text-warn-500">
            Superseded by another document. Check before quoting it.
          </p>
        )}
      </section>

      <section aria-label="Processing information">
        <h4 className="mb-2 text-xs font-medium opacity-80">Processing information</h4>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Field label="Status" value={doc.status.replace(/_/g, " ")} />
          <Field
            label="Review status"
            value={REVIEW_STATUS_LABEL[doc.review_status ?? "not_reviewed"]}
          />
          <Field label="Pages" value={doc.page_count} />
          {/* Always together - one without the other changes its meaning. */}
          <Field
            label="Chunks (retrievable / total)"
            value={`${doc.chunk_count} / ${doc.chunk_count_total}`}
          />
          <Field label="Embedded chunks" value={doc.embedded_count} />
          <Field label="Pages needing OCR" value={doc.needs_ocr_pages} />
          {/* A COUNT, never a badge: 12 of 546 is not "OCR'd". */}
          {doc.recognised_pages > 0 && doc.page_count ? (
            <Field
              label="Pages read by OCR"
              value={`${doc.recognised_pages} of ${doc.page_count}`}
            />
          ) : null}
          <Field label="Pages with lost equations" value={doc.equation_pages || null} />
          <Field label="Pages excluded" value={doc.pages_excluded || null} />
          <Field label="Uploaded" value={doc.uploaded_at} />
          <Field label="Indexed" value={doc.indexed_at} />
        </dl>

        {doc.status === "stored_not_indexed" && (
          <p className="mt-2 text-xs opacity-70">
            Stored and previewable. This file is not searchable: a template is a
            form to be filled, not a source to quote from.
          </p>
        )}
        {!!doc.pages_excluded_with_clause_headings && (
          <p role="alert" className="mt-2 text-xs text-warn-500">
            {doc.pages_excluded_with_clause_headings} excluded page(s) carried
            numbered clause headings. Real content was probably dropped.
          </p>
        )}
      </section>
    </div>
  );
}
