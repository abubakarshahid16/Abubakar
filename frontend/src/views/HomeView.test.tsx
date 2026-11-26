import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PURPOSE, PurposeLine } from "../components/PurposeLine";
import { parseRoute } from "../routing";
import { HomeView, nextStep } from "./HomeView";

const dashboard = vi.fn();
const metrics = vi.fn();
vi.mock("../api/client", () => ({ reviews: { dashboard: () => dashboard() } }));
vi.mock("../api/technicalQueries", () => ({ technicalQueriesApi: { metrics: () => metrics() } }));

const ON = { required: true, technical_queries: true, user: null } as never;
const OFF = { required: true, technical_queries: false, user: null } as never;

beforeEach(() => {
  dashboard.mockResolvedValue({ ok: true, data: { reviews_awaiting_decision: 3 } });
  metrics.mockResolvedValue({ ok: true, data: { received: 20, triage: 5, drafting: 4, approved: 7, resolved: 9, total: 45 } });
});

describe("Home: the three jobs first (owner, 26 Nov 2026, G9)", () => {
  it("shows the three jobs in everyday words, the open work beside each and one next button", async () => {
    const go = vi.fn();
    render(<HomeView auth={ON} onNavigate={go} />);
    const jobs = { review: "Review a contractor document", technicalQueries: "Answer a contractor query (TQ / CFC)", chat: "Ask a question about our documents" };
    for (const [view, job] of Object.entries(jobs)) {
      expect(within(screen.getByTestId(`home-job-${view}`)).getByRole("button", { name: job })).toBeInTheDocument();
    }
    expect(await screen.findByText("3 reviews waiting for your decision (of the reviews you may see)")).toBeInTheDocument();
    // received + triage + drafting: approved and resolved queries wait for nobody
    expect(await screen.findByText("29 queries waiting for an answer (of the queries you may see)")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("home-next"));
    expect(screen.getByTestId("home-next").textContent).toBe("Open the 3 reviews waiting for your decision");
    expect(go).toHaveBeenCalledWith("review");
    fireEvent.click(screen.getByRole("button", { name: "Ask a question about our documents" }));
    expect(go).toHaveBeenLastCalledWith("chat");
  });

  it("never shows a count it could not read, and says when queries are switched off", async () => {
    dashboard.mockResolvedValue({ ok: false, error: { message: "down" } });
    render(<HomeView auth={OFF} onNavigate={vi.fn()} />);
    await waitFor(() => expect(dashboard).toHaveBeenCalled());
    expect(screen.queryByText(/waiting for your decision \(/)).toBeNull(); // no "0" stands in for an unread count
    expect(metrics).not.toHaveBeenCalled();
    expect(screen.getByText("Switched off on this server. An administrator can switch it on.")).toBeInTheDocument();
    expect(within(screen.getByTestId("home-job-technicalQueries")).getByRole("button")).toBeDisabled();
    expect(screen.getByTestId("home-next").textContent).toBe("Review a contractor document");
  });

  it("points the next button at the queries when no review waits", () => {
    expect(nextStep({ reviewsWaiting: 0, queriesWaiting: 1 }, true)).toEqual({ label: "Open the 1 query waiting for an answer", view: "technicalQueries" });
    expect(nextStep({ reviewsWaiting: 0, queriesWaiting: 4 }, false).view).toBe("review");
  });

  it("is what the app opens on; Documents keeps its own address", () => {
    expect(parseRoute("/")).toEqual({ kind: "view", view: "home" });
    expect(parseRoute("/home")).toEqual({ kind: "view", view: "home", recordId: undefined });
    expect(parseRoute("/documents")).toEqual({ kind: "view", view: "documents", recordId: undefined });
  });
});

describe("every main screen starts with one line: what it is for and what to do next (E4)", () => {
  it("has a line for each main screen and none for the others", () => {
    // Reviews opens with its own line already ("To check a new file, pick it and press Start review ..."), so it gets none here
    for (const view of ["technicalQueries", "chat", "documents"] as const) {
      const { unmount } = render(<PurposeLine view={view} />);
      expect(screen.getByTestId("screen-purpose").textContent).toBe(PURPOSE[view]);
      unmount();
    }
    const { container } = render(<PurposeLine view="ingestion" />);
    expect(container.textContent).toBe("");
  });
});
