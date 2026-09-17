import { test, expect } from "@playwright/test";

const views = ["documents", "chat", "analysis", "reports", "deliverables", "ingestion", "admin"];

test("every keyboard-focusable control exposes the shared visible ring", async ({ page }) => {
  for (const view of views) {
    await page.goto(`http://127.0.0.1:5173/${view}`);
    await page.waitForLoadState("domcontentloaded");
    const controls = page.locator("button:visible, a:visible, input:visible, select:visible, textarea:visible");
    const count = await controls.count();
    for (let i = 0; i < count; i++) {
      await controls.nth(i).focus();
      await expect(controls.nth(i)).toHaveCSS("outline-style", "solid");
      await expect(controls.nth(i)).toHaveCSS("outline-width", "3px");
    }
  }
});
