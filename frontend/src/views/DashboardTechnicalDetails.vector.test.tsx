/**
 * The "Vector search" tile in System Health's Models section.
 *
 * Owner decision 2026-09-27: dense search runs on sqlite-vec, with the exact
 * numpy matrix as the automatic fallback. A fallback must never be silent, so
 * the tile names the active backend and, when it is the fallback, the reason
 * the backend reported. Stale vectors (another model or input format) are
 * named with their count, because they are left out of search until
 * re-embedded.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Metrics, VectorStoreStatus } from "../types/api";
import { DashboardTechnicalDetails } from "./DashboardTechnicalDetails";

const ACTIVE: VectorStoreStatus = {
  requested: "auto",
  active: "sqlite_vec",
  fallback_reason: null,
  sqlite_vec_version: "v0.1.9",
  exact: true,
  embedding_tag: "model_qint8_avx512_vnni.onnx+heading-v1",
  last_error: null,
  current_vectors: 22784,
  stale_vectors: 0,
};

function makeMetrics(vector_store: VectorStoreStatus | null): Metrics {
  return {
    at: "2026-09-27T12:00:00Z",
    refresh_seconds: 15,
    corpus_wide: false,
    corpus: {
      documents: 1, by_status: { ready: 1 }, pages_declared: 10, pages_extracted: 10,
      chunks_total: 20, chunks_retrievable: 20, chunks_excluded: 0,
      chunks_indexed_keyword: 20, chunks_embedded: 20,
    },
    exclusions: [],
    jobs: { by_state: {}, running: 0, failed_documents: 0, failures: [] },
    throughput: {},
    retrieval: null,
    system: null,
    models: {
      embed_model: "e5-small", embed_model_present: true, reranker_model: "reranker",
      reranker_present: true, answer_model: "qwen3.5:4b", answer_model_reachable: true,
      answer_model_installed: true, answer_model_loaded: true, ollama_error: null,
    },
    vector_store,
    worker: {
      alive: true, current_document: null, seconds_since_heartbeat: 0.4,
      seconds_since_progress: 12, documents_completed: 1, pending_count: 0,
      oldest_pending_age_seconds: null, stalled: false, stalled_reasons: [], last_error: null,
    },
    warnings: [],
  };
}

function renderTile(vector_store: VectorStoreStatus | null) {
  const m = makeMetrics(vector_store);
  render(
    <DashboardTechnicalDetails metrics={m} corpus={m.corpus} throughput={m.throughput}
      retrieval={m.retrieval} jobs={m.jobs} worker={m.worker} models={m.models}
      system={m.system} noSearchable={0} />,
  );
}

describe("Vector search tile", () => {
  it("names sqlite-vec and its version when it is active", () => {
    renderTile(ACTIVE);
    const tile = screen.getByText("Vector search").parentElement as HTMLElement;
    expect(tile.textContent).toContain("sqlite-vec v0.1.9");
    expect(tile.textContent).toContain("exact search");
  });

  it("says a fallback is a fallback and why", () => {
    renderTile({ ...ACTIVE, active: "numpy", sqlite_vec_version: null,
      fallback_reason: "the sqlite-vec package is not installed" });
    const tile = screen.getByText("Vector search").parentElement as HTMLElement;
    expect(tile.textContent).toContain("numpy (fallback)");
    expect(tile.textContent).toContain("the sqlite-vec package is not installed");
  });

  it("counts stale vectors that need re-embedding", () => {
    renderTile({ ...ACTIVE, stale_vectors: 1200 });
    const tile = screen.getByText("Vector search").parentElement as HTMLElement;
    expect(tile.textContent).toMatch(/1,?200 stale vectors need re-embedding/);
  });

  it("renders nothing for a backend that does not report the block", () => {
    renderTile(null);
    expect(screen.queryByText("Vector search")).toBeNull();
  });
});
