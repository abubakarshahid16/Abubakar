/**
 * The Administration page's Database section: a window on the tables.
 *
 * A WINDOW, NOT A WORKBENCH, and the UI must not pretend otherwise. There is
 * no edit affordance anywhere in this file - no input bound to a cell, no
 * save, no delete, no context menu, not even a disabled one. A disabled Save
 * would be worse than none: it tells a reader the capability exists and that
 * they lack permission, which is a false claim about what this screen is.
 *
 * EVERY COUNT CARRIES ITS DENOMINATOR (CLAUDE.md rule 4). The paging line
 * reads "rows 21-40 of 6,805", never "page 2".
 *
 * NULL RENDERS AS NOTHING. Not "null", not "-", not 0. An empty cell is what
 * an absent value looks like, and the three alternatives each assert
 * something the database did not say.
 *
 * CREDENTIAL MATERIAL IS ALREADY GONE. The server replaces those values
 * before they reach the wire, so this file renders whatever it is given and
 * marks the column - it never decides what is secret, because a second copy
 * of that rule is a second thing to get wrong.
 */
import { useCallback, useEffect, useState } from "react";

import type {
  AdminClient, DbRows, DbTable, DbTableInfo, LoadFailure,
} from "../../types/admin";

/** The server's mask string, repeated here only to recognise it for the
 *  tooltip. It is never produced by this file. */
const MASK = "•••";

export interface DatabaseSectionProps {
  client: AdminClient;
  /** Rows per page. The server caps whatever is asked. */
  pageSize?: number;
}

export function DatabaseSection({ client, pageSize = 25 }: DatabaseSectionProps) {
  const [tables, setTables] = useState<DbTable[] | null>(null);
  const [failure, setFailure] = useState<LoadFailure | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [info, setInfo] = useState<DbTableInfo | null>(null);
  const [page, setPage] = useState<DbRows | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (!client.dbTables) return;
    void client.dbTables().then((r) => {
      // SHAPE-CHECKED AT THE EDGE, and this is the second time. `ok` means
      // the request succeeded, NOT that the body is what this screen
      // expects; an `ok` response carrying the wrong shape put `undefined`
      // into state, `.map` threw, and the WHOLE Administration page went
      // blank over one section - the identical failure the Dashboard had
      // one phase earlier (honesty audit entry 42). A body this component
      // cannot use is a FAILURE, never "no tables": the second reads as a
      // claim about the database.
      if (r.ok && Array.isArray(r.data?.tables)) {
        setTables(r.data.tables);
        setFailure(null);
        return;
      }
      setTables(null);
      setFailure(
        !r.ok && r.disconnected ? { kind: "offline" }
        : !r.ok && r.error.code === "not_found" ? { kind: "missing" }
        : !r.ok ? { kind: "failed", code: r.error.code, message: r.error.message }
        : { kind: "failed", code: "internal",
            message: "The backend answered with something this screen cannot read." });
    });
  }, [client]);

  const open = useCallback(async (name: string, at: number) => {
    setSelected(name);
    setOffset(at);
    const [i, p] = await Promise.all([
      client.dbTable?.(name),
      client.dbRows?.(name, pageSize, at),
    ]);
    // Same guard on both: a column list that is not a list, or rows that are
    // not rows, render as nothing rather than throwing mid-render.
    setInfo(i && i.ok && Array.isArray(i.data?.columns) ? i.data : null);
    setPage(
      p && p.ok && Array.isArray(p.data?.rows) && Array.isArray(p.data?.columns)
        ? p.data : null);
  }, [client, pageSize]);

  if (!client.dbTables) return null;

  return (
    <section aria-labelledby="admin-db-heading" className="space-y-3">
      <h2 id="admin-db-heading" className="text-sm font-semibold text-slateish-200">
        Database
      </h2>
      <p className="text-xs text-slateish-400">
        Read-only. Nothing on this screen changes anything. Values in columns
        that hold credentials are masked before they leave the server.
      </p>

      {failure && (
        <p role="alert" className="rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/10 px-3 py-2 text-xs text-warn-500">
          {failure.kind === "offline"
            ? "The backend is not running, so the tables cannot be listed."
            : failure.kind === "missing"
              ? "This backend does not serve the database explorer."
              : failure.message}
        </p>
      )}

      {!failure && tables === null && (
        <p className="text-xs text-slateish-400">Loading tables…</p>
      )}

      {tables !== null && (
        <div className="grid gap-3 lg:grid-cols-[18rem_1fr]">
          {/* ------------------------------------------- the table list */}
          <div className="max-h-96 overflow-y-auto rounded-[var(--radius-md)] border border-ink-600">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-ink-800 uppercase tracking-wide text-slateish-400">
                <tr>
                  <th scope="col" className="px-3 py-2">Table</th>
                  <th scope="col" className="px-3 py-2 text-right">Rows</th>
                </tr>
              </thead>
              <tbody>
                {tables.map((t) => (
                  <tr key={t.name} className="border-t border-ink-700">
                    <td className="px-3 py-1.5">
                      <button
                        type="button" onClick={() => void open(t.name, 0)}
                        aria-current={selected === t.name ? "true" : undefined}
                        className={`text-left hover:underline ${
                          selected === t.name ? "font-semibold text-signal-400" : "text-slateish-200"}`}
                      >
                        {t.name}
                      </button>
                    </td>
                    <td className="px-3 py-1.5 text-right text-slateish-400">
                      {t.row_count.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ------------------------------------- the selected table */}
          <div className="min-w-0 space-y-3">
            {selected === null && (
              <p className="text-xs text-slateish-400">
                Choose a table to see its columns and a page of its rows.
              </p>
            )}

            {info && (
              <div className="rounded-[var(--radius-md)] border border-ink-600 p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slateish-300">
                  {info.name} — columns
                </h3>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {info.columns.map((c) => (
                    <li
                      key={c.name}
                      className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-2 py-0.5 text-xs text-slateish-300"
                    >
                      {c.name}
                      {c.type ? <span className="text-slateish-500"> {c.type}</span> : null}
                      {c.pk ? <span className="text-signal-400"> pk</span> : null}
                      {c.sensitive ? (
                        <span title="masked credential material" className="text-warn-500"> masked</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {page && (
              <div className="space-y-2">
                <Paging page={page} pageSize={pageSize}
                        onGo={(at) => void open(page.name, at)} />
                <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-600">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-ink-800 uppercase tracking-wide text-slateish-400">
                      <tr>
                        {page.columns.map((c) => (
                          <th key={c} scope="col" className="whitespace-nowrap px-3 py-2">
                            {c}
                            {page.masked_columns?.includes(c) ? (
                              <span title="masked credential material" className="text-warn-500"> •</span>
                            ) : null}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {page.rows.map((row, i) => (
                        <tr key={`${offset + i}`} className="border-t border-ink-700 align-top">
                          {row.map((value, j) => (
                            <td key={page.columns[j] ?? j}
                                className="max-w-[24rem] truncate px-3 py-1.5 text-slateish-300"
                                title={value === MASK ? "masked credential material" : undefined}>
                              {/* NULL RENDERS AS NOTHING. `String(null)` is
                                  "null" and `value || ""` would also blank a
                                  real 0 and a real "", each of which is a
                                  value the database actually holds. */}
                              {value === null || value === undefined ? "" : String(value)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {page.rows.length === 0 && (
                  <p className="text-xs text-slateish-400">This table has no rows.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** "rows 21-40 of 6,805", and never "page 2 of 273".
 *
 *  A page number is a fact about the pager; the range and the total are facts
 *  about the data, and they are what a reader needs to know whether they are
 *  looking at all of it. */
function Paging({ page, pageSize, onGo }: {
  page: DbRows; pageSize: number; onGo: (offset: number) => void;
}) {
  const first = page.total === 0 ? 0 : page.offset + 1;
  const last = Math.min(page.offset + page.rows.length, page.total);
  const back = Math.max(0, page.offset - pageSize);
  const next = page.offset + pageSize;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slateish-400">
      <span>
        rows {first.toLocaleString()}–{last.toLocaleString()} of{" "}
        {page.total.toLocaleString()}
      </span>
      <button
        type="button" onClick={() => onGo(back)} disabled={page.offset === 0}
        className="rounded-[var(--radius-xs)] border border-ink-500 px-2 py-0.5 hover:bg-ink-700 disabled:opacity-40"
      >
        Previous
      </button>
      <button
        type="button" onClick={() => onGo(next)} disabled={next >= page.total}
        className="rounded-[var(--radius-xs)] border border-ink-500 px-2 py-0.5 hover:bg-ink-700 disabled:opacity-40"
      >
        Next
      </button>
      {page.limit < pageSize && (
        <span className="text-warn-500">
          the server capped this page at {page.limit.toLocaleString()} rows
        </span>
      )}
    </div>
  );
}
