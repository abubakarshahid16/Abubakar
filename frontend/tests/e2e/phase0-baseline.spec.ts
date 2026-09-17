import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const views = [
  "Dashboard",
  "Documents",
  "Chat",
  "Analysis",
  "Reports",
  "Deliverables",
  "Ingestion",
  "Administration",
] as const;

const sizes = [
  { width: 1366, height: 768 },
  { width: 1600, height: 900 },
  { width: 1920, height: 1080 },
] as const;

const beforeDir = path.resolve("..", "docs", "ui-redesign", "before");
const axePath = path.resolve("..", "docs", "ui-redesign", "axe-baseline.json");
type AxeRow = {
  view: string;
  theme: string;
  serious: Array<{ id: string; help: string; nodes: number }>;
  critical: Array<{ id: string; help: string; nodes: number }>;
};

async function openView(page: Page, view: string) {
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  if (view !== "Documents") {
    await page.getByRole("button", { name: new RegExp(`^${view}\\b`) }).click();
  }
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
}

test("capture the complete Phase 0 visual and accessibility baseline", async ({ page }) => {
  test.setTimeout(15 * 60 * 1000);
  const axeRows: AxeRow[] = [];
  await mkdir(beforeDir, { recursive: true });

  for (const size of sizes) {
    for (const theme of ["light", "dark"] as const) {
      for (const view of views) {
        await page.setViewportSize(size);
        await openView(page, view);
        await page.getByRole("button", { name: theme === "light" ? "light" : "dark", exact: true }).click();
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        // Capture the settled screen rather than a transient loading card. Some
        // live metrics calls take four seconds on the Phase 0 machine.
        await page.waitForTimeout(5_000);
        await page.screenshot({
          path: path.join(beforeDir, `${view.toLowerCase()}-${theme}-${size.width}x${size.height}.png`),
          fullPage: true,
        });

        if (size.width === 1600) {
          const result = await new AxeBuilder({ page }).analyze();
          axeRows.push({
            view,
            theme,
            serious: result.violations
              .filter((v) => v.impact === "serious")
              .map((v) => ({ id: v.id, help: v.help, nodes: v.nodes.length })),
            critical: result.violations
              .filter((v) => v.impact === "critical")
              .map((v) => ({ id: v.id, help: v.help, nodes: v.nodes.length })),
          });
        }
      }
    }
  }

  await writeFile(axePath, JSON.stringify(axeRows, null, 2), "utf8");
});
