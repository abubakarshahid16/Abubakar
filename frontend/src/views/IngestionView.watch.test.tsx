/**
 * The watched-folder panel on the Ingestion screen.
 *
 * The panel exists to answer "is the drop folder working", and it is worth
 * having only if it refuses to invent the answer. These tests hold the five
 * properties that make it honest rather than decorative:
 *
 *  - the feature being OFF is a calm sentence, not an error and not a blank
 *  - three outcomes are told apart by their WORDS, so colour is not the only
 *    signal (the assertions are on text; a class name is not an affordance)
 *  - a folder the caller may not see renders as nothing at all - no dash, no
 *    "hidden", no placeholder that implies a value was withheld
 *  - an enabled folder with no arrivals says so, rather than showing an
 *    empty box or a fabricated row
 *  - a failed read says the status is unknown, and shows nothing else
 */
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IngestionView } from "./IngestionView";
import { api } from "../api/client";
import type { Health, Result, WatchStatus } from "../api/client";
import type { Connection } from "../components/Shell";
import type { Metrics } from "../types/api";

const health: Health = {
  ok: true,
  embed_model_present: true,
  answer_model_present: true,
  ingestion: { alive: true, stalled: false, busy: false },
};

const connection: Connection = { state: "online", health, at: Date.now() };

/** The worker and throughput halves of this screen are covered by
 *  IngestionView.test.tsx. Only enough is supplied here for the view to get
 *  past its own guards - the panel under test reads none of it. */
const metrics = {
  at: "2026-09-07T12:00:00Z",
  refresh_seconds: 15,
  throughput: {
    extract: {
      unit: "pages/s",
      samples: 2,
      median: 277.6,
      best: 280.1,
      items_total: 1400,
      seconds_total: 5,
    },
  },
  worker: {
    alive: true,
    current_document: null,
    seconds_since_heartbeat: 0.4,
    seconds_since_progress: 12,
    documents_completed: 3,
    pending_count: 0,
    oldest_pending_age_seconds: 12,
    stalled: false,
    stalled_reasons: [],
    last_error: null,
  },
} as unknown as Metrics;

const FOLDER_NAME = "watch-inbox";

/** Backend-authored, and guaranteed by backend tests to carry no host path. */
const SCAN_ERROR = "The folder could not be opened. Check that it still exists.";

function ago(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

function makeStatus(over: Partial<WatchStatus> = {}): WatchStatus {
  return {
    enabled: true,
    folder_name: FOLDER_NAME,
    last_scan_at: ago(2 * 60_000),
    interval_seconds: 300,
    reachable: true,
    last_error: null,
    recent: [],
    ...over,
  };
}

/** The API client method is the seam. The rest of the screen is served real
 *  fixtures so the panel is rendered where it actually lives. */
function mount(watch: Result<WatchStatus>) {
  vi.spyOn(api, "metrics").mockResolvedValue({ ok: true, data: metrics });
  vi.spyOn(api, "documents").mockResolvedValue({ ok: true, data: [] });
  vi.spyOn(api, "watchStatus").mockResolvedValue(watch);
  render(<IngestionView connection={connection} onRetryConnection={() => {}} />);
}

function ok(status: WatchStatus): Result<WatchStatus> {
  return { ok: true, data: status };
}

/** The panel, and nothing around it. The screen carries an em dash of its own
 *  in the worker tiles, so a "no placeholder" assertion has to be scoped. */
async function panel(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: "Watched folder" });
  const section = heading.closest("section");
  if (!section) throw new Error("the Watched folder heading is not inside a section");
  return section;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the watched folder when it is off", () => {
  it("says so in one calm line, and says nothing else", async () => {
    mount(
      ok({
        enabled: false,
        folder_name: null,
        last_scan_at: null,
        interval_seconds: null,
        // Both reachability fields are cleared when the feature is off.
        reachable: null,
        last_error: null,
        recent: [],
      }),
    );

    const section = await panel();
    expect(
      within(section).getByText("The watched folder is not configured."),
    ).toBeInTheDocument();

    // Off is not a fault: no error role anywhere on the screen.
    expect(screen.queryByRole("alert")).toBeNull();
    // And no folder, no interval, no list container waiting to be filled.
    expect(within(section).queryByText(/checks every/i)).toBeNull();
    expect(within(section).queryByText(/last checked/i)).toBeNull();
    expect(within(section).queryAllByRole("list")).toHaveLength(0);
    expect(within(section).queryByText(/Nothing has arrived/i)).toBeNull();
    // The reachability fields are null here and must add nothing to the line.
    expect(within(section).queryByText(/not being read/i)).toBeNull();
    expect(within(section).queryByText(/unknown/i)).toBeNull();
    expect(within(section).queryByText(/reachable/i)).toBeNull();
  });
});

describe("the watched folder when it cannot be reached", () => {
  it("says so in the present tense, and explains why", async () => {
    mount(
      ok(
        makeStatus({
          reachable: false,
          last_error: SCAN_ERROR,
          // The last successful scan is still the last scan. Rows from before
          // the folder went away must not be mistaken for the live state.
          recent: [
            { filename: "pump-datasheet.pdf", outcome: "ingested", at: ago(3600_000), detail: null },
          ],
        }),
      ),
    );

    const section = await panel();

    // Text, not colour: the danger token is invisible to a reader who cannot
    // see it, and to anyone reading this screen in a monochrome print.
    const banner = within(section).getByRole("alert");
    expect(banner).toHaveTextContent("The folder is not being read right now.");
    expect(banner).toHaveTextContent(SCAN_ERROR);

    // Present tense, and OUTSIDE the list - not one more past event.
    expect(banner.closest("li")).toBeNull();
    expect(within(section).getAllByRole("listitem")).toHaveLength(1);
    expect(within(banner).queryByText("pump-datasheet.pdf")).toBeNull();
  });

  it("keeps saying it while the rest of the panel still reports", async () => {
    mount(ok(makeStatus({ reachable: false, last_error: SCAN_ERROR })));

    const section = await panel();
    // The failure does not blank the facts that are still true.
    expect(within(section).getByText("checks every 5 minutes")).toBeInTheDocument();
    expect(within(section).getByText(FOLDER_NAME)).toBeInTheDocument();
    expect(within(section).getByRole("alert")).toHaveTextContent(SCAN_ERROR);
  });
});

describe("the watched folder when it is healthy or has not scanned yet", () => {
  it("says nothing at all when the last scan found the folder", async () => {
    // A panel that reports OK on every poll is a panel people stop reading.
    mount(ok(makeStatus({ reachable: true, last_error: null })));

    const section = await panel();
    // The panel is genuinely here, so the absences below are its choice.
    expect(within(section).getByText(FOLDER_NAME)).toBeInTheDocument();

    expect(within(section).queryByRole("alert")).toBeNull();
    expect(within(section).queryByText(/not being read/i)).toBeNull();
    expect(within(section).queryByText(SCAN_ERROR)).toBeNull();
    expect(within(section).queryByText(/^ok$/i)).toBeNull();
    expect(within(section).queryByText(/healthy/i)).toBeNull();
    expect(within(section).queryByText(/reachable/i)).toBeNull();
    expect(within(section).queryByText(/connected/i)).toBeNull();
  });

  it("never shows the explanation without the failure that frames it", async () => {
    // A stale last_error alongside reachable true would read as a live fault.
    mount(ok(makeStatus({ reachable: true, last_error: SCAN_ERROR })));

    const section = await panel();
    expect(within(section).getByText(FOLDER_NAME)).toBeInTheDocument();
    expect(within(section).queryByText(SCAN_ERROR)).toBeNull();
    expect(within(section).queryByRole("alert")).toBeNull();
  });

  it("says nothing about reachability before the first scan has finished", async () => {
    mount(ok(makeStatus({ reachable: null, last_error: null, last_scan_at: null })));

    const section = await panel();
    // Present, and still telling the reader a scan is coming.
    expect(within(section).getByText("checks every 5 minutes")).toBeInTheDocument();

    expect(within(section).queryByRole("alert")).toBeNull();
    expect(within(section).queryByText(/not being read/i)).toBeNull();
    expect(within(section).queryByText(/unknown/i)).toBeNull();
    expect(within(section).queryByText(/reachable/i)).toBeNull();
    expect(within(section).queryByText("—")).toBeNull();
    expect(within(section).queryByText("-")).toBeNull();
    expect(within(section).queryByText(/N\/A/i)).toBeNull();
    // No scan has run, so there is no "last checked" claim either.
    expect(within(section).queryByText(/last checked/i)).toBeNull();
  });
});

describe("the watched folder when it is on", () => {
  it("renders each recent arrival with an outcome told apart by its word", async () => {
    mount(
      ok(
        makeStatus({
          recent: [
            { filename: "pump-datasheet.pdf", outcome: "ingested", at: ago(30_000), detail: null },
            { filename: "spec-rev-b.pdf", outcome: "duplicate", at: ago(20 * 60_000), detail: null },
            {
              filename: "scan-broken.pdf",
              outcome: "failed",
              at: ago(3 * 3600_000),
              detail: "the file is not a PDF",
            },
          ],
        }),
      ),
    );

    const section = await panel();
    const rows = within(section).getAllByRole("listitem");
    expect(rows).toHaveLength(3);

    // Text, not classes. Colour alone would leave these three identical to a
    // reader who cannot see it.
    expect(within(rows[0]).getByText("pump-datasheet.pdf")).toBeInTheDocument();
    expect(within(rows[0]).getByText("ingested")).toBeInTheDocument();
    expect(within(rows[1]).getByText("spec-rev-b.pdf")).toBeInTheDocument();
    expect(within(rows[1]).getByText("duplicate")).toBeInTheDocument();
    expect(within(rows[2]).getByText("scan-broken.pdf")).toBeInTheDocument();
    expect(within(rows[2]).getByText("failed")).toBeInTheDocument();
    // A failure carries its reason; the other two have none to carry.
    expect(within(rows[2]).getByText("the file is not a PDF")).toBeInTheDocument();

    // The supporting facts, in words rather than raw seconds.
    expect(within(section).getByText(FOLDER_NAME)).toBeInTheDocument();
    expect(within(section).getByText("checks every 5 minutes")).toBeInTheDocument();
    expect(within(section).getByText(/last checked 2 minutes ago/)).toBeInTheDocument();
  });

  it("keeps the absolute timestamp on the relative phrase", async () => {
    const scannedAt = ago(2 * 60_000);
    mount(ok(makeStatus({ last_scan_at: scannedAt })));

    const section = await panel();
    expect(within(section).getByText(/last checked 2 minutes ago/)).toHaveAttribute(
      "title",
      scannedAt,
    );
  });

  it("renders nothing at all in place of a folder the caller may not see", async () => {
    mount(ok(makeStatus({ folder_name: null, recent: [] })));

    const section = await panel();
    // The panel is genuinely on screen - so the absences below are the panel's
    // choice, not the panel being missing.
    expect(within(section).getByText("checks every 5 minutes")).toBeInTheDocument();

    expect(within(section).queryByText(FOLDER_NAME)).toBeNull();
    // Not even the label that would introduce a name.
    expect(within(section).queryByText(/watching a folder/i)).toBeNull();
    // No dash, no "N/A", no "hidden" standing in for the path.
    expect(within(section).queryByText("—")).toBeNull();
    expect(within(section).queryByText("-")).toBeNull();
    expect(within(section).queryByText(/N\/A/i)).toBeNull();
    expect(within(section).queryByText(/hidden/i)).toBeNull();
    expect(within(section).queryByText(/not available/i)).toBeNull();
  });

  it("names the folder without showing anything that looks like a path", async () => {
    // The route no longer HAS the host path - it was removed, not gated. A
    // reader who takes "watch-inbox" for a truncated path has been misled by
    // this panel, not by the API.
    mount(ok(makeStatus({ folder_name: FOLDER_NAME, recent: [] })));

    const section = await panel();
    expect(within(section).getByText(FOLDER_NAME)).toBeInTheDocument();

    const shown = section.textContent ?? "";
    expect(shown).toContain(FOLDER_NAME);
    // No separator of any flavour, and no drive letter, anywhere on the panel.
    expect(shown).not.toContain("\\");
    expect(shown).not.toContain("/");
    expect(shown).not.toContain(":");
    expect(shown).not.toMatch(/\.\./);
    // Nor smuggled into an attribute a hover would reveal.
    for (const el of Array.from(section.querySelectorAll("[title],[aria-label]"))) {
      const meta = `${el.getAttribute("title") ?? ""} ${el.getAttribute("aria-label") ?? ""}`;
      expect(meta).not.toContain("\\");
      expect(meta).not.toMatch(/[A-Za-z]:/);
    }
  });

  it("says nothing has arrived rather than showing an empty box", async () => {
    mount(ok(makeStatus({ recent: [] })));

    const section = await panel();
    expect(
      within(section).getByText("Nothing has arrived in the folder yet."),
    ).toBeInTheDocument();
    expect(within(section).queryAllByRole("list")).toHaveLength(0);
    expect(within(section).queryAllByRole("listitem")).toHaveLength(0);
  });
});

describe("the watched folder when it cannot be read", () => {
  it("says the status is unknown rather than showing stale or invented values", async () => {
    mount({
      ok: false,
      disconnected: false,
      error: { code: "internal", message: "The backend could not complete this request." },
    });

    const section = await panel();
    expect(
      within(section).getByText("The watched folder could not be read, so its status is unknown."),
    ).toBeInTheDocument();

    // Nothing is asserted about the folder in either direction.
    expect(within(section).queryByText(FOLDER_NAME)).toBeNull();
    expect(within(section).queryByText(/checks every/i)).toBeNull();
    expect(within(section).queryByText(/last checked/i)).toBeNull();
    expect(within(section).queryByText(/not configured/i)).toBeNull();
    expect(within(section).queryByText(/Nothing has arrived/i)).toBeNull();
    expect(within(section).queryAllByRole("listitem")).toHaveLength(0);
  });
});

/**
 * The scan summary line.
 *
 * Why it exists: a reader dropped a PDF into the folder, opened this screen,
 * saw three rows all reading `duplicate` and concluded the feature was broken.
 * It was working - the scan that would pick up the new file had not run. The
 * panel showed a history of decisions and never said "I looked, and there was
 * nothing new", so a steady-state panel and a dead one read identically.
 *
 * What these tests hold is that the line is HONEST as well as present. The
 * count is inferred from events sharing a timestamp, not reported by the API,
 * so it is worded as a lower bound; the ten-event window is called out as the
 * window rather than shown as a total; a scan newer than every event says so
 * instead of re-describing an older scan as the latest; and off, empty and
 * failed states produce no number at all.
 *
 * Assertions are on text and scoped with within(section) for the reason the
 * top of this file gives - the surrounding screen has copy and punctuation of
 * its own, so an unscoped absence assertion proves nothing about the panel.
 */
describe("the scan summary line", () => {
  it("counts the newest same-second group, and marks the count as a lower bound", async () => {
    // One scan's events share their timestamp to the second. This is the case
    // from the live data: three decisions, one of them a new file.
    const scannedAt = ago(90_000);
    mount(
      ok(
        makeStatus({
          last_scan_at: scannedAt,
          recent: [
            { filename: "pump-datasheet.pdf", outcome: "ingested", at: scannedAt, detail: null },
            { filename: "spec-rev-b.pdf", outcome: "duplicate", at: scannedAt, detail: null },
            { filename: "spec-rev-a.pdf", outcome: "duplicate", at: scannedAt, detail: null },
          ],
        }),
      ),
    );

    const section = await panel();
    // Three seen, one new - and "at least", because the grouping is an
    // inference from shared timestamps rather than a figure the API states.
    expect(
      within(section).getByText("the last check saw at least 3 files, including 1 new file."),
    ).toBeInTheDocument();
    // Not dressed up as a reported total.
    expect(within(section).queryByText(/saw 3 files/)).toBeNull();
    // The rows are still the rows: the line is a summary, not a fourth entry.
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    expect(within(section).queryByText(/Only the newest/)).toBeNull();

    // The panel's no-separator guarantee covers this line too: a count that
    // introduced a colon or a slash would break the one assertion that keeps
    // a host path off this screen.
    const shown = section.textContent ?? "";
    expect(shown).not.toContain("\\");
    expect(shown).not.toContain("/");
    expect(shown).not.toContain(":");
  });

  it("does not count events older than the scan that has since run", async () => {
    // The ordinary steady state, and the case the reader needed: the same three
    // decisions, but the folder has been checked since and found nothing.
    const eventsAt = ago(90_000);
    mount(
      ok(
        makeStatus({
          last_scan_at: ago(20_000),
          recent: [
            { filename: "pump-datasheet.pdf", outcome: "ingested", at: eventsAt, detail: null },
            { filename: "spec-rev-b.pdf", outcome: "duplicate", at: eventsAt, detail: null },
            { filename: "spec-rev-a.pdf", outcome: "duplicate", at: eventsAt, detail: null },
          ],
        }),
      ),
    );

    const section = await panel();
    expect(
      within(section).getByText("the last check found nothing new in the folder."),
    ).toBeInTheDocument();
    // The older group must not be re-labelled as what the latest check did.
    expect(within(section).queryByText(/at least/)).toBeNull();
    expect(within(section).queryByText(/3 files/)).toBeNull();
    expect(within(section).queryByText(/1 new file/)).toBeNull();
    // The history itself is untouched - the rows and their words remain.
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    expect(within(section).getByText("pump-datasheet.pdf")).toBeInTheDocument();
  });

  it("says a check happened and found nothing when there are no events at all", async () => {
    mount(ok(makeStatus({ last_scan_at: ago(60_000), recent: [] })));

    const section = await panel();
    expect(
      within(section).getByText("the last check found nothing new in the folder."),
    ).toBeInTheDocument();
    // No count is invented out of an empty list - not a zero, not a dash.
    expect(within(section).queryByText(/at least/)).toBeNull();
    expect((section.textContent ?? "")).not.toMatch(/\d+ files?/);
    expect(within(section).queryByText("0")).toBeNull();
  });

  it("claims no check at all before the first scan has been recorded", async () => {
    // No scan has finished, so there is no check to describe - and an empty
    // `recent` is not evidence that one looked.
    mount(ok(makeStatus({ last_scan_at: null, recent: [] })));

    const section = await panel();
    expect(within(section).getByText("checks every 5 minutes")).toBeInTheDocument();

    expect(within(section).queryByText(/last check/i)).toBeNull();
    expect(within(section).queryByText(/nothing new/i)).toBeNull();
    expect(within(section).queryByText(/at least/)).toBeNull();
  });

  it("presents the count as bounded by the window when the group fills it", async () => {
    // Ten kept events, all from one scan. The scan may have seen more; how many
    // more is not in this payload, so the window is named as the limit.
    const scannedAt = ago(45_000);
    const recent = Array.from({ length: 10 }, (_unused, i) => ({
      filename: `drop-${i}.pdf`,
      outcome: (i < 2 ? "ingested" : "duplicate") as WatchStatus["recent"][number]["outcome"],
      at: scannedAt,
      detail: null,
    }));
    mount(ok(makeStatus({ last_scan_at: scannedAt, recent })));

    const section = await panel();
    const line = within(section).getByText(/at least 10 files/);
    expect(line).toHaveTextContent("including 2 new files");
    // The number is the window's size, and the line says so rather than
    // letting "10" be read as the total the scan saw.
    expect(line).toHaveTextContent(
      "Only the newest 10 decisions are kept here, so it may have seen more.",
    );
    expect(within(section).queryByText(/saw 10 files/)).toBeNull();
  });

  it("says nothing about scans when the feature is off", async () => {
    mount(
      ok({
        enabled: false,
        folder_name: null,
        last_scan_at: null,
        interval_seconds: null,
        reachable: null,
        last_error: null,
        recent: [],
      }),
    );

    const section = await panel();
    expect(
      within(section).getByText("The watched folder is not configured."),
    ).toBeInTheDocument();
    expect(within(section).queryByText(/last check/i)).toBeNull();
    expect(within(section).queryByText(/at least/)).toBeNull();
    expect(within(section).queryByText(/nothing new/i)).toBeNull();
  });

  it("says nothing about scans when the request failed", async () => {
    // A count survives a failed read only by being stale, and a stale count
    // presented as current is the untruth this panel refuses everywhere else.
    mount({
      ok: false,
      disconnected: false,
      error: { code: "internal", message: "The backend could not complete this request." },
    });

    const section = await panel();
    expect(
      within(section).getByText("The watched folder could not be read, so its status is unknown."),
    ).toBeInTheDocument();
    expect(within(section).queryByText(/last check/i)).toBeNull();
    expect(within(section).queryByText(/at least/)).toBeNull();
    expect(within(section).queryByText(/nothing new/i)).toBeNull();
    expect(within(section).queryByText(/files/i)).toBeNull();
  });
});
