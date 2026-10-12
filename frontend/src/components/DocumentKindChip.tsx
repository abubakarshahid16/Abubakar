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
 */
import { useState } from "react";

import type { DocumentClassification, DocumentKindOption } from "../types/api";

export function DocumentKindChip({
  classification,
  kinds,
  isAdmin = false,
  onConfirm,
}: {
  classification?: DocumentClassification;
  kinds?: DocumentKindOption[];
  isAdmin?: boolean;
  onConfirm?: (kind: string) => void;
}) {
  const [changing, setChanging] = useState(false);
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
        title={classification.document_kind_evidence?.reason ?? "The router could not tell what kind of document this is."}
      >
        Kind unclear, engineer to choose
      </span>
    );
  }

  const canPick = isAdmin && !!onConfirm && !!kinds && kinds.length > 0;
  return (
    <>
      {chip}
      {canPick && state !== "confirmed" && !changing && (
        <button
          type="button"
          className="text-xs text-signal-400 underline"
          onClick={() => (state === "suggested" && kind ? onConfirm?.(kind) : setChanging(true))}
        >
          {state === "suggested" && kind ? "Confirm kind" : "Choose kind"}
        </button>
      )}
      {canPick && (state === "suggested" || state === "confirmed") && !changing && (
        <button type="button" className="text-xs text-slateish-400 underline" onClick={() => setChanging(true)}>
          Change kind
        </button>
      )}
      {canPick && changing && (
        <select
          aria-label="Document kind"
          className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-800 px-1 py-0.5 text-xs"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) {
              onConfirm?.(e.target.value);
              setChanging(false);
            }
          }}
        >
          <option value="" disabled>
            Pick a kind
          </option>
          {kinds?.map((k) => (
            <option key={k.id} value={k.id}>
              {k.label}
            </option>
          ))}
        </select>
      )}
    </>
  );
}
