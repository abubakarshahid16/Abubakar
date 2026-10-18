/**
 * #1070: the Dashboard polls once a minute through the shared poller, makes no
 * call in a hidden tab, and looks again the moment the tab is shown. It used
 * to run its own 15 s timer that never stopped.
 */
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IDLE_MS } from "../hooks/usePoll";
import { DashboardView } from "./DashboardViewContent";

const calls = { metrics: 0 };

vi.mock("../api/client", () => ({
  api: { metrics: vi.fn(async () => { calls.metrics += 1; return { ok: false, error: { code: "x", message: "not now" }, disconnected: false }; }) },
  classification: { coverage: vi.fn(async () => ({ ok: false })) },
  management: { summary: vi.fn(async () => ({ ok: false })) },
}));

function setVisibility(v: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => v });
  document.dispatchEvent(new Event("visibilitychange"));
}

afterEach(() => {
  vi.useRealTimers();
  calls.metrics = 0;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
});

const online = { state: "online", at: 0, health: {} } as never;

describe("the Dashboard's polling (#1070)", () => {
  it("asks for metrics once a minute, never while hidden, and at once when shown", () => {
    vi.useFakeTimers();
    render(<DashboardView connection={online} onRetryConnection={() => undefined} />);
    expect(calls.metrics).toBe(1);
    act(() => { vi.advanceTimersByTime(15_000 * 3); });
    expect(calls.metrics).toBe(1); // not every 15 s any more
    act(() => { vi.advanceTimersByTime(IDLE_MS - 15_000 * 3); });
    expect(calls.metrics).toBe(2);

    act(() => setVisibility("hidden"));
    act(() => { vi.advanceTimersByTime(IDLE_MS * 10); });
    expect(calls.metrics).toBe(2);

    act(() => setVisibility("visible"));
    expect(calls.metrics).toBe(3);
  });
});
