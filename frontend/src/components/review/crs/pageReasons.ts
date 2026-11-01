/**
 * Order 121 Part B: why a page was not read, in plain words.
 *
 * The readers record their own wording for an unread page ("vision reader:
 * page kind 'cover' (the model's word, unverified); 0 field(s) proposed...",
 * "the AI reader timed out on this page", "recognition failed: ..."). The
 * engineer gets one short clause; the reader's wording stays under
 * "Technical details". A page kind is the model's guess and is said as one.
 * These patterns read the app's OWN reader wording, never a document's.
 */

/** #1550: reasons that mean NO reading came back for the page (#1473's kinds):
 *  such a page "was not read", never "not fully read". */
const NO_READING = [
  /set aside by a rule although it holds clause text/i,
  /excluded from the index on purpose/i,
  /^image with no reading$/i,
  /^blank page$/i,
];

/** The page kinds the chunker's page rules name, in plain words. */
const KIND_WORDS: Record<string, string> = { toc: "table of contents" };

const PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/page kind '([^']+)'/i, (m) => `it looks like a ${m[1]} page (the computer's guess)`],
  [/timed out/i, () => "the reader ran out of time on it"],
  [/reader was unavailable/i, () => "the reader was not available"],
  [/cut off before this page/i, () => "the reader stopped before it reached this page"],
  [/reader was stopped/i, () => "the reading was stopped before this page"],
  [/recognition failed/i, () => "the scanned text on it could not be recognised"],
  [/vision reader refused/i, () => "the picture reader declined to read it"],
  [/vision reader not run/i, () => "the picture reader could not look at it"],
  [/a reader failed on this page/i, () => "a reader failed on it"],
  [/never saw it|no retrievable chunk/i, () => "no text could be taken from it"],
  [/recorded no result for this document/i, () => "no values have been read from this document yet"],
  [/no field was read from this page/i, () => "no values were found on it"],
  // #1550: the plain words `page_not_read.unread_page_words` stores (#1473).
  // The not-excused one first: it names a rule too, and is never an excuse.
  [/set aside by a rule although it holds clause text/i,
    () => "a rule set it aside although it holds clause text, so it still needs reading"],
  [/excluded from the index on purpose \(rule page_classified_([a-z_]+)\)/i,
    (m) => `it was left out on purpose as a ${KIND_WORDS[m[1]] ?? m[1].replace(/_/g, " ")} page`],
  [/excluded from the index on purpose/i, () => "it was left out on purpose"],
  [/^image with no reading$/i, () => "it is a picture and no reading came back from it"],
  [/^blank page$/i, () => "it is blank"],
];

/** The plain clause for a reader's reason, or "" when none fits (the line
 *  then says only that the page was not fully read). */
export function plainPageReason(reason: string | null | undefined): string {
  if (!reason) return "";
  for (const [pattern, words] of PATTERNS) {
    const m = reason.match(pattern);
    if (m) return words(m);
  }
  return "";
}

/** "Page 1 was not fully read: it looks like a cover page (the computer's guess)." */
export function unreadPageLine(page: number, reason: string | null | undefined): string {
  const why = plainPageReason(reason);
  const how = reason && NO_READING.some((p) => p.test(reason)) ? "was not read" : "was not fully read";
  return why ? `Page ${page} ${how}: ${why}.` : `Page ${page} ${how}.`;
}
