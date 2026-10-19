/**
 * Order 117 item 6, piece 4: the review screens and the evidence drawer in the
 * serious/critical axe gate.
 *
 * The main gate (`contrast-root-cause.spec.ts`) opens a fresh, empty app, where
 * no review run exists, so it never reached these screens. Here every `/api`
 * call is answered from made-up fixtures in the page itself (`page.route`), so
 * the CRS sheet, its drawer, the card view, "How this was reviewed" and the
 * review workspace (switch on, in this browser only) render with rows in
 * both themes, and no backend or document is involved.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

const RUN = "run-axe";
const run = {
  review_run_id: RUN, submittal_document_id: "doc-sub", submittal_filename: "sample-datasheet.pdf",
  equipment_tags: [], status: "completed", created_at: "2026-10-18T08:00:00Z", completed_at: "2026-10-18T08:20:00Z",
  standards_in_scope: 1, findings_total: 3, by_status: { COMPLIANT: 1, NON_COMPLIANT: 1, MISSING_INFORMATION: 1 },
  recommended_code: "Approved with Comments", recommended_reason: "One value does not meet the standard.",
  engineer_final_code: null,
  page_coverage: { pages_total: 2, fact_pages: [1, 2], pages_not_read_into_fields: [], not_read_reasons: {} },
};
function finding(id: string, status: string, page: number) {
  return {
    id, document_id: "doc-sub", review_run_id: RUN, compliance_status: status, status: "open",
    approval_status: "pending", severity: "major", category: "requirement_deviation",
    matched_phrase: `Field ${id}`, finding: `Field ${id} reads 10 bar; the standard asks for 12 bar.`,
    requirement: "r", required_action: `Contractor to correct field ${id}.`, contractor_page: page,
    contractor_evidence_text: "10 bar", standard_document_id: "doc-std", standard_clause: "4.1",
    standard_page: 3, requirement_source_text: "The design pressure shall be 12 bar.",
    governing_sources: [], unresolved_evidence: [], citation_ids: [], escalation_level: 0,
    created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:00:00Z",
  };
}
const findings = [finding("a", "NON_COMPLIANT", 1), finding("b", "MISSING_INFORMATION", 2), finding("c", "COMPLIANT", 1)];

const answers: Array<[RegExp, unknown]> = [
  [/\/api\/health$/, { ok: true, embed_model_present: true, answer_model_configured: true, ingestion: { alive: true, stalled: false, busy: false } }],
  [new RegExp(`/api/reviews/runs/${RUN}$`), run],
  [/\/api\/reviews\/runs(\?.*)?$/, { runs: [run], total: 1, limit: null, offset: 0 }],
  [/\/api\/reviews\/findings/, { findings, total: findings.length, limit: null, offset: 0 }],
  [new RegExp(`/api/reviews/runs/${RUN}/standards`), {
    standards: [{ standard_document_id: "doc-std", filename: "sample-standard.pdf", included: true }], missing_references: [],
  }],
  [new RegExp(`/api/reviews/runs/${RUN}/crs/decisions`), { decisions: [] }],
  // Order 121: the sheet's "Before you sign" box, with every kind of item open.
  [new RegExp(`/api/reviews/runs/${RUN}/crs/issue-gate`), {
    review_run_id: RUN, issuable: false, final_code_recorded: false, blockers: ["open"],
    unread_pages: [{ page: 2, reason: "vision reader: page kind 'cover'" }],
    open_findings: [{ finding_id: "a", row_kind: "non_compliant", item: 1 }, { finding_id: "k", row_kind: "standard_not_cited", item: 2 }],
  }],
  // Workspace v2: the submittal's readiness (pages read, standards missing).
  [/\/api\/reviews\/readiness\/doc-sub$/, {
    submittal_document_id: "doc-sub", pages_total: 2, pages_read: 1, unread_pages: [2],
    unread_page_reasons: { "2": "vision reader: page kind 'cover'" }, ledger_state: "current", ledger_note: null,
    standards_cited: 1, standards_held: ["sample-standard.pdf"], standards_missing: [],
    last_run_id: RUN, nothing_changed: true, changes: [],
  }],
  [/\/api\/documents\/doc-sub$/, { id: "doc-sub", filename: "sample-datasheet.pdf", page_count: 2, status: "ready" }],
];

async function serveFixtures(page: Page, unanswered: Set<string>) {
  // The API only: a glob like "**/api/**" also matches Vite's own module
  // `/src/api/client.ts`, and the app never loads.
  await page.route((url) => url.pathname.startsWith("/api/"), (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname + url.search;
    const hit = answers.find(([pattern]) => pattern.test(path));
    if (hit) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(hit[1]) });
    unanswered.add(`${route.request().method()} ${url.pathname}`);
    return route.fulfill({ status: 404, contentType: "application/json",
      body: JSON.stringify({ detail: { code: "not_found", message: "not in this audit" } }) });
  });
}

async function seriousOrCritical(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .flatMap((v) => v.nodes.map((n) => ({ rule: v.id, impact: v.impact, target: n.target, summary: n.failureSummary })));
}

// Order 137: the review workspace is the only review design. Every old
// review address (cards, crs-sheet, how, ...) now leads into it, so the audit
// opens the workspace's own addresses: the comment sheet tab (with its
// evidence drawer and the action bar) and the "How this was reviewed" tab.
const screens: ReadonlyArray<{ name: string; path: string; ready: (p: Page) => Locator }> = [
  { name: "review workspace: comment sheet", path: `/review/${RUN}/workspace`,
    ready: (p: Page) => p.getByRole("grid", { name: "Comment resolution sheet" }) },
  { name: "review workspace: How this was reviewed", path: `/review/${RUN}/workspace?tab=how`,
    ready: (p: Page) => p.getByTestId("how-reviewed") },
];

for (const theme of ["light", "dark"] as const) {
  test(`review screens and the evidence drawer have no serious/critical axe violations (${theme})`, async ({ page }) => {
    const unanswered = new Set<string>();
    await serveFixtures(page, unanswered);
    // No transitions mid-audit: a theme switch fades colours, and axe would
    // measure a blend of the two themes.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1600, height: 900 });
    const found: Record<string, unknown[]> = {};
    for (const screen of screens) {
      await page.goto(screen.path);
      await expect(screen.ready(page)).toBeVisible({ timeout: 15_000 });
      // The app's own theme switch, as the main gate does.
      if ((await page.locator("html").getAttribute("data-theme")) !== theme) {
        await page.getByRole("button", { name: theme, exact: true }).click();
      }
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForTimeout(1_000);
      found[screen.name] = await seriousOrCritical(page);
      if (screen.name === "review workspace: comment sheet") {
        await expect(page.getByTestId("ws-action-bar")).toBeVisible();
        const grid = page.getByRole("grid", { name: "Comment resolution sheet" });
        await grid.getByRole("row").nth(1).click();
        await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10_000 });
        found["evidence drawer"] = await seriousOrCritical(page);
        await page.keyboard.press("Escape");
      }
    }
    console.log(`${theme}: API paths answered 404 (not needed for these screens): ${[...unanswered].sort().join(", ") || "none"}`);
    expect(Object.keys(found)).toEqual([
      "review workspace: comment sheet", "evidence drawer", "review workspace: How this was reviewed",
    ]);
    expect(found, "serious/critical accessibility violations").toEqual({
      "review workspace: comment sheet": [], "evidence drawer": [], "review workspace: How this was reviewed": [],
    });
  });
}
