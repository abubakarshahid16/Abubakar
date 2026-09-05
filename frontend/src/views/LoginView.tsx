/**
 * Login screen. Rendered ABOVE the Shell, not inside it (design-authentication
 * section F): health stays unauthenticated, so the connection badge works here
 * and "backend offline" is distinguishable from "wrong password".
 *
 * Two rules this file exists to enforce:
 *  - ONE message for every credential failure. Unknown email and wrong password
 *    read identically, or the login page becomes an account-enumeration oracle.
 *    Rate limiting (429) is the single permitted exception: the user has to be
 *    told to wait, and 429 reveals nothing about which half was wrong.
 *  - The token lives in memory only. A reload signs you out. That is deliberate,
 *    and the user is told before they find out the hard way.
 *
 * Data flow is by props; this component calls no api.* function itself.
 */
import { useId, useState, type FormEvent } from "react";

import type { LoginRequest, Me } from "../types/analysis";

export type LoginOutcome =
  | { ok: true }
  | { ok: false; kind?: "credentials" | "rate_limited" | "offline"; message?: string };

// The ONE string. Never branch on which half was wrong.
const CREDENTIALS_MESSAGE = "That email and password did not match an account.";
const RATE_LIMITED_MESSAGE =
  "Too many sign-in attempts. Wait a minute and try again.";
const OFFLINE_MESSAGE =
  "The backend is not running, so sign-in cannot be checked. This is not a password problem.";

export function LoginView({
  onLogin,
  connected,
}: {
  /** Resolves with ok:false and an optional kind. A `message` on a
   *  credentials failure is deliberately IGNORED so a backend that
   *  distinguishes unknown-email from wrong-password cannot leak it here. */
  onLogin: (req: LoginRequest) => Promise<LoginOutcome>;
  connected: boolean;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailId = useId();
  const passwordId = useId();
  const errorId = useId();

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    if (!connected) {
      setError(OFFLINE_MESSAGE);
      return;
    }
    setSubmitting(true);
    try {
      const result = await onLogin({ email: email.trim(), password });
      if (!result.ok) {
        if (result.kind === "rate_limited") setError(result.message ?? RATE_LIMITED_MESSAGE);
        else if (result.kind === "offline") setError(OFFLINE_MESSAGE);
        else setError(CREDENTIALS_MESSAGE);
      }
    } catch {
      // A thrown error is a transport failure, not a credential verdict.
      setError(OFFLINE_MESSAGE);
    } finally {
      setSubmitting(false);
      setPassword("");
    }
  };

  const disabled = submitting;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-12">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slateish-200">Sign in</h1>
          <p className="mt-1 text-sm text-slateish-400">
            Local accounts only. Your role decides which documents you can see.
          </p>
        </div>
        <ConnectionLine connected={connected} />
      </header>

      <form onSubmit={submit} noValidate className="space-y-4" aria-describedby={errorId}>
        <div>
          <label htmlFor={emailId} className="block text-xs font-medium text-slateish-300">
            Email
          </label>
          <input
            id={emailId}
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            required
            disabled={disabled}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-200 placeholder:text-slateish-500 disabled:opacity-40"
          />
        </div>

        <div>
          <label htmlFor={passwordId} className="block text-xs font-medium text-slateish-300">
            Password
          </label>
          <input
            id={passwordId}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            disabled={disabled}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-200 disabled:opacity-40"
          />
        </div>

        {/* The single error region. aria-live so a screen reader hears the
            verdict without focus moving; role=alert for the same reason. */}
        <div id={errorId} role="alert" aria-live="assertive" className="min-h-[1.25rem]">
          {error && (
            <p className="rounded border border-danger-500/50 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">
              <span aria-hidden="true">! </span>
              {error}
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={disabled || email.length === 0 || password.length === 0}
          aria-busy={submitting}
          className="w-full rounded bg-signal-500/20 px-4 py-2 text-sm font-medium text-signal-300 ring-1 ring-signal-500/50 hover:bg-signal-500/30 disabled:opacity-40"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-6 text-xs text-slateish-400">
        Your session is held in memory only. Reloading or closing this page signs
        you out. This is deliberate: nothing about your login is written to disk.
      </p>
      <p className="mt-2 text-xs text-slateish-500">Nothing you type leaves this machine.</p>
    </main>
  );
}

/** A reduced copy of the Shell's badge for the two states that matter here.
 *  Text as well as colour: "offline" is the word, not just an amber dot. */
function ConnectionLine({ connected }: { connected: boolean }) {
  return connected ? (
    <span className="flex shrink-0 items-center gap-2 text-xs text-signal-400" role="status">
      <span aria-hidden className="h-2 w-2 rounded-full bg-signal-500" />
      Connected
    </span>
  ) : (
    <span
      className="flex shrink-0 items-center gap-2 text-xs font-medium text-warn-500"
      role="status"
      aria-live="assertive"
    >
      <span aria-hidden className="h-2 w-2 rounded-full bg-warn-500" />
      Backend offline
    </span>
  );
}

/**
 * Role badge for the shell header. Under auth_mode="disabled" there is no user,
 * and it says so quietly - never a placeholder name, because a made-up
 * "Administrator" on a report or a screen is a false attribution.
 */
export function RoleBadge({ me, onLogout }: { me: Me | null; onLogout: () => void }) {
  if (me === null) {
    return (
      <span className="text-xs text-slateish-500" role="status">
        Authentication disabled — no user identity
      </span>
    );
  }
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-slateish-200">{me.display_name}</span>
        {me.roles.length === 0 ? (
          <span className="text-slateish-500">no roles</span>
        ) : (
          me.roles.map((r) => (
            <span
              key={r}
              className="rounded bg-ink-700 px-2 py-0.5 text-[11px] text-slateish-300"
            >
              {r}
            </span>
          ))
        )}
      </span>
      <button
        type="button"
        onClick={onLogout}
        className="rounded border border-ink-600 px-2.5 py-1 text-xs text-slateish-300 transition-colors hover:bg-ink-700"
      >
        Sign out
      </button>
    </div>
  );
}
