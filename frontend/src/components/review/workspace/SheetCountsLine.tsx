/**
 * OWNER: builder B. The comment sheet's one count line, e.g. "12 comments,
 * 3 need you, 40 met, 7 not applicable, 3 pages to check". Every number is
 * `computeReviewNumbers`'s; nothing is counted here.
 */
import type { ReactNode } from "react";

import type { SheetCountsLineProps } from "./contract";

function Part({ n, one, many, count }: { n: number; one: string; many: string; count?: string }) {
  return (
    <>
      <span data-count={count}>{n.toLocaleString()}</span> {n === 1 ? one : many}
    </>
  );
}

export function SheetCountsLine({ numbers }: SheetCountsLineProps) {
  const parts: ReactNode[] = [
    <Part key="c" n={numbers.comments} one="comment" many="comments" count="comments" />,
    <Part key="y" n={numbers.needsYou} one="needs you" many="need you" count="needsYou" />,
  ];
  if (numbers.met > 0) parts.push(<Part key="m" n={numbers.met} one="met" many="met" count="met" />);
  // Comments on the sheet and parts of the standards are different things,
  // so each is said in its own words (W1: no "rows" or "clauses").
  if (numbers.notApplicableRows > 0) {
    parts.push(<Part key="n" n={numbers.notApplicableRows} one="not applicable" many="not applicable" count="notApplicableRows" />);
  }
  if (numbers.notApplicableClauses !== null && numbers.notApplicableClauses > 0) {
    parts.push(<Part key="nc" n={numbers.notApplicableClauses} one="part of the standards does not apply" many="parts of the standards do not apply" count="notApplicableClauses" />);
  }
  if (numbers.anotherDocument > 0) parts.push(<Part key="a" n={numbers.anotherDocument} one="for another document" many="for another document" />);
  if (numbers.pagesKnown && numbers.unreadPages.length > 0) {
    parts.push(<Part key="p" n={numbers.unreadPages.length} one="page to check" many="pages to check" count="unreadPages" />);
  }
  if (numbers.standardsKnown && numbers.missingStandards.length > 0) {
    parts.push(<Part key="s" n={numbers.missingStandards.length} one="standard missing" many="standards missing" count="missingStandards" />);
  }
  if (numbers.removed > 0) parts.push(<Part key="r" n={numbers.removed} one="removed by an engineer" many="removed by an engineer" />);
  return (
    <p data-testid="ws-sheet-counts" className="text-sm text-slateish-300">
      {parts.map((p, i) => <span key={i}>{i > 0 && ", "}{p}</span>)}
    </p>
  );
}
