import type { ViewId } from "./components/Shell";

/** Order 95 piece 3 / order 104: the review inbox (/review/inbox) stays off
 *  the landing page until the owner's click-through says yes. Flipping this
 *  to true makes the inbox what /review opens. */
export const INBOX_IS_DEFAULT = false;

/** The record segment that opens the inbox under /review. */
export const INBOX_RECORD = "inbox";

export type AppRoute =
  | { kind: "view"; view: ViewId; recordId?: string; panel?: string }
  | { kind: "forbidden"; path: string };

/** #967 PR 3: the pages a record of a view keeps behind links, as a third
 *  path segment (`/review/<run>/findings`). Only a view listed here takes
 *  one, and only the panels it names: any other three-part path stays
 *  "forbidden", as every over-deep path always was. */
export const PANELS: Partial<Record<ViewId, readonly string[]>> = {
  // Order 95 piece 2: "cards" is the card view (an alias while it is the
  // default) and "crs-sheet" the new comment sheet; see CRS_SHEET_IS_DEFAULT.
  // "crs" was already taken: it is the card view's Comment Resolution Sheet
  // page behind the scenes (#967 PR 3), so the new sheet cannot share it.
  // "how" (order 95 piece 5): the audit page "How this was reviewed" - a
  // page of its own (`HowReviewedView`), not a Behind-the-scenes panel.
  review: ["cards", "crs-sheet", "findings", "standards", "steps", "numbers", "crs", "how"],
};

/**
 * THE OWNER'S SWITCH (order 95 piece 2, Part of #967). Which screen
 * `/review/<run>` opens:
 *   false - the current card view (the review screen people use today);
 *           the new comment sheet is at `/review/<run>/crs-sheet`.
 *   true  - the new comment sheet; the card view stays at `/review/<run>/cards`.
 * Both explicit addresses always work, whichever value this has. Flip it only
 * after the owner has clicked through the new sheet and said so. Every link
 * between the two screens reads it through `reviewScreenFor` /
 * `panelForReviewScreen`, so this one line is the whole switch.
 */
export const CRS_SHEET_IS_DEFAULT = false;

/** The third path segment that always opens each review screen. */
export const REVIEW_SCREEN_PANELS = { cards: "cards", crsSheet: "crs-sheet" } as const;

export type ReviewScreen = keyof typeof REVIEW_SCREEN_PANELS;

/** What `/review/<run>[/<panel>]` shows: one of the two screens, and for the
 *  card view the behind-the-scenes page, if any. `panel` must already be
 *  one `parseRoute` accepted. */
export function reviewScreenFor(
  panel: string | undefined, crsSheetIsDefault: boolean = CRS_SHEET_IS_DEFAULT,
): { screen: "cards"; panel?: string } | { screen: "crsSheet" } {
  if (!panel) return crsSheetIsDefault ? { screen: "crsSheet" } : { screen: "cards" };
  if (panel === REVIEW_SCREEN_PANELS.crsSheet) return { screen: "crsSheet" };
  if (panel === REVIEW_SCREEN_PANELS.cards) return { screen: "cards" };
  return { screen: "cards", panel };
}

/** The panel to link to for a screen: none (plain `/review/<run>`) for the
 *  default one, its own segment for the other. */
export function panelForReviewScreen(
  screen: ReviewScreen, crsSheetIsDefault: boolean = CRS_SHEET_IS_DEFAULT,
): string | undefined {
  const isDefault = (screen === "crsSheet") === crsSheetIsDefault;
  return isDefault ? undefined : REVIEW_SCREEN_PANELS[screen];
}

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
  if (parts.length > 3 || (parts.length >= 2 && !parts[1])) {
    return { kind: "forbidden", path: pathname };
  }
  if (parts.length === 3 && !(PANELS[view] ?? []).includes(parts[2])) {
    return { kind: "forbidden", path: pathname };
  }
  return { kind: "view", view, recordId: parts[1], ...(parts[2] ? { panel: parts[2] } : {}) };
}

export function pathForView(view: ViewId, recordId?: string, panel?: string): string {
  if (!recordId) return `/${view}`;
  const base = `/${view}/${encodeURIComponent(recordId)}`;
  return panel ? `${base}/${encodeURIComponent(panel)}` : base;
}
