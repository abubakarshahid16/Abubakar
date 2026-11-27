/** COMPANY's usual position on cost and schedule, OFFERED beside the draft (lead-4's final design, 27 Nov 2026): the set sentence, a quiet
 *  hint when the request mentions money or time, and ONE action that adds the sentence to the engineer's own reply. The code never puts it
 *  in a draft; the engineer reads it, decides, and saves the reply as any other edit. Kit parts only. */
import { Button, Small } from "../components/kit/Kit";

/** The reply with the sentence as its last paragraph, added once (a second press changes nothing). */
export function withPositionLine(reply: string, line: string): string {
  const text = (reply ?? "").trimEnd();
  if (!line || text.includes(line)) return reply;
  return text ? `${text}\n\n${line}` : line;
}

export function TechnicalQueryPosition({ position, canEdit, onAdd }: {
  position: { line: string; hint: string | null } | null | undefined;
  /** The engineer's own reply can be written now (the editor under Redo is open to them). */
  canEdit: boolean;
  onAdd: () => void;
}) {
  if (!position?.line) return null;
  return (
    <div data-testid="position-offer" className="mt-4 border-y border-ink-700 py-3 text-sm text-slateish-300">
      <p className="font-semibold text-slateish-200">COMPANY&rsquo;s usual position on cost and schedule</p>
      <p className="mt-1">&ldquo;{position.line}&rdquo;</p>
      {position.hint && <div data-testid="position-hint" className="mt-1"><Small>{position.hint}</Small></div>}
      <div className="mt-2">
        {canEdit
          ? <Button variant="secondary" size="sm" data-testid="position-add" onClick={onAdd}>Add COMPANY&rsquo;s usual cost/schedule sentence</Button>
          : <Small>It can be added while the reply can still be changed; this one is past that step.</Small>}
      </div>
    </div>
  );
}
