/**
 * THE FIXED COLOUR OF EVERY STATUS WORD (owner, 27 Nov 2026 03:30, C: "Waiting for approval" boxed and "In progress" plain grey on one
 * list). A chip's colour comes from its WORD, here, and nowhere else: the same word is the same colour on every page.
 *   done  (green): finished as hoped      check (amber): needs a person's look      late (red): gone wrong or overdue
 *   info  (blue):  the system is working  plain (grey): anything else, said as it is
 */
export type KitTone = "done" | "check" | "late" | "info" | "plain";

const WORDS: Record<KitTone, string[]> = {
  done: ["approved", "signed off", "done", "closed", "sent", "ready", "active", "connected", "mailbox connected", "read", "kept", "answered", "held"],
  check: ["waiting for approval", "waiting for you", "needs a person", "not signed off", "review ready", "to check", "no contractor",
    "no query number", "being changed", "needs a label", "mailbox needs a label", "no mailbox connected", "not held", "superseded", "changed since",
    "ai, to be checked"],
  late: ["late", "overdue", "failed", "stopped by an error", "mailbox problem", "rejected", "not read", "blocked"],
  info: ["in progress", "running", "queued", "importing", "being read", "being rewritten", "checking"],
  plain: ["duplicate", "cancelled", "draft", "not started"],
};

const TONE_OF = new Map<string, KitTone>(Object.entries(WORDS).flatMap(([tone, words]) => words.map((w) => [w, tone as KitTone])));

/** The tone of a status word (case and spacing aside); a word not listed is plain grey, never guessed. */
export function toneOfWord(word: string): KitTone {
  return TONE_OF.get(word.trim().toLowerCase().replace(/\s+/g, " ")) ?? "plain";
}

/** Every listed word, by tone (for the kit's preview and its tests). */
export const KIT_WORDS: Readonly<Record<KitTone, readonly string[]>> = WORDS;
