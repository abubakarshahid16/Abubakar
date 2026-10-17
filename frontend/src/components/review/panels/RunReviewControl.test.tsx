/**
 * "Check it" for one document (#967 PR 3), on made-up readiness: the
 * readiness strip with its denominators, "Nothing changed since the last
 * run" asked BEFORE a re-run, Read unread pages, the vision reader's real
 * reason, and the admin gate with its reason. Ported from the old page's
 * tests; the words are unchanged.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewReadiness } from "../../../types/api";
import { RunReviewControl } from "./RunReviewControl";

const readiness = vi.fn();
const rereadPages = vi.fn();
const startReviewRun = vi.fn();
const visionReaderStatus = vi.fn();

vi.mock("../../../api/client", () => ({
  reviews: {
    readiness: (...args: unknown[]) => readiness(...args),
    rereadPages: (...args: unknown[]) => rereadPages(...args),
    startReviewRun: (...args: unknown[]) => startReviewRun(...args),
    visionReaderStatus: (...args: unknown[]) => visionReaderStatus(...args),
  },
}));

function ready(over: Partial<ReviewReadiness> = {}): ReviewReadiness {
  return {
    submittal_document_id: "doc-sub",
    pages_total: 5,
    pages_read: 3,
    unread_pages: [4, 5],
    unread_page_reasons: {
      "4": "no label-value pairs recovered from this page",
      "5": "read only by the page reader",
    },
    standards_cited: 3,
    standards_held: ["API 999.pdf"],
    standards_missing: ["API 998", "API 997"],
    last_run_id: "run-2",
    nothing_changed: false,
    changes: ["2 datasheet value(s) read since the last run"],
    ...over,
  };
}

beforeEach(() => {
  for (const mock of [readiness, rereadPages, startReviewRun, visionReaderStatus]) mock.mockReset();
  readiness.mockResolvedValue({ ok: true, data: ready() });
  startReviewRun.mockResolvedValue({ ok: true, data: { review_run_id: "run-3" } });
  visionReaderStatus.mockResolvedValue({ ok: true, data: {
    state: "READY", ready: true, reason: "Vision reader ready.", fix: "", detail: null,
    checked_at: "2026-09-27T00:00:00+00:00" } });
});

function control(over: Partial<Parameters<typeof RunReviewControl>[0]> = {}) {
  return render(
    <RunReviewControl submittalId="doc-sub" isAdmin label="Check it" onStarted={vi.fn()} {...over} />,
  );
}

const strip = async () => within(await screen.findByTestId("readiness-strip"));

describe("the readiness strip", () => {
  it("states pages read and standards held and missing, with denominators", async () => {
    const onOpenStandards = vi.fn();
    control({ onOpenStandards });
    const s = await strip();
    expect(readiness).toHaveBeenCalledWith("doc-sub");
    expect(s.getByText(/Pages read: 3 of 5/)).toBeInTheDocument();
    expect(s.getByText(/not read: 4/)).toBeInTheDocument();
    expect(s.getByText(/Standards cited: 1 held, 2 missing \(of 3\)/)).toBeInTheDocument();
    expect(s.getByText(/2 datasheet value\(s\) read since the last run/)).toBeInTheDocument();
    await userEvent.click(s.getByRole("button", { name: "Upload missing standards" }));
    expect(onOpenStandards).toHaveBeenCalled();
  });

  it("offers no upload link when nothing is missing", async () => {
    readiness.mockResolvedValue({ ok: true, data: ready({ standards_missing: [], standards_cited: 1 }) });
    control();
    expect((await strip()).queryByRole("button", { name: "Upload missing standards" })).toBeNull();
  });

  it("HONESTY GROUP: names WHY each unread page is unread, not just its number", async () => {
    readiness.mockResolvedValue({ ok: true, data: ready({ unread_page_reasons: {
      "4": "no label-value pairs recovered from this page",
      "5": "vision reader not run (page could not be rendered)",
    } }) });
    control();
    const s = await strip();
    expect(s.getByText(/Page 4: no label-value pairs recovered from this page/)).toBeInTheDocument();
    expect(s.getByText(/Page 5: vision reader not run \(page could not be rendered\)/)).toBeInTheDocument();
  });

  it("says a reason was not recorded rather than showing nothing", async () => {
    readiness.mockResolvedValue({ ok: true, data: ready({ unread_page_reasons: {} }) });
    control();
    expect((await strip()).getByText(/Page 4: reason not recorded/)).toBeInTheDocument();
  });
});

describe("a re-run that cannot say anything new", () => {
  it("is asked about first when nothing changed", async () => {
    readiness.mockResolvedValue({ ok: true, data: ready({ nothing_changed: true, changes: [] }) });
    const onStarted = vi.fn();
    control({ onStarted });
    await strip();
    await userEvent.click(screen.getByRole("button", { name: "Check it" }));
    expect(screen.getByRole("alertdialog", { name: "Nothing changed since the last run" })).toBeInTheDocument();
    expect(startReviewRun).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Run again anyway" }));
    expect(startReviewRun).toHaveBeenCalledWith("doc-sub");
    expect(onStarted).toHaveBeenCalledWith("run-3");
  });

  it("runs straight away when something changed", async () => {
    control();
    await strip();
    await userEvent.click(screen.getByRole("button", { name: "Check it" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(startReviewRun).toHaveBeenCalledWith("doc-sub");
  });

  it("shows the server's refusal as the server worded it", async () => {
    startReviewRun.mockResolvedValue({ ok: false, error: { message: "a review of this submittal is already running" } });
    control();
    await strip();
    await userEvent.click(screen.getByRole("button", { name: "Check it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already running");
  });
});

describe("Read unread pages", () => {
  it("re-extracts and shows the returned readiness, only when pages are unread", async () => {
    rereadPages.mockResolvedValue({ ok: true, data: ready({ unread_pages: [], nothing_changed: true, changes: [] }) });
    const onReread = vi.fn(async () => undefined);
    control({ onReread });
    const s = await strip();
    await userEvent.click(s.getByRole("button", { name: "Read unread pages" }));
    expect(rereadPages).toHaveBeenCalledWith("doc-sub");
    expect(await s.findByText(/Nothing changed since the last run/)).toBeInTheDocument();
    expect(s.queryByRole("button", { name: "Read unread pages" })).toBeNull();
    expect(onReread).toHaveBeenCalled();
  });

  it("shows the error rather than failing silently", async () => {
    rereadPages.mockResolvedValue({ ok: false, error: { message: "budget exceeded" } });
    control();
    const s = await strip();
    await userEvent.click(s.getByRole("button", { name: "Read unread pages" }));
    expect(await s.findByRole("alert")).toHaveTextContent("budget exceeded");
  });

  it("shows the vision reader's real reason and the fix when page images cannot be read", async () => {
    visionReaderStatus.mockResolvedValue({ ok: true, data: {
      state: "KEY_INVALID", ready: false, reason: "Claude rejected the API key.",
      fix: "Check the key in backend/.env is current and active, then restart the backend.",
      detail: "HTTP 401", checked_at: "2026-09-27T00:00:00+00:00" } });
    control();
    const s = await strip();
    const line = await s.findByText(/Page images will not be read/);
    expect(line).toHaveTextContent("Claude rejected the API key.");
    expect(line).toHaveTextContent("HTTP 401");
    expect(s.getByRole("button", { name: "Read unread pages" })).toBeEnabled();
  });
});

describe("the launcher a non-admin cannot use (#925 item 1)", () => {
  it("is enabled for an administrator", async () => {
    control({ isAdmin: true });
    await strip();
    expect(screen.getByRole("button", { name: "Check it" })).not.toBeDisabled();
    expect(screen.queryByText(/Only an administrator can start a review/)).toBeNull();
  });

  it("is disabled, and says why, for a non-admin", async () => {
    control({ isAdmin: false });
    await strip();
    expect(screen.getByRole("button", { name: "Check it" })).toBeDisabled();
    expect(screen.getByText(/Only an administrator can start a review/)).toBeInTheDocument();
  });
});
