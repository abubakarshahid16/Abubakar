/**
 * ONE home for the plain words of the redesigned review page (owner, 12 Nov 2026; SPEC.md). Nothing here decides anything: the
 * backend's plan and points already carry the facts; these functions only SAY them. No code word, no id, no model name.
 */
import type { EngineChoice, PointsListing, ReviewPlan, ReviewPoint } from "../../../api/reviewPoints";

export const ENGINE_LABELS: Record<EngineChoice, string> = { automatic: "Automatic", claude: "Claude", local: "Local only" };
export const NEEDS_YES = "needs the owner's yes for this upload";

export const TILE_ORDER = ["not_met", "questions", "met", "does_not_apply"] as const;
export const TILE_LABELS: Record<(typeof TILE_ORDER)[number], string> = {
  not_met: "Not met", questions: "Questions for you", met: "Met", does_not_apply: "Does not apply",
};

const usd = (n: number) => `USD ${Number.isInteger(n) ? n : n.toFixed(2)}`;

/** U5: Claude cannot run now (the spend ledger holds a standing refusal): the plain reason, or null when nothing stands in the way. */
export function claudeDownWords(plan: ReviewPlan): string | null {
  const r = plan.claude_standing_refusal;
  return r && r.words ? `Claude is not available now (${r.words})` : null;
}

/** "Engine: Claude. Text of this paper and of 4 rule books will leave this computer." The first line of the engine line. */
export function engineWords(plan: ReviewPlan): string {
  const down = claudeDownWords(plan);
  if (down && plan.choice === "automatic") return `${down}, so Automatic runs on this computer.`;
  if (down && plan.choice === "claude") return `${down}, so this choice cannot run now.`;
  if (plan.refused) return plan.refused.endsWith(".") ? plan.refused : `${plan.refused}.`;
  const onClaude = plan.parts.filter((p) => p.engine === "claude");
  const name = onClaude.length ? "Claude" : "this computer";
  if (!plan.text_leaves) return `Engine: ${name}. No text leaves this computer.`;
  const n = plan.documents.rule_books.length;
  const books = n > 0 ? `of ${n} rule book${n === 1 ? "" : "s"}` : "of its rule books";
  return `Engine: ${name}. Text of this paper and ${books} will leave this computer.`;
}

/** "Cost: about USD 0.50, limit USD 15" (the last review's real cost, when there is one) or "Cost: limit USD 15". Null: nothing is sent. */
export function costWords(plan: ReviewPlan): string | null {
  const limit = plan.cost.at_most_usd;
  if (limit == null || (claudeDownWords(plan) && plan.choice === "automatic")) return null;
  const last = plan.cost.last_review_usd;
  return last != null ? `Cost: about ${usd(last)}, limit ${usd(limit)}` : `Cost: limit ${usd(limit)}`;
}

/** What will not run, one plain sentence each. */
export function wontRunWords(plan: ReviewPlan): string[] {
  const out: string[] = [];
  for (const p of plan.parts) {
    if (p.engine === "not_run" && p.why) out.push(`${p.name === "ai_review" ? "The AI review" : "The rule check"} will not run: ${p.why.replace(/^the AI review needs Claude and will not run; /i, "")}`);
  }
  for (const w of plan.wont_run) out.push(`${w.part}: ${w.why}`);
  return out.map((s) => (s.endsWith(".") ? s : `${s}.`));
}

/** The small line under a tile. A count the review cannot have is simply absent (never 0). */
export function tileLine(tile: (typeof TILE_ORDER)[number], c: PointsListing["counts"]["tiles"][keyof PointsListing["counts"]["tiles"]]): string {
  if (tile === "questions") return c.groups != null ? `in ${c.groups} group${c.groups === 1 ? "" : "s"}` : "";
  const bits: string[] = [];
  if (c.two_readers != null) bits.push(`${c.two_readers} two readers`);
  if (c.one_reader != null) bits.push(`${c.one_reader} one reader`);
  const line = bits.join(" · ");
  if (c.proven_by_code != null && c.proven_by_code > 0) return line ? `${line} · ${c.proven_by_code} proven by code` : `${c.proven_by_code} proven by code`;
  return line;
}

/** The one line under the tiles: how firm the result is. Null when there is nothing to say. */
export function firmnessLine(c: PointsListing["counts"]): string | null {
  const parts: string[] = [];
  let proven = 0; let two: number | null = null; let one = 0;
  for (const t of ["not_met", "met"] as const) {
    const x = c.tiles[t];
    proven += x.proven_by_code ?? 0;
    one += x.one_reader ?? 0;
    if (x.two_readers != null) two = (two ?? 0) + x.two_readers;
  }
  if (proven) parts.push(`${proven} proven by code`);
  if (two != null && two > 0) parts.push(`${two} agreed by two readers`);
  if (one) parts.push(`${one} one reader's view`);
  return parts.length ? `How firm this is: ${parts.join(", ")}. A person decides each point.` : null;
}

/** The point's place: "page 4 · API 610, clause 6.2". Missing parts are left out. */
export function placeWords(p: ReviewPoint): string {
  const page = p.page != null ? `page ${p.page}` : "";
  const book = p.rule_book ? (p.clause ? `${p.rule_book}, clause ${p.clause}` : p.rule_book) : "";
  return [page, book].filter(Boolean).join(" · ");
}

/** The place of a group of alike points: the pages they stand on, listed once, then the rule book and clause they share. */
export function groupPlaceWords(points: ReviewPoint[]): string {
  const pages = [...new Set(points.map((p) => p.page).filter((n): n is number => n != null))].sort((a, b) => a - b);
  const first = points[0];
  const book = first.rule_book ? (first.clause ? `${first.rule_book}, clause ${first.clause}` : first.rule_book) : "";
  const where = pages.length ? `${pages.length === 1 ? "page" : "pages"} ${pages.join(", ")}` : "";
  return [where, book].filter(Boolean).join(" · ");
}

/** The tags a point's name carried, as the opened point says them. Empty when it had none. */
export function tagsWords(p: ReviewPoint): string {
  const n = p.tags?.length ?? 0;
  return n === 0 ? "" : `Applies to: ${n} tag${n === 1 ? "" : "s"}`;
}

/** The words of the state of a decided point, with who decided (the AI's view stays the AI's until a person keeps it). */
export function stateWords(p: ReviewPoint): string {
  const d = p.decision;
  if (!d.state) return "";
  if (p.source === "added") return "Added";
  return d.by ? `${d.words} by ${d.by}` : d.words;
}

/** Why Sign and issue waits, in one line, or null when nothing waits. */
export function signWaits(opts: { undecided: number; codeRecorded: boolean | null; blockers?: string[] }): string | null {
  const bits: string[] = [];
  if (opts.undecided > 0) bits.push(`${opts.undecided} point${opts.undecided === 1 ? " is" : "s are"} not decided yet`);
  if (opts.codeRecorded === false) bits.push("the review code is not recorded");
  for (const b of opts.blockers ?? []) bits.push(b);
  if (!bits.length) return null;
  const sentence = bits.length === 1 ? bits[0] : `${bits.slice(0, -1).join(", ")}, and ${bits[bits.length - 1]}`;
  return `Sign and issue waits: ${sentence}.`;
}

