/**
 * #620 (owner's option a): the Administration page lists the Company
 * standards waiting for confirmation, states the boundary, and confirms one.
 * Invented ids and file names only.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AdminClient, AdminResult, HeldCompanyStandardList } from "../../types/admin";
import { CompanyStandardsSection } from "./CompanyStandardsSection";

const page = (standards: HeldCompanyStandardList["standards"]): AdminResult<HeldCompanyStandardList> => ({
  ok: true,
  data: { standards, total: standards.length, limit: null, offset: 0, confirm_from: "2026-10-18T00:00:00" },
});

function client(over: Partial<AdminClient>): AdminClient {
  return { ...({} as AdminClient), ...over };
}

afterEach(() => { vi.restoreAllMocks(); });

describe("CompanyStandardsSection (#620)", () => {
  it("lists the waiting standards with their count and states the option-(a) boundary", async () => {
    const held = vi.fn().mockResolvedValue(page([
      { id: "std-1", filename: "sample-company-standard.pdf", uploaded_at: "2026-10-19T09:00:00Z" },
    ]));
    render(<CompanyStandardsSection client={client({ heldCompanyStandards: held, confirmCompanyStandard: vi.fn() })} />);
    expect(await screen.findByTestId("admin-held-count")).toHaveTextContent("1 Company standard is waiting for confirmation.");
    expect(screen.getByTestId("admin-held-boundary")).toHaveTextContent(
      "Company standards uploaded before 2026-10-18 count as confirmed and are not listed here.");
    const row = screen.getByTestId("admin-held-std-1");
    expect(row).toHaveTextContent("sample-company-standard.pdf");
    expect(row).toHaveTextContent("uploaded 2026-10-19");
  });

  it("an empty list says nothing is waiting, and still says which standards it does not cover", async () => {
    const held = vi.fn().mockResolvedValue(page([]));
    render(<CompanyStandardsSection client={client({ heldCompanyStandards: held })} />);
    expect(await screen.findByTestId("admin-held-count")).toHaveTextContent("No Company standard is waiting for confirmation.");
    expect(screen.getByTestId("admin-held-boundary")).toHaveTextContent("uploaded before 2026-10-18 count as confirmed");
  });

  it("confirm asks first, calls the route, then reads the list again", async () => {
    const user = userEvent.setup();
    const held = vi.fn()
      .mockResolvedValueOnce(page([{ id: "std-1", filename: "sample-company-standard.pdf", uploaded_at: null }]))
      .mockResolvedValueOnce(page([]));
    const confirmRoute = vi.fn().mockResolvedValue({ ok: true, data: { document_id: "std-1", confirmed: true } });
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<CompanyStandardsSection client={client({ heldCompanyStandards: held, confirmCompanyStandard: confirmRoute })} />);
    await user.click(within(await screen.findByTestId("admin-held-std-1")).getByRole("button", { name: "Confirm for reviews" }));
    expect(ask).toHaveBeenCalled();
    expect(confirmRoute).toHaveBeenCalledWith("std-1");
    expect(await screen.findByRole("status")).toHaveTextContent('Confirmed: "sample-company-standard.pdf" is used from the next review.');
    expect(held).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("admin-held-count")).toHaveTextContent("No Company standard is waiting");
  });

  it("saying no to the question confirms nothing", async () => {
    const user = userEvent.setup();
    const held = vi.fn().mockResolvedValue(page([{ id: "std-1", filename: "s.pdf", uploaded_at: null }]));
    const confirmRoute = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<CompanyStandardsSection client={client({ heldCompanyStandards: held, confirmCompanyStandard: confirmRoute })} />);
    await user.click(await screen.findByRole("button", { name: "Confirm for reviews" }));
    expect(confirmRoute).not.toHaveBeenCalled();
  });

  it("an unreachable backend and an unbuilt route are not 'nothing waiting'", async () => {
    const offline = vi.fn().mockResolvedValue({ ok: false, disconnected: true, error: { code: "internal", message: "x" } });
    const { unmount } = render(<CompanyStandardsSection client={client({ heldCompanyStandards: offline })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The backend is not running");
    expect(screen.queryByTestId("admin-held-count")).toBeNull();
    unmount();
    const missing = vi.fn().mockResolvedValue({ ok: false, disconnected: false, error: { code: "not_found", message: "x" } });
    render(<CompanyStandardsSection client={client({ heldCompanyStandards: missing })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("does not serve the Company standard confirmation list");
  });
});
