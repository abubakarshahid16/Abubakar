/**
 * WHAT THE CONTRACTOR IS ASKING, AS ONE READABLE ASK (owner, 26 Nov 2026 21:29 and 21:36: "it is so difficult for me to read ... if I
 * have to open the email and check, then what is the point"). The question box arrives filled: a lead-in line (the email's own question,
 * else the query's subject) and the requests found on the form as a numbered list; each numbered line is shown with the file and page it
 * was found on. Builds on the found questions (builder H: the first BOX_FOUND go in, the rest wait folded). Nothing here confirms or
 * sends anything: it is text the engineer reads, edits and confirms.
 */

export interface FoundQuestion {
  question: string;
  filename: string | null;
  page: number | null;
}

export interface QuestionSource {
  confirmed_question?: string | null;
  edited_question?: string | null;
  proposed_question?: string | null;
  proposed_questions?: FoundQuestion[] | null;
  extracted_question?: string | null;
  extracted_question_main?: string | null;
  subject?: string | null;
  title_short?: string | null;
}

/** Without the server's composed ask: how many found requests start in the list (builder H). With it, every request is in the ask and
 *  the page folds the list after this many ("N more requests"), hiding none. */
export const LIST_FOUND = 6;

const NUMBERED = /^\s*(\d{1,2})[.)]\s+(.*\S)\s*$/;

/** The subject without mail prefixes ("Fw:", "Re:"), for a lead-in when the email itself asks nothing. */
function plainSubject(q: QuestionSource): string {
  const subject = (q.title_short || q.subject || "").replace(/^\s*((fw|fwd|re)\s*:\s*)+/i, "").trim();
  return subject;
}

/** The text the question box starts with: the confirmed wording; else a lead-in and the found requests, numbered; else the form's own
 *  question section; else the email's question. */
export function startingText(q: QuestionSource & { ready?: { question?: string | null } | null }): string {
  // THE SERVER IS THE ONE HOME (builder A, 26 Nov 2026): it composes the ask by the same rule, keeps EVERY found request, and finds the
  // sources and writes the draft for exactly that text; the page shows it as it is. The rule below is only for a server without it.
  if (q.ready && typeof q.ready.question === "string") return q.ready.question;
  if (q.confirmed_question) return q.confirmed_question;
  if (q.edited_question) return q.edited_question; // the engineer's own wording, saved, not confirmed (builder A)
  const email = (q.extracted_question_main ?? q.extracted_question ?? "").trim();
  const found = [...new Set((q.proposed_questions ?? []).slice(0, LIST_FOUND).map((f) => f.question.trim()).filter((t) => t && !email.includes(t)))];
  if (found.length) {
    const subject = plainSubject(q);
    const lead = email || (subject ? `About ${subject}, the contractor asks for the following:` : "The contractor asks for the following:");
    return [lead, ...found.map((t, i) => `${i + 1}. ${t}`)].join("\n");
  }
  return (q.proposed_question ?? "").trim() || email;
}

export interface ReadableLine {
  kind: "lead" | "item";
  n?: number;
  text: string;
  /** "file, page N" when the line is a request found on the form. */
  source?: string;
}

/** The question text as the page shows it: the lead-in, then each numbered request with where it was found. */
export function readableLines(text: string, found: FoundQuestion[] | null | undefined): ReadableLine[] {
  const where = new Map<string, string>();
  for (const f of found ?? []) {
    const key = f.question.trim();
    if (key && !where.has(key)) where.set(key, [f.filename, f.page != null ? `page ${f.page}` : null].filter(Boolean).join(", "));
  }
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const m = NUMBERED.exec(line);
      if (!m) return { kind: "lead" as const, text: line, source: where.get(line) || undefined };
      // a form's own list marker ("- Matching line list") is not part of the request: shown without it, its source still found
      const shown = m[2].replace(/^[-–•*]\s+/, "");
      return { kind: "item" as const, n: Number(m[1]), text: shown, source: where.get(m[2]) || where.get(shown) || undefined };
    });
}

/** The found requests not in the text (the ones beyond LIST_FOUND, or taken out): the "may have missed a request" mark counts them. */
export function notInText(text: string, found: FoundQuestion[] | null | undefined): FoundQuestion[] {
  return (found ?? []).filter((f) => f.question.trim() && !text.includes(f.question.trim()));
}

/** The text with one more request appended as the next number. */
export function withRequest(text: string, request: string): string {
  const items = readableLines(text, []).filter((l) => l.kind === "item").map((l) => l.n ?? 0);
  const next = (items.length ? Math.max(...items) : 0) + 1;
  return [text.trim(), `${next}. ${request.trim()}`].filter(Boolean).join("\n");
}

export interface EvidenceForMarks {
  match_count?: number | null;
  match_terms?: number | null;
  evidence_state: string;
  /** False when found for an earlier wording (builder A): never counted for the current question's marks. */
  for_current_question?: boolean | null;
}

/** The sources found for the wording the page works from (builder A's for_current_question; all of them on an older server). */
export function currentSources<T extends { for_current_question?: boolean | null }>(evidence: T[] | null | undefined): T[] {
  return (evidence ?? []).filter((e) => e.for_current_question !== false);
}

export interface MarksSource extends QuestionSource {
  evidence?: EvidenceForMarks[] | null;
  evidence_coverage?: { cited_first?: string[] | null } | null;
  evidence_job?: { state?: string | null } | null;
}

/** More key words than any question holds: the sources were searched for a whole mail or form text, not for the ask (measured on the
 *  stored queries, 26 Nov 2026: 200 to 560 key words, when a question holds tens). The ratio of key words then says nothing. */
export const QUESTION_KEY_WORDS_MAX = 60;

export function staleSources(q: MarksSource): boolean {
  return currentSources(q.evidence).some((e) => (e.match_terms ?? 0) > QUESTION_KEY_WORDS_MAX);
}

/** HONEST MARKS INSTEAD OF GATES (owner, 26 Nov 2026 21:36): one plain line per thing the system is unsure of, shown on the item it is
 *  about; nothing here blocks the page. `question` marks sit under the question, `evidence` marks above the sources. */
export function honestMarks(q: MarksSource, text: string): { question: string[]; evidence: string[] } {
  const question: string[] = [];
  const left = notInText(text, q.proposed_questions);
  if (left.length) question.push(`${left.length} more line${left.length === 1 ? " was" : "s were"} found on the form and ${left.length === 1 ? "is" : "are"} not in the list: one may be a request. Check below.`);
  const evidence: string[] = [];
  const running = q.evidence_job?.state === "queued" || q.evidence_job?.state === "running";
  const all = currentSources(q.evidence);
  if (!running && all.length === 0) evidence.push("No source was found for this question yet: the answer has nothing to stand on.");
  const scored = all.filter((e) => (e.match_terms ?? 0) > 0);
  if (staleSources(q)) {
    evidence.push("These sources were found for the whole text of the mail, not for the question: find them again for the question.");
  } else if (scored.length) {
    const best = scored.reduce((a, b) => ((b.match_count ?? 0) / (b.match_terms ?? 1) > (a.match_count ?? 0) / (a.match_terms ?? 1) ? b : a));
    if ((best.match_count ?? 0) / (best.match_terms ?? 1) < 0.5) {
      evidence.push("Weak match: the sources found share few words with the question. Read them before relying on the reply.");
    }
  }
  for (const line of q.evidence_coverage?.cited_first ?? []) {
    if (/not held|not found|not looked up/i.test(line)) evidence.push(`The form cites ${line.replace(/^(\w)/, (c) => c.toLowerCase())}.`);
  }
  return { question, evidence };
}

export interface ReadyState {
  evidence: "ready" | "refreshing" | "none" | "failed";
  evidence_fresh: boolean;
  draft: "ready" | "refreshing" | "none" | "not_written";
  draft_fresh: boolean;
  draft_note?: string | null;
  marks?: string[];
}

/** One plain line on where the sources and the draft stand (builder A's `ready`), or null when nothing is under way. */
export function readyLine(r: ReadyState | null | undefined): string | null {
  if (!r) return null;
  if (r.evidence === "refreshing") return "Finding the sources for this question; a draft follows.";
  if (r.draft === "refreshing") return "Writing a draft from the sources found.";
  if (r.evidence === "failed") return "The sources could not be found this time.";
  if (r.draft === "not_written") return r.draft_note ? `No draft was written: ${r.draft_note}.` : "No draft was written.";
  if (r.draft === "ready" && !r.draft_fresh) return "The draft answers an earlier wording of the question.";
  return null;
}

/** Who wrote a draft, in plain words, and whether it used paid credit (owner, 26 Nov 2026: "say which one writes it"). */
export function draftAuthor(d: { system?: boolean | null; model?: string | null } | null | undefined): string | null {
  if (!d) return null;
  if (d.system === false) return "Written by an engineer.";
  if (d.system !== true) return null;
  // builder A: the automatic draft is always the local model and needs no credit; a Claude draft is only an engineer's own request
  if (/claude/i.test(d.model ?? "")) return "Written by Claude from the sources found (uses paid credit).";
  return `Written by ${d.model ? `${d.model}, the AI on this computer,` : "the AI on this computer"} from the sources found (no credit needed).`;
}

export interface SourceRow {
  id: string;
  evidence_state: string;
  supersession_state: string;
  for_current_question?: boolean | null;
}

/** THE ONE-CLICK SOURCE DECISION (lead-4, 26 Nov 2026, on the owner's "approve once"): which sources a press of "Keep the sources the
 *  draft cites, reject the others" would keep and which it would reject. Only the CURRENT wording's sources the system found and nobody
 *  has decided ("proposed"); never one found for an earlier wording, never one flagged for review (needs review, conflicting, ambiguous),
 *  never one already decided. Each decision is the same call as its own Keep or Reject button, so every one stays changeable. */
export function citedSplit(
  evidence: SourceRow[] | null | undefined,
  citationsJson: string | null | undefined,
): { keep: SourceRow[]; reject: SourceRow[] } {
  let cited: Set<string>;
  try {
    cited = new Set((JSON.parse(citationsJson || "[]") as { evidence_id?: string }[]).map((c) => c.evidence_id ?? "").filter(Boolean));
  } catch {
    cited = new Set();
  }
  const open = currentSources(evidence).filter((e) => e.evidence_state === "proposed");
  return { keep: open.filter((e) => cited.has(e.id)), reject: open.filter((e) => !cited.has(e.id)) };
}

// ---------------------------------------------------------------------- the page read in ten seconds (owner, 26 Nov 2026 22:41)

/** The subject's topic: the short title, else the subject, without mail prefixes and a trailing "Clarification". */
function topicOf(q: { title_short?: string | null; subject?: string | null }): string {
  return (q.title_short || q.subject || "")
    .replace(/^\s*((fw|fwd|re)\s*:\s*)+/i, "")
    .replace(/[\s_-]*clarification\s*$/i, "")
    .trim();
}

/** ONE plain sentence on top: who asks, how many things, about what ("The contractor asks for 6 items about MP fuel gas tie-in
 *  details."). The count is the numbered requests of the ask the page shows (one when it is a single question). */
export function queryHeadline(q: { contractor_name?: string | null; title_short?: string | null; subject?: string | null }, askText: string): string {
  const who = (q.contractor_name ?? "").trim() || "The contractor";
  const n = readableLines(askText, []).filter((l) => l.kind === "item").length;
  const topic = topicOf(q);
  const what = n > 1 ? `for ${n} items` : "one question";
  return `${who} asks ${what}${topic ? ` about ${topic}` : ""}.`;
}

/** The status in everyday words (owner: "DRAFTING - NORMAL means nothing to me"); a priority is said only when it is not normal. */
export function plainStatus(status: string, priority?: string | null): string {
  const word: Record<string, string> = {
    received: "In progress", triage: "In progress", drafting: "In progress", awaiting_review: "In progress: waiting for your approval",
    changes_requested: "In progress: the reply is being changed", approved: "Approved, not sent yet", send_pending: "Being sent",
    sent: "Sent", awaiting_confirmation: "Sent, waiting for the contractor to confirm", resolved: "Closed",
    duplicate: "Closed as a duplicate", cancelled: "Cancelled", failed: "Stopped by an error",
  };
  const p = (priority ?? "").toLowerCase();
  return `${word[status] ?? status.replaceAll("_", " ")}${p && p !== "normal" ? ` · ${p} priority` : ""}`;
}

export type StepState = "done" | "working" | "todo";
export interface Step { label: string; state: StepState }

/** Three steps and the approval, each with its own mark (owner: instead of the dense status sentence). */
export function querySteps(q: {
  status: string;
  drafts?: unknown[] | null;
  evidence?: { for_current_question?: boolean | null }[] | null;
  ready?: { evidence?: string | null; draft?: string | null } | null;
}, askText: string): Step[] {
  const approved = ["approved", "send_pending", "sent", "awaiting_confirmation", "resolved"].includes(q.status);
  const sources = currentSources(q.evidence).length;
  return [
    { label: "Question found", state: askText.trim() ? "done" : "todo" },
    { label: "Sources found", state: q.ready?.evidence === "refreshing" ? "working" : sources ? "done" : "todo" },
    { label: "Reply written", state: q.ready?.draft === "refreshing" ? "working" : q.drafts?.length ? "done" : "todo" },
    { label: "Approved", state: approved ? "done" : "todo" },
  ];
}

/** "file, page 1" said once under the list when every request was found in the same place (owner: it repeated under each item). */
export function sharedSource(lines: ReadableLine[]): string | null {
  const items = lines.filter((l) => l.kind === "item");
  if (items.length < 2 || items.some((l) => !l.source)) return null;
  return items.every((l) => l.source === items[0].source) ? items[0].source ?? null : null;
}

/** The short phrase that says what is asked, to be shown in bold, and the rest: up to a colon or the first comma when that part is
 *  short, else the first seven words. */
export function boldSplit(text: string): [string, string] {
  const colon = text.indexOf(":");
  if (colon > 0 && colon <= 80) return [text.slice(0, colon + 1), text.slice(colon + 1)];
  const comma = text.indexOf(", ");
  if (comma > 0 && comma <= 60) return [text.slice(0, comma + 1), text.slice(comma + 1)];
  const words = text.split(" ");
  return words.length <= 9 ? [text, ""] : [words.slice(0, 7).join(" "), ` ${words.slice(7).join(" ")}`];
}

/** A mark from the server in everyday words (the E3 word map): "the local model" is "the AI on this computer", a passage is a source. */
export function plainMark(mark: string): string {
  return mark
    .replace(/\bthe local (drafting )?model\b/gi, "the AI on this computer")
    .replace(/\bpassages\b/g, "sources")
    .replace(/\bpassage\b/g, "source");
}

// ------------------------------------------------------------------ the lower half: the decision, the quote, who handles it (owner, 27 Nov 2026 00:02)

/** At most this many characters of a source passage show before "Show the whole passage" (about three lines at laptop width). */
export const QUOTE_SHORT = 260;

/** The first part of a long passage, cut at a word, and whether it was cut (rule: no cut without a visible mark and the full text beside it). */
export function shortQuote(text: string, max = QUOTE_SHORT): { short: string; cut: boolean } {
  const plain = (text ?? "").replace(/\s+/g, " ").trim();
  if (plain.length <= max) return { short: plain, cut: false };
  const at = plain.lastIndexOf(" ", max);
  return { short: plain.slice(0, at > max * 0.6 ? at : max).trimEnd(), cut: true };
}

const STOP = new Set(["about", "above", "after", "again", "being", "below", "between", "could", "every", "following", "from", "have", "into",
  "other", "please", "provide", "shall", "should", "since", "that", "their", "there", "these", "this", "those", "under", "which", "while",
  "with", "would", "where", "what", "when", "confirm", "clarify", "contractor", "required", "requirement", "kindly"]);

/** The words of the ask that are worth marking in a passage: five letters or more, not common words, at most 12. */
export function askWords(ask: string): string[] {
  const seen = new Set<string>();
  for (const w of (ask ?? "").toLowerCase().match(/[a-z][a-z0-9-]{4,}/g) ?? []) if (!STOP.has(w)) seen.add(w);
  return [...seen].slice(0, 12);
}

/** The passage in pieces, each piece marked when it is one of the ask's words (whole words, any case). */
export function markedPieces(text: string, words: string[]): Array<{ text: string; hit: boolean }> {
  if (!words.length || !text) return [{ text, hit: false }];
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
  const out: Array<{ text: string; hit: boolean }> = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index), hit: false });
    out.push({ text: m[0], hit: true });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hit: false });
  return out;
}

/** The decision under the reply, in the words a reviewer would say, and the one line of what happens next. */
export type Decision = { kind: "decide" | "no_role" | "none"; hint: string };
export function decisionFor(q: { status: string; can_review?: boolean; drafts?: unknown[] | null }): Decision {
  if (q.status !== "awaiting_review" || !q.drafts?.length) return { kind: "none", hint: "" };
  if (!q.can_review) return { kind: "no_role", hint: "Approving needs the technical-query reviewer role. An administrator can give it to you under Administration." };
  return { kind: "decide", hint: "Approve records that you checked this reply. Nothing is sent: you then download it as a Word file and send it yourself." };
}

/** Why the Word reply cannot be downloaded yet, or null when it can (the server serves it once a reply is approved). */
export function wordReplyWhyNot(q: { status: string; drafts?: unknown[] | null }): string | null {
  if (!q.drafts?.length) return "There is no reply yet.";
  if (!["approved", "sent", "awaiting_confirmation", "resolved"].includes(q.status)) return "Available once the reply is approved.";
  return null;
}

/** "From the subject: contractor code ABC, discipline PRO" beside empty fields, so they are never blank with no hint; null when nothing was read. */
export function fromSubjectHint(q: { contractor_code?: string | null; discipline_code?: string | null }): string | null {
  const parts = [q.contractor_code ? `contractor code ${q.contractor_code}` : "", q.discipline_code ? `discipline ${q.discipline_code}` : ""].filter(Boolean);
  return parts.length ? `From the subject: ${parts.join(", ")}. Add a rule under “Rules for who it goes to” and every query with this code fills itself.` : null;
}

/** The decisions so far in plain words; empty: "Nobody has approved this yet." */
export function historyWords(decisions: Array<{ decision: string; comment?: string | null }> | null | undefined): string[] {
  const words: Record<string, string> = { approve: "Approved", approved: "Approved", request_changes: "Sent back", changes_requested: "Sent back", reject: "Rejected" };
  if (!decisions?.length) return ["Nobody has approved this yet."];
  return decisions.map((d) => `${words[d.decision] ?? d.decision}${d.comment ? `: ${d.comment}` : ""}`);
}

/** A list row's second line in plain words (F's walk, 27 Nov 2026: "awaiting_review · unassigned" on every row): the contractor when set,
 *  where the query stands, and who has it by name. A missing contractor is said once above the list, not on each row. */
export function rowLine(item: { contractor_name?: string | null; status: string; assignee_user_id?: string | null },
  people: Array<{ id: string; display_name: string }> = []): string {
  const word: Record<string, string> = {
    received: "In progress", triage: "In progress", drafting: "In progress", awaiting_review: "Waiting for approval",
    changes_requested: "Being changed", approved: "Approved, not sent", send_pending: "Being sent", sent: "Sent",
    awaiting_confirmation: "Sent, waiting for confirmation", resolved: "Closed", duplicate: "Closed as a duplicate", cancelled: "Cancelled",
    failed: "Stopped by an error",
  };
  const who = item.assignee_user_id ? `with ${people.find((p) => p.id === item.assignee_user_id)?.display_name ?? "a person"}` : "nobody assigned";
  return [item.contractor_name || "", word[item.status] ?? item.status.replaceAll("_", " "), who].filter(Boolean).join(" · ");
}

/** A passage's match in plain words (owner's live walk, 27 Nov 2026 01:15: "8 of 22 key words" reads as machine talk); the counts stay
 *  one hover away, so nothing is hidden. Null when the passage carries no count. */
export function matchWords(e: { match_count?: number | null; match_terms?: number | null; match_ok?: number | null }): { words: string; counts: string } | null {
  if (!e.match_terms) return null;
  const counts = `${e.match_count ?? 0} of ${e.match_terms} of the question's key words`;
  const ok = e.match_ok ?? ((e.match_count ?? 0) * 2 >= e.match_terms ? 1 : 0);
  return { words: ok ? "Shares many words with the question" : "Weak match: this quote shares few words with the question", counts };
}

/** While the sources or the reply are being prepared again, the reply on screen is the OLD one (owner's live walk, 27 Nov 2026 01:15). */
export function replyBeingRewritten(ready: { evidence?: string; draft?: string } | null | undefined): boolean {
  return ready?.evidence === "refreshing" || ready?.draft === "refreshing";
}
