/** The other queries a request names (a CFC or TQ number in its text), one sentence each (builder C's handover to A, 27 Nov 2026).
 *  Looked up on the server with the CALLER's own visibility (technical_query_refs): a held query the caller may not open shows only
 *  the number the request itself carries, never its subject or status. Kit parts only: Tag for the number, LinkButton to open it. */
import type { TechnicalQuery } from "../api/technicalQueries";
import { LinkButton, Tag } from "../components/kit/Kit";
import { plainStatus } from "./technicalQueryQuestion";

export type CrossRef = NonNullable<TechnicalQuery["cross_refs"]>[number];

/** The server's own mark for these references ("The request names ..., held in this system: see it before replying."): when the
 *  references are shown here, that mark is not repeated as a separate warning (one sentence per reference). */
export const REFS_MARK = /^The request names .+ held in this system/;

export function TechnicalQueryCrossRefs({ refs, onOpen }: { refs: CrossRef[] | null | undefined; onOpen: (id: string) => void }) {
  if (!refs?.length) return null;
  return (
    <div data-testid="cross-refs" className="mt-3 text-sm">
      <p className="font-semibold text-slateish-200">Other queries this request names</p>
      <ul className="mt-1 space-y-1">
        {refs.map((r, i) => (
          <li key={`${r.reference}-${r.query_id ?? i}`} data-testid="cross-ref" className="text-slateish-300">
            <Tag>{r.reference}</Tag>{" "}
            {!r.held ? "is not held in this system."
              : r.query_id ? <>is held here{r.subject ? `: ${r.subject}` : ""}{r.status ? ` (${plainStatus(r.status).toLowerCase()})` : ""}. Read it before replying: <LinkButton tone="action" onClick={() => onOpen(r.query_id!)}>open it</LinkButton>.</>
              : "is held here, but you may not open it: ask whoever handles it before replying."}
          </li>
        ))}
      </ul>
    </div>
  );
}
