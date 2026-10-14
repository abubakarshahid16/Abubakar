/**
 * The Comment Resolution Sheet as the workbook lays it out.
 *
 * RECOGNISABLY THE WORKBOOK: the header block over the seven columns the
 * client's template defines, the rows in the order the sheet numbers them,
 * and the recommended review code on its own line underneath. Every value
 * comes from the route verbatim - the labels are the client's wording, not
 * this screen's, so nothing here re-types what their document says.
 *
 * Split out of `ReviewRunsView.tsx` (#925 item 7: that file was 1,421 lines
 * against the A14 quality ratchet's baseline). `CrsTransmittalsForm` was
 * already imported from there by `ReviewCrsList.test.tsx` - a sign this
 * piece belonged in its own file, not that one.
 */
import { useState } from "react";

import { reviews as reviewsApi } from "../../api/client";
import type { CrsPreview } from "../../types/api";
import {
  CrsItemCell, CrsReplyImportControl, CrsResolutionCell, CrsResponseCell,
} from "./CrsCommentControls";

/** #725 F7: enter the CRS header's company and contractor transmittal
 *  numbers. Starts from what the sheet prints now; "" clears a number. */
export function CrsTransmittalsForm(
  { runId, header, onChanged }: {
    runId: string; header: CrsPreview["header"]; onChanged: () => void;
  },
) {
  const valueOf = (prefix: string) =>
    header.find((h) => h.label.replace(/\s+/g, " ").startsWith(prefix))?.value ?? "";
  const [company, setCompany] = useState(valueOf("COMPANY Transmittal"));
  const [contractor, setContractor] = useState(valueOf("CONTRACTOR Transmittal"));
  const [state, setState] = useState<"idle" | "saving" | "saved" | string>("idle");
  const save = async () => {
    setState("saving");
    const res = await reviewsApi.setCrsTransmittals(runId, {
      company_transmittal: company, contractor_transmittal: contractor,
    });
    if (res.ok) {
      setState("saved");
      onChanged();
    } else {
      setState(`Not saved: ${res.error.message}`);
    }
  };
  return (
    <form
      aria-label="Transmittal numbers"
      className="flex flex-wrap items-end gap-2 text-xs"
      onSubmit={(e) => { e.preventDefault(); void save(); }}
    >
      <label className="flex flex-col text-slateish-300">
        Company transmittal no.
        <input value={company} maxLength={80} onChange={(e) => setCompany(e.target.value)}
          className="mt-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2 py-1 text-slateish-100" />
      </label>
      <label className="flex flex-col text-slateish-300">
        Contractor transmittal no.
        <input value={contractor} maxLength={80} onChange={(e) => setContractor(e.target.value)}
          className="mt-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2 py-1 text-slateish-100" />
      </label>
      <button type="submit" disabled={state === "saving"}
        className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-slateish-200">
        Save transmittal numbers
      </button>
      {state === "saved" && <span role="status" className="text-slateish-400">Saved</span>}
      {state !== "idle" && state !== "saving" && state !== "saved" && (
        <span role="alert" className="text-danger-500">{state}</span>
      )}
    </form>
  );
}

export function CrsPreviewSheet(
  { preview, runId, onChanged }: { preview: CrsPreview; runId: string; onChanged: () => void },
) {
  return (
    <section
      aria-label="Comment Resolution Sheet preview"
      className="space-y-3 overflow-x-auto rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4"
    >
      <div className="space-y-1 text-center">
        {/* The title carries the newline the sheet merges across row 1. */}
        <p className="whitespace-pre-line text-sm font-semibold text-slateish-100">
          {preview.title}
        </p>
        <p className="text-sm font-semibold text-slateish-100">{preview.subtitle}</p>
      </div>

      <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
        {preview.header.map((field) => (
          <div key={field.label} className="contents">
            <dt className="text-xs font-semibold text-slateish-200">{field.label}</dt>
            {/* BLANK IS BLANK. The transmittal numbers are empty because
                nobody has issued one, and a placeholder here would be this
                screen inventing provenance the document does not have. */}
            <dd className="text-xs text-slateish-300">{field.value}</dd>
          </div>
        ))}
      </dl>

      {/* #725 F7: the two transmittal numbers are entered here, never invented. */}
      <CrsTransmittalsForm runId={runId} header={preview.header} onChanged={onChanged} />

      {/* AFTER ISSUE: the contractor's returned sheet, matched by each
          comment's permanent number (never by position). */}
      <CrsReplyImportControl runId={runId} onChanged={onChanged} />

      <table className="w-full min-w-[56rem] border-collapse text-xs">
        <thead>
          <tr>
            {preview.columns.map((column) => (
              <th
                key={column} scope="col"
                className="border border-ink-600 bg-ink-800 px-2 py-1 text-left font-semibold text-slateish-200"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row) => (
            <tr key={row.item_no}>
              <td className="border border-ink-600 px-2 py-1 text-center align-top text-slateish-300">
                <CrsItemCell runId={runId} row={row} />
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                {row.document_name}
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                {row.page_section}
              </td>
              <td className="whitespace-pre-line border border-ink-600 px-2 py-1 align-top text-slateish-200">
                {row.comment}
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                {row.comment_by}
              </td>
              {/* CONTRACTOR'S RESPONSE is theirs: empty until they reply,
                  then their reply as imported or recorded - never written
                  here by the machine. FINAL RESOLUTION is the COMPANY's:
                  Open until a reviewer closes it (2026-09-29, industry
                  practice). Both come from the server's sheet, so this cell
                  shows exactly what the file says. */}
              <td className="border border-ink-600 px-2 py-1 align-top">
                <CrsResponseCell runId={runId} row={row} onChanged={onChanged} />
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top">
                <CrsResolutionCell runId={runId} row={row} onChanged={onChanged} />
              </td>
              {/* CRS quick wins: the standard and clause, in their own column
                  after the client's seven (Page/Section is the datasheet's). */}
              {preview.columns.includes("Standard Reference") && (
                <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                  {row.standard_reference ?? ""}
                </td>
              )}
              {/* #725 F7: the severity, after Standard Reference, both copies. */}
              {preview.columns.includes("Severity") && (
                <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                  {row.severity ?? ""}
                </td>
              )}
              {/* Owner order 2f: the last column, internal copy only. */}
              {preview.columns.includes("AI Review Comments") && (
                <td className="whitespace-pre-line border border-ink-600 px-2 py-1 align-top text-slateish-200">
                  {row.ai_review_comment}
                </td>
              )}
              {/* R30: the reasoning behind the row, internal copy only. */}
              {preview.columns.includes("Reasoning (internal)") && (
                <td data-testid="crs-reasoning"
                  className="whitespace-pre-line border border-ink-600 px-2 py-1 align-top text-xs text-slateish-300">
                  {row.reasoning ?? ""}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Owner order 2f: the engineer's internal notes, on their own sheet -
          never in COMPANY Comments, and not in the contractor's copy. */}
      {(preview.review_notes ?? []).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slateish-200">
            Review notes - internal ({(preview.review_notes ?? []).length})
          </summary>
          <table className="mt-2 w-full border-collapse">
            <thead>
              <tr>
                {["Note", "Standard", "Count", "Detail"].map((h) => (
                  <th key={h} scope="col" className="border border-ink-600 bg-ink-800 px-2 py-1 text-left font-semibold text-slateish-200">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(preview.review_notes ?? []).map((n, i) => (
                <tr key={i}>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-200">{n.note}</td>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">{n.standard}</td>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">{n.count ?? ""}</td>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">{n.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {/* NULL RENDERS AS NOTHING. A run with no recommendation shows no line
          at all rather than an empty or placeholder code. */}
      {preview.recommended_code && (
        <p className="text-xs text-slateish-200">
          <span className="font-semibold">{preview.recommended_code_label}</span>{" "}
          <span className="font-semibold">{preview.recommended_code}</span>
          {preview.recommended_code_reason
            ? <span className="text-slateish-400"> — {preview.recommended_code_reason}</span>
            : null}
        </p>
      )}
      {/* #633: a sheet that could not check everything says so, above the code. */}
      {preview.incomplete_notice && (
        <p className="text-xs font-semibold text-warn-500" role="note" data-testid="crs-incomplete">
          {preview.incomplete_notice}
        </p>
      )}
      {/* B10: whether an engineer decided the code, or it is still the AI's. */}
      {preview.recommended_code && preview.recommended_code_status && (
        <p className="text-xs text-warn-500" data-testid="crs-code-status">
          {preview.recommended_code_status}
        </p>
      )}
    </section>
  );
}
