/** SPEC 1: "kind · equipment type · pages · kind decided by <how>" with a Change link (the existing kind picker). */
import { useEffect, useState } from "react";

import { classification } from "../../../api/documents";
import type { KindUsed } from "../../../api/reviewPoints";
import { DocumentKindChip } from "../../DocumentKindChip";
import { kindUsedWords } from "./words";

type Cls = Awaited<ReturnType<typeof classification.ofDocument>>;
type Kinds = Awaited<ReturnType<typeof classification.kinds>>;

/** Only a CONFIRMED kind says who decided it: a guessed kind is already said by the chip ("guessed, not confirmed"), and one line says it once. */
const HOW: Record<string, string> = { confirmed: "an engineer" };

export function KindLine({ documentId, pages, isAdmin, kindUsed = null }: {
  documentId: string | null; pages: number | null | undefined; isAdmin: boolean | undefined;
  /** The kind the paper's AI review used (`listing.kind_used`); null or absent: the stored kind, as before. */
  kindUsed?: KindUsed | null;
}) {
  const [cls, setCls] = useState<Cls | null>(null);
  const [kinds, setKinds] = useState<Kinds | null>(null);
  useEffect(() => {
    if (!documentId) return;
    let live = true;
    void classification.ofDocument(documentId).then((r) => { if (live) setCls(r); });
    void classification.kinds().then((r) => { if (live) setKinds(r); });
    return () => { live = false; };
  }, [documentId]);
  const c = cls && cls.ok ? cls.data : undefined;
  const k = kinds && kinds.ok ? kinds.data : undefined;
  const equipment = c?.equipment_type ? String(c.equipment_type).replace(/_/g, " ") : null;
  const how = kindUsed ? (kindUsed.confirmed ? HOW.confirmed : null) : c?.document_kind_state ? HOW[c.document_kind_state] : null;
  const usedLabel = kindUsed?.kind ? k?.kinds.find((x) => x.id === kindUsed.kind)?.label ?? null : null;
  return (
    <p data-testid="v2-kind-line" className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
      {kindUsed && (
        <span data-testid="v2-kind-used" title={`The kind this review used: ${kindUsed.source}`}
          className={`rounded-[var(--radius-xs)] px-2 py-0.5 text-xs ${kindUsed.guess || !kindUsed.known ? "border border-warn-500/40 bg-warn-500/10 text-warn-500" : "bg-ink-700 text-slateish-300"}`}>
          {kindUsedWords(kindUsed, usedLabel)}
        </span>
      )}
      {c && <DocumentKindChip classification={c} kinds={k?.kinds} isAdmin={isAdmin === true} hideChip={kindUsed != null}
        onConfirm={(kind) => { if (documentId) void classification.confirmKind(documentId, kind).then((r) => { if (r.ok) setCls(r); }); }} />}
      {equipment && <span>· {equipment}</span>}
      {pages != null && <span>· {pages} page{pages === 1 ? "" : "s"}</span>}
      {how && <span>· kind decided by {how}</span>}
    </p>
  );
}
