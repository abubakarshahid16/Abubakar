/**
 * OWNER: builder C (v2.2). The read-only look at the comment sheet as the
 * contractor gets it: the server's own preview of the CONTRACTOR'S copy
 * (`reviewsApi.previewCrs(runId, "issue")`: unconfirmed and AI-only rows left out)
 * drawn by `CrsPreviewSheet readOnly`, with the internal-only columns and
 * notes left out (`contractorView`). Used by "Preview and confirm"
 * (SignConfirm) and by the "Preview CRS" step of the bar (ActionBar).
 *
 * It issues nothing and changes nothing: it only reads the preview. The
 * sheet is read again each time this piece is shown (mounted), so the look
 * is what the server holds now.
 */
import { useCallback, useEffect, useState } from "react";

import { reviews as reviewsApi } from "../../../../api/client";
import type { CrsPreview } from "../../../../types/api";
import { CrsPreviewSheet } from "../../CrsPreviewSheet";

/** Columns and notes the server marks as internal: the contractor's copy
 *  does not carry them, so the preview of that copy does not show them. */
const INTERNAL_COLUMNS = new Set(["AI Review Comments", "Reasoning (internal)", "Rule trust (internal)"]);

/** The preview as the contractor's copy lays it out. */
export function contractorView(preview: CrsPreview): CrsPreview {
  return {
    ...preview,
    columns: preview.columns.filter((c) => !INTERNAL_COLUMNS.has(c) && !/\(internal\)\s*$/i.test(c)),
    review_notes: [],
  };
}

type Preview = { kind: "loading" } | { kind: "ready"; preview: CrsPreview } | { kind: "error"; message: string };

export interface CrsLookProps {
  runId: string;
  /** Plain words after "The preview of the sheet could not be loaded (...)."
   *  when the read fails. */
  failNote?: string;
  /** data-testid of the failure line. */
  errorTestId?: string;
}

export function CrsLook({ runId, failNote = "", errorTestId = "ws-crs-look-error" }: CrsLookProps) {
  const [preview, setPreview] = useState<Preview>({ kind: "loading" });

  const load = useCallback(async (live: () => boolean) => {
    const result = await reviewsApi.previewCrs(runId, "issue");
    if (!live()) return;
    setPreview(result.ok ? { kind: "ready", preview: result.data } : { kind: "error", message: result.error.message });
  }, [runId]);

  useEffect(() => {
    let live = true;
    setPreview({ kind: "loading" });
    void load(() => live);
    return () => { live = false; };
  }, [load]);

  if (preview.kind === "loading") return <p className="text-slateish-400">Loading the sheet…</p>;
  if (preview.kind === "error") {
    return (
      <p role="alert" data-testid={errorTestId} className="text-warn-500">
        The preview of the sheet could not be loaded ({preview.message}).{failNote ? ` ${failNote}` : ""}
      </p>
    );
  }
  return (
    <div className="max-h-[55vh] overflow-auto">
      <CrsPreviewSheet readOnly preview={contractorView(preview.preview)} runId={runId}
        onChanged={() => void load(() => true)} />
    </div>
  );
}
