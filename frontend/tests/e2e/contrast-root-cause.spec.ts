import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import path from "node:path";

const views = ["Dashboard", "Documents", "Document Q&A", "Analysis", "CRS & Reports", "Deliverables", "Ingestion", "Administration"] as const;
const themes = ["light", "dark"] as const;
const outputPath = path.resolve("..", "docs", "ui-redesign", process.env.CONTRAST_OUTPUT ?? "contrast-root-cause.json");

type AuditRun = {
  view: string;
  theme: string;
  nodes_scanned: number;
  serious: number;
  critical: number;
  violations: Array<{
    rule: string;
    impact: string | null;
    target: string[][];
    failureSummary?: string;
    computed: unknown;
  }>;
};

let authenticated = false;
let currentView: string | null = null;

async function authenticate(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 30_000 });
  if (await page.getByRole("heading", { name: "Sign in" }).isVisible().catch(() => false)) {
    const email = process.env.AUDIT_EMAIL;
    const password = process.env.AUDIT_PASSWORD;
    if (!email || !password) {
      throw new Error("Contrast audit reached the sign-in screen. Set AUDIT_EMAIL and AUDIT_PASSWORD for the disposable local audit account.");
    }
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  }
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({ timeout: 15_000 });
  authenticated = true;
  currentView = "Documents";
}

async function openView(page: Page, view: string) {
  if (!authenticated) await authenticate(page);
  if (currentView !== view) {
    await page.getByRole("button", { name: new RegExp(`^${view}\\b`) }).click();
    currentView = view;
  }
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
}

test("collect every serious/critical contrast node with computed colors", async ({ page }) => {
  test.setTimeout(10 * 60 * 1000);
  const runs: AuditRun[] = [];
  await page.setViewportSize({ width: 1600, height: 900 });
  console.log(`Axe audit matrix: ${views.length} views x ${themes.length} themes = ${views.length * themes.length} authenticated runs`);
  for (const theme of themes) {
    for (const view of views) {
      await openView(page, view);
      await page.getByRole("button", { name: theme, exact: true }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForTimeout(5_000);
      const result = await new AxeBuilder({ page }).analyze();
      const seriousViolations = result.violations.filter((v) => v.impact === "serious");
      const criticalViolations = result.violations.filter((v) => v.impact === "critical");
      const nodesScanned = await page.locator("body *").count();
      const violations: AuditRun["violations"] = [];
      for (const violation of [...seriousViolations, ...criticalViolations]) {
        for (const node of violation.nodes) {
          const computed = await page.evaluate((target) => {
            let element: Element | null = null;
            for (const selector of target) {
              try { element = document.querySelector(selector); } catch { /* axe target can be non-CSS */ }
              if (element) break;
            }
            if (!element) return null;
            const style = getComputedStyle(element);
            let background: Element | null = element;
            let backgroundColor = "transparent";
            while (background) {
              const candidate = getComputedStyle(background).backgroundColor;
              if (candidate !== "transparent" && !candidate.startsWith("rgba(0, 0, 0, 0)")) {
                backgroundColor = candidate;
                break;
              }
              background = background.parentElement;
            }
            return {
              tag: element.tagName.toLowerCase(),
              text: (element.textContent ?? "").trim().replace(/\\s+/g, " ").slice(0, 160),
              className: element.getAttribute("class") ?? "",
              ancestorClasses: background?.getAttribute("class") ?? "",
              foreground: style.color,
              background: backgroundColor,
              fontSize: style.fontSize,
              fontWeight: style.fontWeight,
              lineHeight: style.lineHeight,
            };
          }, node.target);
          violations.push({ rule: violation.id, impact: violation.impact, target: node.target, failureSummary: node.failureSummary, computed });
        }
      }
      const run: AuditRun = { view, theme, nodes_scanned: nodesScanned, serious: seriousViolations.length, critical: criticalViolations.length, violations };
      runs.push(run);
      console.log(`${view} / ${theme}: ${run.serious} serious, ${run.critical} critical, ${run.nodes_scanned} nodes scanned`);
    }
  }
  await writeFile(outputPath, JSON.stringify(runs, null, 2), "utf8");
  expect(runs, "the audit must record every view/theme run").toHaveLength(views.length * themes.length);
  expect(runs.flatMap((run) => run.violations), "serious/critical accessibility violations").toEqual([]);
});
