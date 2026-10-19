/**
 * v2.1 (N2): one failed request on screen: the plain words first, the
 * server's own words folded under "Details" for whoever looks into it.
 */
import type { PlainError } from "./plainError";

export function PlainErrorLine({ error, className = "text-sm text-red-400", testId }: {
  error: PlainError; className?: string; testId?: string;
}) {
  return (
    <div role="alert" data-testid={testId} className={className}>
      <p>{error.words}</p>
      {error.detail && (
        <details className="mt-1 text-xs text-slateish-400">
          <summary className="cursor-pointer">Details</summary>
          <p className="mt-1 break-words">{error.detail}</p>
        </details>
      )}
    </div>
  );
}
