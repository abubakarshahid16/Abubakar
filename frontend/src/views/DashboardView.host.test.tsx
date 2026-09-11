/**
 * The dashboard when this reader is not allowed to see the machine (#77).
 *
 * The backend now withholds the host block from any caller without the admin
 * capability, and Pydantic puts a single `null` on the wire for it. The
 * dashboard destructured `system` and dereferenced it fourteen times without
 * a guard, so the honest backend answer would have crashed the screen for
 * every engineer - a disclosure fix that takes the dashboard down for the
 * majority of users is not a fix.
 *
 * TWO PROPERTIES, and the second matters more than the first:
 *
 *   1. The screen renders. No throw, and the rest of the dashboard - corpus,
 *      models, worker, warnings - is still there.
 *
 *   2. It does not INVENT the numbers it was refused. `bytes(undefined)` and
 *      `percent ?? 0` are the tempting shape of the guard and both of them
 *      state a measurement that is false: "0 B free of 0 B" is not a withheld
 *      value, it is a wrong one, and a full-width zeroed bar reads as a
 *      healthy machine with no disk. The rule this file holds is that an
 *      absent measurement produces NO measurement on screen.
 *
 * The warning is deliberately NOT part of the host block and is asserted here
 * as well: `low_memory_for_answer_model` still reaches a non-admin, because it
 * is a statement about what the product is about to fail to do rather than a
 * fact about the machine. Its figure-free wording is the backend's job
 * (test_metrics_host_telemetry.py); that it still RENDERS is this file's.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Health } from "../api/client";
import type { Metrics, WorkerStatus } from "../types/api";

const worker: WorkerStatus = {
  alive: true,
  current_document: null,
  seconds_since_heartbeat: 0.4,
  seconds_since_progress: 12,
  documents_completed: 5,
  pending_count: 0,
  oldest_pending_age_seconds: null,
  stalled: false,
  stalled_reasons: [],
  last_error: null,
};

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

/** A non-admin's metrics payload: scoped corpus figures, no host block.
 *
 * `system: null` rather than a missing key, because that is what the wire
 * actually carries - the route omits it from its dict and the response model
 * serialises the optional field as null. Testing the shape the frontend will
 * really be handed, not the shape the backend intends. */
function nonAdminMetrics(over: Partial<Metrics> = {}): Metrics {
  return {
    at: "2026-09-06T12:00:00Z",
    refresh_seconds: 15,
    corpus_wide: false,
    corpus: {
      documents: 1,
      by_status: { ready: 1 },
      pages_declared: 200,
      pages_extracted: 200,
      chunks_total: 500,
      chunks_retrievable: 480,
      chunks_excluded: 20,
      chunks_indexed_keyword: 480,
      chunks_embedded: 480,
    },
    exclusions: [],
    jobs: { by_state: {}, running: 0, failed_documents: 0, failures: [] },
    throughput: { extract: null, chunk: null, keyword_index: null, embed: null },
    retrieval: null,
    system: null,
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
    worker,
    warnings: [],
    ...over,
  };
}

function mockApi(metrics: Metrics) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      const body = url.includes("/metrics")
        ? metrics
        : url.includes("/health")
          ? health
          : [];
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

async function openDashboard(metrics: Metrics) {
  mockApi(metrics);
  render(<App />);
  await userEvent.click(await screen.findByRole("button", { name: /Dashboard/ }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the dashboard for a reader who may not see the machine", () => {
  it("still renders the rest of the screen", async () => {
    await openDashboard(nonAdminMetrics());

    // Proof the dashboard MOUNTED rather than that a throw was swallowed:
    // a scoped corpus figure the same payload carries.
    expect(await screen.findByText(/1 document loaded, 480 passages/)).toBeInTheDocument();
  });

  it("shows no host measurements at all rather than zeros", async () => {
    await openDashboard(nonAdminMetrics());
    await screen.findByText(/1 document loaded, 480 passages/);

    const text = document.body.textContent ?? "";

    // The three headings of the Machine card. Absent, because a card whose
    // every value is missing is not a card - an empty "CPU"/"Memory"/"Disk"
    // frame invites the reader to conclude the machine has none.
    expect(screen.queryByText("Machine")).toBeNull();
    expect(screen.queryByText("CPU")).toBeNull();
    expect(screen.queryByText("Memory")).toBeNull();
    expect(screen.queryByText("Disk")).toBeNull();

    // `bytes(undefined)` and `?? 0` are the two guards that would pass the
    // assertions above only if the whole card were dropped, and would fail
    // loudly here if the card were kept with blanked values. Both spellings
    // are checked because `bytes()` may render either.
    expect(text).not.toMatch(/0 B\b/);
    expect(text).not.toMatch(/\bfree of\b/);
    // The host card's own phrasing, not the bare word: "installed, not
    // resident" is the ANSWER MODEL's hint and is legitimately on this
    // screen for every reader. Asserting on /resident/ alone would fail on
    // correct output - a test that punishes the wrong thing.
    expect(text).not.toMatch(/this backend:[^]*resident/);
    expect(text).not.toMatch(/NaN|undefined/);
  });

  it("still shows a warning that is about the product, not the machine", async () => {
    /** The warning survives the host gate. Its figure-free wording is proven
     *  on the backend; what is proven here is that the dashboard renders a
     *  warning for a reader who has no `system` block, because the code path
     *  that reads warnings sits below the one that crashed. */
    await openDashboard(
      nonAdminMetrics({
        warnings: [
          {
            code: "low_memory_for_answer_model",
            // "warning", not "warn": metrics.py emits only info | warning |
            // error, so a "warn" fixture described a response the backend
            // cannot produce.
            severity: "warning",
            // Always sent, null where no document is implicated - the field is
            // required in both schemas.MetricWarning and the contract, so
            // omitting it described an impossible response too.
            document_id: null,
            message:
              "This machine is low on memory for the answer model. Tier 2 " +
              "(Explain) may be slow or fail. Quoted answers are unaffected. " +
              "Closing other applications will help.",
          },
        ],
      }),
    );

    expect(await screen.findByText(/Tier 2 \(Explain\) may be slow or fail/)).toBeTruthy();
  });
});

describe("the dashboard for an admin", () => {
  it("still shows the machine card in full", async () => {
    /** The gate must scope the feature, not remove it. Same screen, same
     *  fixture, host block present. */
    await openDashboard(
      nonAdminMetrics({
        corpus_wide: true,
        system: {
          cpu_percent_since_last_call: 31.5,
          cpu_window_seconds: 15,
          cpu_logical_cores: 12,
          cpu_physical_cores: 10,
          ram_total_bytes: 16_000_000_000,
          ram_used_bytes: 9_600_000_000,
          ram_free_bytes: 6_400_000_000,
          ram_percent: 60,
          process_rss_bytes: 512_000_000,
          disk_total_bytes: 500_000_000_000,
          disk_used_bytes: 250_000_000_000,
          disk_free_bytes: 250_000_000_000,
          disk_percent: 50,
          data_dir_bytes: 1_200_000_000,
        },
      }),
    );

    expect(await screen.findByText("Machine")).toBeTruthy();
    expect(screen.getByText("CPU")).toBeTruthy();
    expect(screen.getByText(/10 physical/)).toBeTruthy();
    expect(screen.getByText(/free of/)).toBeTruthy();
  });
});
