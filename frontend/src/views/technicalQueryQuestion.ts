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

/** A question kept before 27 Nov 2026 carries the old "[cut here: ...]" mark: shown as the plain sentence the server now writes. */
const OLD_CUT = /(?:\s+[^\s.?!,;:)\]]+)?\s*\[cut here: [^\]]*\]/g; // the word before an old mark may be cut mid-word: it goes too
const CUT_WORDS = "\u2026 The rest of the question is in the email files.";

/** The question text as the page shows it: the lead-in, then each numbered request with where it was found. */
export function readableLines(text: string, found: FoundQuestion[] | null | undefined): ReadableLine[] {
  const where = new Map<string, string>();
  for (const f of found ?? []) {
    const key = f.question.trim();
    if (key && !where.has(key)) where.set(key, [f.filename, f.page != null ? `page ${f.page}` : null].filter(Boolean).join(", "));
  }
  const out: ReadableLine[] = [];
  // a request that WRAPS onto the next line belongs to its item (the owner's regression query, 27 Nov 2026: item 3 ended "... before Mechanical" and its
  // last word "Completion?" was shown as a lead-in ABOVE the list); a blank line ends an item, as on the server (items_of)
  let inItem = false;
  for (const raw of text.split("\n")) {
    const line = raw.replace(OLD_CUT, CUT_WORDS).trim();
    if (!line) {
      inItem = false;
      continue;
    }
    const m = NUMBERED.exec(line);
    const last = out[out.length - 1];
    if (!m && inItem && last?.kind === "item") {
      last.text = `${last.text} ${line}`;
      continue;
    }
    if (!m) {
      out.push({ kind: "lead", text: line, source: where.get(line) || undefined });
      inItem = false;
      continue;
    }
    // a form's own list marker ("- Matching line list") is not part of the request: shown without it, its source still found
    const shown = m[2].replace(/^[-–•*]\s+/, "");
    out.push({ kind: "item", n: Number(m[1]), text: shown, source: where.get(m[2]) || where.get(shown) || undefined });
    inItem = true;
  }
  return out;
}

/** A long lead paragraph shown as short paragraphs of whole sentences (H's audit #51, 27 Nov 2026: a form's question section with no list
 *  read as one dense wall). Display only: the words and their order never change. A paragraph up to LEAD_PARA chars stays whole; a sentence
 *  ends at ". ", "? " or "! " before a capital or an opening bracket, never after a short abbreviation ("e.g.", "No.", "Rev."), an initial or
 *  a bare one- or two-digit number (a list marker "1."); an inline bullet ("• 1.5 litres ...") is a line of its own. */
export const LEAD_PARA = 320;
const NOT_AN_END = /(?:\b(?:e\.g|i\.e|etc|no|nos|fig|figs|rev|ref|refs|sec|cl|approx|min|max|vs|incl|para|vol|pp|ch|dwg|doc|mr|ms|dr)|(?:^|[^A-Za-z0-9-])[A-Za-z]|(?:^|[\s(])\d{1,2})\.$/i;
const BULLET = /^[•▪◦]\s/;
export function leadParagraphs(text: string): string[] {
  if (text.length <= LEAD_PARA) return [text];
  const pieces: string[] = [];
  let start = 0;
  const end = /(?:[.?!]["'”’)]?\s+(?=[A-Z(“"•▪◦])|[:;]?\s+(?=[•▪◦]\s))/g;
  for (let m = end.exec(text); m; m = end.exec(text)) {
    const upTo = m.index + m[0].trimEnd().length;
    if (upTo <= start) continue;
    if (/\.$/.test(text.slice(0, upTo)) && NOT_AN_END.test(text.slice(Math.max(0, upTo - 8), upTo))) continue;
    pieces.push(text.slice(start, upTo));
    start = m.index + m[0].length;
  }
  pieces.push(text.slice(start));
  const out: string[] = [];
  let lastBullet = false;
  for (const piece of pieces) {
    const bullet = BULLET.test(piece);
    const last = out[out.length - 1];
    if (last !== undefined && !bullet && !lastBullet && last.length + 1 + piece.length <= LEAD_PARA) out[out.length - 1] = `${last} ${piece}`;
    else out.push(piece);
    lastBullet = bullet;
  }
  return out;
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
  if (!running && all.length === 0) evidence.push("No source found for this question yet. The reply has nothing to rest on.");
  const scored = all.filter((e) => (e.match_terms ?? 0) > 0);
  if (staleSources(q)) {
    evidence.push("Find the sources again: these were found for the whole email, not for the question.");
  } else if (scored.length) {
    const best = scored.reduce((a, b) => ((b.match_count ?? 0) / (b.match_terms ?? 1) > (a.match_count ?? 0) / (a.match_terms ?? 1) ? b : a));
    if ((best.match_count ?? 0) / (best.match_terms ?? 1) < 0.5) {
      evidence.push("Weak match: the sources share few words with the question. Read them before you rely on the reply.");
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
  if (r.evidence === "refreshing") return "Finding the sources for this question. The reply follows.";
  if (r.draft === "refreshing") return "Writing the reply from the sources found.";
  if (r.evidence === "failed") return "The sources could not be found. Try Find the sources again.";
  if (r.draft === "not_written") return r.draft_note ? `No reply was written: ${r.draft_note}.` : "No reply was written.";
  if (r.draft === "ready" && !r.draft_fresh) return "The reply answers an earlier wording of the question.";
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
): { keep: SourceRow[]; reject: SourceRow[]; citesNone: boolean } {
  let cited: Set<string>;
  try {
    cited = new Set((JSON.parse(citationsJson || "[]") as { evidence_id?: string }[]).map((c) => c.evidence_id ?? "").filter(Boolean));
  } catch {
    cited = new Set();
  }
  // NEVER REJECT EVERYTHING (H's review of the owner's file, Q3: a reply citing 0 sources offered to reject all 12): when the reply cites
  // none of this question's sources (no citation, or only sources of an earlier search), nothing is kept or rejected by the bulk step
  if (!currentSources(evidence).some((e) => cited.has(e.id))) return { keep: [], reject: [], citesNone: true };
  const open = currentSources(evidence).filter((e) => e.evidence_state === "proposed");
  return { keep: open.filter((e) => cited.has(e.id)), reject: open.filter((e) => !cited.has(e.id)), citesNone: false };
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
    received: "In progress", triage: "In progress", drafting: "In progress", awaiting_review: "Waiting for your approval",
    changes_requested: "The reply is being changed", approved: "Approved, not sent yet", send_pending: "Being sent",
    sent: "Sent", awaiting_confirmation: "Sent, waiting for the contractor to confirm", resolved: "Closed",
    duplicate: "Closed as a duplicate", cancelled: "Cancelled", failed: "Stopped by an error",
  };
  const p = (priority ?? "").toLowerCase();
  return `${word[status] ?? status.replaceAll("_", " ")}${p && p !== "normal" ? ` · ${p} priority` : ""}`;
}

export type StepState = "done" | "working" | "todo" | "stale" | "warn";
export interface Step { label: string; state: StepState }

/** Three steps and the approval, each with its own mark (owner: instead of the dense status sentence). */
export function querySteps(q: {
  status: string;
  drafts?: Array<{ citations_json?: string | null }> | null;
  evidence?: { for_current_question?: boolean | null }[] | null;
  ready?: { evidence?: string | null; draft?: string | null; draft_fresh?: boolean | null } | null;
}, askText: string): Step[] {
  const approved = ["approved", "send_pending", "sent", "awaiting_confirmation", "resolved"].includes(q.status);
  const sources = currentSources(q.evidence).length;
  return [
    { label: "Question found", state: askText.trim() ? "done" : "todo" },
    { label: "Sources found", state: q.ready?.evidence === "refreshing" ? "working" : sources ? "done" : "todo" },
    q.ready?.draft === "refreshing" ? { label: "Reply written", state: "working" }
      : !q.drafts?.length ? { label: "Reply written", state: "todo" }
      // ticked only when the reply answers the CURRENT question (H's review of the owner's file, Q4): a reply to an earlier wording is said so
      : q.ready?.draft_fresh === false ? { label: "Reply written", state: "stale" }
      // a reply that cites no source is written, but not ready: never a plain tick (F's walk, 27 Nov 2026)
      : citesNoSource(q.drafts[q.drafts.length - 1]) ? { label: "Reply written: uses no source yet", state: "warn" }
      : { label: "Reply written", state: "done" },
    { label: "Approved", state: approved ? "done" : "todo" },
  ];
}

/** The latest reply cites no source: its citations are empty (an unreadable record counts as none). */
function citesNoSource(draft: { citations_json?: string | null } | undefined): boolean {
  try {
    const cited = JSON.parse(draft?.citations_json || "[]");
    return !Array.isArray(cited) || cited.length === 0;
  } catch {
    return true;
  }
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
  if (!q.can_review) return { kind: "no_role", hint: "Approving needs the query reviewer role. Ask an administrator to give it to you." };
  return { kind: "decide", hint: "Approve means the reply is ready to send. The app does not send it. Download it as a Word file and send it yourself." };
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
  return parts.length ? `From the subject: ${parts.join(", ")}. Under More, “Rules for who it goes to”, add a rule once. Every query with this code then gets it.` : null;
}

/** The decisions so far in plain words; empty: "Nobody has approved this yet." */
export function historyWords(decisions: Array<{ decision: string; comment?: string | null }> | null | undefined): string[] {
  const words: Record<string, string> = { approve: "Approved", approved: "Approved", request_changes: "Sent back", changes_requested: "Sent back", reject: "Rejected" };
  if (!decisions?.length) return ["Nobody has approved this yet."];
  return decisions.map((d) => `${words[d.decision] ?? d.decision}${d.comment ? `: ${d.comment}` : ""}`);
}

// ------------------------------------------------------------------ the list page (owner, 27 Nov 2026: "the same pattern as a tidy list")

/** The short tag a query is known by ("CFC-7"), from the number read in its subject, exactly as written there (review of #1938: leading
 *  zeros are kept, so CFC-7 and CFC-007 never look like one query); null when the subject carries none. */
export function queryTag(q: { ref_type?: string | null; ref_number?: string | null }): string | null {
  if (!q.ref_type || !q.ref_number) return null;
  return `${q.ref_type}-${q.ref_number}`;
}

/** One status chip per row, in four plain words (and the closed ones), with its tone. */
export type ChipTone = "neutral" | "wait" | "done" | "problem";
export function statusChip(status: string): { words: string; tone: ChipTone } {
  if (status === "awaiting_review") return { words: "Waiting for approval", tone: "wait" };
  if (["approved", "send_pending", "sent", "awaiting_confirmation"].includes(status)) return { words: status === "approved" ? "Approved" : "Sent", tone: "done" };
  if (["resolved", "duplicate", "cancelled"].includes(status)) return { words: status === "resolved" ? "Closed" : status === "duplicate" ? "Duplicate" : "Cancelled", tone: "neutral" };
  if (status === "failed") return { words: "Stopped by an error", tone: "problem" };
  return { words: "In progress", tone: "neutral" };
}

/** The short amber chips of a row; the full sentence goes on hover (and inside the query). */
export function problemChips(q: { needs_person?: number | null; ref_type?: string | null; contractor_name?: string | null; contractor_code?: string | null }): Array<{ words: string; why: string }> {
  const out: Array<{ words: string; why: string }> = [];
  if (q.needs_person || !q.ref_type) out.push({ words: "No query number", why: "Check which query this is. The subject has no full TQ or CFC number." });
  // the code printed in the reference number, when there is one, is named (never a guessed contractor; lead-4, 26 Nov 2026)
  if (!q.contractor_name) out.push({ words: "No contractor", why: q.contractor_code
    ? `Under More, “Rules for who it goes to”, say which contractor the code ${q.contractor_code} is. Every query with this code then gets it.`
    : "Under More, “Rules for who it goes to”, add this contractor's code once. Every query with this code then gets it." });
  return out;
}

/** "4 min ago", "3 h ago", "on 25 Nov"; null when never checked. */
export function agoWords(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const min = Math.max(0, Math.round((now - t) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  if (min < 24 * 60) return `${Math.round(min / 60)} h ago`;
  return `on ${new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
}

/** The mailbox in one small chip: connected (with when it was last checked), importing, waiting for a label, not connected, or a problem. */
export function mailboxChip(
  mailboxes: Array<{ connection_state: string; last_checked_at?: string | null; import_job?: { state: string; kind: string; done: number; total: number; error?: string | null } | null }>,
  canManage: boolean, now = Date.now(),
): { words: string; tone: "ok" | "wait" | "problem" } | null {
  if (mailboxes.some((m) => m.connection_state === "error" || m.connection_state === "revoked")) return { words: "Mailbox problem", tone: "problem" };
  const active = mailboxes.find((m) => m.connection_state === "active");
  if (active) {
    const job = active.import_job;
    if (job && (job.state === "failed" || (job.state === "queued" && job.error))) return { words: "Mailbox problem", tone: "problem" };
    if (job && job.state === "running" && job.kind === "import") return { words: `Mailbox: importing, ${job.done} of ${job.total} read`, tone: "wait" };
    const ago = agoWords(active.last_checked_at, now);
    return { words: ago ? `Mailbox connected · checked ${ago}` : "Mailbox connected · not checked yet", tone: "ok" };
  }
  if (mailboxes.length) return { words: "Mailbox needs a label", tone: "wait" };
  return canManage ? { words: "No mailbox connected", tone: "wait" } : null;
}

/** The count line, which is also a filter: only the states that exist right now, each with its number. */
export type QuickView = "waiting" | "progress" | "person" | "approved" | "sent" | "closed" | "stopped";
/** Each bucket holds exactly the rows whose status chip says its word (review of #1938: "2 approved" must never show a row chipped "Sent"). */
const BUCKET_WORDS: Record<Exclude<QuickView, "person">, string[]> = {
  waiting: ["Waiting for approval"], progress: ["In progress"], approved: ["Approved"], sent: ["Sent"], closed: ["Closed", "Duplicate", "Cancelled"],
  stopped: ["Stopped by an error"],
};
export function quickMatch(view: QuickView, q: { status: string; needs_person?: number | null; ref_type?: string | null }): boolean {
  if (view === "person") return Boolean(q.needs_person) || !q.ref_type;
  return BUCKET_WORDS[view].includes(statusChip(q.status).words);
}
/** The count line (owner's live walk, 27 Nov 2026: "34 queries: 16 waiting, 18 in progress, 1 needs a person" made 35). `parts` are the
 *  status buckets: every query is in exactly one, so they always add up to the total. `ofThem` is the queries among those that need a
 *  person (a problem, not a status): said apart, as "N of them", so it is never added to the status counts. */
export function countLine(items: Array<{ status: string; needs_person?: number | null; ref_type?: string | null }>): {
  total: number; parts: Array<{ view: QuickView; n: number; words: string }>; ofThem: { view: QuickView; n: number; words: string } | null;
} {
  const n = (v: QuickView) => items.filter((q) => quickMatch(v, q)).length;
  const parts: Array<{ view: QuickView; n: number; words: string }> = [
    { view: "waiting", n: n("waiting"), words: "waiting for approval" },
    { view: "progress", n: n("progress"), words: "in progress" },
    { view: "approved", n: n("approved"), words: "approved" },
    { view: "sent", n: n("sent"), words: "sent" },
    { view: "closed", n: n("closed"), words: "closed" },
    { view: "stopped", n: n("stopped"), words: "stopped by an error" },
  ];
  const person = n("person");
  return { total: items.length, parts: parts.filter((p) => p.n > 0), ofThem: person ? { view: "person", n: person, words: person === 1 ? "needs a query number" : "need a query number" } : null };
  // the owner's words (written order, 27 Nov 2026 10:59): these are the queries whose subject has no full TQ or CFC number; the line
  // is the one place it is said, and clicking it lists exactly them (the rows no longer carry a "No query number" chip)
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

/** The sources grouped under the request they were found for (builder A's per-item search, 27 Nov 2026: `item_no`, 1-based into
 *  `ready.items`; null = found for the whole request). No items, or no source carries a number: one group with no heading, as before.
 *  A request with no source keeps its heading and says so; a number past the list joins "For the whole request". */
export interface SourceGroup<T> { title: string | null; rows: T[] }
export function groupByItem<T extends { item_no?: number | null }>(rows: T[], items: string[] | null | undefined): SourceGroup<T>[] {
  const list = items ?? [];
  if (!list.length || !rows.some((r) => typeof r.item_no === "number")) return [{ title: null, rows }];
  const groups: SourceGroup<T>[] = list.map((item, i) => ({ title: `${i + 1}. ${item}`, rows: rows.filter((r) => r.item_no === i + 1) }));
  const whole = rows.filter((r) => typeof r.item_no !== "number" || r.item_no < 1 || r.item_no > list.length);
  if (whole.length) groups.push({ title: "For the whole request", rows: whole });
  return groups;
}
