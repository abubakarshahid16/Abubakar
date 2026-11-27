/** SPEC 1: "kind · equipment type · pages · kind decided by <how>" with a Change link (the existing kind picker). */
import { useEffect, useState } from "react";

import { classification } from "../../../api/documents";
import { DocumentKindChip } from "../../DocumentKindChip";

type Cls = Awaited<ReturnType<typeof classification.ofDocument>>;
type Kinds = Awaited<ReturnType<typeof classification.kinds>>;

/** Only a CONFIRMED kind says who decided it: a guessed kind is already said by the chip ("guessed, not confirmed"), and one line says it once. */
const HOW: Record<string, string> = { confirmed: "an engineer" };

export function KindLine({ documentId, pages, isAdmin, aiEquipment }: {
  documentId: string | null; pages: number | null | undefined; isAdmin: boolean | undefined;
  /** The equipment type the AI named for THIS review (its identity step); it wins over the stored suggestion, which can be another type. */
  aiEquipment?: string | null;
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
  const named = aiEquipment ? String(aiEquipment).replace(/_/g, " ") : null;
  const equipment = named ?? (c?.equipment_type ? String(c.equipment_type).replace(/_/g, " ") : null);
  const how = c?.document_kind_state ? HOW[c.document_kind_state] : null;
  // The facts after the chip, joined with a dot only BETWEEN them: a line never starts with " · " (H's R9, 27 Nov 2026)
  const facts = [
    equipment ? `${equipment}${named ? " (named by the AI for this review)" : !c?.confirmed ? " (suggested)" : ""}` : null,
    pages != null ? `${pages} page${pages === 1 ? "" : "s"}` : null,
    how ? `type decided by ${how}` : null,
  ].filter((f): f is string => f !== null);
  return (
    <p data-testid="v2-kind-line" className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
      {c && <DocumentKindChip classification={c} kinds={k?.kinds} isAdmin={isAdmin === true}
        onConfirm={async (kind) => {
          if (!documentId) return null;
          const r = await classification.confirmKind(documentId, kind);
          if (r.ok) { setCls(r); return null; }
          return "The type could not be saved. Try again."; // shown beside the picker, never silent (G2)
        }} />}
      {facts.length > 0 && <span data-testid="v2-kind-facts">{facts.join(" · ")}</span>}
    </p>
  );
}
