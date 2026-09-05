/**
 * MarketPanel: every row is sample, no URL is a link, and nothing leaves the
 * machine without the exact string being shown and egress being allowed.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarketPanel } from "./MarketPanel";
import type { EgressState, MarketFinding, PublicMarketQuery } from "../../types/analysis";

const FINDINGS: MarketFinding[] = [
  {
    claim: "Zinc-rich epoxy primers list at roughly USD 18–24 per litre in Q2 2026.",
    url: "https://example.com/coatings/price-index-2026-q2",
    publisher: "Example Coatings Index",
    published_at: "2026-06-30",
    retrieved_at: "2026-09-01T10:15:00Z",
    verification: "snippet_only",
    is_sample: true,
  },
  {
    claim: "Lead time for NORSOK-qualified systems averaged six weeks.",
    url: "https://example.org/supply/lead-times",
    publisher: "Example Supply Watch",
    published_at: null,
    retrieved_at: "2026-09-01T10:16:00Z",
    verification: "source_not_verified",
    is_sample: true,
  },
];

const OFFLINE: EgressState = { web_search_enabled: false, allow_public_egress: false };

const QUERY: PublicMarketQuery = { query: "zinc epoxy primer price", country: "NO", freshness_days: 90 };

describe("MarketPanel: sample data", () => {
  it("shows the SAMPLE DATA banner", () => {
    render(<MarketPanel findings={FINDINGS} egress={OFFLINE} />);
    expect(screen.getByRole("note")).toHaveTextContent(/SAMPLE DATA — NOT LIVE/);
  });

  it("tags every finding row as SAMPLE", () => {
    expect(FINDINGS.length).toBeGreaterThan(1);
    expect(FINDINGS.every((f) => f.is_sample)).toBe(true);
    render(<MarketPanel findings={FINDINGS} egress={OFFLINE} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(FINDINGS.length);
    for (const li of items) {
      expect(within(li).getByText(/^sample$/i)).toBeInTheDocument();
    }
  });

  it("renders URLs as text with no <a> element anywhere", () => {
    expect(FINDINGS.every((f) => /^https?:\/\//.test(f.url))).toBe(true);
    const { container } = render(<MarketPanel findings={FINDINGS} egress={OFFLINE} />);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(screen.getByText(FINDINGS[0].url)).toBeInTheDocument();
  });
});

describe("MarketPanel: egress state", () => {
  it("shows both pills when web search and public egress are off", () => {
    expect(OFFLINE.web_search_enabled).toBe(false);
    expect(OFFLINE.allow_public_egress).toBe(false);
    render(<MarketPanel findings={[]} egress={OFFLINE} />);
    expect(screen.getByText(/web search off/i)).toBeInTheDocument();
    expect(screen.getByText(/public egress blocked/i)).toBeInTheDocument();
  });

  it("disables Confirm and states the reason when egress is blocked", () => {
    expect(OFFLINE.allow_public_egress).toBe(false);
    render(
      <MarketPanel
        findings={[]}
        egress={OFFLINE}
        pendingQuery={QUERY}
        onConfirmQuery={vi.fn()}
        onCancelQuery={vi.fn()}
      />,
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Confirm and send" })).toBeDisabled();
    expect(within(dialog).getByRole("status")).toHaveTextContent("Public egress is blocked in this build.");
    expect(within(dialog).getByText(JSON.stringify(QUERY))).toBeInTheDocument();
  });

  it("the confirm dialog is a modal dialog", () => {
    render(<MarketPanel findings={[]} egress={OFFLINE} pendingQuery={QUERY} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("renders no dialog when there is no pending query", () => {
    render(<MarketPanel findings={[]} egress={OFFLINE} pendingQuery={null} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
