/**
 * THE ONE HOME OF A CONFIRM REQUEST (builder C, 26 Nov 2026): what "Save metadata" sends to confirm a document's classification. The
 * Documents screen's editor sends it with the engineer's edits; the query page's "Confirm source document" sends it with the values
 * already recorded, unchanged (the same action, reached in place: F's click count, a 5-click round trip per source document).
 */
import type { DocumentClassification, DocumentRole } from "../../types/api";

/** The free-text fields, in the order an engineer reads them off a title block. */
export const TEXT_FIELDS = [
  ["title", "Title"],
  ["document_number", "Document number"],
  ["revision", "Revision"],
  ["effective_date", "Effective date"],
  ["project", "Project"],
  ["contractor_vendor", "Contractor or vendor"],
  ["equipment_type", "Equipment type"],
  ["service", "Service"],
  ["transmittal_number", "Transmittal number"],
] as const;

export interface MetadataEdits {
  role: DocumentRole | "";
  text: Record<string, string>;
  tags: string;
}

/** The recorded values as the editor shows them (its starting state). */
export function editsOf(record: DocumentClassification | null | undefined): MetadataEdits {
  const text: Record<string, string> = {};
  for (const [field] of TEXT_FIELDS) text[field] = (record?.[field as keyof DocumentClassification] as string | null) ?? "";
  return { role: (record?.document_role as DocumentRole | undefined) ?? "", text, tags: (record?.equipment_tags ?? []).join(", ") };
}

/** The body of the confirm request. Blank means CLEARED, so an empty string is sent as null rather than as "" (a "" in the column would
 *  be a value that renders as nothing and sorts as something - a third state nobody asked for). */
export function confirmBody(record: DocumentClassification | null | undefined, edits: MetadataEdits = editsOf(record)): Record<string, unknown> {
  const body: Record<string, unknown> = {
    doc_type: record?.doc_type ?? null,
    discipline: record?.discipline ?? null,
    doc_class: record?.doc_class ?? null,
    subject_ids: (record?.subjects ?? []).map((s) => s.id),
    document_role: edits.role === "" ? null : edits.role,
    equipment_tags: edits.tags.split(",").map((t) => t.trim()).filter(Boolean),
  };
  for (const [field] of TEXT_FIELDS) body[field] = edits.text[field]?.trim() ? edits.text[field].trim() : null;
  return body;
}
