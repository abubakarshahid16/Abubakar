/**
 * MarketPanel: what leaves the machine, and what every row admits about itself.
 *
 * WHY EVERY ASSERTION IS SCOPED WITH within(). The panel is one card among
 * several on the analysis screen, and the screen around it carries text of the
 * same shapes: em dashes in the worker tiles, its own role="status" line above
 * this panel, and a "sample data - not live" badge in the AnalysisView
 * summary. A negative assertion ("no dash", "no rows") is only a statement
 * about THIS panel if it is scoped to this panel, and a row-level claim ("this
 * row says it is background only") is only a claim about that row if it is
 * scoped to the row - unscoped, a caption printed on every row passes a test
 * that meant to pin it to one. The same reason IngestionView.watch.test.tsx
 * scopes its no-placeholder assertions to the watched-folder section.
 *
 * The no-separator guarantee in IngestionView.watch.test.tsx does NOT apply
 * here and is not asserted: that test keeps a HOST FILESYSTEM PATH off the
 * watched-folder panel, and it forbids "/" and ":" to do it. This panel's job
 * is to print a public url, publisher and ISO timestamp for every row - all
 * three of which contain both characters by construction - and it never
 * receives a host path. Nothing on this screen reads a filesystem.
 *
 * `market.preview` and `market.search` are mocked; the panel is rendered
 * directly, so nothing here depends on a database, a fixture file or the
 * developer's machine.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MarketPanel } from "./MarketPanel";
import { market } from "../../api/client";
import type { MarketPreview, MarketRow, MarketSearchResult, Result } from "../../api/client";
import type { EgressState, MarketFinding, PublicMarketQuery } from "../../types/analysis";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  // Declared inside the factory: vi.mock is hoisted above any top-level const.
  return {
    ...actual,
    market: { ...actual.market, preview: vi.fn(), search: vi.fn() },
  };
});

const previewMock = vi.mocked(market.preview);
const searchMock = vi.mocked(market.search);

// ------------------------------------------------------------------ fixtures

const FINDINGS: MarketFinding[] = [
  {
    claim: "Zinc-rich epoxy primers list at roughly USD 18-24 per litre in Q2 2026.",
    url: "https://example.com/coatings/price-index-2026-q2",
    publisher: "Example Coatings Index",
    published_at: "2026-06-30",
    retrieved_at: "2026-09-01T10:15:00Z",
    // source_not_verified, not snippet_only: MarketFinding.verification is
    // pinned to the one value this build can produce, because nothing here
    // has been read. The URL and publisher stay deliberately plausible - the
    // property under test is that the panel labels a row as SAMPLE even when
    // it looks real, which is the case that actually misleads someone.
    verification: "source_not_verified",
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
const OPEN: EgressState = { web_search_enabled: true, allow_public_egress: true };

const QUERY: PublicMarketQuery = { query: "sea water pump alloy price", country: "NO", freshness_days: 90 };

/** The typed text and the phrase that survives scrubbing are DIFFERENT
 *  strings, and deliberately so: the project name is exactly the kind of thing
 *  the backend strips, and two identical strings would let a panel that sends
 *  the raw text pass every assertion below. */
const TYPED = "zinc epoxy primer price for the Statfjord tie-in";
const SCRUBBED = "zinc epoxy primer price";

/** The backend's payload, deliberately NOT `JSON.stringify(the form)`: a
 *  client-side reconstruction passing this test would prove nothing about what
 *  actually leaves the machine. The extra key is what makes them differ. */
const PAYLOAD = { q: SCRUBBED, tier: "web", redactions_applied: 2 };

/** The tier lists carry TIER IDS, which are not the provider labels a row
 *  wears: market_providers.py attempts "web", "literature", "reference" and
 *  labels their rows "market search", "published literature" and
 *  "reference - background only". Two vocabularies, and the API does not say
 *  which one a tier list holds - so the panel prints them exactly as sent
 *  rather than translating, and these fixtures use the ids the backend really
 *  sends. */
const TIERS = ["web", "literature", "reference"];

/** The payload block is a <pre> and keeps its newlines. getByText collapses
 *  whitespace by default, which would never match a multi-line string - so the
 *  comparison is made against the text exactly as it is rendered. */
const PAYLOAD_TEXT = JSON.stringify(PAYLOAD, null, 2);
const VERBATIM = { collapseWhitespace: false } as const;

function preview(over: Partial<MarketPreview> = {}): MarketPreview {
  return { phrase: SCRUBBED, payload: PAYLOAD, tiers_configured: TIERS, ...over };
}

const MARKET_ROW: MarketRow = {
  text: "Zinc-rich primer tenders closed at NOK 210 per litre in June 2026.",
  provider_label: "market search",
  publisher: "Nordic Coatings Monitor",
  published: "2026-06-18",
  retrieved: "2026-09-07T08:02:00Z",
  url: "https://example.com/monitor/june-2026",
  verification: "source_read",
  is_sample: false,
};

/** Undated on purpose: `published` null is the case where a UI invents a date. */
const REFERENCE_ROW: MarketRow = {
  text: "Zinc-rich primers are anticorrosive coatings containing metallic zinc dust.",
  provider_label: "reference - background only",
  publisher: "Example Reference Works",
  published: null,
  retrieved: "2026-09-07T08:02:05Z",
  url: "https://example.org/wiki/zinc-rich-primer",
  verification: "snippet_only",
  is_sample: false,
};

const SAMPLE_ROW: MarketRow = {
  text: "Illustrative: primer prices rose over the quarter.",
  // Its OWN provenance label, matching what the backend now sends. It used to
  // borrow "reference - background only", which made the panel print "this row
  // is not a market finding" over a row that is an illustrative MARKET row -
  // both sentences true of a sample, and the provenance still wrong.
  provider_label: "sample - illustrative only",
  publisher: "Example Sample Source",
  published: null,
  retrieved: "2026-09-07T08:00:00Z",
  url: "sample://market/1",
  verification: "source_not_verified",
  is_sample: true,
};

function result(over: Partial<MarketSearchResult> = {}): MarketSearchResult {
  return {
    enabled: true,
    rows: [MARKET_ROW, REFERENCE_ROW],
    tiers_attempted: TIERS,
    tiers_answered: TIERS,
    failure: null,
    ...over,
  };
}

const ok = <T,>(data: T) => ({ ok: true as const, data });
const down = (): Result<never> => ({
  ok: false,
  disconnected: true,
  error: { code: "internal", message: "Cannot reach the backend. failed to fetch" },
});

// ---------------------------------------------------------------- harness

/** The panel, and nothing around it. */
function panel(): HTMLElement {
  return screen.getByRole("region", { name: "Public market information" });
}

function mount(egress: EgressState = OPEN, findings: MarketFinding[] = []) {
  return render(<MarketPanel findings={findings} egress={egress} />);
}

async function type(user: ReturnType<typeof userEvent.setup>) {
  await user.type(within(panel()).getByLabelText("Query"), TYPED);
}

async function openPreview(user: ReturnType<typeof userEvent.setup>) {
  await type(user);
  await user.click(within(panel()).getByRole("button", { name: "Preview exact outbound query" }));
  return await screen.findByRole("dialog");
}

/** Open the preview, wait for the payload to actually be on screen, then make
 *  the one click that can send. */
async function sendSearch(user: ReturnType<typeof userEvent.setup>) {
  const dialog = await openPreview(user);
  await within(dialog).findByText(PAYLOAD_TEXT, VERBATIM);
  await user.click(within(dialog).getByRole("button", { name: "Confirm and send" }));
  await waitFor(() => expect(searchMock).toHaveBeenCalledTimes(1));
}

/** The row whose text begins with this. Rows are <li>, one per finding. */
function row(text: string): HTMLElement {
  const li = within(panel())
    .getAllByRole("listitem")
    .find((el) => (el.textContent ?? "").includes(text));
  if (!li) throw new Error(`no row containing ${text}`);
  return li;
}

beforeEach(() => {
  previewMock.mockReset();
  searchMock.mockReset();
  previewMock.mockResolvedValue(ok(preview()));
  searchMock.mockResolvedValue(ok(result()));
});

// ------------------------------------------------------- nothing is dispatched

describe("MarketPanel: nothing leaves the machine without a click", () => {
  it("dispatches no search after typing, after Enter and after blur", async () => {
    const user = userEvent.setup();
    mount();

    await type(user);
    expect(searchMock).not.toHaveBeenCalled();
    // Typing alone does not even read the preview route.
    expect(previewMock).not.toHaveBeenCalled();

    // Enter in the field OPENS THE PREVIEW. It is the keyboard path to the
    // dialog, and it is not a send.
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(searchMock).not.toHaveBeenCalled();

    // Out of the field, into the next control, and out of the dialog.
    await user.keyboard("{Escape}");
    await user.tab();
    await user.tab();
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("sends only when Confirm is clicked, and sends the scrubbed phrase", async () => {
    const user = userEvent.setup();
    mount();
    await sendSearch(user);
    expect(searchMock).toHaveBeenCalledWith({
      phrase: SCRUBBED,
      country: null,
      freshness_days: null,
    });
  });

  it("Cancel closes the dialog, sends nothing, and says so", async () => {
    const user = userEvent.setup();
    mount();
    const dialog = await openPreview(user);
    expect(within(dialog).getByText("Cancel closes this and sends nothing.")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(searchMock).not.toHaveBeenCalled();
  });
});

// ------------------------------------------------------------- the payload

describe("MarketPanel: the exact payload is shown before anything is sent", () => {
  it("renders the typed phrase, the scrubbed phrase and the backend's payload verbatim", async () => {
    const user = userEvent.setup();
    mount();
    const dialog = await openPreview(user);

    expect(await within(dialog).findByText(PAYLOAD_TEXT, VERBATIM)).toBeInTheDocument();
    expect(within(dialog).getByText("What you typed")).toBeInTheDocument();
    expect(within(dialog).getByText(TYPED)).toBeInTheDocument();
    expect(within(dialog).getByText("The phrase that would be sent")).toBeInTheDocument();
    // Shown, and still not sent.
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("sends nothing when the payload was never shown, and says nothing was sent", async () => {
    // The preview route is the only way to learn the payload. If it cannot be
    // read, the panel has nothing to show, so it must not send.
    previewMock.mockResolvedValue(down());
    const user = userEvent.setup();
    mount();
    const dialog = await openPreview(user);
    await within(dialog).findByText(
      "The backend could not be reached, so the exact outbound payload cannot be shown here.",
    );

    await user.click(within(dialog).getByRole("button", { name: "Confirm and send" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(searchMock).not.toHaveBeenCalled();
    expect(
      within(panel()).getByText(
        "Nothing was sent. The exact outbound payload was never shown, and this panel does not send what it cannot show.",
      ),
    ).toBeInTheDocument();
  });
});

// --------------------------------------------------------------- null phrase

describe("MarketPanel: nothing safe survived", () => {
  it("disables the send control, states the reason, and never offers the raw text", async () => {
    previewMock.mockResolvedValue(ok(preview({ phrase: null })));
    const user = userEvent.setup();
    mount();
    const dialog = await openPreview(user);

    expect(
      await within(dialog).findByText(
        "No safe search phrase could be formed from what you typed, so no search is possible. " +
          "The text you typed will not be sent in its place, and nothing has been sent.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Confirm and send" })).toBeDisabled();

    // No second control offering the raw string instead.
    for (const b of within(dialog).getAllByRole("button")) {
      expect(b.textContent ?? "").not.toMatch(/anyway|as typed|unscrubbed|raw/i);
    }
    // No payload block at all: there is no payload.
    expect(within(dialog).queryByText(PAYLOAD_TEXT, VERBATIM)).toBeNull();
    expect(within(dialog).queryByText("The phrase that would be sent")).toBeNull();

    await user.click(within(dialog).getByRole("button", { name: "Confirm and send" }));
    expect(searchMock).not.toHaveBeenCalled();
  });
});

// -------------------------------------------------------------- provenance

describe("MarketPanel: every row wears its provenance", () => {
  it("distinguishes a reference row from a market row in TEXT, not in colour", async () => {
    const user = userEvent.setup();
    mount();
    await sendSearch(user);

    const reference = row(REFERENCE_ROW.text);
    const marketRow = row(MARKET_ROW.text);

    expect(within(reference).getByText("reference - background only")).toBeInTheDocument();
    expect(
      within(reference).getByText(
        "Background only. This row is not a market finding and cannot evidence a market condition.",
      ),
    ).toBeInTheDocument();

    expect(within(marketRow).getByText("market search")).toBeInTheDocument();
    // The caption is the reference row's, and only the reference row's.
    expect(within(marketRow).queryByText(/Background only/)).toBeNull();
    expect(within(marketRow).queryByText("reference - background only")).toBeNull();
  });

  it("prints publisher, retrieved, url and verification on every row, and no links", async () => {
    const user = userEvent.setup();
    mount();
    await sendSearch(user);

    const marketRow = row(MARKET_ROW.text);
    expect(within(marketRow).getByText(MARKET_ROW.publisher)).toBeInTheDocument();
    expect(within(marketRow).getByText(MARKET_ROW.retrieved)).toBeInTheDocument();
    expect(within(marketRow).getByText(MARKET_ROW.url)).toBeInTheDocument();
    expect(within(marketRow).getByText("source read")).toBeInTheDocument();

    expect(panel().querySelectorAll("a")).toHaveLength(0);
  });

  it("renders a null published date as NOTHING - no dash, no N/A, no today", async () => {
    const user = userEvent.setup();
    mount();
    await sendSearch(user);

    const undated = row(REFERENCE_ROW.text);
    expect(REFERENCE_ROW.published).toBeNull();
    // Not the label either: a label over an empty cell asserts a date was
    // reported and then withheld.
    expect(within(undated).queryByText("published")).toBeNull();
    expect(within(undated).queryByText("—")).toBeNull();
    expect(within(undated).queryByText("-")).toBeNull();
    expect(within(undated).queryByText(/N\/A/i)).toBeNull();
    expect(within(undated).queryByText(/unknown/i)).toBeNull();
    // And no date the panel made up - today's or any other. The ONLY calendar
    // date on an undated row is the one inside `retrieved`, which the payload
    // did send. Asserted this way rather than against `new Date()` so the test
    // cannot pass or fail depending on the day it is run.
    const dates = (undated.textContent ?? "").match(/\d{4}-\d{2}-\d{2}/g) ?? [];
    expect(dates).toEqual([REFERENCE_ROW.retrieved.slice(0, 10)]);

    // The row that HAS a date still shows the label and the date, so the
    // absence above is the null being honoured and not the label being gone.
    const dated = row(MARKET_ROW.text);
    expect(within(dated).getByText("published")).toBeInTheDocument();
    expect(within(dated).getByText("2026-06-18")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------ tier fallback

describe("MarketPanel: the fallback is visible", () => {
  it("states in words that the general web search did not answer", async () => {
    searchMock.mockResolvedValue(
      ok(result({
        rows: [REFERENCE_ROW],
        tiers_attempted: ["web", "reference"],
        tiers_answered: ["reference"],
      })),
    );
    const user = userEvent.setup();
    mount();
    await sendSearch(user);

    const p = panel();
    expect(
      await within(p).findByText("Tiers attempted: web, reference"),
    ).toBeInTheDocument();
    expect(within(p).getByText("Tiers that answered: reference")).toBeInTheDocument();
    expect(within(p).getByText("Tried and did not answer: web")).toBeInTheDocument();
    expect(
      within(p).getByText(
        "The general web search did not answer. The rows below come from reference sources: " +
          "they are background only and are not market findings.",
      ),
    ).toBeInTheDocument();
  });

  it("does not claim a fallback when every attempted tier answered", async () => {
    const user = userEvent.setup();
    mount();
    await sendSearch(user);
    expect(within(panel()).queryByText(/did not answer/)).toBeNull();
  });
});

// ------------------------------------------------------ failure and empty

describe("MarketPanel: failure and empty states", () => {
  it("shows the failure and NO rows - not even the samples the payload carried", async () => {
    // The contract says rows is empty on a failure. This fixture breaks the
    // contract ON PURPOSE and puts the samples back: the property under test
    // is that the panel CANNOT render them next to a failure, not that the
    // backend happened to omit them.
    searchMock.mockResolvedValue(
      ok(result({
        rows: [SAMPLE_ROW, MARKET_ROW],
        tiers_answered: [],
        failure: "No public source answered: every provider timed out.",
      })),
    );
    const user = userEvent.setup();
    mount(OPEN, FINDINGS);
    await sendSearch(user);

    const p = panel();
    expect(
      await within(p).findByText("No public source answered: every provider timed out."),
    ).toBeInTheDocument();
    expect(
      within(p).getByText("No rows are shown, and no sample rows have been put in their place."),
    ).toBeInTheDocument();

    expect(within(p).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(p).queryByText(SAMPLE_ROW.text)).toBeNull();
    expect(within(p).queryByText(MARKET_ROW.text)).toBeNull();
    // Nor the legacy fixtures this panel was mounted with.
    expect(within(p).queryByText(FINDINGS[0].claim)).toBeNull();
    expect(within(p).queryByText(/SAMPLE DATA/)).toBeNull();
  });

  it("says no results when the search ran and found nothing", async () => {
    searchMock.mockResolvedValue(ok(result({ rows: [] })));
    const user = userEvent.setup();
    mount(OPEN, FINDINGS);
    await sendSearch(user);

    const p = panel();
    expect(
      await within(p).findByText(
        "The search ran and found nothing. That is the answer: there are no public findings for this phrase.",
      ),
    ).toBeInTheDocument();
    expect(within(p).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(p).queryByText(/SAMPLE DATA/)).toBeNull();
  });

  it("says the backend could not be reached, and leaves nothing stale on screen", async () => {
    const user = userEvent.setup();
    mount();
    // A real result first, so there IS something stale to leave behind.
    await sendSearch(user);
    expect(within(panel()).getByText(MARKET_ROW.text)).toBeInTheDocument();

    searchMock.mockResolvedValue(down());
    const dialog = await openPreview(user);
    await within(dialog).findByText(PAYLOAD_TEXT, VERBATIM);
    await user.click(within(dialog).getByRole("button", { name: "Confirm and send" }));

    const p = panel();
    expect(
      await within(p).findByText(
        "The backend could not be reached, so no search was made. Nothing is shown here.",
      ),
    ).toBeInTheDocument();
    expect(within(p).queryByText(MARKET_ROW.text)).toBeNull();
    expect(within(p).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("renders the samples WITH the not-live caption when the feature is off", async () => {
    searchMock.mockResolvedValue(
      ok(result({ enabled: false, rows: [SAMPLE_ROW], tiers_attempted: [], tiers_answered: [] })),
    );
    const user = userEvent.setup();
    mount(OPEN);
    await sendSearch(user);

    const p = panel();
    expect(await within(p).findByText(SAMPLE_ROW.text)).toBeInTheDocument();
    expect(within(p).getByRole("note")).toHaveTextContent(
      "SAMPLE DATA — NOT LIVE. This machine is offline. Every row below is an illustrative " +
        "sample and must not be described as live market data.",
    );
    const sample = row(SAMPLE_ROW.text);
    expect(within(sample).getByText(/^sample$/i)).toBeInTheDocument();
    // The url that resolves nowhere, kept as sent.
    expect(within(sample).getByText("sample://market/1")).toBeInTheDocument();
  });

  it("gives a sample row its own provenance, not the reference row's", async () => {
    // The defect this pins: while samples were labelled
    // "reference - background only", this row read "Background only. This row
    // is not a market finding and cannot evidence a market condition." A
    // sample IS not a market finding, so the sentence was true - and the
    // provenance was still wrong, because the row is an illustrative MARKET
    // row and a reader would carry that label away as its source. A wrong
    // provenance label on a compliance screen is the whole reason this panel
    // prints one on every row.
    searchMock.mockResolvedValue(
      ok(result({ enabled: false, rows: [SAMPLE_ROW], tiers_attempted: [], tiers_answered: [] })),
    );
    const user = userEvent.setup();
    mount(OPEN);
    await sendSearch(user);

    const sample = row(SAMPLE_ROW.text);
    expect(within(sample).getByText("sample - illustrative only")).toBeInTheDocument();
    expect(within(sample).queryByText("reference - background only")).toBeNull();
    expect(within(sample).queryByText(/not a market finding/i)).toBeNull();
    // `is_sample` stays the machine-readable carrier; the label is for a reader.
    expect(within(sample).getByText(/^sample$/i)).toBeInTheDocument();
  });
});

// ------------------------------------------------- the legacy sample fixture

describe("MarketPanel: the offline sample presentation", () => {
  it("shows the SAMPLE DATA banner and tags every fixture row", () => {
    expect(FINDINGS.length).toBeGreaterThan(1);
    expect(FINDINGS.every((f) => f.is_sample)).toBe(true);
    render(<MarketPanel findings={FINDINGS} egress={OFFLINE} />);

    const p = panel();
    expect(within(p).getByRole("note")).toHaveTextContent(/SAMPLE DATA — NOT LIVE/);
    const items = within(p).getAllByRole("listitem");
    expect(items).toHaveLength(FINDINGS.length);
    for (const li of items) expect(within(li).getByText(/^sample$/i)).toBeInTheDocument();
  });

  it("keeps the caption that public findings cannot prove compliance", () => {
    render(<MarketPanel findings={FINDINGS} egress={OFFLINE} />);
    expect(
      within(panel()).getByText(
        "Public web findings cannot prove internal project compliance. Snippets are preliminary " +
          "evidence; the verification column says whether the page was read.",
      ),
    ).toBeInTheDocument();
  });

  it("disables Confirm and states the reason when public egress is blocked", async () => {
    expect(OFFLINE.allow_public_egress).toBe(false);
    const user = userEvent.setup();
    render(<MarketPanel findings={[]} egress={OFFLINE} />);
    const dialog = await openPreview(user);

    expect(within(dialog).getByRole("button", { name: "Confirm and send" })).toBeDisabled();
    expect(
      within(dialog).getByText("Public egress is blocked in this build."),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Confirm and send" }));
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("renders URLs as text with no <a> element anywhere", () => {
    expect(FINDINGS.every((f) => /^https?:\/\//.test(f.url))).toBe(true);
    const { container } = render(<MarketPanel findings={FINDINGS} egress={OFFLINE} />);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(within(panel()).getByText(FINDINGS[0].url)).toBeInTheDocument();
  });

  it("shows both pills when web search and public egress are off", () => {
    render(<MarketPanel findings={[]} egress={OFFLINE} />);
    const p = panel();
    expect(within(p).getByText(/web search off/i)).toBeInTheDocument();
    expect(within(p).getByText(/public egress blocked/i)).toBeInTheDocument();
  });

  it("renders no dialog until the preview is opened", () => {
    render(<MarketPanel findings={[]} egress={OFFLINE} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("still honours a parent-controlled pending query", async () => {
    render(
      <MarketPanel
        findings={[]}
        egress={OFFLINE}
        onPreviewQuery={vi.fn()}
        pendingQuery={QUERY}
        onConfirmQuery={vi.fn()}
        onCancelQuery={vi.fn()}
      />,
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(within(dialog).getByText(QUERY.query)).toBeInTheDocument();
    await waitFor(() => expect(previewMock).toHaveBeenCalledWith(QUERY.query));
  });
});
