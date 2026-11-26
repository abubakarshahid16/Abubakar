/**
 * What SORT of document this is, as the document-type router read it (W5b-02).
 *
 * Three honest states (CLAUDE.md rule 4, "a guess is shown as a guess"):
 *   - confirmed: a person agreed. Plain chip.
 *   - suggested: the router's guess. Amber, with a question mark, "guessed".
 *   - needs_engineer: the router could NOT tell. No kind is shown; the card says
 *     so and asks. It is never rendered as a default type.
 * Not routed (absent or null state) renders nothing at all.
 *
 * The picker appears only for an admin: the confirm route 404s everyone else,
 * and a control that always 404s is worse than none.
 *
 * A pick is never silent (order 14, G2): while the save is on its way the card says "Saving the type...", and when the save
 * fails the card says so next to the picker (the caller's `onConfirm` resolves to the problem in words, or null when saved).
 * The old card went straight back to "Choose kind" and told the page-top notice, which a reader far down a long list never saw.
 */
import { useEffect, useRef, useState } from "react";

import { keepScroll } from "../keepScroll";

import type { DocumentClassification, DocumentKindOption } from "../types/api";
import { DocumentRoleChip } from "./DocumentRoleChip";

export function DocumentKindChip({
  classification,
  kinds,
  isAdmin = false,
  onConfirm,
}: {
  classification?: DocumentClassification;
  kinds?: DocumentKindOption[];
  isAdmin?: boolean;
  /** Saves the kind. May return a promise of the problem in words (shown here), or null when it was saved. */
  onConfirm?: (kind: string) => void | string | null | Promise<string | null | void>;
}) {
  const [changing, setChanging] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const picker = useRef<HTMLSelectElement>(null);
  // The picker takes the focus the "Choose kind" button had, without moving the page (a button that disappears under the pointer
  // otherwise drops focus to the top of the document).
  useEffect(() => {
    if (changing) picker.current?.focus({ preventScroll: true });
  }, [changing]);

  async function save(kind: string) {
    setProblem(null);
    setSaving(true);
    let said: string | null | void = null;
    try {
      said = await onConfirm?.(kind);
    } catch {
      said = "The type could not be saved. Try again.";
    }
    setSaving(false);
    if (said) {
      setProblem(said);
      setChanging(true); // the picker comes back: nothing was saved
    }
  }
  const state = classification?.document_kind_state ?? null;
  if (!classification || state === null) return null;
  const kind = classification.document_kind ?? null;
  const label = kinds?.find((k) => k.id === kind)?.label ?? kind;

  let chip;
  if (state === "confirmed" && kind) {
    chip = (
      <span data-testid="kind-chip" className="rounded-[var(--radius-xs)] bg-ink-700 px-2 py-0.5 text-xs text-slateish-300">
        {label}
      </span>
    );
  } else if (state === "suggested" && kind) {
    chip = (
      <span
        data-testid="kind-chip"
        className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-2 py-0.5 text-xs text-warn-500"
        title={classification.document_kind_evidence?.reason ?? "Suggested by the document-type router, not yet confirmed."}
      >
        {`${label}? · guessed, not confirmed`}
      </span>
    );
  } else {
    chip = (
      <span
        data-testid="kind-chip"
        className="rounded-[var(--radius-xs)] border border-ink-600 px-2 py-0.5 text-xs text-slateish-400"
        title={classification.document_kind_evidence?.reason ?? "The app could not tell what type of document this is."}
      >
        Type unclear, engineer to choose
      </span>
    );
  }

  const canPick = isAdmin && !!onConfirm && !!kinds && kinds.length > 0;
  return (
    <>
      {chip}
      {saving && <span role="status" data-testid="kind-saving" className="text-xs text-slateish-400">Saving the type...</span>}
      {problem && <span role="alert" data-testid="kind-problem" className="text-xs text-danger-500">{problem}</span>}
      {canPick && !saving && state !== "confirmed" && !changing && (
        <button
          type="button"
          className="text-xs text-signal-400 underline"
          onClick={(e) => {
            const from = e.currentTarget;
            if (state === "suggested" && kind) void save(kind);
            else keepScroll(from, () => setChanging(true));
          }}
        >
          {state === "suggested" && kind ? "Confirm type" : "Choose type"}
        </button>
      )}
      {canPick && !saving && (state === "suggested" || state === "confirmed") && !changing && (
        <button type="button" className="text-xs text-slateish-400 underline" onClick={(e) => keepScroll(e.currentTarget, () => setChanging(true))}>
          Change type
        </button>
      )}
      {canPick && changing && !saving && (
        <select
          ref={picker}
          aria-label="Document type"
          className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-800 px-1 py-0.5 text-xs"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) {
              setChanging(false);
              void save(e.target.value);
            }
          }}
        >
          <option value="" disabled>
            Pick a type
          </option>
          {kinds?.map((k) => (
            <option key={k.id} value={k.id}>
              {k.label}
            </option>
          ))}
        </select>
      )}
      {/* Order 14 lane E: the suggested role (nothing when its switch is off or the document has a role). */}
      <DocumentRoleChip classification={classification} isAdmin={isAdmin} />
    </>
  );
}
