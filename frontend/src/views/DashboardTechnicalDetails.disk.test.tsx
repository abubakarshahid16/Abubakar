/**
 * The Disk card on the Machine section.
 *
 * The backend sends `disk_percent: null` when the OS reports a disk total of
 * 0 - the disk was never measured. The card used to render that through
 * `disk_percent ?? 0`: a 0%-used progressbar in the healthy tone and "0 B
 * free", a measurement nobody took (CLAUDE.md rule 4: null renders as
 * nothing). These tests render the card directly, so the assertion is on the
 * Disk tile alone and cannot be satisfied by the CPU tile beside it.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Metrics, SystemMetrics } from "../types/api";
import { DashboardTechnicalDetails } from "./DashboardTechnicalDetails";

const HOST: SystemMetrics = {
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
  disk_used_bytes: 400_000_000_000,
  disk_free_bytes: 100_000_000_000,
  disk_percent: 80,
  data_dir_bytes: 1_200_000_000,
};

function makeMetrics(system: SystemMetrics): Metrics {
  return {
    at: "2026-09-27T12:00:00Z",
    refresh_seconds: 15,
    corpus_wide: false,
    corpus: {
      documents: 1,
      by_status: { ready: 1 },
      pages_declared: 10,
      pages_extracted: 10,
      chunks_total: 20,
      chunks_retrievable: 20,
      chunks_excluded: 0,
      chunks_indexed_keyword: 20,
      chunks_embedded: 20,
    },
    exclusions: [],
    jobs: { by_state: {}, running: 0, failed_documents: 0, failures: [] },
    throughput: {},
    retrieval: null,
    system,
    models: {
      embed_model: "e5-small",
      embed_model_present: true,
      reranker_model: "reranker",
      reranker_present: true,
      answer_model: "qwen3.5:4b",
      answer_model_reachable: true,
      answer_model_installed: true,
      answer_model_loaded: true,
      ollama_error: null,
    },
    worker: {
      alive: true,
      current_document: null,
      seconds_since_heartbeat: 0.4,
      seconds_since_progress: 12,
      documents_completed: 1,
      pending_count: 0,
      oldest_pending_age_seconds: null,
      stalled: false,
      stalled_reasons: [],
      last_error: null,
    },
    warnings: [],
  };
}

function renderDiskCard(system: SystemMetrics): HTMLElement {
  const m = makeMetrics(system);
  render(
    <DashboardTechnicalDetails
      metrics={m}
      corpus={m.corpus}
      throughput={m.throughput}
      retrieval={m.retrieval}
      jobs={m.jobs}
      worker={m.worker}
      models={m.models}
      system={m.system}
      noSearchable={0}
    />,
  );
  // The label <p> sits directly inside the card's own div.
  return screen.getByText("Disk").parentElement as HTMLElement;
}

describe("Disk card", () => {
  it("says the disk is not measured instead of drawing a 0% bar", () => {
    const card = renderDiskCard({ ...HOST, disk_percent: null, disk_total_bytes: 0, disk_used_bytes: 0, disk_free_bytes: 0 });
    expect(within(card).getByText(/not measured yet/i)).toBeInTheDocument();
    expect(within(card).queryByRole("progressbar")).toBeNull();
    // Neither a zeroed free figure nor a percentage.
    expect(card.textContent).not.toMatch(/0 B\s*free/);
    expect(card.textContent).not.toMatch(/\d+%/);
    // The data-dir size is its own directory walk, still measured.
    expect(within(card).getByText(/documents and index: 1\.1 GB/)).toBeInTheDocument();
  });

  it("shows the free space and a bar at the measured percentage", () => {
    const card = renderDiskCard(HOST);
    expect(within(card).queryByText(/not measured yet/i)).toBeNull();
    const bar = within(card).getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "80");
    expect(card.textContent).toMatch(/93 GB\s*free/);
  });

  it("uses the same not-measured wording and style as the CPU card", () => {
    renderDiskCard({ ...HOST, cpu_percent_since_last_call: null, disk_percent: null });
    const cpu = screen.getByText("CPU").parentElement as HTMLElement;
    const disk = screen.getByText("Disk").parentElement as HTMLElement;
    const cpuNote = within(cpu).getByText(/not measured yet/i);
    const diskNote = within(disk).getByText(/not measured yet/i);
    expect(diskNote.textContent?.trim()).toBe(cpuNote.textContent?.trim());
    expect(diskNote.className).toBe(cpuNote.className);
  });
});
