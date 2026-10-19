/**
 * OWNER: builder C. The workspace's comment sheet: the existing CrsTable
 * over `plainRow(rows)`, with the depth / show-met / selection / edit and
 * remove state and the keyboard (J / K, E, R, Enter) kept exactly as
 * CrsSheetView keeps them, and WorkspaceEvidence on the right for the open
 * row. The only comment list on the workspace screen.
 *
 * The open row lives in the URL (`row` + `panel=evidence`), so it is a prop:
 * opening a row, moving with Previous / Next (or J / K in the drawer), a page
 * jump and closing all report through `onOpenRow`; the screen above writes
 * the URL and hands the new key back as `openRowKey`.
 *
 * Counts are not made here: the header line, the table's folded line (from
 * the `numbers` prop) and the sign-off panel (the `footer`) take theirs from
 * computeReviewNumbers.
 */
import { useCallback, useContext, useEffect, useMemo, useState } from "react";

import { CRS_SHEET_IS_DEFAULT, panelForReviewScreen } from "../../../routing";
import { NavigationContext } from "../../NavLink";
import type { RowMode } from "../crs/CrsRow";
import { CrsTable } from "../crs/CrsTable";
import { type CrsRow, type Depth, spotCheckKeys, visibleRows } from "../crs/crsRows";
import type { TierCounts } from "../crs/tiers";
import { commentPages, firstRowOnPage, stepRow } from "../crs/evidenceNav";
import { useCrsKeys } from "../crs/useCrsKeys";
import type { WorkspaceSheetProps } from "./contract";
import { WorkspaceEvidence } from "./WorkspaceEvidence";
import { plainRow } from "./plainWords";
import { DecisionPanel } from "./decide/DecisionPanel";
import { nextUndecided } from "./decide/nextUndecided";

/** Where the keyboard goes back to when the drawer closes (as CrsSheetView). */
function returnTarget(prev: HTMLElement | null, rowKey: string): HTMLElement | null {
  const active = document.activeElement as HTMLElement | null;
  if (active?.closest?.("[role=dialog]")) return prev;
  if (active && active !== document.body) return active;
  const tr = Array.from(document.querySelectorAll<HTMLElement>("tr[data-row-key]")).find((el) => el.dataset.rowKey === rowKey);
  return tr?.querySelector<HTMLElement>("button") ?? prev;
}

export function WorkspaceSheet({
  runId, rows, submittal, standardNames, decisions, openRowKey, onOpenRow, numbers, footer,
}: WorkspaceSheetProps) {
  const [depth, setDepth] = useState<Depth>("standard");
  const [showMet, setShowMet] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(openRowKey);
  const [mode, setMode] = useState<{ key: string; kind: RowMode } | null>(null);
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const navigate = useContext(NavigationContext);

  // A row opened from outside (the URL, "Decide comments") is selected too.
  const [openFor, setOpenFor] = useState(openRowKey);
  if (openFor !== openRowKey) {
    setOpenFor(openRowKey);
    if (openRowKey) setSelectedKey(openRowKey);
  }

  const plain = useMemo(() => rows.map(plainRow), [rows]);
  // The folded "met / not applicable" line shows the workspace's one set of
  // numbers (computeReviewNumbers), so it matches the count line above.
  // These are ROW counts, as CrsSheetView hands its table `rowCounts(rows)`;
  // the clause count goes to the table's own clause line.
  const counts = useMemo<TierCounts>(() => ({
    met: numbers.met, notApplicable: numbers.notApplicableRows, anotherDocument: numbers.anotherDocument,
    comment: numbers.comments - numbers.needsYou, needsYou: numbers.needsYou,
  }), [numbers.met, numbers.notApplicableRows, numbers.anotherDocument, numbers.comments, numbers.needsYou]);
  const spot = useMemo(() => spotCheckKeys(rows, runId), [rows, runId]);
  const shown = useMemo(() => visibleRows(plain, depth, showMet, spot), [plain, depth, showMet, spot]);
  const pagesWithComments = useMemo(() => commentPages(shown), [shown]);
  const drawerRow = openRowKey === null ? null : plain.find((r) => r.key === openRowKey) ?? null;

  const { markOpened, keep } = decisions;
  // An open row counts as opened, however it was opened.
  const drawerKey = drawerRow?.key ?? null;
  useEffect(() => { if (drawerKey) markOpened(drawerKey); }, [drawerKey, markOpened]);

  const openEvidence = useCallback((row: CrsRow) => {
    setReturnTo((prev) => returnTarget(prev, row.key));
    markOpened(row.key);
    onOpenRow(row.key);
  }, [markOpened, onOpenRow]);
  const moveTo = useCallback((row: CrsRow) => {
    markOpened(row.key);
    setSelectedKey(row.key);
    onOpenRow(row.key);
  }, [markOpened, onOpenRow]);
  const selectRow = useCallback((row: CrsRow) => setSelectedKey(row.key), []);
  const changeMode = useCallback((key: string, kind: RowMode) => setMode(kind ? { key, kind } : null), []);
  const closeDrawer = useCallback(() => onOpenRow(null), [onOpenRow]);

  // D1: after a decision in the panel, move to the next comment still to
  // decide (the one source's undecidedKeys, in sheet order); when none is
  // left, stay and say so.
  const [doneNote, setDoneNote] = useState<{ key: string; text: string } | null>(null);
  const orderKeys = useMemo(() => plain.map((r) => r.key), [plain]);
  const onDecided = useCallback((rowKey: string) => {
    const next = nextUndecided(orderKeys, numbers.undecidedKeys, rowKey);
    if (next) {
      setDoneNote(null);
      markOpened(next);
      setSelectedKey(next);
      onOpenRow(next);
    } else {
      setDoneNote({ key: rowKey, text: "That was the last comment to decide." });
    }
  }, [orderKeys, numbers.undecidedKeys, markOpened, onOpenRow]);
  const openCards = useCallback(() => {
    navigate?.("review", runId, panelForReviewScreen("cards", CRS_SHEET_IS_DEFAULT));
  }, [navigate, runId]);

  const keyActions = useMemo(() => ({
    select: (row: CrsRow) => setSelectedKey(row.key),
    edit: (row: CrsRow) => { if (row.tier.tier !== "A") setMode({ key: row.key, kind: "edit" }); },
    remove: (row: CrsRow) => { if (row.tier.tier !== "A") setMode({ key: row.key, kind: "remove" }); },
    keep: (row: CrsRow) => { if (row.tier.tier !== "A") keep(row.key); },
  }), [keep]);
  useCrsKeys(shown, selectedKey, keyActions, drawerRow === null);

  const nav = useMemo(() => {
    if (!drawerRow) return undefined;
    const index = shown.findIndex((r) => r.key === drawerRow.key);
    if (index < 0) return undefined;
    const prev = stepRow(shown, drawerRow.key, -1);
    const next = stepRow(shown, drawerRow.key, 1);
    return { index, total: shown.length, onPrev: prev ? () => moveTo(prev) : null, onNext: next ? () => moveTo(next) : null };
  }, [drawerRow, shown, moveTo]);
  const pager = useMemo(() => ({
    pageCount: submittal?.page_count ?? null,
    commentPages: pagesWithComments,
    onPage: (page: number) => {
      const row = firstRowOnPage(shown, page);
      if (row) moveTo(row);
      return row !== null;
    },
  }), [submittal, pagesWithComments, shown, moveTo]);

  return (
    <div className="space-y-4" data-testid="ws-sheet" data-rows={rows.length}>
      <CrsTable
        rows={shown} allRows={plain} counts={counts} depth={depth} onDepth={setDepth} showMet={showMet} onShowMet={setShowMet}
        spot={spot} selectedKey={selectedKey} onSelect={selectRow} onOpenEvidence={openEvidence}
        mode={mode} onMode={changeMode} decisions={decisions}
        clausesNotApplicable={numbers.notApplicableClauses}
        tierHeader="Kind"
      />
      {footer}
      {drawerRow && (
        <WorkspaceEvidence row={drawerRow} runId={runId} standardNames={standardNames} returnTo={returnTo}
          onClose={closeDrawer} onOpenCards={openCards} nav={nav} pager={pager}
          decide={drawerRow.tier.tier !== "A" ? (
            <DecisionPanel row={drawerRow} decisions={decisions} onDecided={onDecided}
              note={doneNote?.key === drawerRow.key ? doneNote.text : null} />
          ) : null} />
      )}
    </div>
  );
}
