/**
 * The container for AdminView: owns the API calls, hands the view data.
 *
 * THE ROUTES CALLED HERE DO NOT EXIST YET. They are specified, exactly, in
 * docs/design-admin-screen.md and are being implemented in parallel. Until
 * they land every read returns 404, and a 404 is reported to the view as
 * `missing` rather than as an empty list - "no users" is a claim about the
 * data and this screen is not entitled to make it.
 *
 * The transport is an interface (AdminClient) rather than a direct import
 * because api/client.ts has no admin section yet and is open in another
 * editor. `makeAdminClient` here mirrors that module's rules exactly - one
 * fetch, the bearer token attached in one place, a typed Result, and a network
 * failure kept distinct from an API error. When the admin block lands in
 * api/client.ts, delete makeAdminClient and pass that object in instead;
 * nothing else in this file changes.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  AdminClient,
  AdminResult,
  AdminDiscipline,
  AdminGrantDocument,
  AdminUser,
  CreateUserRequest,
  CreatedUser,
  GrantRequest,
  LoadFailure,
} from "../types/admin";
import { AdminView } from "./AdminView";

const BASE = "/api";
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** Why a failed call failed, in the two words a reader can act on. Codes are
 *  the contract's own; anything else is a generic failure. */
const MESSAGES: Record<string, string> = {
  email_in_use: "That email address already has an account.",
  invalid_email: "That is not an email address the backend will accept.",
  unknown_discipline: "That discipline does not exist on the backend.",
  cannot_deactivate_self: "You cannot deactivate your own account. Ask another administrator.",
  unknown_document: "That document is no longer on the backend.",
  not_found: "The backend does not know about that.",
};

async function adminRequest<T>(
  path: string,
  token: string | null,
  init?: RequestInit,
): Promise<AdminResult<T>> {
  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch (e) {
    // fetch rejects only at the network level: nothing served the request.
    return {
      ok: false,
      disconnected: true,
      error: {
        code: "internal",
        message: `Cannot reach the backend. ${e instanceof Error ? e.message : "Network request failed."}`,
      },
    };
  }

  if (!response.ok) {
    if (GATEWAY_STATUSES.has(response.status)) {
      return {
        ok: false,
        disconnected: true,
        error: { code: "internal", message: "Cannot reach the backend. Nothing answered on the API port." },
      };
    }
    let code = response.status === 404 ? "not_found" : "internal";
    let message = MESSAGES[code] ?? "The backend could not complete this request.";
    try {
      const body = await response.json();
      const raw = body?.detail ?? body;
      if (raw && typeof raw === "object" && "code" in raw) {
        code = String(raw.code);
        message = MESSAGES[code] ?? String(raw.message ?? message);
      }
    } catch {
      /* keep the fallback */
    }
    return { ok: false, disconnected: false, error: { code, message } };
  }

  return { ok: true, data: (await response.json()) as T };
}

/** The admin routes as api/client.ts would express them. See the file note. */
export function makeAdminClient(token: () => string | null): AdminClient {
  const json = (body: unknown): RequestInit => ({
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return {
    users: () => adminRequest("/admin/users", token()),
    createUser: (body) => adminRequest("/admin/users", token(), { method: "POST", ...json(body) }),
    deactivateUser: (id) =>
      adminRequest(`/admin/users/${encodeURIComponent(id)}`, token(), { method: "DELETE" }),
    issuePasswordReset: (id) =>
      adminRequest(`/admin/users/${encodeURIComponent(id)}/password-reset`, token(), { method: "POST" }),
    disciplines: () => adminRequest("/admin/disciplines", token()),
    grants: () => adminRequest("/admin/grants", token()),
    // PUT and DELETE on a grant are idempotent by contract, so a retried click
    // cannot double-grant and revoking something already revoked is not an error.
    grant: (body) => adminRequest("/admin/grants", token(), { method: "PUT", ...json(body) }),
    revoke: (body) => adminRequest("/admin/grants", token(), { method: "DELETE", ...json(body) }),
  };
}

/** An unreachable backend and a rejected request get different sentences, and
 *  a contract error code gets wording the UI owns rather than whatever prose
 *  the server happened to send. */
function explain(r: Extract<AdminResult<unknown>, { ok: false }>, consequence: string): string {
  if (r.disconnected) return `The backend is not running, ${consequence}.`;
  return MESSAGES[r.error.code] ?? r.error.message;
}

/** Three conditions, never collapsed into one: unreachable backend, unbuilt
 *  route, rejected request. */
function toFailure(r: Extract<AdminResult<unknown>, { ok: false }>): LoadFailure {
  if (r.disconnected) return { kind: "offline" };
  if (r.error.code === "not_found") return { kind: "missing" };
  return { kind: "failed", code: r.error.code, message: MESSAGES[r.error.code] ?? r.error.message };
}

export function AdminScreen({
  client,
  tokenProvider = () => null,
}: {
  /** Injected in tests. In the app the default is used. */
  client?: AdminClient;
  /** Reads the bearer token from api/client.ts, which owns it. */
  tokenProvider?: () => string | null;
}) {
  const api = useMemo(
    () => client ?? makeAdminClient(tokenProvider),
    [client, tokenProvider],
  );

  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [usersFailure, setUsersFailure] = useState<LoadFailure | null>(null);
  const [disciplines, setDisciplines] = useState<AdminDiscipline[] | null>(null);
  const [disciplinesFailure, setDisciplinesFailure] = useState<LoadFailure | null>(null);
  const [documents, setDocuments] = useState<AdminGrantDocument[] | null>(null);
  const [documentsFailure, setDocumentsFailure] = useState<LoadFailure | null>(null);

  const [created, setCreated] = useState<CreatedUser | null>(null);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [u, d, g] = await Promise.all([api.users(), api.disciplines(), api.grants()]);

    // Each section keeps its own outcome. One dead route must not blank the
    // other two, and a failure must never leave a stale list on screen
    // looking live.
    if (u.ok) {
      setUsers(u.data.users);
      setUsersFailure(null);
    } else {
      setUsers(null);
      setUsersFailure(toFailure(u));
    }
    if (d.ok) {
      setDisciplines(d.data.disciplines);
      setDisciplinesFailure(null);
    } else {
      setDisciplines(null);
      setDisciplinesFailure(toFailure(d));
    }
    if (g.ok) {
      setDocuments(g.data.documents);
      setDocumentsFailure(null);
    } else {
      setDocuments(null);
      setDocumentsFailure(toFailure(g));
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const createUser = useCallback(
    async (body: CreateUserRequest) => {
      setCreateBusy(true);
      setCreateError(null);
      const r = await api.createUser(body);
      setCreateBusy(false);
      if (r.ok) {
        // Held in state for this render only, never persisted and never
        // logged. The token is not retrievable a second time, so the list
        // refresh below cannot and must not bring it back.
        setCreated(r.data);
        await load();
        return;
      }
      setCreateError(explain(r, "so nothing was created"));
    },
    [api, load],
  );

  const deactivateUser = useCallback(
    async (userId: string) => {
      setBusyKey(`user:${userId}`);
      const r = await api.deactivateUser(userId);
      setBusyKey(null);
      if (!r.ok) {
        setCreateError(explain(r, "so nothing was changed"));
        return;
      }
      await load();
    },
    [api, load],
  );

  const issuePasswordReset = useCallback(async (userId: string) => {
    setBusyKey(`reset:${userId}`);
    setCreateError(null);
    const result = api.issuePasswordReset
      ? await api.issuePasswordReset(userId)
      : { ok: false as const, disconnected: false as const,
          error: { code: "not_found", message: "Password reset could not be completed." } };
    setBusyKey(null);
    if (result.ok) setCreated(result.data);
    else setCreateError(explain(result, "so no reset token was issued"));
  }, [api]);

  const changeGrant = useCallback(
    async (body: GrantRequest, grant: boolean) => {
      setBusyKey(`grant:${body.document_id}:${body.discipline}`);
      const r = grant ? await api.grant(body) : await api.revoke(body);
      setBusyKey(null);
      if (!r.ok) {
        setCreateError(explain(r, "so access was not changed"));
        return;
      }
      // Re-read rather than patch locally: a revoke takes effect on the next
      // request by contract, and the counts and warnings all move with it.
      await load();
    },
    [api, load],
  );

  return (
    <AdminView
      users={users}
      usersFailure={usersFailure}
      disciplines={disciplines}
      disciplinesFailure={disciplinesFailure}
      documents={documents}
      documentsFailure={documentsFailure}
      created={created}
      createBusy={createBusy}
      createError={createError}
      onCreateUser={(body) => void createUser(body)}
      onDismissCreated={() => setCreated(null)}
      onDeactivateUser={(id) => void deactivateUser(id)}
      onResetPassword={(id) => void issuePasswordReset(id)}
      onGrant={(body) => void changeGrant(body, true)}
      onRevoke={(body) => void changeGrant(body, false)}
      onRetry={() => void load()}
      busyKey={busyKey}
    />
  );
}
