import type { ViewId } from "./components/Shell";

export type AppRoute =
  | { kind: "view"; view: ViewId; recordId?: string }
  | { kind: "forbidden"; path: string };

const titles: Record<ViewId, string> = {
  dashboard: "Dashboard",
  documents: "Documents",
  chat: "Chat",
  analysis: "Analysis Hub",
  reports: "CRS & Reports",
  deliverables: "Deliverables and timeline",
  ingestion: "Ingestion",
  admin: "Administration",
  standards: "Standards Library",
  review: "AI Submittal Review",
};

/** Every view the app can open, derived from `titles` - a `Record<ViewId, ...>`,
 *  so the compiler refuses a ViewId without an entry. A hand-kept second list
 *  once omitted "standards", and a refresh on /standards said "This address
 *  cannot be opened" (audit 2026-09-30). */
const ROUTABLE_VIEWS: ReadonlySet<string> = new Set(Object.keys(titles));

export function isRoutableView(view: string): view is ViewId {
  return ROUTABLE_VIEWS.has(view);
}

export function titleForView(view: ViewId): string {
  return `${titles[view]} · RAG Intelligence System`;
}

export function parseRoute(pathname: string): AppRoute {
  const parts = pathname.split("/").filter(Boolean).map((part) => {
    try {
      return decodeURIComponent(part);
    } catch {
      return part;
    }
  });
  if (parts.length === 0) return { kind: "view", view: "documents" };
  const view = parts[0] as ViewId;
  if (!isRoutableView(view)) {
    return { kind: "forbidden", path: pathname };
  }
  if (parts.length > 2 || (parts.length === 2 && !parts[1])) {
    return { kind: "forbidden", path: pathname };
  }
  return { kind: "view", view, recordId: parts[1] };
}

export function pathForView(view: ViewId, recordId?: string): string {
  return recordId ? `/${view}/${encodeURIComponent(recordId)}` : `/${view}`;
}
