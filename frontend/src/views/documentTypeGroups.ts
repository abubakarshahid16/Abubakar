import { NOT_IN_REGISTER_LABEL } from "../components/classification/registerLabels";
import type { DocumentClassification, DocumentRecord } from "../types/api";

/** The filter-chip and group key for "no confirmed type yet". Never a
 *  register type name - the register's own strings come from
 *  `vocabulary.types` and this must never collide with one of them. */
export const AWAITING_TYPE = "__awaiting_type__";

/** The filter-chip key for "has a role, no register type". Same rule as
 *  `AWAITING_TYPE`: never a register type name. */
export const NOT_IN_REGISTER = "__not_in_register__";

/** The heading and filter-chip label for the group above. Kept as one
 *  constant so the filter chip, the group heading and any message about it
 *  are always the same words. */
export const AWAITING_TYPE_LABEL = "Awaiting a type";

export type TypeGroup = { name: string; documents: DocumentRecord[] };

/**
 * A document's confirmed-or-not type, from the per-document classification
 * fetch - NEVER from anything on `DocumentRecord` itself, because
 * `GET /api/documents` does not carry it.
 *
 * A classification that has not answered yet (still in flight) is treated
 * the same as `doc_type: null` for grouping purposes: it renders in the
 * "awaiting a type" group until its real answer arrives, rather than being
 * hidden from the list altogether while loading.
 */
export function typeOf(doc: DocumentRecord, byId: Record<string, DocumentClassification>): string | null {
  return byId[doc.id]?.doc_type ?? null;
}

/**
 * The documents, grouped by confirmed-or-guessed type - in the register's
 * own order, one group per `types` entry, plus a final "awaiting a type"
 * group. A type is never invented here: `types` comes from
 * `useTypeVocabulary`, which reads it from the register.
 *
 * Every group is built even when it has no documents - see the empty-group
 * message in the view. Hiding an empty group would be indistinguishable from
 * a group nobody thought to build, and this screen exists to be able to tell
 * the two apart.
 */
export function groupByType(
  documents: DocumentRecord[],
  types: string[],
  byId: Record<string, DocumentClassification>,
): { groups: TypeGroup[]; awaiting: TypeGroup; notInRegister: TypeGroup } {
  const groups: TypeGroup[] = types.map((t) => ({ name: t, documents: [] }));
  const byName = new Map(groups.map((g) => [g.name, g]));
  const awaiting: DocumentRecord[] = [];
  const notInRegister: DocumentRecord[] = [];
  for (const doc of documents) {
    const t = typeOf(doc, byId);
    const bucket = t !== null ? byName.get(t) : undefined;
    // A type the classification carries but the register no longer lists is
    // not something this screen invents a group for - the document still
    // has to appear somewhere, so it falls back to "awaiting a type" rather
    // than being silently dropped.
    if (bucket) bucket.documents.push(doc);
    else if (t === null && byId[doc.id]?.document_role) notInRegister.push(doc);
    else awaiting.push(doc);
  }
  return {
    groups,
    awaiting: { name: AWAITING_TYPE_LABEL, documents: awaiting },
    notInRegister: { name: NOT_IN_REGISTER_LABEL, documents: notInRegister },
  };
}
