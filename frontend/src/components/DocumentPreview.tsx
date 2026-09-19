/**
 * Preview the ORIGINAL uploaded file: a PDF in the browser's viewer, an XLSX
 * as a read-only sheet.
 *
 * THE BYTES ARE FETCHED WITH THE BEARER HEADER, never by handing a URL to an
 * `<iframe src>` or an `<a href>`. A navigation carries no Authorization
 * header, so under auth_mode=demo_required it resolves to an empty scope and
 * the backend answers 404 - which reads to the user as "this document does not
 * exist" while they are looking at it in a list. That defect has now been
 * fixed three times in this codebase (page images, report downloads, uploads);
 * this is the fourth surface and it is built that way from the start.
 *
 * The object URL is created from the fetched blob and revoked on unmount, so
 * the bytes do not leak for the lifetime of the tab.
 *
 * XLSX IS READ-ONLY, AND DELIBERATELY SO. A workbook here is a CRS template -
 * a form to be filled - and this screen is for looking at it, not editing it.
 * The original bytes are never modified; "download original" hands back
 * exactly what was uploaded.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { DocumentRecord } from "../types/api";

type Phase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "pdf"; url: string }
  | { kind: "sheet"; sheets: SheetData[] }
  | { kind: "error"; message: string };

export interface SheetData {
  name: string;
  /** Row-major cells. Ragged rows are normal - a sheet is not a rectangle. */
  rows: string[][];
  /** The preview stopped short of the sheet's full extent, and says so. */
  truncated?: boolean;
}

/** Is this document a workbook? Decided from the FILENAME the server stored,
 *  which it derived from the validated bytes - not from anything the uploader
 *  typed. See `upload.sanitise_filename`. */
export function isWorkbook(doc: Pick<DocumentRecord, "filename">): boolean {
  return doc.filename.toLowerCase().endsWith(".xlsx");
}

/*  THE WORKBOOK IS READ ON THE SERVER, not here.
 *
 *  The obvious alternative is SheetJS in the browser. Against it: the npm
 *  `xlsx` package is no longer published there by its authors, so installing
 *  it pulls a stale release with published prototype-pollution advisories -
 *  a poor addition to a product whose premise is that documents are safe on
 *  this machine - and it would mean a third-party parser running over a file
 *  an outside contractor supplied. `backend/app/workbook.py` does it with the
 *  Python standard library, bounded, behind the same scope check as every
 *  other document read. */

export function DocumentPreview({ doc }: { doc: DocumentRecord }) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [active, setActive] = useState(0);
  const workbook = useMemo(() => isWorkbook(doc), [doc]);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    setPhase({ kind: "loading" });

    if (workbook) {
      void api.workbook(doc.id).then((result) => {
        if (cancelled) return;
        if (!result.ok) {
          setPhase({ kind: "error", message: "This workbook could not be read." });
          return;
        }
        setPhase({ kind: "sheet", sheets: result.data.sheets });
      });
      return () => { cancelled = true; };
    }

    void api.originalFile(doc.id, doc.filename).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setPhase({
          kind: "error",
          // The failure KIND, never a server-authored sentence.
          message:
            result.failure.kind === "unavailable"
              ? "The original file is no longer stored."
              : result.failure.kind === "unauthenticated"
                ? "Your session has expired. Sign in to view this document."
                : "The original file could not be loaded.",
        });
        return;
      }
      created = URL.createObjectURL(result.blob);
      setPhase({ kind: "pdf", url: created });
    });
    return () => {
      cancelled = true;
      // Revoked on unmount: an object URL holds the bytes alive for the
      // lifetime of the document otherwise.
      if (created) URL.revokeObjectURL(created);
    };
  }, [doc.id, doc.filename, workbook]);

  const download = useCallback(() => {
    void api.originalFile(doc.id, doc.filename).then((result) => {
      if (!result.ok) return;
      const url = URL.createObjectURL(result.blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = result.filename;
      a.click();
      URL.revokeObjectURL(url);
    });
  }, [doc.id, doc.filename]);

  return (
    <section
      aria-label="Document preview"
      className="flex min-h-0 flex-1 flex-col gap-3 bg-ink-900 p-4"
    >
      {/* NO FILENAME HERE. The Drawer's own header already reads
          "Preview - <filename>", and repeating it underneath gave every
          preview two titles, one of them truncated differently. The action
          stays, because "Download original" is the way out of the embedded
          viewer to the real file. */}
      <header className="flex items-center justify-end gap-3">
        <button
          type="button"
          onClick={download}
          className="rounded border border-ink-600 px-2 py-1 text-xs text-slateish-300 hover:bg-ink-700"
        >
          Download original
        </button>
      </header>

      {phase.kind === "loading" && <p className="text-xs opacity-70">Loading the original…</p>}

      {phase.kind === "error" && (
        <p role="alert" className="text-xs text-warn-500">{phase.message}</p>
      )}

      {phase.kind === "pdf" && (
        // THE FRAGMENT IS VIEWER CONFIGURATION, NOT A QUERY. It is read by the
        // browser's built-in PDF viewer and never sent anywhere - which also
        // means it is safe on a blob: URL, where a query string would not be.
        // `toolbar=0` and `navpanes=0` remove the viewer's own chrome, whose
        // thumbnail rail ate a third of a panel that was already too narrow;
        // `view=FitH` fits the page to the width rather than opening at 100%
        // and making the reader scroll horizontally on every document.
        //
        // These are hints. A browser that ignores them shows its normal
        // viewer, which is why "Download original" is not conditional on them.
        <iframe
          title={`Preview of ${doc.filename}`}
          src={`${phase.url}#toolbar=0&navpanes=0&view=FitH`}
          className="min-h-0 w-full flex-1 rounded border border-ink-700 bg-white"
        />
      )}

      {phase.kind === "sheet" && phase.sheets.length === 0 && (
        <p className="text-xs opacity-70">This workbook has no sheets.</p>
      )}

      {phase.kind === "sheet" && phase.sheets.length > 0 && (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
          <div role="tablist" aria-label="Sheets" className="flex flex-wrap gap-1">
            {phase.sheets.map((sheet, i) => (
              <button
                key={sheet.name}
                role="tab"
                type="button"
                aria-selected={i === active}
                onClick={() => setActive(i)}
                className={`rounded px-2 py-1 text-xs ${
                  i === active ? "bg-white/15" : "bg-white/5"
                }`}
              >
                {sheet.name}
              </button>
            ))}
          </div>
          <SheetTable sheet={phase.sheets[active] ?? phase.sheets[0]} />
          {(phase.sheets[active] ?? phase.sheets[0])?.truncated && (
            <p role="status" className="text-xs text-warn-500">
              This preview does not show the whole sheet. Download the original
              to see all of it.
            </p>
          )}
          <p className="text-xs opacity-70">
            Read-only preview. Download the original to edit it.
          </p>
        </div>
      )}
    </section>
  );
}

/** POPULATED CELLS ONLY.
 *
 *  A CRS template is mostly empty, and rendering its full addressable grid
 *  would be thousands of blank cells the reader has to scroll past to find the
 *  three that are filled. An empty cell renders as NOTHING - never "0", never
 *  a dash, which would read as a recorded value. */
function SheetTable({ sheet }: { sheet: SheetData }) {
  const rows = sheet.rows.filter((row) => row.some((cell) => cell !== ""));
  if (rows.length === 0) {
    return <p className="text-xs opacity-70">This sheet has no populated cells.</p>;
  }
  return (
    <div className="max-h-[60vh] overflow-auto rounded border border-white/10">
      <table className="w-full border-collapse text-xs">
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="odd:bg-white/[0.03]">
              {row.map((cell, c) => (
                <td key={c} className="border border-white/10 px-2 py-1 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
