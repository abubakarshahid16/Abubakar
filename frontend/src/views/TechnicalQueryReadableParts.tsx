/** The query page made readable (owner's Part 3, item 2, 27 Nov 2026), kit parts only: the reply as a real numbered list, the revision
 *  of each source document in one plain sentence with "How to confirm" folded, and how the query was made in one closed fold. LOOK ONLY:
 *  the same words, marks and actions as before. */
import { Fold } from "../components/kit/Kit";
import { boldPieces, plainTitle, replyBlocks } from "./technicalQueryReadable";

function Inline({ text }: { text: string }) {
  return <>{boldPieces(text).map((p, i) => (p.bold ? <strong key={i} className="font-semibold text-slateish-100">{p.text}</strong> : <span key={i}>{p.text}</span>))}</>;
}

/** The reply: each numbered answer a list item (its title in bold, its lines under it), the lead and closing paragraphs as paragraphs. */
export function ReplyText({ answer }: { answer: string }) {
  const blocks = replyBlocks(answer);
  const out: JSX.Element[] = [];
  let items: JSX.Element[] = [];
  const flush = () => {
    if (items.length) out.push(<ol key={`ol-${out.length}`} className="mt-2 list-decimal space-y-3 pl-6">{items}</ol>);
    items = [];
  };
  blocks.forEach((b, i) => {
    if (b.kind === "item") {
      items.push(
        <li key={`i-${i}`} value={b.n}>
          <p className="font-semibold text-slateish-100">{plainTitle(b.title)}</p>
          {b.body.map((line, j) => <p key={j} className="mt-1"><Inline text={line} /></p>)}
        </li>,
      );
    } else {
      flush();
      out.push(<p key={`p-${i}`} className="mt-2"><Inline text={b.text} /></p>);
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
      {documents.map((name) => <p key={name} data-testid="revision-line" className="mt-1">We have not yet confirmed that we hold the latest revision of {name}.</p>)}
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
