/**
 * #666: the administrator's "Free model memory" button.
 *
 * MUTATION PROOF (scripts/mutations/w7_666_model_memory.py, M4212 to M4214):
 * the button not calling the route, the result not naming a model that is
 * still loaded, and the button shown to a non-admin each fail a test here.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { FreeModelMemory } from "./FreeModelMemory";
import { DashboardTechnicalDetails } from "../views/DashboardTechnicalDetails";
import type { Metrics } from "../types/api";

afterEach(() => vi.unstubAllGlobals());

function answer(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("FreeModelMemory", () => {
  it("asks the server to unload and names what was freed", async () => {
    const fetchMock = answer(200, { reachable: true, freed: ["qwen3.5:4b"], still_loaded: [] });
    render(<FreeModelMemory />);
    fireEvent.click(screen.getByRole("button", { name: "Free model memory" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Freed: qwen3.5:4b."));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/admin/models/unload");
    expect(init.method).toBe("POST");
  });

  it("names a model that is still loaded instead of claiming success", async () => {
    answer(200, { reachable: true, freed: [], still_loaded: ["qwen3.5:2b"] });
    render(<FreeModelMemory />);
    fireEvent.click(screen.getByRole("button", { name: "Free model memory" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Still loaded: qwen3.5:2b."));
    expect(screen.getByRole("status").textContent).not.toContain("Freed");
  });

  it("says so when Ollama cannot be reached", async () => {
    answer(200, { reachable: false, freed: [], still_loaded: [] });
    render(<FreeModelMemory />);
    fireEvent.click(screen.getByRole("button", { name: "Free model memory" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("could not be reached"));
  });

  it("shows the server's refusal", async () => {
    answer(404, { detail: { code: "not_found", message: "not found" } });
    render(<FreeModelMemory />);
    fireEvent.click(screen.getByRole("button", { name: "Free model memory" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  });
});

describe("the models panel", () => {
  const m = {
    at: "2026-10-09T12:00:00Z", refresh_seconds: 15, corpus_wide: false,
    corpus: { documents: 1, by_status: { ready: 1 }, pages_declared: 1, pages_extracted: 1,
      chunks_total: 1, chunks_retrievable: 1, chunks_excluded: 0, chunks_indexed_keyword: 1,
      chunks_embedded: 1 },
    exclusions: [], jobs: { by_state: {}, running: 0, failed_documents: 0, failures: [] },
    throughput: {}, retrieval: null, system: undefined,
    models: { embed_model: "e5-small", embed_model_present: true, reranker_model: "rr",
      reranker_present: true, answer_model: "qwen3.5:4b", answer_model_reachable: true,
      answer_model_installed: true, answer_model_loaded: true, ollama_error: null },
    worker: { alive: true, current_document: null, seconds_since_heartbeat: 0.4,
      seconds_since_progress: 12, documents_completed: 1, pending_count: 0,
      oldest_pending_age_seconds: null, stalled: false, stalled_reasons: [], last_error: null },
    warnings: [],
  } as unknown as Metrics;
  const view = (isAdmin: boolean) => render(
    <DashboardTechnicalDetails metrics={m} corpus={m.corpus} throughput={m.throughput}
      retrieval={m.retrieval} jobs={m.jobs} worker={m.worker} models={m.models}
      system={m.system} noSearchable={0} isAdmin={isAdmin} />);

  it("shows the button to an administrator only", () => {
    const admin = view(true);
    expect(admin.container.querySelector('[data-testid="free-model-memory"]')).not.toBeNull();
    admin.unmount();
    const other = view(false);
    expect(other.container.querySelector('[data-testid="free-model-memory"]')).toBeNull();
  });
});
