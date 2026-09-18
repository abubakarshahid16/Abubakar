import type { ViewId } from "./components/Shell";

export type AppRoute =
  | { kind: "view"; view: ViewId; recordId?: string }
  | { kind: "forbidden"; path: string };

const titles: Record<ViewId, string> = {
  dashboard: "Dashboard",
  documents: "Documents",
  chat: "Document review chat",
  analysis: "Engineering analysis",
  reports: "Reports",
  deliverables: "Deliverables and timeline",
  ingestion: "Ingestion",
  admin: "Administration",
  review: "Submittal review",
};

export function titleForView(view: ViewId): string {
  return `${titles[view]} · EPC Intelligence`;
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
  if (!["dashboard", "documents", "chat", "analysis", "reports", "deliverables", "ingestion", "admin", "review"].includes(view)) {
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
