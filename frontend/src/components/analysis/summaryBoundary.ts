import type { AnalysisResult } from "../../types/analysis";

/**
 * Whose documents the summary's passages come from (honesty invariant 4: every
 * count states its boundary, #1026). "Passages from M of the S documents this
 * search could reach (the ones you can read)": M = the distinct documents of the cited passages,
 * S = the documents this search could reach after the filter and the caller's
 * own grants (the server's `applied_scope.documents_in_scope`, carried in
 * `coverage.authorized_documents_selected` by `toAnalysisResult`). Null when a
 * cited passage is missing from the ledger or has no document, when the count
 * is absent (a placeholder 0 is absent: a summary that cites passages came from
 * at least one document) or smaller than M: a boundary the card cannot prove is
 * not stated, and is never shown as 0.
 */
export function summaryBoundary(result: AnalysisResult): string | null {
  const ids = result.summary_cited_evidence_ids;
  const inScope = result.coverage?.authorized_documents_selected;
  if (ids.length === 0 || !Number.isInteger(inScope) || (inScope as number) < 1) return null;
  const documentOf = new Map(result.evidence_ledger.map((e) => [e.evidence_id, e.document_id]));
  const cited = new Set<string>();
  for (const id of ids) {
    const document = documentOf.get(id);
    if (typeof document !== "string" || document === "") return null;
    cited.add(document);
  }
  const total = inScope as number;
  if (cited.size > total) return null;
  return `Passages from ${cited.size} of the ${total} document${total === 1 ? "" : "s"} this search could reach (the ones you can read)`;
}
