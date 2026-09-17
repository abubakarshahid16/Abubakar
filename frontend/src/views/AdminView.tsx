/**
 * Administration. Users, disciplines, and which discipline sees which document.
 *
 * THE ROUTES THIS SCREEN CALLS DO NOT EXIST YET. They are specified in
 * docs/design-admin-screen.md and are being implemented in parallel; until
 * they land every section renders "not built yet" rather than an empty table,
 * because an empty table is a claim about the data and a 404 is not.
 *
 * Rules this file exists to hold, all from the design document:
 *  - A null renders as NOTHING. Never a zero, never a dash, never "N/A".
 *    `last_login_at` is the one that matters and the one most likely to be
 *    given a placeholder by somebody being helpful.
 *  - Revoke and deactivate are destructive: quiet until hovered, danger
 *    coloured then, and they confirm before acting. A revoke that looks like
 *    a neutral button gets clicked like one.
 *  - A setup/reset token is shown ONCE, beside a sentence saying so. It is never
 *    re-rendered, never stored and never logged.
 *  - "The backend is not running" and "that request failed" never look alike.
 *
 * Data flow is by props; this component calls no api.* function itself.
 */
import { useEffect, useState } from "react";

import { DisconnectedState, EmptyState, Spinner } from "../components/states";
import type {
  AdminDiscipline,
  AdminGrantDocument,
  AdminUser,
  CreateUserRequest,
  CreatedUser,
  GrantRequest,
  LoadFailure,
} from "../types/admin";
import { management, reviews } from "../api/client";

function formatWhen(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+/, "").replace("Z", " UTC");
}

/**
 * The "seeded but useless" summary.
 *
 * A user with no discipline signs in successfully and sees an empty corpus;
 * during a demo that is indistinguishable from broken search. Counting it at
 * the top is the whole reason this screen is worth building - an admin should
 * not have to scan three tables to find out the system is quietly inert.
 */
export function summarise(
  users: AdminUser[] | null,
  disciplines: AdminDiscipline[] | null,
  documents: AdminGrantDocument[] | null,
): string[] {
  const lines: string[] = [];
  const noDiscipline = (users ?? []).filter((u) => u.active && u.warning === "no_discipline").length;
  const noDocuments = (disciplines ?? []).filter((d) => d.warning === "no_documents").length;
  const unseen = (documents ?? []).filter((d) => d.warning === "no_discipline_can_see_this").length;
  if (noDiscipline > 0) {
    lines.push(
      `${noDiscipline} user${noDiscipline === 1 ? " has" : "s have"} no discipline.`,
    );
  }
  if (noDocuments > 0) {
    lines.push(
      `${noDocuments} discipline${noDocuments === 1 ? " has" : "s have"} no documents.`,
    );
  }
  if (unseen > 0) {
    lines.push(
      `${unseen} document${unseen === 1 ? "" : "s"} ${unseen === 1 ? "is" : "are"} visible to nobody.`,
    );
  }
  return lines;
}

/** Failure states, kept visually distinct on purpose. An unbuilt route, a
 *  dead backend and a rejected request are three different facts and an
 *  operator acts differently on each. */
function SectionFailure({ failure, onRetry }: { failure: LoadFailure; onRetry: () => void }) {
  if (failure.kind === "offline") return <DisconnectedState onRetry={onRetry} />;
  if (failure.kind === "missing") {
    return (
      <div
        role="status"
        className="rounded-[var(--radius-md)] border border-dashed border-ink-600 bg-ink-850/60 p-6 text-sm"
      >
        <p className="text-slateish-300">This admin route is not built yet.</p>
        <p className="mt-1 text-slateish-400">
          The backend answered 404. That is not the same as having no data - nothing
          about users, disciplines or grants can be shown until the route exists.
        </p>
      </div>
    );
  }
  // Not the shared ErrorState: its ApiError type carries the closed shared
  // code union, and the admin codes are not in it yet (see AdminErrorCode).
  // Same shape and same colour, so the two read identically on screen.
  return (
    <div role="alert" className="rounded-[var(--radius-md)] border border-danger-500/50 bg-danger-500/10 p-4 text-sm">
      <p className="font-medium text-danger-500">That request failed</p>
      <p className="mt-1 text-slateish-300">{failure.message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1 text-slateish-200 hover:bg-ink-700"
      >
        Try again
      </button>
    </div>
  );
}

/**
 * A destructive action.
 *
 * Quiet until hovered, danger-coloured then, and it will not act on one
 * click: the first click asks, and only the confirm button calls through.
 * The cancel path is as easy to reach as the confirm path, because an
 * accidental revoke and an accidental confirm are the same mistake.
 */
export function DangerAction({
  label,
  confirmLabel,
  question,
  onConfirm,
  busy,
}: {
  label: string;
  confirmLabel: string;
  question: string;
  onConfirm: () => void;
  busy?: boolean;
}) {
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        disabled={busy}
        onClick={() => setAsking(true)}
        className="rounded-[var(--radius-xs)] border border-transparent px-2 py-1 text-xs text-slateish-400 transition-colors hover:border-danger-500 hover:bg-danger-500/10 hover:text-danger-500 focus-visible:border-danger-500 focus-visible:text-danger-500 disabled:opacity-50"
      >
        {label}
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-xs text-danger-500">{question}</span>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
        className="rounded-[var(--radius-xs)] border border-danger-500 bg-danger-500/10 px-2 py-1 text-xs font-medium text-danger-500 disabled:opacity-50"
      >
        {confirmLabel}
      </button>
      <button
        type="button"
        onClick={() => setAsking(false)}
        className="rounded-[var(--radius-xs)] border border-ink-500 px-2 py-1 text-xs text-slateish-300 hover:bg-ink-700"
      >
        Keep it
      </button>
    </span>
  );
}

/** The one place in the application that renders a secret. Once. */
function SetupTokenBlock({ created, onDismiss }: { created: CreatedUser; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div
      role="alert"
      className="rounded-[var(--radius-md)] border border-signal-500 bg-signal-500/10 p-4 text-sm"
    >
      <p className="font-medium text-slateish-200">
        Setup token for {created.email}
      </p>
      <p className="mt-1 text-slateish-300">
        This is shown once and cannot be retrieved again. Send it to the person now;
        if it is lost, create the user again. It expires{" "}
        {formatWhen(created.setup_token_expires_at)}.
      </p>
      <p className="mt-3 break-all rounded-[var(--radius-xs)] bg-ink-900 p-3 font-mono text-xs text-slateish-200">
        {created.setup_token}
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => {
            // Best effort: the clipboard API is unavailable over plain http on
            // some hosts, and a failed copy must not lose the only copy of the
            // token - the value stays on screen either way.
            void navigator.clipboard?.writeText(created.setup_token).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
          className="rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1 text-slateish-200 hover:bg-ink-700"
        >
          Copy
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-[var(--radius-xs)] border border-ink-500 px-3 py-1 text-slateish-200 hover:bg-ink-700"
        >
          Done - hide it
        </button>
        {copied && <span className="self-center text-xs text-slateish-400">Copied.</span>}
      </div>
    </div>
  );
}

function CreateUserForm({
  disciplines,
  onCreate,
  busy,
  error,
}: {
  disciplines: AdminDiscipline[] | null;
  onCreate: (body: CreateUserRequest) => void;
  busy: boolean;
  error: string | null;
}) {
  const [email, setEmail] = useState("");
  const [discipline, setDiscipline] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  return (
    <form
      className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-800 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onCreate({
          email: email.trim(),
          disciplines: discipline ? [discipline] : [],
          is_admin: isAdmin,
        });
      }}
    >
      <h3 className="text-sm font-medium text-slateish-200">Add a user</h3>
      {/* No password field, deliberately. A password typed here is a password
          an admin knows and a password in a request body is a password in a
          log - this repo found exactly that defect in its 422 handler. The
          user redeems a one-time token at first sign-in instead. */}
      <p className="mt-1 text-xs text-slateish-400">
        No password is set here. Creating the user produces a one-time setup token,
        shown once, which they redeem when they first sign in.
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-slateish-400">
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-64 rounded-[var(--radius-xs)] border border-ink-500 bg-ink-900 px-2 py-1 text-sm text-slateish-200"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slateish-400">
          Discipline
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value)}
            className="w-56 rounded-[var(--radius-xs)] border border-ink-500 bg-ink-900 px-2 py-1 text-sm text-slateish-200"
          >
            {/* An empty choice is offered because the state exists anyway, and
                the summary at the top names it the moment it does. Hiding it
                here would only mean creating the user and then wondering. */}
            <option value="">No discipline yet</option>
            {(disciplines ?? []).map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-1 text-xs text-slateish-300">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => setIsAdmin(e.target.checked)}
          />
          Also an administrator
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-[var(--radius-xs)] border border-signal-500 bg-signal-500/10 px-3 py-1 text-sm text-signal-500 disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create user"}
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger-500">
          {error}
        </p>
      )}
    </form>
  );
}

export interface AdminViewProps {
  /** null = still loading. A failure is carried separately so an empty list
   *  and a failed request are never the same rendering. */
  users: AdminUser[] | null;
  usersFailure: LoadFailure | null;
  disciplines: AdminDiscipline[] | null;
  disciplinesFailure: LoadFailure | null;
  documents: AdminGrantDocument[] | null;
  documentsFailure: LoadFailure | null;

  /** Set only immediately after a successful create, and cleared on dismiss.
   *  Never re-fetched: the token is not retrievable a second time. */
  created: CreatedUser | null;
  createBusy: boolean;
  createError: string | null;
  onCreateUser: (body: CreateUserRequest) => void;
  onDismissCreated: () => void;

  onDeactivateUser: (userId: string) => void;
  onResetPassword?: (userId: string) => void;
  onGrant: (body: GrantRequest) => void;
  onRevoke: (body: GrantRequest) => void;
  onRetry: () => void;
  /** A row-level action in flight, so the row it belongs to can say so. */
  busyKey: string | null;
}

export function AdminView(props: AdminViewProps) {
  const {
    users,
    usersFailure,
    disciplines,
    disciplinesFailure,
    documents,
    documentsFailure,
    created,
    createBusy,
    createError,
    onCreateUser,
    onDismissCreated,
    onDeactivateUser,
    onResetPassword = () => undefined,
    onGrant,
    onRevoke,
    onRetry,
    busyKey,
  } = props;

  const summary = summarise(users, disciplines, documents);
  const disciplineNames = (disciplines ?? []).map((d) => d.name);
  const [baselineRules, setBaselineRules] = useState<import("../types/api").ReviewBaselineRule[]>([]);
  const [baselineType, setBaselineType] = useState("");
  const [baselineTarget, setBaselineTarget] = useState("");
  const [baselineMessage, setBaselineMessage] = useState<string | null>(null);
  const [editingBaseline, setEditingBaseline] = useState<string | null>(null);
  const [summarySchedule, setSummarySchedule] = useState("disabled");
  useEffect(() => { void reviews.baselineRules().then((result) => { if (result.ok) setBaselineRules(result.data.rules ?? []); }); void management.summarySchedule().then((result) => { if (result.ok) setSummarySchedule(result.data.schedule ?? "disabled"); }); }, []);
  async function createBaselineRule() {
    if (!baselineType.trim() || !baselineTarget.trim()) return;
    const result = editingBaseline
      ? await reviews.updateBaselineRule(editingBaseline, { submittal_doc_type: baselineType.trim(), baseline_doc_type: baselineTarget.trim(), priority: 0, active: true })
      : await reviews.createBaselineRule({ submittal_doc_type: baselineType.trim(), baseline_doc_type: baselineTarget.trim(), priority: 0, active: true });
    if (result.ok) { setBaselineRules((current) => editingBaseline ? current.map((rule) => rule.id === result.data.id ? result.data : rule) : [result.data, ...current]); setBaselineType(""); setBaselineTarget(""); setEditingBaseline(null); setBaselineMessage(editingBaseline ? "Baseline rule updated." : "Baseline rule created."); }
    else setBaselineMessage(result.error.message);
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-xl font-semibold text-slateish-200">Administration</h1>
        <p className="mt-1 text-sm text-slateish-400">
          Users, disciplines, and which discipline can see which document. Grants are
          per discipline, never per person, so adding somebody to a team gives them the
          team's documents.
        </p>
      </header>

      {summary.length > 0 && (
        <section
          role="status"
          aria-label="Access problems"
          className="rounded-[var(--radius-md)] border border-warn-500/50 bg-warn-500/10 p-4 text-sm"
        >
          <p className="font-medium text-warn-500">This system is seeded but not usable</p>
          <p className="mt-1 text-slateish-300">{summary.join(" ")}</p>
          <p className="mt-2 text-slateish-400">
            Each of these looks like broken search to the person it affects: they sign in
            successfully and find nothing.
          </p>
        </section>
      )}

      {created && <SetupTokenBlock created={created} onDismiss={onDismissCreated} />}

      <section aria-label="Engineering review administration" className="space-y-4">
        <h2 className="text-sm font-semibold text-slateish-200">Engineering review controls</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-800 p-4">
            <h3 className="text-sm font-medium text-slateish-200">Baseline rules</h3>
            <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-slateish-400"><tr><th className="px-2 py-1">Submittal type</th><th className="px-2 py-1">Baseline type</th><th className="px-2 py-1">Priority</th><th /></tr></thead><tbody>{baselineRules.map((rule) => <tr key={rule.id} className="border-t border-ink-600"><td className="px-2 py-2 text-slateish-200">{rule.submittal_doc_type || "Any"}</td><td className="px-2 py-2 text-slateish-200">{rule.baseline_doc_type}</td><td className="px-2 py-2 text-slateish-400">{rule.priority}</td><td className="px-2 py-2"><button type="button" onClick={() => { setEditingBaseline(rule.id); setBaselineType(rule.submittal_doc_type || ""); setBaselineTarget(rule.baseline_doc_type); }} className="text-signal-400 hover:underline">Edit</button></td></tr>)}</tbody></table></div>
            <div className="mt-3 flex flex-wrap gap-2"><input aria-label="Submittal document type" value={baselineType} onChange={(e) => setBaselineType(e.target.value)} placeholder="Submittal type" className="w-36 rounded-[var(--radius-xs)] border border-ink-500 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" /><input aria-label="Baseline document type" value={baselineTarget} onChange={(e) => setBaselineTarget(e.target.value)} placeholder="Baseline type" className="w-36 rounded-[var(--radius-xs)] border border-ink-500 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200" /><button type="button" onClick={() => void createBaselineRule()} className="rounded-[var(--radius-xs)] bg-signal-500/20 px-3 py-1.5 text-xs text-signal-300">{editingBaseline ? "Save rule" : "Add rule"}</button></div>
            {baselineMessage && <p role="status" className="mt-2 text-xs text-slateish-400">{baselineMessage}</p>}
          </div>
          <div className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-800 p-4"><h3 className="text-sm font-medium text-slateish-200">Management summaries</h3><p className="mt-1 text-xs text-slateish-400">Choose the reporting cadence used by the scheduled summary job.</p><div className="mt-3 flex flex-wrap items-center gap-2"><select aria-label="Summary schedule" value={summarySchedule} onChange={(e) => { const next = e.target.value as "disabled" | "daily" | "weekly"; setSummarySchedule(next); void management.setSummarySchedule({ schedule: next, weekday_utc: 0, hour_utc: 8 }); }} className="rounded-[var(--radius-xs)] border border-ink-500 bg-ink-900 px-2 py-1.5 text-xs text-slateish-200"><option value="disabled">Disabled</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select><button type="button" onClick={() => void management.emailSummary()} className="rounded-[var(--radius-xs)] bg-signal-500/20 px-3 py-1.5 text-xs text-signal-300">Send now</button></div><p className="mt-2 text-xs text-slateish-500">Selected cadence: {summarySchedule}.</p></div>
        </div>
      </section>

      <section aria-labelledby="admin-users-heading" className="space-y-3">
        <h2 id="admin-users-heading" className="text-sm font-semibold text-slateish-200">
          Users
        </h2>

        <CreateUserForm
          disciplines={disciplines}
          onCreate={onCreateUser}
          busy={createBusy}
          error={createError}
        />

        {usersFailure && <SectionFailure failure={usersFailure} onRetry={onRetry} />}
        {!usersFailure && users === null && <Spinner label="Loading users" />}
        {!usersFailure && users !== null && users.length === 0 && (
          <EmptyState title="No users" hint="Nobody can sign in to this deployment yet." />
        )}

        {!usersFailure && users !== null && users.length > 0 && (
          <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-600">
            <table className="w-full text-left text-sm">
              <thead className="bg-ink-850 text-xs uppercase text-slateish-400">
                <tr>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Disciplines</th>
                  <th className="px-3 py-2">Admin</th>
                  <th className="px-3 py-2">Created</th>
                  <th className="px-3 py-2">Last sign-in</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  // Keyed by user_id and every cell read from `u`. One user's
                  // data appearing in another's row is the failure mode of
                  // index keys plus row-level state; there is no row state
                  // here beyond the confirm, which is keyed with the row.
                  <tr key={u.user_id} className="border-t border-ink-600 align-top">
                    <td className="px-3 py-2 text-slateish-200">
                      {u.email}
                      {!u.active && (
                        <span className="ml-2 text-xs text-slateish-400">deactivated</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slateish-300">
                      {u.disciplines.length > 0 ? (
                        u.disciplines.join(", ")
                      ) : (
                        <span className="text-warn-500">
                          No discipline - this account sees nothing
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slateish-300">
                      {/* A false flag is not a fact worth a word. */}
                      {u.is_admin ? "Admin" : null}
                    </td>
                    <td className="px-3 py-2 text-slateish-400">{formatWhen(u.created_at)}</td>
                    <td className="px-3 py-2 text-slateish-400">
                      {/* null renders as NOTHING. Not a dash, not "never",
                          not a zero - a placeholder invents a fact the
                          server did not send. */}
                      {u.last_login_at ? formatWhen(u.last_login_at) : null}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {u.active && (
                        <div className="flex justify-end gap-2">
                          <button type="button"
                            disabled={busyKey === `reset:${u.user_id}`}
                            onClick={() => onResetPassword(u.user_id)}
                            className="rounded-[var(--radius-xs)] border border-ink-500 px-2 py-1 text-xs text-slateish-300 hover:bg-ink-700 disabled:opacity-50">
                            Reset password
                          </button>
                          <DangerAction
                            label="Deactivate"
                            confirmLabel="Deactivate"
                            question={`Deactivate ${u.email}?`}
                            busy={busyKey === `user:${u.user_id}`}
                            onConfirm={() => onDeactivateUser(u.user_id)}
                          />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="admin-disciplines-heading" className="space-y-3">
        <h2 id="admin-disciplines-heading" className="text-sm font-semibold text-slateish-200">
          Disciplines
        </h2>

        {disciplinesFailure && (
          <SectionFailure failure={disciplinesFailure} onRetry={onRetry} />
        )}
        {!disciplinesFailure && disciplines === null && <Spinner label="Loading disciplines" />}
        {!disciplinesFailure && disciplines !== null && disciplines.length === 0 && (
          <EmptyState title="No disciplines" />
        )}

        {!disciplinesFailure && disciplines !== null && disciplines.length > 0 && (
          <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-600">
            <table className="w-full text-left text-sm">
              <thead className="bg-ink-850 text-xs uppercase text-slateish-400">
                <tr>
                  <th className="px-3 py-2">Discipline</th>
                  <th className="px-3 py-2">Users</th>
                  <th className="px-3 py-2">Documents</th>
                </tr>
              </thead>
              <tbody>
                {disciplines.map((d) => (
                  <tr key={d.name} className="border-t border-ink-600">
                    <td className="px-3 py-2 text-slateish-200">{d.name}</td>
                    <td className="px-3 py-2 text-slateish-300">{d.user_count}</td>
                    <td className="px-3 py-2 text-slateish-300">
                      {d.document_count}
                      {d.warning === "no_documents" && (
                        <span className="ml-2 text-warn-500">
                          Nobody in this discipline can find anything
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="admin-documents-heading" className="space-y-3">
        <h2 id="admin-documents-heading" className="text-sm font-semibold text-slateish-200">
          Documents and who can see them
        </h2>

        {documentsFailure && <SectionFailure failure={documentsFailure} onRetry={onRetry} />}
        {!documentsFailure && documents === null && <Spinner label="Loading documents" />}
        {!documentsFailure && documents !== null && documents.length === 0 && (
          <EmptyState title="No documents" hint="Upload a document before granting access to it." />
        )}

        {!documentsFailure && documents !== null && documents.length > 0 && (
          <ul className="space-y-2">
            {documents.map((doc) => (
              <li
                key={doc.document_id}
                className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-800 p-3"
              >
                <p className="text-sm text-slateish-200">{doc.filename}</p>
                {doc.warning === "no_discipline_can_see_this" && (
                  <p className="mt-1 text-xs text-warn-500">
                    No discipline can see this. It is invisible in every search, which
                    looks exactly like a failed upload.
                  </p>
                )}

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {disciplineNames.map((name) => {
                    const granted = doc.disciplines.includes(name);
                    const key = `grant:${doc.document_id}:${name}`;
                    if (granted) {
                      return (
                        <span
                          key={name}
                          className="inline-flex items-center gap-2 rounded-[var(--radius-xs)] border border-ink-500 bg-ink-850 px-2 py-1 text-xs text-slateish-200"
                        >
                          {name}
                          <DangerAction
                            label="Revoke"
                            confirmLabel="Revoke"
                            question={`Revoke ${name}?`}
                            busy={busyKey === key}
                            onConfirm={() =>
                              onRevoke({ document_id: doc.document_id, discipline: name })
                            }
                          />
                        </span>
                      );
                    }
                    return (
                      <button
                        key={name}
                        type="button"
                        disabled={busyKey === key}
                        onClick={() => onGrant({ document_id: doc.document_id, discipline: name })}
                        className="rounded-[var(--radius-xs)] border border-ink-500 px-2 py-1 text-xs text-slateish-400 hover:bg-ink-700 hover:text-slateish-200 disabled:opacity-50"
                      >
                        Grant {name}
                      </button>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-xs text-slateish-400">
        Reset tokens are shown once and expire after 24 hours. The user enters the token on the sign-in screen.
      </p>
    </div>
  );
}
