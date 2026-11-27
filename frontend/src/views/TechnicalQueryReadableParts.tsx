/** The query page made readable (owner's Part 3, item 2, 27 Nov 2026), kit parts only: the reply as a real numbered list, the revision
 *  of each source document in one plain sentence with "How to confirm" folded, and how the query was made in one closed fold. LOOK ONLY:
 *  the same words, marks and actions as before. */
import { leadParagraphs } from "./technicalQueryQuestion";
import type { ReactElement } from "react";

import { Fold } from "../components/kit/Kit";
import { boldPieces, bulletText, plainTitle, replyBlocks } from "./technicalQueryReadable";

function Inline({ text }: { text: string }) {
  return <>{boldPieces(text).map((p, i) => (p.bold ? <strong key={i} className="font-semibold text-slateish-100">{p.text}</strong> : <span key={i}>{p.text}</span>))}</>;
}

/** An answer's lines under its title: bullet lines as a list, the others as paragraphs. */
function Body({ lines }: { lines: string[] }) {
  const out: ReactElement[] = [];
  let run: string[] = [];
  const flush = () => {
    if (run.length) out.push(<ul key={`u-${out.length}`} className="mt-1 list-disc space-y-1 pl-5">{run.map((t, k) => <li key={k}><Inline text={t} /></li>)}</ul>);
    run = [];
  };
  lines.forEach((line, j) => {
    const bullet = bulletText(line);
    if (bullet !== null) run.push(bullet);
    else {
      flush();
      // a long line is shown as short paragraphs of whole sentences; the words and their order never change (H's table, 8 and W)
      leadParagraphs(line).forEach((piece, k) => out.push(<p key={`l-${j}-${k}`} className="mt-1"><Inline text={piece} /></p>));
    }
  });
  flush();
  return <>{out}</>;
}

/** The reply: each numbered answer a list item (its title in bold, its lines under it), the lead and closing paragraphs as paragraphs. */
export function ReplyText({ answer }: { answer: string }) {
  const blocks = replyBlocks(answer);
  const out: ReactElement[] = [];
  let items: ReactElement[] = [];
  let bullets: ReactElement[] = [];
  const flush = () => {
    if (items.length) out.push(<ol key={`ol-${out.length}`} className="mt-2 list-decimal space-y-3 pl-6">{items}</ol>);
    if (bullets.length) out.push(<ul key={`ul-${out.length}`} className="mt-2 list-disc space-y-1 pl-6">{bullets}</ul>);
    items = [];
    bullets = [];
  };
  blocks.forEach((b, i) => {
    if (b.kind === "item") {
      if (bullets.length) flush(); // keep the reply's own order
      items.push(
        <li key={`i-${i}`} value={b.n}>
          <p className="font-semibold text-slateish-100">{plainTitle(b.title)}</p>
          <Body lines={b.body} />
        </li>,
      );
    } else if (b.kind === "bullet") {
      if (items.length) flush();
      bullets.push(<li key={`b-${i}`}><Inline text={b.text} /></li>);
    } else {
      flush();
      leadParagraphs(b.text).forEach((piece, k) => out.push(<p key={`p-${i}-${k}`} className="mt-2"><Inline text={piece} /></p>));
    }
  });
  flush();
  return <div data-testid="reply-text" className="mt-2 text-sm text-slateish-300">{out}</div>;
}

/** One plain sentence per cited document whose revision is not confirmed, with "How to confirm" folded under it. */
export function RevisionLines({ documents, isAdmin }: { documents: string[]; isAdmin: boolean }) {
  if (!documents.length) return null;
  return (
    <div data-testid="revision-lines" className="mt-2 text-sm text-slateish-300">
      {/* one sentence for every such document, said once (builder H's table of the 34 queries, 27 Nov 2026, 7d) */}
      <p data-testid="revision-line" className="mt-1">We have not yet checked that {documents.length === 1 ? `${documents[0]} is the current revision` : `${documents.slice(0, -1).join(", ")} and ${documents[documents.length - 1]} are the current revisions`}.</p>
      <Fold title="How to confirm" testId="revision-how">
        {isAdmin
          ? "Press “Confirm source document” on its source below, once you have checked it is the current revision. Or open it under Documents, then Details, and save its details."
          : "An administrator confirms it: under Documents, its Details, saved with its revision. Until then a reviewer checks the revision by hand."}
      </Fold>
    </div>
  );
}

/** How this query was made (who proposed the question, who wrote the reply), in one closed fold. */
export function MadeFold({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="mt-2">
      <Fold title="How this was made" testId="how-made">
        {lines.map((line) => <p key={line} data-testid="how-made-line">{line}</p>)}
      </Fold>
    </div>
  );
}
