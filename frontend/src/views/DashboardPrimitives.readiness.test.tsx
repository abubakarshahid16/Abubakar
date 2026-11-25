/** The Uploads line of "What this system can do right now": a review on the worker's one thread is busy, not stopped. Invented values. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Metrics } from "../types/api";
import { ReadinessPanel } from "./DashboardPrimitives";

function metrics(worker: Record<string, unknown>): Metrics {
  return {
    corpus: { documents: 3, chunks_retrievable: 40 },
    models: { embed_model_present: true, reranker_present: true, answer_model_reachable: true },
    worker: { alive: true, current_document: null, pending_count: 0, stalled: false, stalled_reasons: [], ...worker },
  } as unknown as Metrics;
}

describe("Uploads line", () => {
  it("says a review is running and how many uploads wait, never that processing stopped", () => {
    render(<ReadinessPanel metrics={metrics({ reviewing: true, pending_count: 3 })} />);
    expect(screen.getByText("busy with a review: 3 uploads waiting")).toBeInTheDocument();
    expect(screen.queryByText(/processing has stopped/)).toBeNull();
  });

  it("one upload waiting is said in the singular", () => {
    render(<ReadinessPanel metrics={metrics({ reviewing: true, pending_count: 1 })} />);
    expect(screen.getByText("busy with a review: 1 upload waiting")).toBeInTheDocument();
  });

  it("a stalled worker with no document and no review still says processing has stopped", () => {
    render(<ReadinessPanel metrics={metrics({ stalled: true, reviewing: false })} />);
    expect(screen.getByText("processing has stopped - new uploads will wait")).toBeInTheDocument();
  });

  it("an idle worker says new documents will be processed", () => {
    render(<ReadinessPanel metrics={metrics({})} />);
    expect(screen.getByText("new documents will be processed as they arrive")).toBeInTheDocument();
  });
});
