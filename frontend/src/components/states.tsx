/**
 * Shared loading / empty / error / disconnected states.
 *
 * The rule these exist to enforce: when the backend is unreachable the UI says
 * so plainly. It never spins forever, and it never keeps showing the last
 * numbers it saw as though they were live. A stale number presented as current
 * is the same class of lie as a status field that reports work it is not doing.
 */
import type { ReactNode } from "react";

import { START_BACKEND_COMMAND } from "../../../contracts/runtime";
import type { ApiError } from "../types/api";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-slateish-400" role="status" aria-live="polite">
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-ink-500 border-t-signal-400"
      />
      <span className="text-sm">{label}…</span>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-ink-600 bg-ink-850/60 p-10 text-center">
      <p className="text-slateish-300">{title}</p>
      {hint && <p className="mt-1 text-sm text-slateish-400">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-danger-500/50 bg-danger-500/10 p-4 text-sm"
    >
      <p className="font-medium text-danger-500">Request failed</p>
      <p className="mt-1 text-slateish-300">{error.message}</p>
      <p className="mt-1 font-mono text-xs text-slateish-400">code: {error.code}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-ink-500 px-3 py-1 text-slateish-200 hover:bg-ink-700"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/**
 * Shown whenever the API cannot be reached. Deliberately blunt: an operator
 * must never mistake a dead backend for a quiet one.
 */
export function DisconnectedState({ onRetry }: { onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-warn-500/50 bg-warn-500/10 p-5 text-sm"
    >
      <p className="font-medium text-warn-500">The backend is not running</p>
      <p className="mt-2 text-slateish-300">
        Nothing on this screen is live. Any figures shown elsewhere are the last
        values received and may be out of date.
      </p>
      <pre className="mt-3 overflow-x-auto rounded bg-ink-900 p-3 font-mono text-xs text-slateish-300">
{START_BACKEND_COMMAND}
      </pre>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-warn-500/60 px-3 py-1 text-warn-500 hover:bg-warn-500/15"
        >
          Retry connection
        </button>
      )}
    </div>
  );
}

export function NotBuiltYet({ name }: { name: string }) {
  return (
    <div className="rounded-lg border border-dashed border-ink-600 bg-ink-850/60 p-12 text-center">
      <p className="text-lg text-slateish-300">{name}</p>
      <p className="mt-2 text-sm text-slateish-400">
        Not built yet. This screen is a placeholder so the navigation is honest
        about what exists.
      </p>
    </div>
  );
}
