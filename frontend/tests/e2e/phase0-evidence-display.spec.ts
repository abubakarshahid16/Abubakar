import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const conversationId = "conv_316311bb58f9";
const outputDir = path.resolve(process.cwd(), "../docs/ui-redesign");

test("capture the existing evidence-removed disclosure from a real stored answer", async ({
  page,
  request,
}) => {
  const response = await request.get(`http://127.0.0.1:8000/api/conversations/${conversationId}`);
  expect(response.status()).toBe(200);
  const detail = await response.json();

  // The app only asks for the newest 20 conversations. Put this older, real
  // stored conversation on that first page without changing its detail payload.
  await page.route("**/api/conversations?limit=20", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        total: 1,
        limit: 20,
        offset: 0,
        conversations: [
          {
            ...detail.conversation,
            first_question: detail.conversation.title,
          },
        ],
      }),
    });
  });

  await mkdir(outputDir, { recursive: true });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();
  await page.getByText(detail.conversation.title, { exact: true }).click();
  await expect(page.getByText(/One source did not fit the model's context window/i)).toBeVisible();
  await page.screenshot({
    path: path.join(outputDir, "evidence-removed-chat.png"),
    fullPage: true,
  });
});

test("capture the existing dropped-sentence disclosure with its recorded reason", async ({ page }) => {
  await page.route("**/api/analysis/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        question: "What is required?",
        evidence_ledger: [
          {
            evidence_id: "ev-phase0",
            document_id: "doc-phase0",
            filename: "phase0-evidence.pdf",
            page_start: 12,
            page_end: 12,
            section: "4.2",
            exact_span: "The contractor shall submit the calculation package for review.",
            text_source: "extracted",
            ocr_min_conf: null,
            ocr_alphabet_violations: 0,
            relevance_score: null,
            relevance_score_type: null,
          },
        ],
        summary: "The calculation package must be submitted for review [S1].",
        summary_truncated: false,
        summary_cited_evidence_ids: ["ev-phase0"],
        documented_findings: [],
        rejected_citations: [],
        evidence_removed: [],
        refusal: null,
        dropped_sentences: [
          {
            sentence: "The package is fully approved.",
            reason: "claims an approval that no cited span records",
          },
        ],
        not_implemented_sections: [],
        applied_scope: null,
      }),
    });
  });

  await mkdir(outputDir, { recursive: true });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /^Analysis\b/ }).click();
  await page.getByLabel("Question").fill("What is required?");
  await page.getByRole("button", { name: "Run analysis" }).click();
  const disclosure = page.getByText("1 sentence was removed from this summary", { exact: true });
  await expect(disclosure).toBeVisible();
  await disclosure.click();
  await expect(page.getByText(/claims an approval that no cited span records/)).toBeVisible();
  await page.screenshot({
    path: path.join(outputDir, "dropped-sentences-analysis-controlled.png"),
    fullPage: true,
  });
});
