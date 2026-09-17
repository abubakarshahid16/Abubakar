import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import path from "node:path";

const views = ["Dashboard", "Documents", "Chat", "Analysis", "Reports", "Deliverables", "Ingestion", "Administration"] as const;
const themes = ["light", "dark"] as const;
const outputPath = path.resolve("..", "docs", "ui-redesign", process.env.CONTRAST_OUTPUT ?? "contrast-root-cause.json");

async function openView(page: Page, view: string) {
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({ timeout: 15_000 });
  if (view !== "Documents") await page.getByRole("button", { name: new RegExp(`^${view}\\b`) }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
}

test("collect every serious/critical contrast node with computed colors", async ({ page }) => {
  test.setTimeout(10 * 60 * 1000);
  const rows: unknown[] = [];
  await page.setViewportSize({ width: 1600, height: 900 });
  for (const theme of themes) {
    for (const view of views) {
      await openView(page, view);
      await page.getByRole("button", { name: theme, exact: true }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForTimeout(5_000);
      const result = await new AxeBuilder({ page }).analyze();
      for (const violation of result.violations.filter((v) => v.impact === "serious" || v.impact === "critical")) {
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
          rows.push({ view, theme, rule: violation.id, impact: violation.impact, target: node.target, failureSummary: node.failureSummary, computed });
        }
      }
    }
  }
  await writeFile(outputPath, JSON.stringify(rows, null, 2), "utf8");
  expect(rows.filter((row: any) => row.rule === "color-contrast" || row.rule === "list"),
    "serious/critical accessibility violations").toEqual([]);
});
