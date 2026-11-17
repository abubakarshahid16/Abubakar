/**
 * v2.1 L1: the "select bar" is back. A searchable list of every contractor
 * submittal and a "Start review" button that ALWAYS starts a fresh review
 * (never opens an old one). Before it starts it asks when the latest review
 * is signed, carries the engineer's final code, or the readiness check says
 * nothing changed since (`ReviewAgainButton`'s one confirm). The start
 * watches the run (`reviewAgain` -> `watchRun`), so the "ready" notice
 * appears wherever the reader goes (L6).
 *
 * Order 14 LPS S1: the list also offers every contract paper the reader may
 * read and the contract packages they form (`GET /api/reviews/contract-papers`).
 * A package is reviewed ONE PAPER AT A TIME: choosing it lists its papers, each
 * with its own Start review, and each start goes through the one pre-start
 * step with that paper's own list of what will leave this computer. Nothing
 * here decides what may leave: Automatic keeps a contract on this computer;
 * only an explicit choice of Claude in that step sends it (rule 1).
 */
import { useEffect, useId, useMemo, useState } from "react";

import { type ContractPapers, reviewPlan } from "../../../../api/reviewPlan";
import type { DocumentRecord, ReviewRunSummary } from "../../../../types/api";
import { truncationNote } from "../../reviewFormat";
import { ReviewAgainButton } from "../ReviewAgainButton";
import { matchesName } from "./landingRows";

export function StartReviewBar({ documents, submittalsTotal, runs, onStarted }: {
  /** Every CONTRACTOR_SUBMITTAL document the page loaded. */
  documents: DocumentRecord[];
  submittalsTotal: number | null;
  runs: ReviewRunSummary[];
  onStarted: (runId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState("");
  const [contracts, setContracts] = useState<ContractPapers | null>(null);
  const selectId = useId();
  useEffect(() => {
    let live = true;
    void reviewPlan.contractPapers().then((r) => { if (live && r.ok) setContracts(r.data); }, () => undefined);
    return () => { live = false; };
  }, []);
  const contractPapers = contracts?.papers ?? [];
  const contractIds = new Set(contractPapers.map((p) => p.document_id));
  const sorted = useMemo(
    () => [...documents].sort((a, b) => a.filename.localeCompare(b.filename)),
    [documents],
  );
  // A contract paper the documents list also holds is offered once, under the contract papers.
  const shown = sorted.filter((d) => !contractIds.has(d.id) && (matchesName(d.filename, query) || d.id === chosen));
  const shownContracts = contractPapers.filter((p) => matchesName(p.filename, query) || p.document_id === chosen);
  const nameOf = (id: string) => contractPapers.find((p) => p.document_id === id)?.filename ?? id;
  const packages = (contracts?.packages ?? []).map((pkg, i) => ({ ...pkg, value: `${PACKAGE}${i}` }));
  const shownPackages = packages.filter(
    (pkg) => pkg.value === chosen || matchesName(pkg.number ?? "", query) || pkg.papers.some((id) => matchesName(nameOf(id), query)),
  );
  const chosenPackage = packages.find((pkg) => pkg.value === chosen) ?? null;
  const chosenName = chosenPackage ? null : (documents.find((d) => d.id === chosen)?.filename ?? contractPapers.find((p) => p.document_id === chosen)?.filename ?? null);
  const offered = shown.length + shownContracts.length + shownPackages.length;
  const boundary = truncationNote(documents.length, submittalsTotal, "contractor submittals");

  return (
    <div className="space-y-2" data-testid="start-review-bar">
      <label htmlFor={selectId} className="block text-sm font-medium text-slateish-200">Choose a submittal</label>
      {documents.length === 0 && contractPapers.length === 0 ? (
        <p className="text-sm text-slateish-300">There are no contractor submittals to choose from yet. Drop a file below instead.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type to find a file"
            aria-label="Find a submittal by file name"
            className="min-w-[12rem] flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-slateish-100"
          />
          <select
            id={selectId}
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
            className="min-w-[12rem] flex-1 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-slateish-100"
          >
            <option value="">
              {offered === 0 ? "No file name matches" : `Choose one of ${offered.toLocaleString("en-US")}`}
            </option>
            {contractPapers.length === 0
              ? shown.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)
              : (
                <>
                  {shown.length > 0 && (
                    <optgroup label="Contractor submittals">
                      {shown.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
                    </optgroup>
                  )}
                  {shownPackages.length > 0 && (
                    <optgroup label="Contract packages (each paper is reviewed on its own)">
                      {shownPackages.map((pkg) => (
                        <option key={pkg.value} value={pkg.value}>{packageLabel(pkg.number, pkg.papers.length)}</option>
                      ))}
                    </optgroup>
                  )}
                  {shownContracts.length > 0 && (
                    <optgroup label="Contract papers">
                      {shownContracts.map((p) => <option key={p.document_id} value={p.document_id}>{p.filename}</option>)}
                    </optgroup>
                  )}
                </>
              )}
          </select>
          {!chosenPackage && (
            <ReviewAgainButton
              documentId={chosen}
              filename={chosenName}
              runs={runs}
              label="Start review"
              primary
              disabled={!chosen}
              onStarted={onStarted}
            />
          )}
        </div>
      )}
      {chosenPackage && (
        <div data-testid="package-papers" className="space-y-2 rounded-[var(--radius-sm)] border border-ink-700 p-3">
          <p className="text-sm text-slateish-200">
            {packageLabel(chosenPackage.number, chosenPackage.papers.length)}. {PACKAGE_WORDS}
          </p>
          <ul className="space-y-2">
            {chosenPackage.papers.map((id) => (
              <li key={id} className="flex flex-wrap items-start justify-between gap-2 text-sm text-slateish-100">
                <span className="min-w-[12rem] flex-1 break-words">{nameOf(id)}</span>
                <ReviewAgainButton
                  documentId={id}
                  filename={nameOf(id)}
                  runs={runs}
                  label="Start review"
                  ariaLabel={`Start review of ${nameOf(id)}`}
                  onStarted={onStarted}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
      {contracts && contractPapers.length > 0 && (
        <p className="text-xs text-slateish-400" data-testid="contract-papers-boundary">
          Also offered: {contracts.boundary}, and the contract packages they form (papers whose covers print the same number).
        </p>
      )}
      <p className="text-xs text-slateish-400">Start review always starts a fresh review. Earlier reviews stay as they are.</p>
      {boundary && <p className="text-xs text-slateish-400">{boundary}</p>}
    </div>
  );
}

const PACKAGE = "package:";

/** Order 14 LPS S1: a package is reviewed one paper at a time, each through its own pre-start step (rule 1 unchanged). */
export const PACKAGE_WORDS =
  "Each paper is reviewed on its own: its Start review first shows what will leave this computer for that paper, and Automatic keeps a "
  + "contract on this computer (only choosing Claude there sends it).";

function packageLabel(number: string | null, n: number): string {
  return `Contract package ${number ?? "with no cover number"}: ${n.toLocaleString("en-US")} paper${n === 1 ? "" : "s"}`;
}
