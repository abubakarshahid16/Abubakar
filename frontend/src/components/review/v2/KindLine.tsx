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
  return (
    <p data-testid="v2-kind-line" className="flex flex-wrap items-center gap-2 text-sm text-slateish-300">
      {c && <DocumentKindChip classification={c} kinds={k?.kinds} isAdmin={isAdmin === true}
        onConfirm={async (kind) => {
          if (!documentId) return null;
          const r = await classification.confirmKind(documentId, kind);
          if (r.ok) { setCls(r); return null; }
          return "The type could not be saved. Try again."; // shown beside the picker, never silent (G2)
        }} />}
      {equipment && <span>· {equipment}{named ? " (named by the AI for this review)" : !c?.confirmed && " (suggested)"}</span>}
      {pages != null && <span>· {pages} page{pages === 1 ? "" : "s"}</span>}
      {how && <span>· type decided by {how}</span>}
    </p>
  );
}
