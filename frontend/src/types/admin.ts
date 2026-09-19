/**
 * The admin route contract, transcribed from docs/design-admin-screen.md.
 *
 * These shapes are written BEFORE the routes exist. That is the point: the
 * document exists because contract drift (`claim` vs `text`, `facet` as string
 * vs list) cost this project an hour and was found by a 500 in front of a live
 * request rather than by a type. If a shape here is wrong, change the design
 * document first and say so - do not diverge silently.
 *
 * Local to the admin screen rather than in /contracts/types.ts because the
 * backend agent owns that file for these routes; when the routes land, these
 * declarations should be deleted in favour of the shared ones.
 */
/** Warnings are enums, never prose. The server names the condition and the UI
 *  owns the wording - a message the UI has to parse for meaning is a contract
 *  that breaks silently when the wording changes. */
export type UserWarning = "no_discipline";
export type DisciplineWarning = "no_documents";
export type DocumentWarning = "no_discipline_can_see_this";

export interface AdminUser {
  user_id: string;
  email: string;
  disciplines: string[];
  is_admin: boolean;
  active: boolean;
  created_at: string;
  /** null for a user who has never signed in. Renders as NOTHING - never a
   *  dash, never a zero, never "never". */
  last_login_at: string | null;
  warning: UserWarning | null;
}

export interface AdminUserList {
  users: AdminUser[];
}

export interface CreateUserRequest {
  email: string;
  disciplines: string[];
  is_admin: boolean;
}

/** The only response in the application that carries a secret.
 *
 *  `shown_once: true` is the contract that it is not retrievable again. It is
 *  never stored, never logged, and never rendered a second time. */
export interface CreatedUser {
  user_id: string;
  email: string;
  setup_token: string;
  setup_token_expires_at: string;
  shown_once: boolean;
}

export interface DeactivatedUser {
  user_id: string;
  active: boolean;
}

export interface AdminDiscipline {
  name: string;
  user_count: number;
  document_count: number;
  warning: DisciplineWarning | null;
}

export interface AdminDisciplineList {
  disciplines: AdminDiscipline[];
}

export interface AdminGrantDocument {
  document_id: string;
  filename: string;
  /** The disciplines that can see this document. Empty means nobody can, and
   *  the document is invisible in every search - which looks exactly like a
   *  broken upload. */
  disciplines: string[];
  warning: DocumentWarning | null;
}

export interface AdminGrantList {
  documents: AdminGrantDocument[];
}

export interface GrantRequest {
  document_id: string;
  discipline: string;
}

export interface GrantResult {
  document_id: string;
  discipline: string;
  granted: boolean;
}

/**
 * The admin error codes, from the design document's "Error codes the UI
 * switches on".
 *
 * NOT added to ApiError in /contracts/types.ts: that union is shared and the
 * backend agent owns it for these routes. Widening it from here would be the
 * silent divergence this whole document exists to prevent. When the routes
 * land, these codes belong in the shared union and this alias should go.
 */
export type AdminErrorCode =
  | "email_in_use"
  | "unknown_discipline"
  | "invalid_email"
  | "cannot_deactivate_self"
  | "unknown_document"
  | "not_found"
  | "internal";

export interface AdminError {
  code: AdminErrorCode | string;
  message: string;
}

/** The same three-way result api/client.ts returns, and for the same reason:
 *  a network failure must stay distinguishable from an API error all the way
 *  to the screen. Declared here rather than reusing Result<T> only because
 *  Result carries the shared ApiError code union - see AdminErrorCode. */
export type AdminResult<T> =
  | { ok: true; data: T }
  | { ok: false; disconnected: true; error: AdminError }
  | { ok: false; disconnected: false; error: AdminError };

/**
 * The transport the screen needs, as an interface so a test can supply one
 * without a fetch mock and so the real implementation can move into
 * api/client.ts (where the bearer token lives) without touching the screen.
 */
// ------------------------------------------ the read-only database explorer
//
// A WINDOW, NOT A WORKBENCH. There is no write shape anywhere in this block,
// deliberately: a screen built against these types cannot discover an edit
// path, because none is described.

export interface DbTable {
  name: string;
  row_count: number;
}

export interface DbColumn {
  name: string;
  type?: string | null;
  notnull?: boolean;
  pk?: boolean;
  /** The column's NAME says it holds credential material, so its values
   *  arrive masked. The column itself is still listed - hiding it would
   *  misreport the shape of the table. */
  sensitive?: boolean;
}

export interface DbTableInfo {
  name: string;
  columns: DbColumn[];
  row_count: number;
}

export interface DbRows {
  name: string;
  columns: string[];
  /** Values as stored, except credential-shaped columns, which the SERVER
   *  replaced before they reached the wire. Never masked here. */
  rows: unknown[][];
  offset: number;
  limit: number;
  /** The whole table. Without it a page implies completeness it lacks. */
  total: number;
  masked_columns?: string[];
}

export interface AdminClient {
  users(): Promise<AdminResult<AdminUserList>>;
  createUser(body: CreateUserRequest): Promise<AdminResult<CreatedUser>>;
  deactivateUser(userId: string): Promise<AdminResult<DeactivatedUser>>;
  issuePasswordReset?(userId: string): Promise<AdminResult<CreatedUser>>;
  disciplines(): Promise<AdminResult<AdminDisciplineList>>;
  grants(): Promise<AdminResult<AdminGrantList>>;
  grant(body: GrantRequest): Promise<AdminResult<GrantResult>>;
  revoke(body: GrantRequest): Promise<AdminResult<GrantResult>>;
  /** Three reads and no write. Optional so an injected test double may omit
   *  them, exactly as `issuePasswordReset` above already is. */
  dbTables?(): Promise<AdminResult<{ tables: DbTable[] }>>;
  dbTable?(name: string): Promise<AdminResult<DbTableInfo>>;
  dbRows?(name: string, limit: number, offset: number): Promise<AdminResult<DbRows>>;
}

/**
 * Why a load produced no data. `offline` and `failed` are kept apart on
 * purpose: "the backend is not running" and "that request failed" reading the
 * same is a recorded defect in this project. `missing` is its own state
 * because these routes DO NOT EXIST YET - a 404 from an unbuilt route must not
 * render as "no users".
 */
export type LoadFailure =
  | { kind: "offline" }
  | { kind: "missing" }
  | { kind: "failed"; code: string; message: string };
