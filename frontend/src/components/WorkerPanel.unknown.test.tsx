/**
 * The worker panel before (or without) the worker detail from /api/metrics.
 *
 * `worker` is optional: health alone says alive/busy/stalled, and the four
 * figures (pending, oldest waiting, since progress, completed) come only from
 * metrics. They used to render through `worker?.x ?? 0`, so a panel whose
 * metrics had not arrived - or had failed - stated "pending 0" and
 * "since progress 0s": an empty, healthy queue nobody measured (CLAUDE.md
 * rule 4: null renders as nothing).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Health } from "../api/client";
import type { WorkerStatus } from "../types/api";
import type { Connection } from "./Shell";
import { WorkerPanel } from "./WorkerPanel";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

const online: Connection = { state: "online", health, at: 0 };

const worker: WorkerStatus = {
  alive: true,
  current_document: null,
  seconds_since_heartbeat: 0.4,
  seconds_since_progress: 12,
  documents_completed: 5,
  pending_count: 3,
  oldest_pending_age_seconds: 40,
  stalled: false,
  stalled_reasons: [],
  last_error: null,
};

describe("worker figures", () => {
  it("renders no figures, rather than zeros, when the worker detail is absent", () => {
    render(<WorkerPanel connection={online} worker={null} />);
    // The panel itself still reports from health.
    expect(screen.getByText("idle")).toBeInTheDocument();
    expect(screen.queryByText("pending")).toBeNull();
    expect(screen.queryByText("since progress")).toBeNull();
    expect(screen.queryByText("completed since the worker started")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText("0s")).toBeNull();
  });

  it("shows the measured figures when the worker detail is present", () => {
    render(<WorkerPanel connection={online} worker={worker} />);
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("12s")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });
});
