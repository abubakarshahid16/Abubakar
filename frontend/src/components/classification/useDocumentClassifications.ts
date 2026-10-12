/**
 * Per-document classification, read from the document list.
 *
 * `GET /api/documents` carries each document's full classification, so a page
 * load is ONE request. This used to fan out one
 * `GET /documents/{id}/classification` per document (about 100 requests on
 * every load, seen in the live app 2026-10-08). The server applies the same
 * access scope to the list as to the single route, so a caller sees the
 * classification only of documents they may read.
 *
 * What stays local: a classification this screen just confirmed or edited
 * (`setOne`) is kept until the list catches up with it. Without that, a poll
 * that was already in flight when the engineer confirmed would put the
 * pre-confirm answer back on the card.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import type { DocumentClassification, DocumentRecord } from "../../types/api";

export interface DocumentClassifications {
  /** Present when the list carried that document's classification. Absent
   *  (not `null`) otherwise - callers must not read a missing entry as
   *  "awaiting a type", which is a real answer the server gives. */
  byId: Record<string, DocumentClassification>;
  /** Patches one document's classification in place, e.g. after `confirm`
   *  returns - so the card updates instantly rather than waiting for the
   *  next poll. */
  setOne: (id: string, next: DocumentClassification) => void;
  /** Always true: the classifications arrive WITH the list, so there is no
   *  second wave of answers to wait for. Kept so a caller can still avoid
   *  mounting a card in one group and remounting it in another. */
  settled: boolean;
}

export function useDocumentClassifications(
  documents: Pick<DocumentRecord, "id" | "classification">[],
): DocumentClassifications {
  const [overrides, setOverrides] = useState<Record<string, DocumentClassification>>({});
  const overridesRef = useRef(overrides);
  overridesRef.current = overrides;

  const byId = useMemo(() => {
    const out: Record<string, DocumentClassification> = {};
    for (const doc of documents) {
      if (doc.classification) out[doc.id] = doc.classification;
    }
    for (const [id, local] of Object.entries(overrides)) {
      if (!(id in out)) continue;
      // The list has caught up with the local edit: the list is the truth again.
      if (JSON.stringify(out[id]) === JSON.stringify(local)) continue;
      out[id] = local;
    }
    return out;
  }, [documents, overrides]);

  const setOne = useCallback((id: string, next: DocumentClassification) => {
    setOverrides((prev) => ({ ...prev, [id]: next }));
  }, []);

  return { byId, setOne, settled: true };
}
