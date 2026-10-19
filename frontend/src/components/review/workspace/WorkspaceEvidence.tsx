/**
 * OWNER: builder C. The evidence panel for the review workspace.
 *
 * It IS the existing CrsEvidenceDrawer (same page image, quote, rule,
 * history and keys), with two display-only changes:
 *   1. the drawer is handed a copy of the row whose finding texts have their
 *      codes rewritten as plain words (`plainText`); ids, pages and statuses
 *      are untouched, so history and page marks still line up;
 *   2. a "What the review noted" block lists each code the row's findings
 *      carry, in plain words, the raw code folded under "Details".
 * Nothing here changes a stored value.
 */
import { useMemo } from "react";

import type { ReviewFinding } from "../../../types/api";
import { CrsEvidenceDrawer, type CrsEvidenceDrawerProps } from "../crs/CrsEvidenceDrawer";
import type { CrsRow } from "../crs/crsRows";
import { PlainTerm } from "./PlainTerm";
import { type FoundCode, codesIn, plainText } from "./plainWords";

/** The finding texts the drawer shows that the review wrote (not the
 *  contractor's quote and not the engineer's own wording). */
const REVIEW_TEXTS = ["finding", "required_action", "requirement_source_text", "requirement", "ai_rationale"] as const;

function plainFinding(f: ReviewFinding): ReviewFinding {
  const copy = { ...f };
  for (const field of REVIEW_TEXTS) {
    const value = f[field];
    if (typeof value === "string") copy[field] = plainText(value);
  }
  return copy;
}

/** Every code the row's findings carry: the codes inside the review's texts,
 *  then the leading finding's compliance status. Each once. */
function rowCodes(row: CrsRow): FoundCode[] {
  const found: FoundCode[] = [];
  for (const f of row.findings) {
    for (const field of REVIEW_TEXTS) found.push(...codesIn(f[field]));
  }
  const status = row.findings[0]?.compliance_status;
  if (status) found.push({ code: status, kind: "status" });
  const seen = new Set<string>();
  return found.filter((c) => (seen.has(c.code) ? false : (seen.add(c.code), true)));
}

export function WorkspaceEvidence(props: CrsEvidenceDrawerProps) {
  const { row } = props;
  const shown = useMemo(() => ({ ...row, findings: row.findings.map(plainFinding) }), [row]);
  const codes = useMemo(() => rowCodes(row), [row]);
  const h = "text-xs font-semibold uppercase tracking-wide text-slateish-400";
  const extra = codes.length > 0 ? (
    <section aria-label="What the review noted" data-testid="ws-evidence-plain">
      <h3 className={h}>What the review noted</h3>
      <ul className="mt-1 space-y-1 text-sm text-slateish-200">
        {codes.map((c) => <li key={c.code}><PlainTerm code={c.code} kind={c.kind} /></li>)}
      </ul>
    </section>
  ) : null;
  return <CrsEvidenceDrawer {...props} row={shown} extra={extra} />;
}
