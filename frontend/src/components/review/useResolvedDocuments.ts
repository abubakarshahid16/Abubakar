/**
 * THE CITED DOCUMENTS, FETCHED BY ID WHEN THEY ARE NOT ALREADY IN HAND.
 *
 * A findings list carries document IDs, and the page's document list holds
 * the submittals plus whatever standards fitted in one page of results - so
 * the standard a finding cites is often missing from it. Rendering "not
 * readable" in that case states something untrue about the reader's access;
 * the honest thing is to go and get it, and to say "still loading" until
 * the answer is known.
 *
 * Shared by `FindingDetail` and `FindingsTable` (#925 item 6: the table
 * grew its own per-row evidence view and needed the same resolution this
 * hook already did once) - extracted rather than duplicated, CLAUDE.md
 * rule 2. Behaviour is unchanged from the code this replaces in
 * `FindingDetail.tsx`.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { DocumentRecord } from "../../types/api";

export function useResolvedDocuments(
  standardId: string | null, submittalId: string | null, documents: DocumentRecord[],
) {
  const [fetched, setFetched] = useState<Record<string, DocumentRecord | null>>({});

  useEffect(() => {
    for (const id of [standardId, submittalId]) {
      if (!id) continue;
      if (documents.some((d) => d.id === id)) continue;
      if (id in fetched) continue;
      setFetched((current) => ({ ...current, [id]: null }));
      void api.document(id).then((result) => {
        setFetched((current) => ({
          ...current, [id]: result.ok ? result.data : null,
        }));
      });
    }
  }, [standardId, submittalId, documents, fetched]);

  const find = (id: string | null) =>
    (id ? documents.find((d) => d.id === id) ?? fetched[id] ?? null : null);

  return { standard: find(standardId), submittal: find(submittalId) };
}
