/** The Uploads line of "What this system can do right now": a running review is busy, not stopped; since update 7 uploads are read
 * beside it on their own lane and "waiting" is said only for uploads that wait for the local model. Invented values. */
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
  it("says a review is running and how many uploads wait for the model, never that processing stopped", () => {
    render(<ReadinessPanel metrics={metrics({ reviewing: true, pending_count: 3, uploads_waiting_for_review: 3 })} />);
    expect(screen.getByText("busy with a review: 3 new files waiting")).toBeInTheDocument();
    expect(screen.queryByText(/reading has stopped/)).toBeNull();
  });

  it("one upload waiting is said in the singular", () => {
    render(<ReadinessPanel metrics={metrics({ reviewing: true, pending_count: 1, uploads_waiting_for_review: 1 })} />);
    expect(screen.getByText("busy with a review: 1 new file waiting")).toBeInTheDocument();
  });

  it("uploads read beside a running review are not called waiting", () => {
    render(<ReadinessPanel metrics={metrics({ reviewing: true, pending_count: 2, uploads_waiting_for_review: 0 })} />);
    expect(screen.getByText("a review is running; 2 new files are read at the same time")).toBeInTheDocument();
    expect(screen.queryByText(/waiting/)).toBeNull();
  });

  it("a stalled worker with no document and no review still says processing has stopped", () => {
    render(<ReadinessPanel metrics={metrics({ stalled: true, reviewing: false })} />);
    expect(screen.getByText("reading has stopped: new files will wait")).toBeInTheDocument();
  });

  it("an idle worker says new documents will be processed", () => {
    render(<ReadinessPanel metrics={metrics({})} />);
    expect(screen.getByText("new documents are read as they arrive")).toBeInTheDocument();
  });
});

describe("Your documents line (update 12)", () => {
  const withCorpus = (corpus: Record<string, unknown>) =>
    ({ ...metrics({}), corpus: { documents: 3, chunks_retrievable: 40, ...corpus } }) as unknown as Metrics;

  it("says how many technical-query attachments are counted apart, never inside the library's numbers", () => {
    render(<ReadinessPanel metrics={withCorpus({ technical_query_attachments: 2 })} />);
    expect(
      screen.getByText(/3 documents loaded, 40 parts of pages a question can reach \(2 files attached to queries are counted apart\. They join search, Chat and reviews once added to the library\)/),
    ).toBeInTheDocument();
  });

  it("says nothing more when there are none, or when the view is scoped (null)", () => {
    render(<ReadinessPanel metrics={withCorpus({ technical_query_attachments: 0 })} />);
    expect(screen.getByText("3 documents loaded, 40 parts of pages a question can reach")).toBeInTheDocument();
  });
});
