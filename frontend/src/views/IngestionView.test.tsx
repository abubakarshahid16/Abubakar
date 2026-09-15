/**
 * Ingestion is worth having only if it tells the truth while you wait.
 *
 * These tests hold the four properties that make it useful rather than
 * decorative: the answerable moment is shown separately from the finished
 * moment, an unmeasured rate says so instead of showing zero, the file being
 * worked on is named rather than keyed, and an idle screen teaches instead of
 * sitting blank.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { DocumentRecord, Metrics, WorkerStatus } from "../types/api";

const WORKING_ID = "doc_b4f589095afe";

// Health carries three booleans; the detail below is the METRICS worker.

const idleFullWorker: WorkerStatus = {
  alive: true,
  current_document: null,
  seconds_since_heartbeat: 0.4,
  seconds_since_progress: 12,
  documents_completed: 3,
  pending_count: 0,
  oldest_pending_age_seconds: null,
  stalled: false,
  stalled_reasons: [],
  last_error: null,
};

function makeHealth(_over: Partial<Health["ingestion"]> = {}): Health {
  return {
    ok: true,
    embed_model_present: true,
    answer_model_present: true,
    ingestion: {
    // /api/health is unauthenticated and carries only
    // these three. The full worker status is on /api/metrics.
    alive: true,
    stalled: false,
    busy: false,
  },
  };
}

function makeDoc(over: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: WORKING_ID,
    filename: "book4ChemicalProcessDynamicsAndControls.pdf",
    sha256: "a".repeat(64),
    size_bytes: 39_431_460,
    page_count: 1400,
    pages_done: 1400,
    chunk_count: 2113,
    chunk_count_total: 2226,
    disciplines: [],
    embedded_count: 1536,
    status: "partially_searchable",
    needs_ocr_pages: 0,
    recognised_pages: 0,
    equation_pages: 0,
    error: null,
    uploaded_at: "2026-09-04T11:53:44Z",
    indexed_at: null,
    ...over,
  };
}

function makeMetrics(over: Partial<Metrics> = {}): Metrics {
  return {
    at: "2026-09-04T12:00:00Z",
    refresh_seconds: 15,
    // Default to the NARROWER claim. A fixture that defaulted to
    // corpus-wide would make the honest case the one nobody tests.
    corpus_wide: false,
    corpus: {
      documents: 1,
      by_status: { partially_searchable: 1 },
      pages_declared: 1400,
      pages_extracted: 1400,
      chunks_total: 2226,
      chunks_retrievable: 2113,
      chunks_excluded: 113,
      chunks_indexed_keyword: 2113,
      chunks_embedded: 1536,
    },
    exclusions: [],
    jobs: { by_state: { running: 1 }, running: 1, failed_documents: 0, failures: [] },
    throughput: {
      extract: {
        unit: "pages/s",
        samples: 2,
        median: 277.6,
        best: 280.1,
        items_total: 1400,
        seconds_total: 5.0,
      },
      // Never timed long enough to measure. Must not render as a zero.
      chunk: null,
      keyword_index: null,
      embed: {
        unit: "chunks/s",
        samples: 238,
        median: 9.22,
        best: 15.07,
        items_total: 1536,
        seconds_total: 166.6,
      },
    },
    retrieval: null,
    system: {
      cpu_percent_since_last_call: 41,
      cpu_window_seconds: 15,
      cpu_logical_cores: 12,
      cpu_physical_cores: 10,
      ram_total_bytes: 16_000_000_000,
      ram_used_bytes: 14_600_000_000,
      ram_free_bytes: 1_400_000_000,
      ram_percent: 91,
      process_rss_bytes: 512_000_000,
      disk_total_bytes: 500_000_000_000,
      disk_used_bytes: 250_000_000_000,
      disk_free_bytes: 250_000_000_000,
      disk_percent: 50,
      data_dir_bytes: 1_200_000_000,
    },
    models: {
      embed_model: "e5-small",
      embed_model_present: true,
      reranker_model: "reranker",
      reranker_present: true,
      answer_model: "qwen3.5:4b",
      answer_model_reachable: true,
      answer_model_installed: true,
      answer_model_loaded: false,
      ollama_error: null,
    },
    worker: { ...idleFullWorker, current_document: WORKING_ID },
    warnings: [],
    ...over,
  };
}

function mockApi({
  metrics = makeMetrics(),
  documents = [makeDoc()],
  // Health says only THAT work is happening; the metrics worker says which.
  health = makeHealth({ busy: true }),
}: {
  metrics?: Metrics;
  documents?: DocumentRecord[];
  health?: Health;
} = {}) {
  const spy = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = url.includes("/metrics")
      ? metrics
      : url.includes("/health")
        ? health
        : documents;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

async function openIngestion() {
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /Ingestion/ }));
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ingestion navigation", () => {
  it("is no longer marked as not built", async () => {
    mockApi();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const item = within(nav).getByRole("button", { name: /Ingestion/ });
    expect(within(item).queryByText(/not built/i)).toBeNull();
  });

  it("no longer says the screen is a placeholder", async () => {
    mockApi();
    await openIngestion();
    // "Ingestion" is both the nav item and the page heading, so scope to the
    // heading rather than asserting the word appears once.
    expect(
      await screen.findByRole("heading", { level: 1, name: "Ingestion" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/placeholder/i)).toBeNull();
    expect(screen.queryByText(/not built yet/i)).toBeNull();
  });
});

describe("what the reader needs while waiting", () => {
  it("shows the answerable moment separately from the finished moment", async () => {
    // The point of the FTS5-first design: searchable in seconds, fully indexed
    // minutes later. A reader told only a single percentage waits for nothing.
    mockApi();
    await openIngestion();

    expect(
      await screen.findByText(/Searchable by keyword — questions can be asked now/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Fully indexed — wording no longer has to match the document/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/You can ask questions about this document now/),
    ).toBeInTheDocument();
  });

  it("names the file being worked on, never the document id", async () => {
    // The worker panel used to print doc_b4f589095afe at the reader.
    mockApi();
    await openIngestion();

    // Named twice on purpose: once as what the worker is on, once as the
    // card's own heading. The property under test is that the id NEVER
    // appears, which is what the panel used to print at the reader.
    const named = await screen.findAllByText(
      "book4ChemicalProcessDynamicsAndControls.pdf",
    );
    expect(named.length).toBeGreaterThan(0);
    expect(screen.queryByText(WORKING_ID)).toBeNull();
  });

  it("shows embedding position rather than a predicted percentage", async () => {
    mockApi();
    await openIngestion();
    expect(await screen.findByText("1,536 / 2,113")).toBeInTheDocument();
  });
});

describe("never a fabricated number", () => {
  it("says a stage has not been measured instead of showing zero", async () => {
    mockApi();
    await openIngestion();
    await screen.findByText("Throughput");

    // chunk and keyword_index are null in the fixture
    expect(screen.getAllByText(/not measured yet/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("0 chunks/s")).toBeNull();
  });

  it("states the sample count beside a measured rate, so it can be judged", async () => {
    mockApi();
    await openIngestion();
    expect(await screen.findByText(/median of 2 runs/)).toBeInTheDocument();
  });
});

describe("an idle screen teaches", () => {
  it("explains what it will show when nothing is being processed", async () => {
    mockApi({
      documents: [makeDoc({ status: "ready", embedded_count: 2113, indexed_at: "2026-09-04T12:00:00Z" })],
      health: makeHealth({ busy: true }),
    });
    await openIngestion();

    expect(await screen.findByText(/Nothing is being processed/)).toBeInTheDocument();
    expect(screen.getByText(/this is where you will watch it arrive/i)).toBeInTheDocument();
  });
});
