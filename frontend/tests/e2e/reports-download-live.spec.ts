import { expect, test } from "@playwright/test";
import { mkdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";

test("a report download produces a non-empty PDF file", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Reports\b/ }).click();
  const button = page.getByRole("button", { name: "Download" }).first();
  await expect(button).toBeVisible();

  const responsePromise = page.waitForResponse((response) =>
    response.url().includes("/api/reports/") && response.url().endsWith("/download"),
  );
  const downloadPromise = page.waitForEvent("download", { timeout: 10_000 });
  await button.click();

  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/pdf");
  expect(response.headers()["content-disposition"]).toContain("attachment");

  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.pdf$/i);
  const saved = await download.path();
  expect(saved).not.toBeNull();
  const bytes = (await stat(saved!)).size;
  expect(bytes).toBeGreaterThan(0);

  const evidence = {
    http_status: response.status(),
    content_type: response.headers()["content-type"],
    content_disposition: response.headers()["content-disposition"],
    filename: download.suggestedFilename(),
    file_size_bytes: bytes,
    test_file: "frontend/tests/e2e/reports-download-live.spec.ts",
  };
  const outputDir = path.resolve(process.cwd(), "../docs/ui-redesign");
  await mkdir(outputDir, { recursive: true });
  await writeFile(
    path.join(outputDir, "report-download-evidence.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
    "utf8",
  );
});
