/**
 * THE PREVIEW OF THE NEW LOOK (owner, 26 Nov 2026, G9: "I need the best UI and UX"). The three journeys - Home, the review of a
 * document, a contractor query - drawn with the one design system and INVENTED data only: no client name, no real document, no call
 * to the server. It is how the owner sees the new look before anything goes live (the switch VITE_UI_NEW_LOOK stays off there).
 * Address: /preview, /preview/review, /preview/query. Not in the menu.
 */
import type { ViewId } from "../components/Shell";
import { Button, Card, DataTable, Fold, PageHeader, StatusChip } from "../components/ui";
import { HomeJobs } from "./HomeView";

const JOURNEYS = [
  { id: "home", label: "1. Home" },
  { id: "review", label: "2. Review a document" },
  { id: "query", label: "3. Answer a query" },
] as const;

type Journey = (typeof JOURNEYS)[number]["id"];

const COMMENTS = [
  {
    n: 1,
    where: "Standard XS-100, clause 4.2, page 3",
    quote: "Design pressure: 16 bar(g)",
    text: "The datasheet states 16 bar(g); clause 4.2 asks for at least 1.5 times the maximum operating pressure (20 bar(g)). Raise the design pressure or show the basis.",
  },
  {
    n: 2,
    where: "Standard XS-100, clause 6.1, page 5",
    quote: "Seal plan: to be advised",
    text: "The seal plan is left to the vendor. Question to the contractor: which seal plan is offered for this service?",
  },
  {
    n: 3,
    where: "Engineering knowledge (no standard held), page 2",
    quote: "Motor rating: 45 kW",
    text: "The motor rating leaves no margin over the stated absorbed power of 44 kW. Confirm the rating at the end-of-curve point.",
  },
];

function Banner() {
  return (
    <p data-testid="preview-banner" className="rounded-[var(--radius-sm)] border border-pill-cond-border bg-pill-cond-bg px-4 py-2 text-sm text-pill-cond-fg">
      Preview of the new look with invented data. Nothing on this page is real, and no button here changes anything.
    </p>
  );
}

function ReviewJourney() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Pump datasheet P-101 (invented)"
        purpose="Decide each comment, then sign the sheet. Nothing goes to the contractor before an engineer signs."
        actions={<Button>Download the comment sheet</Button>}
      />
      <Card className="flex flex-wrap items-center justify-between gap-4" data-testid="preview-verdict">
        <div>
          <p className="text-[length:var(--t-lg)] font-bold text-slateish-100">3 comments need your decision</p>
          <p className="mt-1 text-sm text-slateish-300">0 of 3 decided. The sheet can be signed once every comment is decided.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <StatusChip status="ai" />
          <Button tone="primary" disabled>Sign the sheet</Button>
        </div>
      </Card>
      <ul className="space-y-4">
        {COMMENTS.map((c) => (
          <Card as="li" key={c.n}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-slateish-200">Comment {c.n} · {c.where}</p>
              <StatusChip status="ai" />
            </div>
            <p className="mt-3 text-[length:var(--t-md)] text-slateish-100">{c.text}</p>
            <blockquote className="mt-3 border-l-4 border-signal-500 pl-3 text-sm text-slateish-300">On the page: "{c.quote}"</blockquote>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button tone="primary">Keep</Button>
              <Button>Change the wording</Button>
              <Button tone="danger">Remove</Button>
            </div>
          </Card>
        ))}
      </ul>
      <Fold title="How this review was made">
        <p>12 pages read of 12. 3 standards applied. 41 points checked: 38 found as asked, 3 comments above.</p>
        <p className="mt-2">Every comment is AI, to be checked, until an engineer signs.</p>
      </Fold>
    </div>
  );
}

function QueryJourney() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="TQ-0042: grout under the pump base plate (invented)"
        purpose="Check the question and the proposed answer, then approve it or ask for changes. Sending stays off."
      />
      <Card>
        <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">The contractor asks</p>
        <p className="mt-2 text-[length:var(--t-lg)] font-semibold text-slateish-100">
          Confirm the grout thickness under the pump base plate.
        </p>
        <p className="mt-2 text-sm text-slateish-300">From the attached form, tq-form-42.docx (the email itself only points to the form).</p>
      </Card>
      <Card data-testid="preview-draft">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">Proposed answer</p>
          <div className="flex gap-2"><StatusChip status="draft" /><StatusChip status="ai" /></div>
        </div>
        <p className="mt-3 text-[length:var(--t-md)] text-slateish-100">
          The grout under the base plate shall be at least 25 mm and at most 50 mm thick [S1]. Use non-shrink grout [S2].
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button tone="primary">Approve the answer</Button>
          <Button>Ask for changes</Button>
        </div>
      </Card>
      <Fold title="Evidence: 2 contract clauses">
        <DataTable
          caption="Evidence for the proposed answer"
          head={["Source", "Where", "Words on the page"]}
          rows={[
            ["S1", "Contract part 4 (invented), clause 9.3, page 12", "\"Grout thickness 25 to 50 mm under every base plate.\""],
            ["S2", "Contract part 4 (invented), clause 9.4, page 12", "\"Grout shall be of the non-shrink type.\""],
          ]}
        />
      </Fold>
      <Fold title="The email and its attachment">
        <p>From: Invented Contractor Ltd. "Please find attached our TQ-0042 for your review."</p>
        <p className="mt-2">tq-form-42.docx: read, 1 page.</p>
      </Fold>
    </div>
  );
}

export function PreviewView({ journey, onNavigate }: { journey?: string; onNavigate: (view: ViewId, recordId?: string) => void }) {
  const current: Journey = JOURNEYS.some((j) => j.id === journey) ? (journey as Journey) : "home";
  return (
    <section className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 md:px-8" aria-label="Preview of the new look">
      <Banner />
      <nav aria-label="Journeys" className="flex flex-wrap gap-2">
        {JOURNEYS.map((j) => (
          <Button key={j.id} tone={j.id === current ? "primary" : "secondary"} aria-current={j.id === current ? "page" : undefined}
            onClick={() => onNavigate("preview", j.id === "home" ? undefined : j.id)}>
            {j.label}
          </Button>
        ))}
      </nav>
      {current === "home" && (
        <div className="-mx-4 md:-mx-8">
          <HomeJobs counts={{ reviewsWaiting: 3, queriesWaiting: 29 }} queriesOn onNavigate={() => undefined} />
        </div>
      )}
      {current === "review" && <ReviewJourney />}
      {current === "query" && <QueryJourney />}
    </section>
  );
}
