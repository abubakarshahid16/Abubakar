/**
 * "How this review was made" (order 14; the owner's picture of 28 Nov 2026, round 1): one plain sentence, four numbers and six
 * steps. No panel is open at the start. Clicking a step opens ONLY that step's panel: beside the list on a wide window, under the
 * clicked step on a narrow one. The close button or another step closes or switches it.
 *
 * Every panel has the same parts: what we did, the result, the proof. Nothing is computed here that the server did not say: a
 * missing value renders as nothing (never 0), a reason that was not recorded says so, and a rule book the viewer may not open is
 * counted, never named (the server already leaves it out of `books`).
 *
 * Round 2 (not here; each needs the server to store or send one more thing): a mark per page and the page beside its text, the
 * rule count per book and the books not picked, the covered / not covered list of the second look, and the two note buttons.
 */
import { plainAi } from "../how/howData";
import { type ReactNode, useMemo, useState } from "react";

import type { GeneralCall, GeneralCompleteness, GeneralLine, GeneralReview } from "../../../api/generalReview";
import { Fold, LinkButton, RowButton, SelectField, ShowMore, StatusChip, Table, TextField, Tile, Tiles } from "../../kit/Kit";

/** The completeness result in words. Three counts of 0 compared nothing: never "all three agree" (REVIEW.md: 0 == 0 is not a pass;
 *  H's one-real-file pass, 27 Nov 2026, R5). */
export function completenessResult(c: GeneralCompleteness): string {
  if (c.nothing_to_compare || (c.page === 0 && c.database === 0 && c.file_rows === 0)) return "nothing to compare: the review has no points";
  return c.ok ? "all three agree" : "they differ: the file is refused";
}

/** The words of a book whose reason was not stored; the server says the same ones (and "not shown: it names a book you may not read"). */
const NO_REASON = "the reason was not recorded for this review";

/** The plain name of each step the run's calls are grouped under; a step this table does not know is shown by its own name. */
export const STEP_NAMES: Record<string, string> = {
  aim_read_pages: "Read the document",
  aim_identify: "Name the document",
  aim_select: "Choose rule books",
  aim_checklist: "Write the list of checks",
  aim_checklist_retry: "Write the list of checks (retry)",
  aim_checklist_knowledge: "Add engineering-knowledge items",
  aim_attack: "A second AI checks the list",
  aim_judge: "Check each item",
  aim_edit: "Write the comments",
  ledger: "Read the spend ledger",
  aim_unread_pages: "Read pages that had no text",
  aim_reference: "Check against the other parts of the same contract",
  aim_answered: "Check whether the document already answers each comment",
  aim_second_read: "A second AI reads it again",
  aim_cross_document: "Compare with the other documents",
};

/** A step's name in words: its own name, else its code without the "aim_" prefix and underscores (never a raw code on a screen, R7). */
export function stepName(step: string): string {
  if (STEP_NAMES[step]) return STEP_NAMES[step];
  const words = step.replace(/^aim_/, "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : step;
}

export interface StepTotals { step: string; name: string; calls: number; models: string[]; seconds: number; usd: number | null }

/** One row per step, in the order the steps first appear. `usd` is null when no call of the step carried a cost (never 0). */
export function totalsByStep(calls: GeneralCall[]): StepTotals[] {
  const by = new Map<string, StepTotals>();
  for (const c of calls) {
    const row = by.get(c.step) ?? { step: c.step, name: stepName(c.step), calls: 0, models: [], seconds: 0, usd: null };
    row.calls += 1;
    if (c.model && !row.models.includes(c.model)) row.models.push(c.model);
    row.seconds += typeof c.seconds === "number" && Number.isFinite(c.seconds) ? c.seconds : 0;
    if (typeof c.usd === "number" && Number.isFinite(c.usd)) row.usd = (row.usd ?? 0) + c.usd;
    by.set(c.step, row);
  }
  return [...by.values()];
}

/** Section 6's sentence on the confirmations: shown only when the server counted them (an older run has no such count). */
export function confirmationsLine(review: GeneralReview): string | null {
  const { comments, confirmations, comment_lines: inComments, confirmation_lines: inConfirmations } = review.counts;
  if (confirmations == null) return null;
  const pts = (n: number) => `${n} point${n === 1 ? "" : "s"}`;
  const sent = `${comments} comment${comments === 1 ? "" : "s"} sent${inComments != null ? ` (covering ${pts(inComments)})` : ""}`;
  const held = `${confirmations} confirmation${confirmations === 1 ? "" : "s"} not sent${inConfirmations != null ? ` (covering ${pts(inConfirmations)})` : ""}`;
  const total = inComments != null && inConfirmations != null ? `; together ${pts(inComments + inConfirmations)} qualified to be sent` : "";
  return `${sent} and ${held}${total}. Every point stays under "Checked each point".`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const minutes = (s: number) => `${(Math.round((s / 60) * 10) / 10).toString()} min`;
const bookOf = (l: GeneralLine) => [l.standard || "engineering knowledge", l.clause].filter(Boolean).join(", clause ");

/** How much to trust a point, from the label the server shows on it. Code decides this, never the wording of a comment. */
export type TrustGroup = "code" | "ai_met" | "yours" | "dismissed";
export function trustOf(shownLabel: string): TrustGroup {
  if (/compared by code/i.test(shownLabel)) return "code";
  if (shownLabel === "AI opinion: met") return "ai_met";
  if (shownLabel === "AI opinion: does not apply") return "dismissed";
  return "yours";
}

const TRUST: { group: TrustGroup; name: string; chip: string; line: (r: GeneralReview) => string }[] = [
  { group: "code", name: "Decided by code", chip: "Most trusted", line: () => "Code compared two numbers. Check only that the right two were paired." },
  { group: "ai_met", name: "Read by the AI as met", chip: "Trust with care", line: () => "The AI said the rule is met. Where it gave a quote, code looked for it on the page. The AI can still misread." },
  {
    group: "yours", name: "For you to decide", chip: "Yours to decide",
    line: (r) => `These points make up the ${plural(r.counts.comments, "comment")}${r.counts.confirmations != null ? ` and the ${plural(r.counts.confirmations, "point")} to confirm` : ""} of the first page. Points that repeat one finding are joined into one comment.`,
  },
  { group: "dismissed", name: "Dismissed by the AI alone", chip: "Least trusted", line: () => "The AI said the rule does not apply. No code and no person checked it." },
];

type StepKey = "read" | "named" | "books" | "checks" | "second" | "counted";
interface Step { key: StepKey; title: string; line: string; chip: string; chipWhy?: string }

/** The six steps of the list: a title, one short line, one status word. Each word comes from the stored review, never a guess. */
export function sixSteps(review: GeneralReview): Step[] {
  const notRead = (review.pages_not_read ?? []).length;
  const record = review.pages_not_read_record;
  const id = review.identity;
  const namedRaw = [id.kind?.replace(/_/g, " "), id.equipment_type?.replace(/_/g, " ")].filter(Boolean).join(", ");
  const named = namedRaw ? namedRaw.charAt(0).toUpperCase() + namedRaw.slice(1) : "";
  const missing = review.not_held.length;
  const byCode = review.counts.decided_by_code?.count ?? null;
  const secondCalls = (review.calls ?? []).filter((c) => c.step === "aim_second_read").length;
  const differ = review.comments.filter((c) => c.readers).length;
  const notApplied = (review.steps_not_applied ?? []).length;
  const c = review.completeness;
  const nothing = c.nothing_to_compare || (c.page === 0 && c.database === 0 && c.file_rows === 0);
  return [
    {
      key: "read", title: "Read the paper",
      line: notRead > 0 ? `${plural(notRead, "part")} of the paper ${notRead === 1 ? "was" : "were"} not read` : record === "all_read" ? "Every page was read" : "Which pages were read is not recorded",
      chip: notRead > 0 ? "Not read" : record === "all_read" ? "Done" : "Not recorded",
    },
    { key: "named", title: "Named the paper", line: named || "What the paper is was not recorded", chip: named ? "Done" : "Not recorded" },
    {
      key: "books", title: "Picked the rule books",
      line: `${review.books.length} used${missing > 0 ? `, ${missing} needed but not in the library` : ""}`,
      chip: missing > 0 ? "Not held" : "Done", chipWhy: missing > 0 ? `${plural(missing, "rule book")} this paper needs ${missing === 1 ? "is" : "are"} not in the library` : undefined,
    },
    {
      key: "checks", title: "Checked each point",
      line: `${plural(review.counts.points, "point")}${byCode != null ? `, ${byCode} compared by code` : ""}`,
      chip: review.counts.points > 0 ? "Done" : "Not recorded",
    },
    {
      key: "second", title: "Second look at the faults",
      line: secondCalls === 0 ? "No second look is recorded for this review" : differ > 0 ? `${plural(differ, "comment")} got a different answer` : "No comment got a different answer",
      chip: notApplied > 0 ? "To check" : secondCalls === 0 ? "Not recorded" : "Done",
      chipWhy: notApplied > 0 ? `${plural(notApplied, "checking step")} did not run` : undefined,
    },
    {
      key: "counted", title: "Counted everything",
      line: nothing ? "Nothing to compare: the review has no points" : `Page ${c.page}, database ${c.database}, file ${c.file_rows}`,
      chip: nothing ? "Not recorded" : c.ok ? "Done" : "Failed", chipWhy: nothing ? undefined : c.ok ? "The three counts agree" : "The three counts differ: the file is refused",
    },
  ];
}

function Fact({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value == null || value === "") return null; // null renders as nothing
  return (
    <div className="kit-fact">
      <span className="kit-fact__label">{label}</span>
      <span className="kit-fact__value">{value}</span>
    </div>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <h4 className="text-sm font-semibold text-signal-300">{title}</h4>
      <div className="space-y-2 text-sm text-slateish-200">{children}</div>
    </div>
  );
}

const CHECKS_PAGE = 20;

/** The points of the review, filtered by how much to trust them, by the result shown, and by a word. Folded to 20 rows at a time. */
function Checks({ points, group, onGroup }: { points: GeneralLine[]; group: TrustGroup | null; onGroup: (g: TrustGroup | null) => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState("");
  const [limit, setLimit] = useState(CHECKS_PAGE);
  const results = useMemo(() => [...new Set(points.map((p) => p.shown_label).filter(Boolean))], [points]);
  const shown = useMemo(() => {
    const q = text.trim().toLowerCase();
    return points.filter((p) => (!group || trustOf(p.shown_label) === group) && (!result || p.shown_label === result) && (!q || JSON.stringify(p).toLowerCase().includes(q)));
  }, [points, text, result, group]);
  return (
    <div className="space-y-2" data-testid="how-checks">
      <div className="flex flex-wrap items-end gap-2">
        <TextField id="how-checks-search" label="Search the points" placeholder="A field, a rule book, a word" value={text} onChange={(e) => { setText(e.target.value); setLimit(CHECKS_PAGE); }} />
        <SelectField id="how-checks-result" label="Show points with this result" value={result} onChange={(e) => { setResult(e.target.value); setLimit(CHECKS_PAGE); }}>
          <option value="">All results</option>
          {results.map((r) => <option key={r} value={r}>{r}</option>)}
        </SelectField>
        {group && <LinkButton tone="action" onClick={() => onGroup(null)}>Show all points</LinkButton>}
      </div>
      <p data-testid="how-checks-count" className="text-xs text-slateish-300">{shown.length} of {points.length} points</p>
      <Table caption="The points of this review"
        columns={["#", "Result", "Field on the paper", "Page", "Rule book, clause", "What code compared", "Comment and the paper's words"]}
        rows={shown.slice(0, limit).map((p) => ({
          key: `${p.n}-${p.item_id}`,
          cells: [
            p.n,
            p.shown_label,
            <>{p.field || p.item_id}{p.topic ? <span className="block text-slateish-400">{p.topic}</span> : null}</>,
            p.page ?? "",
            <>{bookOf(p)}{p.source ? <span className="block text-slateish-400">{p.source}</span> : null}</>,
            p.compared ? <>{p.compared}{p.compare_kind ? <span className="block text-slateish-400">{p.compare_kind}</span> : null}</> : <span className="text-slateish-400">nothing compared by code</span>,
            <>{p.comment}{p.quote ? <span className="block italic text-slateish-300">Paper: “{p.quote}”{p.quote_unverified ? " (code could not find this quote on the page)" : ""}</span> : null}</>,
          ],
        }))} />
      <ShowMore testId="how-checks-more" shown={Math.min(limit, shown.length)} total={shown.length} step={CHECKS_PAGE} onMore={() => setLimit((n) => n + CHECKS_PAGE)} />
    </div>
  );
}

/** What the run's own calls say about the second look: which AI judged and which looked again. Null when no second look is recorded. */
export function secondLookWords(calls: GeneralCall[]): string | null {
  const models = (step: string) => [...new Set(calls.filter((c) => c.step === step && c.model && c.model !== "code").map((c) => c.model))];
  const second = models("aim_second_read");
  if (second.length === 0) return null;
  const first = models("aim_judge");
  const same = first.length > 0 && second.every((m) => first.includes(m));
  return same
    ? "We asked again about each fault. The same AI was asked twice. This is not a second reviewer."
    : "We asked again about each fault. A different AI looked the second time. It is still not a person.";
}

function PanelRead({ review }: { review: GeneralReview }) {
  const notRead = review.pages_not_read ?? [];
  return (
    <>
      <Part title="What we did"><p>Read every page. A page counts as read only when its text or a reading of its picture came back.</p></Part>
      <Part title="The result">
        {notRead.length > 0 ? (
          <div data-testid="general-pages-not-read" className="space-y-1">
            <p className="font-semibold text-slateish-100">{plural(notRead.length, "part")} of this paper {notRead.length === 1 ? "was" : "were"} not read.</p>
            <p>Nothing in this review says anything about them: no text and no picture reading came back, or it has not run yet.</p>
            <ul className="list-disc pl-5">{notRead.map((x) => <li key={x.where}>{x.sentence}</li>)}</ul>
          </div>
        ) : review.pages_not_read_record === "all_read" ? <p>Every page had text or a picture reading.</p>
          : <p data-testid="general-pages-not-recorded">Which pages were read is not recorded for this review.</p>}
      </Part>
      <Part title="The proof"><p>Every comment names its page. Open the page from the comment to compare it with the paper.</p></Part>
    </>
  );
}

function PanelNamed({ review }: { review: GeneralReview }) {
  const id = review.identity;
  return (
    <div data-testid="how-paper" className="space-y-3">
      <Part title="What we did"><p>Named the paper first. Every later step depends on this answer: which rule books, and which list of checks.</p></Part>
      <Part title="The result">
        <div className="flex flex-wrap gap-2">
          <Fact label="Type of paper" value={id.kind} />
          <Fact label="Equipment or subject" value={id.equipment_type?.replace(/_/g, " ")} />
          <Fact label="Subject in the paper's words" value={id.subject} />
        </div>
        {!id.kind && !id.equipment_type && !id.subject && <p className="text-slateish-300">This review did not record what the paper is.</p>}
      </Part>
      <Part title="The proof"><p>If the type is wrong, every later step is wrong too. Use “Change type” at the top of the review and run it again.</p></Part>
    </div>
  );
}

function PanelBooks({ review }: { review: GeneralReview }) {
  return (
    <div data-testid="how-books" className="space-y-3">
      <Part title="What we did"><p>Picked rule books by the paper's subject and equipment, never by shared words.</p></Part>
      <Part title={`The result: ${review.books.length} used${review.books_not_readable ? `, and ${review.books_not_readable} you may not open` : ""}`}>
        {review.documents_listed && <p data-testid="how-listed" className="text-xs text-slateish-300">{review.documents_listed.sentence}</p>}
        {review.books.length === 0 ? <p className="text-slateish-300">none</p> : (
          <ul className="space-y-1">
            {review.books.map((b) => (
              <li key={b.id} data-testid="how-book"><span className="text-slateish-100">{b.title}</span>
                <span className="block text-xs text-slateish-300">Why chosen: {b.why || NO_REASON}</span></li>
            ))}
          </ul>
        )}
      </Part>
      <Part title={`Needed but not in the library: ${review.not_held.length}`}>
        {review.not_held.length === 0 ? <p className="text-slateish-300">none</p> : (
          <ul className="space-y-1" data-testid="how-not-held">
            {review.not_held.map((b) => (
              <li key={b.name}><span className="text-slateish-100">{b.name}</span> <StatusChip word="Not held" />
                {b.why ? <span className="block text-xs text-slateish-300">Why needed: {b.why}</span> : null}</li>
            ))}
          </ul>
        )}
        {review.unlisted_books.sentence && <p data-testid="general-unlisted">{review.unlisted_books.sentence}</p>}
      </Part>
      {review.references && review.references.length > 0 && (
        <Part title={`Parts of the contract read: ${review.references.length}`}>
          <ul className="space-y-1" data-testid="how-references">
            {review.references.map((r, i) => (
              <li key={`${r.part}-${i}`} data-testid="how-reference"><span className="text-slateish-100">{r.part}</span>
                {r.title ? <span className="text-slateish-300"> ({r.title})</span> : null}
                <span className="block text-xs text-slateish-300">
                  {r.status}
                  {r.pages_held ? `; pages read ${r.pages_read ?? 0} of ${r.pages_held}` : ""}
                  {r.questions ? `; ${r.settled ?? 0} of ${r.questions} questions settled` : ""}
                  {r.compared ? `; ${r.compared} sentence${r.compared === 1 ? "" : "s"} of the Form compared${r.differs ? `, ${r.differs} differ` : ""}` : ""}
                </span>
                {r.reason ? <span className="block text-xs text-slateish-300">{r.reason}</span> : null}
              </li>
            ))}
          </ul>
        </Part>
      )}
    </div>
  );
}

function PanelChecks({ review, group, onGroup }: { review: GeneralReview; group: TrustGroup | null; onGroup: (g: TrustGroup | null) => void }) {
  const k = review.checklist;
  const counts = useMemo(() => {
    const by: Record<TrustGroup, number> = { code: 0, ai_met: 0, yours: 0, dismissed: 0 };
    for (const p of review.points) by[trustOf(p.shown_label)] += 1;
    return by;
  }, [review.points]);
  return (
    <>
      <Part title="What we did">
        <p>Opened the rule and the paper for each point. Where both hold a number, code compared them.</p>
        <div data-testid="how-checklist">
          <Fold title="The list of checks this review used">
            {k.key ? (
              <div className="flex flex-wrap gap-2">
                <Fact label="List name" value={k.key} />
                <Fact label="Items" value={k.items} />
                <Fact label="Items every review checks" value={k.always_items || null} />
                <Fact label="Reused or new" value={k.reused == null ? null : k.reused ? "reused from an earlier review" : "built for this review"} />
                <Fact label="Built from" value={k.built_from} />
              </div>
            ) : <p className="text-slateish-300">This review did not record its list of checks.</p>}
          </Fold>
        </div>
      </Part>
      <Part title="The result, and how much to trust each part">
        <div className="grid gap-2 sm:grid-cols-2" data-testid="how-trust">
          {TRUST.map((t) => (
            <div key={t.group} data-testid={`how-trust-${t.group}`} className="kit-fact">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slateish-100">{t.name}: {counts[t.group]}</span>
                <StatusChip word={t.chip} />
              </span>
              <span className="block text-xs text-slateish-300">{t.line(review)}</span>
              {counts[t.group] > 0 && <span><LinkButton tone="action" pressed={group === t.group} onClick={() => onGroup(group === t.group ? null : t.group)}>{group === t.group ? "Showing these" : "Show these"}</LinkButton></span>}
            </div>
          ))}
        </div>
        <p className="text-xs text-slateish-300">{TRUST.map((t) => counts[t.group]).join(" + ")} = {plural(review.points.length, "point")}.</p>
      </Part>
      <Part title="The proof">
        <p>Every row names its rule book and clause, its page, the paper's words, and what code compared. Every row is marked “AI, to be checked”.</p>
        <Checks points={review.points} group={group} onGroup={onGroup} />
      </Part>
    </>
  );
}

function PanelSecond({ review }: { review: GeneralReview }) {
  const words = secondLookWords(review.calls ?? []);
  const differ = review.comments.filter((c) => c.readers);
  const notApplied = review.steps_not_applied ?? [];
  return (
    <>
      <Part title="What we did">
        <p>A fault is a point where the AI said the paper does not meet the rule. Faults become your comments.</p>
        <p data-testid="how-second-words" className="font-semibold text-slateish-100">{words ?? "No second look is recorded for this review."}</p>
      </Part>
      <Part title="The result">
        {words && <p>{differ.length > 0 ? `${plural(differ.length, "comment")} got a different answer the second time. ${differ.length === 1 ? "It is" : "They are"} marked “Two readers differ” on the Comments tab.` : "No comment got a different answer the second time."}</p>}
        {differ.length > 0 && <ul className="list-disc pl-5" data-testid="how-second-differ">{differ.map((c) => <li key={c.n}>{c.title ?? c.field}</li>)}</ul>}
        {notApplied.length > 0 && (
          <div data-testid="general-steps-not-applied" className="space-y-1">
            <p className="font-semibold text-slateish-100">{plural(notApplied.length, "checking step")} did not run on this sheet. Treat what {notApplied.length === 1 ? "it" : "they"} would have checked as unchecked.</p>
            <ul className="list-disc pl-5">{notApplied.map((x) => <li key={`${x.step}:${x.why}`}>{x.sentence}</li>)}</ul>
          </div>
        )}
      </Part>
    </>
  );
}

function PanelCounted({ review }: { review: GeneralReview }) {
  const c = review.completeness;
  const line = confirmationsLine(review);
  return (
    <div data-testid="how-complete" className="space-y-3">
      <Part title="What we did"><p>Counted the points on the page, the lines in the database and the rows in the Excel file. If they differ, the file is refused.</p></Part>
      <Part title="The result">
        <div className="flex flex-wrap gap-2">
          <Fact label="Points on the page" value={c.page} />
          <Fact label="Lines in the database" value={c.database} />
          <Fact label="Rows in the file" value={c.file_rows} />
          <Fact label="Result" value={completenessResult(c)} />
        </div>
        {line && <p data-testid="how-confirmations">{line}</p>}
      </Part>
      <Part title="The proof">
        <div data-testid="how-sheet">
          <Fold title={`The comment sheet: the ${plural(review.comments.length, "row")} that ${review.comments.length === 1 ? "is" : "are"} sent`}>
            {review.comments.length === 0 ? <p className="text-slateish-300">This review has no comments.</p> : (
              <Table caption="The rows of the comment sheet" columns={["#", "Result", "Field", "Page", "Rule book, clause", "Comment"]}
                rows={review.comments.map((l) => ({ key: `${l.n}-${l.item_id}`, cells: [l.n, l.shown_label, l.field || l.item_id, l.page ?? "", bookOf(l), <span className="whitespace-pre-line">{l.comment}</span>] }))} />
            )}
          </Fold>
        </div>
      </Part>
    </div>
  );
}

function TimeAndCost({ review }: { review: GeneralReview }) {
  const steps = useMemo(() => totalsByStep(review.calls ?? []), [review.calls]);
  const totalSeconds = steps.reduce((a, s) => a + s.seconds, 0);
  return (
    <div data-testid="how-time">
      <Fold title="Time and cost of this review">
        <div className="space-y-2 text-sm text-slateish-200">
          <div className="flex flex-wrap gap-2">
            <Fact label="Clock time" value={typeof review.seconds === "number" ? minutes(review.seconds) : null} />
            <Fact label="Cost of the review" value={review.cost.usd != null ? `USD ${review.cost.usd.toFixed(2)}` : null} />
          </div>
          {review.cost.usd == null && <p data-testid="how-cost-unread" className="text-xs text-slateish-300">{review.cost.note ?? "The cost of this review was not read from the spend ledger."}</p>}
          {steps.length === 0 ? <p className="text-slateish-300">No calls were recorded for this review.</p> : (
            <>
              <p className="text-xs text-slateish-300">Seconds add up each call's own time. Calls that ran side by side overlap, so the sum can be longer than the clock time.</p>
              <Table caption="Time and cost per step" columns={["Step", "Calls", "Which AI", "Seconds", "Share of time", "USD"]}
                rows={steps.map((s) => ({
                  key: s.step,
                  cells: [
                    s.name, s.calls,
                    <span title={s.models.join(", ")}>{[...new Set(s.models.map((m) => plainAi(m) ?? m))].join(", ")}</span>,
                    Math.round(s.seconds),
                    `${totalSeconds > 0 ? Math.round((s.seconds / totalSeconds) * 100) : 0}%`,
                    s.usd != null ? s.usd.toFixed(3) : "",
                  ],
                }))} />
            </>
          )}
        </div>
      </Fold>
    </div>
  );
}

export function HowReviewMade({ review, onOpenTab }: {
  review: GeneralReview;
  /** Open another tab of the review page from a number ("23 comments for you" opens the comments). */
  onOpenTab?: (tab: "comments" | "confirm") => void;
}) {
  const [open, setOpen] = useState<StepKey | null>(null); // no panel is open at the start
  const [group, setGroup] = useState<TrustGroup | null>(null);
  const steps = useMemo(() => sixSteps(review), [review]);
  const by = review.counts.by_shown_label ?? {};
  const notApplied = (review.steps_not_applied ?? []).length;
  const missing = review.not_held.length;
  const notRead = (review.pages_not_read ?? []).length;
  const notes = [
    notApplied > 0 ? `${plural(notApplied, "checking step")} did not run.` : "",
    missing > 0 ? `${plural(missing, "rule book")} this paper needs ${missing === 1 ? "is" : "are"} not in the library.` : "",
    notRead > 0 ? `${plural(notRead, "part")} of this paper ${notRead === 1 ? "was" : "were"} not read.` : "",
  ].filter(Boolean).join(" ");
  const openChecks = (g: TrustGroup) => { setGroup(g); setOpen("checks"); };
  const panelOf = (key: StepKey): ReactNode => {
    if (key === "read") return <PanelRead review={review} />;
    if (key === "named") return <PanelNamed review={review} />;
    if (key === "books") return <PanelBooks review={review} />;
    if (key === "checks") return <PanelChecks review={review} group={group} onGroup={setGroup} />;
    if (key === "second") return <PanelSecond review={review} />;
    return <PanelCounted review={review} />;
  };
  return (
    <div data-testid="how-made" className="space-y-4">
      <div data-testid="how-summary"><div data-testid="general-counts" className="space-y-1">
        <p className="text-base font-semibold text-slateish-100">
          {review.counts.points === 0 ? "This review has no points." : `${plural(review.counts.points, "point")} ${review.counts.points === 1 ? "was" : "were"} checked against ${plural(review.books.length, "rule book")}.`}
        </p>
        {notes && <p className="text-sm text-slateish-200">{notes}</p>}
        <p className="text-xs text-slateish-300">{review.counts.boundary}. {review.counts.decided_by_code?.sentence}</p>
      </div></div>

      <Tiles label="The numbers of this review" testId="how-numbers">
        <Tile name="Comments" number={review.counts.comments} label="for you to decide" onOpen={() => onOpenTab?.("comments")} />
        {review.counts.confirmations != null && <Tile name="To confirm" number={review.counts.confirmations} label="points, not sent" onOpen={() => onOpenTab?.("confirm")} />}
        {by["AI opinion: met"] != null && <Tile name="Met" number={by["AI opinion: met"]} label="the AI's view" onOpen={() => openChecks("ai_met")} />}
        {by["AI opinion: does not apply"] != null && <Tile name="Do not apply" number={by["AI opinion: does not apply"]} label="the AI's view, least trusted" onOpen={() => openChecks("dismissed")} />}
      </Tiles>

      {/* Wide: the list in the first column and the open panel beside it. Narrow: one column, the panel straight under its step.
          The seventh row takes the panel's extra height, so the six rows of the list keep their own height. */}
      <ol data-testid="how-steps" className={open == null ? "space-y-2" : "space-y-2 md:grid md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:gap-x-4 md:space-y-0 md:[grid-template-rows:repeat(6,auto)_1fr]"}>
        {steps.map((s, i) => [
          <li key={s.key} data-testid={`how-step-${s.key}`} className="grid grid-cols-[minmax(0,1fr)_6.5rem] items-center gap-2 md:col-start-1 md:pb-2">
            <span className="min-w-0">
              <RowButton selected={open === s.key} onClick={() => setOpen(open === s.key ? null : s.key)}
                first={<>{i + 1}. {s.title}</>} second={s.line} />
            </span>
            <span className="justify-self-end"><StatusChip word={s.chip} why={s.chipWhy} /></span>
          </li>,
          open === s.key ? (
            <li key={`${s.key}-panel`} className="md:col-start-2 md:row-start-1 md:[grid-row-end:span_7]">
              <section aria-label={`Step ${i + 1}: ${s.title}`} data-testid="how-panel" data-step={s.key} className="kit-card space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-base font-semibold text-slateish-100">Step {i + 1}: {s.title}</h3>
                  <LinkButton tone="action" onClick={() => setOpen(null)}>Close</LinkButton>
                </div>
                {panelOf(s.key)}
              </section>
            </li>
          ) : null,
        ])}
      </ol>
      {open == null && <p className="text-xs text-slateish-300">Click a step to see what was done and the proof.</p>}

      <TimeAndCost review={review} />
    </div>
  );
}
