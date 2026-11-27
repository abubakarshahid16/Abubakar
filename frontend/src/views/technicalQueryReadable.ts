/** The query page made readable (owner's Part 3, item 2, 27 Nov 2026): LOOK ONLY. Nothing here changes what the app decides or says about
 *  the evidence; it sorts the same marks into place and lays the same reply text out as a list. */

/** The marks that say how the query was made (who wrote the question and the reply): folded under "How this was made". */
const MADE = [/^The question was proposed by the system/, /^The question is an engineer's wording/, /^Written by the (?:AI on this computer|local model)/];
/** The server's revision line ("The revision of A, B is not confirmed yet (Documents, Details, Save metadata)."): shown as one plain
 *  sentence per document beside the sources instead, when the page can name those documents itself. */
export const REVISION_MARK = /^The revision of .+ is not confirmed yet/;

export function splitMarks(marks: string[], revisionShownBySource: boolean): { made: string[]; shown: string[] } {
  const made: string[] = [];
  const shown: string[] = [];
  for (const mark of marks) {
    if (MADE.some((re) => re.test(mark))) made.push(mark);
    else if (!(revisionShownBySource && REVISION_MARK.test(mark))) shown.push(mark);
  }
  return { made, shown };
}

export type ReplyBlock = { kind: "para"; text: string } | { kind: "bullet"; text: string } | { kind: "item"; n: number; title: string; body: string[] };

/** A bullet line ("* text", "- text", "\u2022 text"), as older replies wrote them (Part 3 picture review); never "**bold**". */
export const BULLET = /^[*\-\u2022]\s+(\S(?:.*\S)?)\s*$/;
export function bulletText(line: string): string | null {
  const m = BULLET.exec(line);
  return m ? m[1] : null;
}

// "1. Title", "**2. Title**", "3) Title", "1. **Title**": a numbered request's answer starts
const ITEM = /^(?:\*\*)?\s*(\d{1,2})[.)]\s+(.*\S)\s*$/;

/** The reply as blocks: a lead paragraph, each numbered answer (its first line the title, the lines under it the body) and a closing
 *  paragraph after the last answer (the set cost / schedule sentence, for one). Every word is kept, in order; only "**" marks go. */
export function replyBlocks(answer: string): ReplyBlock[] {
  const paragraphs = (answer ?? "").replace(/\r/g, "").split(/\n\s*\n/).map((p) => p.split("\n").map((l) => l.trim()).filter(Boolean)).filter((p) => p.length);
  const lastItemParagraph = paragraphs.reduce((last, lines, i) => (lines.some((l) => ITEM.test(l)) ? i : last), -1);
  const blocks: ReplyBlock[] = [];
  paragraphs.forEach((lines, p) => {
    lines.forEach((line, i) => {
      const m = ITEM.exec(line);
      const last = blocks[blocks.length - 1];
      if (m) blocks.push({ kind: "item", n: Number(m[1]), title: m[2], body: [] });
      // a line of the same paragraph, a paragraph before the last answer, or the first body under a heading-only answer ("**2. Title**",
      // no full stop): the answer's own. A one-sentence answer ("3. Not found.") keeps a later paragraph as the closing one.
      else if (last?.kind === "item" && (i > 0 || p <= lastItemParagraph || (last.body.length === 0 && !/[.?!]["')\]]?$/.test(plainTitle(last.title))))) last.body.push(line);
      else if (bulletText(line) !== null) blocks.push({ kind: "bullet", text: bulletText(line)! });
      else blocks.push({ kind: "para", text: line });
    });
  });
  return blocks;
}

/** Text with its "**bold**" marks as pieces; a stray "**" left over is dropped. */
export function boldPieces(text: string): Array<{ text: string; bold: boolean }> {
  // a stray single "*" (an older reply's emphasis) goes too; the words stay
  return (text ?? "").split(/\*\*(.+?)\*\*/g).map((piece, i) => ({ text: piece.replace(/\*+/g, ""), bold: i % 2 === 1 })).filter((p) => p.text);
}

/** A title without its "**" marks. */
export function plainTitle(text: string): string {
  return (text ?? "").replace(/\*\*/g, "").trim();
}
