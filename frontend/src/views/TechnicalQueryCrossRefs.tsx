/** The other queries a request names (a CFC or TQ number in its text), one sentence each (builder C's handover to A, 27 Nov 2026).
 *  Looked up on the server with the CALLER's own visibility (technical_query_refs): a held query the caller may not open shows only
 *  the number the request itself carries, never its subject or status. Kit parts only: Tag for the number, LinkButton to open it. */
import type { TechnicalQuery } from "../api/technicalQueries";
import { LinkButton, Tag } from "../components/kit/Kit";
import { plainStatus } from "./technicalQueryQuestion";

export type CrossRef = NonNullable<TechnicalQuery["cross_refs"]>[number];

/** The server's own mark for these references ("The question names .... Read it in this app before you reply."): when the
 *  references are shown here, that mark is not repeated as a separate warning (one sentence per reference). */
export const REFS_MARK = /^The (?:request|question) names .+(?:held in this system|in this app before you reply)/;

export function TechnicalQueryCrossRefs({ refs, onOpen }: { refs: CrossRef[] | null | undefined; onOpen: (id: string) => void }) {
  if (!refs?.length) return null;
  return (
    <div data-testid="cross-refs" className="mt-3 text-sm">
      <p className="font-semibold text-slateish-200">Other queries this question names</p>
      <ul className="mt-1 space-y-1">
        {refs.map((r, i) => (
          <li key={`${r.reference}-${r.query_id ?? i}`} data-testid="cross-ref" className="text-slateish-300">
            <Tag>{r.reference}</Tag>{" "}
            {!r.held ? "is not in this app."
              : r.query_id ? <>is in this app{r.subject ? `: ${r.subject}` : ""}{r.status ? ` (${plainStatus(r.status).toLowerCase()})` : ""}. Read it before you reply: <LinkButton tone="action" onClick={() => onOpen(r.query_id!)}>open it</LinkButton>.</>
              : "is in this app, but you cannot open it. Ask its owner before you reply."}
          </li>
        ))}
      </ul>
    </div>
  );
}
