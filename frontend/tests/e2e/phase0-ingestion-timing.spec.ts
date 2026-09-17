import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

test("measure five Ingestion navigation runs", async ({ page }) => {
  test.setTimeout(120_000);
  const rows: Array<{
    run: number;
    heading_ms: number;
    requests: Array<{ url: string; status: number; elapsed_ms: number }>;
  }> = [];

  for (let run = 1; run <= 5; run += 1) {
    const started = Date.now();
    const requestStarts = new Map<string, number>();
    const requests: Array<{ url: string; status: number; elapsed_ms: number }> = [];
    const onRequest = (request: { url(): string }) => {
      if (request.url().includes("/api/")) requestStarts.set(request.url(), Date.now());
    };
    const onResponse = (response: { url(): string; status(): number }) => {
      if (!response.url().includes("/api/")) return;
      requests.push({
        url: response.url().replace(/^https?:\/\/[^/]+/, ""),
        status: response.status(),
        elapsed_ms: Date.now() - (requestStarts.get(response.url()) ?? started),
      });
    };
    page.on("request", onRequest);
    page.on("response", onResponse);

    await page.goto("/");
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    const clicked = Date.now();
    await page.getByRole("button", { name: /^Ingestion\b/ }).click();
    await expect(page.getByRole("heading", { name: "Ingestion", level: 1 })).toBeVisible({
      timeout: 15_000,
    });
    rows.push({ run, heading_ms: Date.now() - clicked, requests });

    page.off("request", onRequest);
    page.off("response", onResponse);
  }

  const output = path.resolve("..", "docs", "ui-redesign", "ingestion-timing.json");
  await mkdir(path.dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify(rows, null, 2), "utf8");
});
