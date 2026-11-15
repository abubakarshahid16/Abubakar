/** "How it was reviewed": the nine roles and what each did, read from the run's stored record (nine-role design, section B).
 *  The server answers `GET /api/reviews/runs/{run}/roles` with ids, counts and the codes' own reason words; a document the caller may
 *  not read comes as a count, never a name (`reads[].name` is null and `readable` false). A run from before the record (404, or no
 *  roles) shows one plain line; nothing is invented. */
import { useEffect, useState } from "react";

import { request } from "../../../api/core";

export interface RoleRead {
  document_id: string;
  /** The document's title, resolved by the server at read time; null when it has none. Only documents the caller may read are listed. */
  title: string | null;
  kind: string;
  pages: number[];
  chapter_id: string | null;
  part_no: number | null;
  part_of: number | null;
  chars: number;
  pictures: number;
}
export interface RoleRow {
  role_no: number;
  role: string;
  state: "ran" | "ran_partly" | "not_run";
  why: string | null;
  engine: "claude" | "local" | "code" | null;
  models: string[];
  calls: number;
  usd: number | null;
  produced: Record<string, unknown>;
  reads: RoleRead[];
  /** Documents this role read that the caller may not read: a count, never a name or an id. */
  not_readable: number;
}
export interface RolesAnswer { roles: RoleRow[]; roles_line?: string }

const STATE_WORDS: Record<RoleRow["state"], string> = { ran: "ran", ran_partly: "ran partly", not_run: "not run" };
const ENGINE_WORDS: Record<string, string> = { claude: "Claude", local: "Local", code: "code only" };

export const NOT_RECORDED = "Not recorded: this review was made before the role record.";

function count(value: unknown): string {
  if (Array.isArray(value)) return String(value.length);
  if (value && typeof value === "object") return Object.entries(value).map(([k, v]) => `${k} ${count(v)}`).join(", ");
  return String(value);
}

function where(r: RoleRead): string {
  const part = r.chapter_id ? `, chapter ${r.chapter_id}${r.part_no && r.part_of && r.part_of > 1 ? ` part ${r.part_no} of ${r.part_of}` : ""}` : "";
  return `${r.title ?? "a document"} (${r.kind.replace(/_/g, " ")}${r.pages.length ? `, pages ${r.pages.join(", ")}` : ""}${part})`;
}

function ReadsLine({ reads, notReadable }: { reads: RoleRead[]; notReadable: number }) {
  if (reads.length === 0 && notReadable === 0) return null;
  return (
    <p className="text-xs text-slateish-400" data-testid="role-reads">
      Read {reads.length + notReadable} block(s)
      {reads.length > 0 && <>: {reads.map(where).join("; ")}</>}
      {notReadable > 0 && <>{reads.length > 0 ? "; " : ": "}{notReadable} document(s) you may not read</>}
    </p>
  );
}

export function RolesView({ roles }: { roles: RoleRow[] | null }) {
  if (roles === null || roles.length === 0) return <p data-testid="roles-not-recorded" className="text-sm text-slateish-300">{NOT_RECORDED}</p>;
  const notRun = roles.filter((r) => r.state === "not_run");
  return (
    <div data-testid="roles-panel" className="space-y-2">
      <p className="text-sm text-slateish-100" data-testid="roles-line">
        Roles run: {roles.length - notRun.length} of {roles.length}
        {notRun.length > 0 ? `; not run: ${notRun.map((r) => `${r.role_no} ${r.role}: ${r.why ?? "no reason recorded"}`).join("; ")}` : "; not run: none"}
      </p>
      <ol className="space-y-2">
        {roles.map((r) => (
          <li key={r.role_no} data-testid={`role-${r.role_no}`} className="rounded-[var(--radius-sm)] border border-ink-600 p-2">
            <p className="text-sm font-semibold text-slateish-100">{r.role_no} {r.role}: {STATE_WORDS[r.state]}</p>
            <p className="text-xs text-slateish-300">
              {[r.engine ? ENGINE_WORDS[r.engine] ?? r.engine : null, r.models.join(", ") || null, `${r.calls} call(s)`,
                r.engine === "claude" ? `cost (USD) ${r.usd === null ? "not known" : r.usd.toFixed(2)}` : null]
                .filter(Boolean).join("; ")}
            </p>
            {r.why && r.state !== "ran" && <p className="text-xs text-slateish-300">Why: {r.why}</p>}
            {Object.keys(r.produced).length > 0 && (
              <p className="text-xs text-slateish-400">{Object.entries(r.produced).map(([k, v]) => `${k.replace(/_/g, " ")}: ${count(v)}`).join("; ")}</p>
            )}
            <ReadsLine reads={r.reads} notReadable={r.not_readable ?? 0} />
          </li>
        ))}
      </ol>
    </div>
  );
}

export function RolesPanel({ runId }: { runId: string | null }) {
  const [roles, setRoles] = useState<RoleRow[] | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    if (!runId) { setRoles(null); return; }
    void request<RolesAnswer>(`/reviews/runs/${encodeURIComponent(runId)}/roles`).then((r) => {
      if (live) setRoles(r.ok && Array.isArray(r.data.roles) ? r.data.roles : null);
    });
    return () => { live = false; };
  }, [runId]);
  if (roles === undefined) return null;
  return (
    <section aria-label="Roles" className="mt-3 space-y-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3" data-testid="v2-roles">
      <h3 className="text-sm font-semibold text-slateish-100">The nine roles</h3>
      <RolesView roles={roles} />
    </section>
  );
}
