/**
 * #791 part 2: the review step by step on the review page.
 *
 * MUTATION PROOF: render no step rows and "shows every step" fails; drop the
 * warning line and "flags a step that looks wrong" fails; fetch on mount and
 * "fetches only when opened" fails; drop the download and its test fails.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const reviewTrace = vi.fn();

vi.mock("../api/client", () => ({
  api: {},
  reviews: { reviewTrace: (...args: unknown[]) => reviewTrace(...args) },
}));

import type { ReviewTraceStep } from "../types/api";
import { ReviewPipeline } from "./ReviewPipeline";
import { STEP_NAMES } from "./reviewPipelineSteps";

const STEPS: ReviewTraceStep[] = Object.keys(STEP_NAMES).map((step) => ({
  step, summary: `${step.toLowerCase()} summary`, status: "ok", warning: null,
  counts: {}, items: [], timing: { started_at: "2026-10-11T10:00:00+00:00", seconds: 1.25 },
}));

function trace(overrides: Partial<ReviewTraceStep> & { step: string }) {
  return {
    review_run_id: "run-1", document: "psv-sheet.pdf", source: "stored when the review finished",
    stored_at: "2026-10-11T10:01:00+00:00",
    ai: { ai_engineering_check: { plain: "AI engineering check complete: 2 of 3 proposed item(s) kept",
                                  model: "ollama:local-test" } },
    steps: STEPS.map((s) => (s.step === overrides.step ? { ...s, ...overrides } : s)),
  };
}

async function open() {
  render(<ReviewPipeline runId="run-1" />);
  await userEvent.click(screen.getByText(/how this review was done/i));
}

beforeEach(() => { reviewTrace.mockReset(); });

describe("ReviewPipeline", () => {
  it("fetches only when opened", async () => {
    reviewTrace.mockResolvedValue({ ok: true, data: trace({ step: "READ" }) });
    render(<ReviewPipeline runId="run-1" />);
    expect(reviewTrace).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText(/how this review was done/i));
    expect(reviewTrace).toHaveBeenCalledWith("run-1");
  });

  it("shows every step in order with its summary and timing", async () => {
    reviewTrace.mockResolvedValue({ ok: true, data: trace({ step: "READ" }) });
    await open();
    for (const [step, name] of Object.entries(STEP_NAMES)) {
      const row = await screen.findByTestId(`trace-step-${step}`);
      expect(within(row).getByText(new RegExp(name))).toBeTruthy();
      expect(within(row).getByText(`${step.toLowerCase()} summary`)).toBeTruthy();
      expect(within(row).getByText("(1.3 s)")).toBeTruthy();
    }
    expect(screen.getByText(/source: stored when the review finished/i)).toBeTruthy();
  });

  it("flags a step that looks wrong and one that failed", async () => {
    reviewTrace.mockResolvedValue({ ok: true, data: {
      ...trace({ step: "DECIDE", status: "warning", warning: "0 decisions (no meets, no fails)" }),
      steps: trace({ step: "DECIDE", status: "warning", warning: "0 decisions (no meets, no fails)" })
        .steps.map((s) => (s.step === "CRS" ? { ...s, status: "failed", warning: "CRS not composed" } : s)),
    } });
    await open();
    const decide = await screen.findByTestId("trace-step-DECIDE");
    expect(within(decide).getByText("Warning")).toBeTruthy();
    expect(within(decide).getByText(/warning: 0 decisions/i)).toBeTruthy();
    expect(within(screen.getByTestId("trace-step-CRS")).getByText("Failed")).toBeTruthy();
    expect(within(screen.getByTestId("trace-step-READ")).getByText("OK")).toBeTruthy();
  });

  it("expands a step's items and shows the run's AI use", async () => {
    reviewTrace.mockResolvedValue({ ok: true, data: trace({
      step: "READ", items: ["p1 Set pressure = 10 barg", "p1 Fluid = Gas"] }) });
    await open();
    const read = await screen.findByTestId("trace-step-READ");
    await userEvent.click(within(read).getByText("Show 2 items"));
    expect(within(read).getByText("p1 Set pressure = 10 barg")).toBeTruthy();
    const ai = screen.getByTestId("trace-ai");
    expect(within(ai).getByText(/2 of 3 proposed item\(s\) kept/)).toBeTruthy();
    expect(within(ai).getByText(/model ollama:local-test/)).toBeTruthy();
  });

  it("says why when the trace cannot be read", async () => {
    reviewTrace.mockResolvedValue({ ok: false, error: { message: "no review run with that id" } });
    await open();
    expect((await screen.findByRole("alert")).textContent).toContain("no review run with that id");
  });

  it("downloads the same trace as a JSON file", async () => {
    reviewTrace.mockResolvedValue({ ok: true, data: trace({ step: "READ" }) });
    const created: Blob[] = [];
    const createObjectURL = vi.fn((b: Blob) => { created.push(b); return "blob:x"; });
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await open();
    await userEvent.click(await screen.findByRole("button", { name: /download trace/i }));
    expect(click).toHaveBeenCalled();
    expect(JSON.parse(await created[0].text()).review_run_id).toBe("run-1");
    click.mockRestore();
  });
});
