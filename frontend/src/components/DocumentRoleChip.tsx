/**
 * One upload for the whole app (order 14 lane E): the SUGGESTED role beside the kind, "suggested, confirm or change".
 *
 * Shows nothing when the switch is off, when the document already has a role (the card shows that role), or before the
 * suggestion is known. A suggestion is never a role: only "Confirm role" or "Change role" writes one, through the existing
 * role write (administrators only; the approval rules stay the existing ones). Buttons for administrators only, as the kind chip.
 */
import { useEffect, useState } from "react";

import { classification as classificationApi } from "../api/documents";
import { ROLE_WORDS, type RoleSuggestionSwitch, roleSuggestionOf, roleSuggestionSwitch, suggestionWords } from "../api/roleSuggestion";
import type { DocumentClassification, DocumentRole } from "../types/api";

const CHOICES: DocumentRole[] = ["CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD", "CONTRACT_DOCUMENT", "SUPPORTING_DOCUMENT"];

export function DocumentRoleChip({ classification, isAdmin = false }: { classification: DocumentClassification; isAdmin?: boolean }) {
  const [sw, setSw] = useState<RoleSuggestionSwitch | null>(null);
  const [changing, setChanging] = useState(false);
  const [written, setWritten] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void roleSuggestionSwitch().then((s) => { if (live) setSw(s); });
    return () => { live = false; };
  }, []);
  if (!sw?.enabled || classification.document_role) return null;
  if (written) {
    return <span data-testid="role-suggestion-done" className="text-xs text-slateish-300">{`Role set: ${ROLE_WORDS[written] ?? written}`}</span>;
  }
  const suggestion = roleSuggestionOf(classification.document_kind_evidence);
  const write = async (role: DocumentRole) => {
    setError(null);
    const r = await classificationApi.setRoleBulk({ document_ids: [classification.document_id], document_role: role });
    const failed = r.ok && Array.isArray(r.data.failed) ? r.data.failed : [];
    if (r.ok && failed.length === 0) setWritten(role);
    else setError("The role was not set.");
  };
  return (
    <>
      <span
        data-testid="role-suggestion"
        className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-2 py-0.5 text-xs text-warn-500"
      >
        {suggestion ? suggestionWords(suggestion) : "No role suggested: choose a role."}
      </span>
      {isAdmin && suggestion?.role && !changing && (
        <button type="button" className="text-xs text-signal-400 underline" onClick={() => void write(suggestion.role as DocumentRole)}>
          Confirm role
        </button>
      )}
      {isAdmin && !changing && (
        <button type="button" className="text-xs text-slateish-400 underline" onClick={() => setChanging(true)}>
          {suggestion?.role ? "Change role" : "Choose role"}
        </button>
      )}
      {isAdmin && changing && (
        <select
          aria-label="Document role"
          className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-800 px-1 py-0.5 text-xs"
          defaultValue=""
          onChange={(e) => { if (e.target.value) { setChanging(false); void write(e.target.value as DocumentRole); } }}
        >
          <option value="" disabled>Choose a role</option>
          {CHOICES.map((c) => <option key={c} value={c}>{ROLE_WORDS[c]}</option>)}
        </select>
      )}
      {error && <span className="text-xs text-danger-500">{error}</span>}
    </>
  );
}
