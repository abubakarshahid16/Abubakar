/**
 * One upload for the whole app (order 14 lane E): is the suggested role on, and which roles does the review page list?
 *
 * `GET /api/document-kinds/role-suggestion` answers {enabled, review_roles}. Read ONCE per page load and kept. Anything but a
 * clear answer (an error, an old server without the route) counts as OFF: the screens then behave exactly as before.
 */
import { request } from "./core";

export interface RoleSuggestionSwitch {
  enabled: boolean;
  review_roles: string[];
  /** Order 14 (G2): non-empty means the review page lists EVERY paper except these roles (the general review takes every kind of
   *  paper; a paper with no role recorded is listed too). Absent or empty: the list of `review_roles`, as before. */
  exclude_roles?: string[];
}

export const SWITCH_OFF: RoleSuggestionSwitch = { enabled: false, review_roles: ["CONTRACTOR_SUBMITTAL"], exclude_roles: [] };

let cached: Promise<RoleSuggestionSwitch> | null = null;

export function roleSuggestionSwitch(): Promise<RoleSuggestionSwitch> {
  cached ??= request<RoleSuggestionSwitch>("/document-kinds/role-suggestion")
    .then((r) =>
      r.ok && typeof r.data?.enabled === "boolean" && Array.isArray(r.data.review_roles)
        ? {
            enabled: r.data.enabled,
            review_roles: r.data.review_roles,
            exclude_roles: Array.isArray(r.data.exclude_roles) ? r.data.exclude_roles : [],
          }
        : SWITCH_OFF,
    )
    .catch(() => SWITCH_OFF);
  return cached;
}

/** Tests only: forget the kept answer. */
export function resetRoleSuggestionSwitch(): void {
  cached = null;
}

/** The suggested role as the kind row's evidence carries it (`role_suggestion`). */
export interface RoleSuggestion {
  role: string | null;
  basis: "page" | "kind" | "none";
  page?: string | null;
  kind?: string | null;
  kind_says?: string;
}

export function roleSuggestionOf(evidence: unknown): RoleSuggestion | null {
  const found = (evidence as { role_suggestion?: RoleSuggestion } | null | undefined)?.role_suggestion;
  return found && typeof found === "object" ? found : null;
}

export const ROLE_WORDS: Record<string, string> = {
  CONTRACTOR_SUBMITTAL: "contractor submittal",
  COMPANY_STANDARD: "company standard",
  CONTRACT_DOCUMENT: "contract document",
  SPECIFICATION: "specification",
  SUPPORTING_DOCUMENT: "supporting document",
  CRS_TEMPLATE: "CRS template",
};

export const PAGE_WORDS: Record<string, string> = {
  review: "the AI Submittal Review page",
  standards: "the missing standards list",
  documents: "the Documents page",
};

/** One sentence: what is suggested and why, and the disagreement when the kind points elsewhere. */
export function suggestionWords(s: RoleSuggestion): string {
  if (!s.role) return "No role suggested: choose a role.";
  const role = ROLE_WORDS[s.role] ?? s.role;
  const why =
    s.basis === "page"
      ? `it was uploaded on ${PAGE_WORDS[s.page ?? ""] ?? "a page for that role"}`
      : `it reads as a ${s.kind ?? "document"}`;
  const other = s.kind_says ? `; its contents read as a ${ROLE_WORDS[s.kind_says] ?? s.kind_says}` : "";
  return `Suggested role: ${role} (${why}${other}). Suggested, confirm or change.`;
}
