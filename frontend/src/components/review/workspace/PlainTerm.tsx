/**
 * OWNER: builder C. A stored code shown as plain words, with the raw code
 * folded under a native "Details" (nothing to click through for a manager,
 * still there for an engineer who needs the exact code).
 *
 * Words that are already plain show alone, with no fold. An empty code
 * renders nothing. Rendered as a <span>, so do not put it inside a <p>
 * (a <details> may not sit in a paragraph); use a <div> or <li>.
 */
import type { PlainTermProps } from "./contract";
import { plainWords } from "./plainWords";

export function PlainTerm({ code, kind = "any" }: PlainTermProps) {
  const entry = plainWords(code, kind);
  if (!entry.words) return null;
  if (entry.detail === null) return <span data-plain-term="">{entry.words}</span>;
  return (
    <span data-plain-term="" className="inline-flex flex-wrap items-baseline gap-x-2">
      <span>{entry.words}</span>
      <details className="inline-block text-xs text-slateish-400">
        <summary className="cursor-pointer select-none">Details</summary>
        <code className="font-mono text-slateish-300">{entry.detail}</code>
      </details>
    </span>
  );
}
