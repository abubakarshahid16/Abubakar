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
  return (q.evidence ?? []).some((e) => (e.match_terms ?? 0) > QUESTION_KEY_WORDS_MAX);
}

/** HONEST MARKS INSTEAD OF GATES (owner, 26 Nov 2026 21:36): one plain line per thing the system is unsure of, shown on the item it is
 *  about; nothing here blocks the page. `question` marks sit under the question, `evidence` marks above the sources. */
export function honestMarks(q: MarksSource, text: string): { question: string[]; evidence: string[] } {
  const question: string[] = [];
  const left = notInText(text, q.proposed_questions);
  if (left.length) question.push(`${left.length} more line${left.length === 1 ? " was" : "s were"} found on the form and ${left.length === 1 ? "is" : "are"} not in the list: one may be a request. Check below.`);
  const evidence: string[] = [];
  const running = q.evidence_job?.state === "queued" || q.evidence_job?.state === "running";
  const all = q.evidence ?? [];
  if (!running && all.length === 0) evidence.push("No source was found for this question yet: the answer has nothing to stand on.");
  const scored = all.filter((e) => (e.match_terms ?? 0) > 0);
  if (staleSources(q)) {
    evidence.push("These sources were found for the whole text of the mail, not for the question: find them again for the question.");
  } else if (scored.length) {
    const best = scored.reduce((a, b) => ((b.match_count ?? 0) / (b.match_terms ?? 1) > (a.match_count ?? 0) / (a.match_terms ?? 1) ? b : a));
    if ((best.match_count ?? 0) / (best.match_terms ?? 1) < 0.5) {
      evidence.push(`The sources found match the question only weakly (the best holds ${best.match_count ?? 0} of ${best.match_terms} key words): read them before relying on the answer.`);
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
