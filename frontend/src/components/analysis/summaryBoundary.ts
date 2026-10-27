import type { AnalysisResult } from "../../types/analysis";

/**
 * Whose documents the summary's passages come from (honesty invariant 4: every
 * count states its boundary, #1026). "Passages from M of S selected documents you
 * can read": M = the distinct documents of the cited passages, S = the documents
 * the analysis was allowed to read among those selected (`coverage`). Null when
 * any cited passage is missing from the ledger or the coverage count is absent:
 * a boundary the card cannot prove is not stated, and is never shown as 0.
 */
export function summaryBoundary(result: AnalysisResult): string | null {
  const ids = result.summary_cited_evidence_ids;
  const selected = result.coverage?.authorized_documents_selected;
  if (ids.length === 0 || typeof selected !== "number") return null;
  const documentOf = new Map(result.evidence_ledger.map((e) => [e.evidence_id, e.document_id]));
  const cited = new Set<string>();
  for (const id of ids) {
    const document = documentOf.get(id);
    if (document === undefined) return null;
    cited.add(document);
  }
  return `Passages from ${cited.size} of ${selected} selected document${selected === 1 ? "" : "s"} you can read`;
}
