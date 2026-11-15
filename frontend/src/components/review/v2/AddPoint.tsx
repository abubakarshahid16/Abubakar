/** SPEC 10: the engineer's own comment as a new point (text required; page, rule book and clause optional). It is "Added by <name>",
 *  counts as decided, and goes on the CRS sheets like a kept point with the engineer as its author. */
import { useState } from "react";

export function AddPoint({ onAdd, busy }: { onAdd: (b: { text: string; page?: number; rule_book?: string; clause?: string }) => Promise<boolean>; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(""); const [page, setPage] = useState(""); const [book, setBook] = useState(""); const [clause, setClause] = useState("");
  const field = "rounded border border-ink-500 bg-ink-900 px-2 py-1 text-sm text-slateish-100";
  if (!open) {
    return <button type="button" data-testid="v2-add-open" onClick={() => setOpen(true)} className="text-sm text-signal-300 underline-offset-2 hover:underline">Add a point</button>;
  }
  async function save() {
    const pageNo = page.trim() ? Number(page) : undefined;
    const ok = await onAdd({
      text: text.trim(), ...(pageNo && Number.isInteger(pageNo) && pageNo > 0 ? { page: pageNo } : {}),
      ...(book.trim() ? { rule_book: book.trim() } : {}), ...(clause.trim() ? { clause: clause.trim() } : {}),
    });
    if (ok) { setText(""); setPage(""); setBook(""); setClause(""); setOpen(false); }
  }
  return (
    <section aria-label="Add a point" data-testid="v2-add" className="space-y-2 rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3">
      <label className="block text-xs text-slateish-300">Your comment
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} className={`mt-1 w-full ${field}`} />
      </label>
      <div className="flex flex-wrap gap-3">
        <label className="text-xs text-slateish-300">Page (optional)
          <input value={page} onChange={(e) => setPage(e.target.value)} inputMode="numeric" className={`ml-2 w-20 ${field}`} />
        </label>
        <label className="text-xs text-slateish-300">Rule book (optional)
          <input value={book} onChange={(e) => setBook(e.target.value)} className={`ml-2 w-48 ${field}`} />
        </label>
        <label className="text-xs text-slateish-300">Clause (optional)
          <input value={clause} onChange={(e) => setClause(e.target.value)} className={`ml-2 w-28 ${field}`} />
        </label>
      </div>
      <div className="flex gap-3">
        <button type="button" disabled={busy || !text.trim()} onClick={() => void save()}
          className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1 text-sm font-semibold text-ink-950 disabled:opacity-50">Add this point</button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm text-slateish-300 underline-offset-2 hover:underline">Cancel</button>
      </div>
    </section>
  );
}
