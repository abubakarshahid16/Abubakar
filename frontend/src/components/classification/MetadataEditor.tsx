/**
 * Edit a document's submittal-review metadata, including its ROLE.
 *
 * THE ADMIN CAPABILITY IS REQUIRED, and the backend is what enforces it
 * (`put_document_classification` takes `current_admin`). This form hides the
 * controls from a non-admin as a courtesy, never as the control: a hidden
 * button is not an authorisation decision, and the route answers 404 to a
 * non-admin whatever this component renders.
 *
 * A PUT REPLACES THE WHOLE RECORD. Every field is sent on every save,
 * including the ones left blank, because an administrator clearing a value
 * must be able to clear it - the same rule `subject_ids` already follows. That
 * is why the form is seeded from the stored record and submitted whole rather
 * than as a diff.
 *
 * NULL RENDERS AS NOTHING. An unset field is an empty input with a placeholder
 * naming what it is, never "Unknown" and never 0. Most of these are null on
 * every document classified before this workflow existed.
 */
import { useEffect, useState } from "react";

import { classification } from "../../api/client";
import type { DocumentClassification, DocumentRole } from "../../types/api";

/** The five roles, with the words an engineer uses for them.
 *
 *  The VALUE is the contract and the LABEL is for people. They are kept
 *  together here so a renamed label can never silently change what is sent. */
export const ROLE_OPTIONS: ReadonlyArray<{ value: DocumentRole; label: string }> = [
  { value: "CONTRACTOR_SUBMITTAL", label: "Contractor submittal" },
  { value: "COMPANY_STANDARD", label: "Company standard" },
  { value: "CONTRACT_DOCUMENT", label: "Contract document" },
  { value: "SUPPORTING_DOCUMENT", label: "Supporting document" },
  { value: "CRS_TEMPLATE", label: "CRS template" },
];

/** The free-text fields, in the order an engineer reads them off a title block. */
const TEXT_FIELDS = [
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

type TextField = (typeof TEXT_FIELDS)[number][0];

export interface MetadataEditorProps {
  documentId: string;
  record: DocumentClassification | null;
  /** Whether to render the controls. NOT the authorisation - see the note. */
  canEdit: boolean;
  onSaved?: (next: DocumentClassification) => void;
}

export function MetadataEditor({ documentId, record, canEdit, onSaved }: MetadataEditorProps) {
  const [role, setRole] = useState<DocumentRole | "">("");
  const [text, setText] = useState<Record<string, string>>({});
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setRole((record?.document_role as DocumentRole | undefined) ?? "");
    const seeded: Record<string, string> = {};
    for (const [field] of TEXT_FIELDS) {
      seeded[field] = (record?.[field as keyof DocumentClassification] as string | null) ?? "";
    }
    setText(seeded);
    setTags((record?.equipment_tags ?? []).join(", "));
    setSaved(false);
    setError(null);
  }, [record, documentId]);

  if (!canEdit) {
    return (
      <p className="text-xs opacity-70">
        Only an administrator can change a document&rsquo;s metadata.
      </p>
    );
  }

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    // Blank means CLEARED, so an empty string is sent as null rather than as
    // "". A "" in the column would be a value that renders as nothing and
    // sorts as something - a third state nobody asked for.
    const body: Record<string, unknown> = {
      doc_type: record?.doc_type ?? null,
      discipline: record?.discipline ?? null,
      doc_class: record?.doc_class ?? null,
      subject_ids: (record?.subjects ?? []).map((s) => s.id),
      document_role: role === "" ? null : role,
      equipment_tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
    };
    for (const [field] of TEXT_FIELDS) {
      body[field] = text[field]?.trim() ? text[field].trim() : null;
    }
    const result = await classification.confirm(documentId, body as never);
    setSaving(false);
    if (!result.ok) {
      setError(result.error.message);
      return;
    }
    setSaved(true);
    onSaved?.(result.data);
  };

  return (
    <form
      aria-label="Document metadata"
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label className="flex flex-col gap-1 text-xs">
        <span className="opacity-80">Document role</span>
        <select
          aria-label="Document role"
          value={role}
          onChange={(e) => setRole(e.target.value as DocumentRole | "")}
          className="rounded border border-white/15 bg-transparent px-2 py-1"
        >
          {/* Empty is a real choice: "not recorded". It is not a prompt to
              pick something, and choosing it CLEARS the role. */}
          <option value="">Not recorded</option>
          {ROLE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {TEXT_FIELDS.map(([field, label]) => (
          <label key={field} className="flex flex-col gap-1 text-xs">
            <span className="opacity-80">{label}</span>
            <input
              aria-label={label}
              value={text[field] ?? ""}
              placeholder="Not recorded"
              onChange={(e) =>
                setText((prev) => ({ ...prev, [field as TextField]: e.target.value }))
              }
              className="rounded border border-white/15 bg-transparent px-2 py-1"
            />
          </label>
        ))}
        <label className="flex flex-col gap-1 text-xs sm:col-span-2">
          <span className="opacity-80">Equipment tags</span>
          <input
            aria-label="Equipment tags"
            value={tags}
            placeholder="Not recorded"
            onChange={(e) => setTags(e.target.value)}
            className="rounded border border-white/15 bg-transparent px-2 py-1"
          />
          <span className="opacity-60">Separate tags with commas.</span>
        </label>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-white/15 px-3 py-1 text-xs disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save metadata"}
        </button>
        {saved && <span role="status" className="text-xs opacity-80">Saved.</span>}
        {error && <span role="alert" className="text-xs text-warn-500">{error}</span>}
      </div>
    </form>
  );
}
