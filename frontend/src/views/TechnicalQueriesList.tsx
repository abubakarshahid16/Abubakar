/**
 * The Technical Queries list column, built ONLY from the shared kit (owner, 27 Nov 2026 03:30; standing rule R1; listed in kitPages.ts):
 * the page header, the mailbox chip, the count line that filters, one toolbar, and the queries as one- or two-line rows.
 * The mailbox panel, the filters, the new-query form and the More menu's contents are the page's own and come in as `panels`.
 */
import type { ReactNode } from "react";

import { ChipButton, LinkButton, MoreMenu, Notice, PageHeader, RowButton, Button, Small, Stack, StatusChip, Tag, OneLine } from "../components/kit/Kit";
import type { TechnicalQuery, TechnicalQueryAssignee } from "../api/client";
import { formatWhen } from "../format/when";
import { NEW_LOOK } from "../look";
import { countLine, queryTag, quickMatch, statusChip, type QuickView } from "./technicalQueryQuestion";

export interface ListPanels {
  /** The mailbox's details, shown when its chip is open. */
  mailbox: ReactNode;
  /** Messages about the Gmail connection and any error, above the count line. */
  messages: ReactNode;
  /** The More menu's contents (finding sources for all, the routing rules); null: no More menu. */
  more: ReactNode | null;
  /** The new-query form and the filters, shown under the toolbar when open. */
  handForm: ReactNode;
  filters: ReactNode;
}

/** The mailbox chip's word and detail, from `mailboxChip`'s words ("Mailbox connected · checked 4 min ago"). */
export function mailboxWords(words: string): { word: string; detail?: string } {
  const importing = words.match(/^Mailbox: importing, (.*)$/);
  if (importing) return { word: "Importing", detail: importing[1] };
  const [word, detail] = words.split(" · ");
  return { word, detail };
}

export function TechnicalQueriesList(props: {
  chip: { words: string } | null; mailboxOpen: boolean; onToggleMailbox: () => void;
  loading: boolean; items: TechnicalQuery[]; activeFilters: number; quick: QuickView | null; onQuick: (view: QuickView | null) => void;
  handOpen: boolean; onHand: () => void; filtersOpen: boolean; onFilters: () => void;
  importing: boolean; selectedId: string | null; onOpen: (id: string) => void; assignees: TechnicalQueryAssignee[];
  panels: ListPanels;
}) {
  const { chip, items, quick } = props;
  const line = countLine(items);
  const shown = quick ? items.filter((item) => quickMatch(quick, item)) : items;
  const noContractor = items.filter((item) => !item.contractor_name).length;
  const nobodyAll = items.length > 1 && items.every((i) => !i.assignee_user_id);
  const toggle = (view: QuickView) => props.onQuick(quick === view ? null : view);
  // SAID ONCE (owner, 27 Nov 2026 12:32: 21 rows each carried the same "Waiting for approval"): the state most of the shown rows share
  // is not repeated on each row; a row shows its chip only when its state differs. The count line names every state with its number,
  // and when the rows are mixed one line says which state an unmarked row is in (new look; the classic look keeps a chip on every row).
  const shownWords = shown.map((item) => statusChip(item.status).words);
  // only a CLEAR majority loses its chips: near a half/half split hiding one group saves little and adds words (F's gate on #1987)
  const top = NEW_LOOK && shownWords.length > 1 ? mostCommon(shownWords) : null;
  const common = top !== null && shownWords.filter((w) => w === top).length * 2 > shownWords.length ? top : null;
  const mixed = common !== null && shownWords.some((w) => w !== common);
  return (
    <Stack gap={3}>
      <PageHeader title="Technical Queries and CFCs" titleId="technical-queries-title" />
      {chip ? (() => { const m = mailboxWords(chip.words); return (
        <div>
          <ChipButton word={m.word} detail={m.detail} expanded={props.mailboxOpen} controls="mailbox-panel" onClick={props.onToggleMailbox} testId="mailbox-chip" />
          {props.mailboxOpen ? <div id="mailbox-panel" data-testid="mailbox-panel">{props.panels.mailbox}</div> : null}
        </div>
      ); })() : null}
      {props.panels.messages}
      {/* THE COUNT LINE IS A FILTER: the status parts add up to the total; "of them" is said apart, never added */}
      {props.loading ? <Small>Loading queries</Small> : (
        <p data-testid="count-line" className="kit-lead">
          <strong>{line.total} quer{line.total === 1 ? "y" : "ies"}{props.activeFilters > 0 ? " match the filters" : ""}</strong>{line.parts.length ? ": " : ""}
          {/* the state an unmarked row is in is said HERE, in the count sentence ("32 waiting for approval (no label)"), not as a third note
              over the list (F's gate on #1987, 27 Nov 2026) */}
          {line.parts.map((part, index) => <span key={part.view}>{index ? ", " : ""}<LinkButton pressed={quick === part.view} onClick={() => toggle(part.view)}>{part.n} {part.words}</LinkButton>{mixed && part.words.toLowerCase() === common!.toLowerCase() ? <span data-testid="no-label-part"> (no label)</span> : null}</span>)}
          {line.ofThem ? <>. <LinkButton pressed={quick === "person"} onClick={() => toggle("person")}>{line.ofThem.n} of them {line.ofThem.words}</LinkButton></> : null}
          {quick ? <> · <LinkButton onClick={() => props.onQuick(null)}>show all</LinkButton></> : null}
        </p>
      )}
      <div role="toolbar" aria-label="Query actions" className="kit-row kit-gap-2">
          <Button size="sm" onClick={props.onHand} aria-expanded={props.handOpen}>New query</Button>
          <Button size="sm" onClick={props.onFilters} aria-expanded={props.filtersOpen} aria-controls="query-filters">{props.activeFilters > 0 ? `Filters (${props.activeFilters} active)` : "Filters"}</Button>
          {props.panels.more !== null ? <MoreMenu testId="more-menu">{props.panels.more}</MoreMenu> : null}
      </div>
      {props.panels.handForm}
      {props.panels.filters}
      {/* a problem every query shares is said ONCE above the list, never as a chip on every row (H's audit, 27 Nov 2026, (d)) */}
      {noContractor > 0 ? <Notice tone="warn"><span data-testid="no-contractor-note">{noContractor === items.length ? `None of the ${items.length}` : `${noContractor} of the ${items.length}`} quer{items.length === 1 ? "y has" : "ies have"} a contractor yet. Add its code once under More, &ldquo;Rules for who it goes to&rdquo;, and every query with that code fills itself.</span></Notice> : null}
      {/* the same said-once rule (H's gate on #1971: "Nobody assigned" on every one of 34 rows) */}
      {nobodyAll ? <Small><span data-testid="nobody-assigned-note">Nobody is assigned to any of these {items.length} queries yet.</span></Small> : null}
      <div className="kit-stack kit-gap-2" aria-label="Technical query list">
        {items.length === 0 ? <Small>{props.importing ? "The import is running: queries appear here as their messages arrive." : "No technical queries have been imported."}</Small> : null}
        {items.length > 0 && quick && shown.length === 0 ? <Small>None right now.</Small> : null}
        {shown.map((item) => {
          const tag = queryTag(item);
          const who = item.assignee_user_id ? (props.assignees.find((p) => p.id === item.assignee_user_id)?.display_name ?? "a person") : nobodyAll ? "" : "Nobody assigned";
          const title = item.title_short ?? item.subject;
          return (
            <RowButton key={item.id} selected={props.selectedId === item.id} onClick={() => props.onOpen(item.id)}
              first={<>{tag ? <Tag testId="query-tag">{tag}</Tag> : null}{item.discipline_code ? <Tag>{item.discipline_code}</Tag> : null}<OneLine title={title} lines={NEW_LOOK ? 2 : 1}>{title}</OneLine></>}
              second={(common === null || statusChip(item.status).words !== common || item.contractor_name || who || item.due_at) ? <>
                {common === null || statusChip(item.status).words !== common ? <StatusChip word={statusChip(item.status).words} testId="status-chip" /> : null}
                {item.contractor_name || who ? <span>{[item.contractor_name, who].filter(Boolean).join(" · ")}</span> : null}
                {item.due_at ? <span>due {formatWhen(item.due_at).split(",")[0]}</span> : null}
                {/* SAID ONCE, NOT ON EVERY ROW (owner's written order, 27 Nov 2026 10:59): "No query number" is the count line's "N of them need a
                    query number" (it filters to them) and "No contractor" is the notice above; a row carries neither, and the opened query
                    still says its own problems in full */}
              </> : null} />
          );
        })}
      </div>
    </Stack>
  );
}

/** The word most of the list shares (the first one met wins a tie, so the choice is stable as the list is read top to bottom). */
export function mostCommon(words: string[]): string | null {
  const n = new Map<string, number>();
  for (const w of words) n.set(w, (n.get(w) ?? 0) + 1);
  let best: string | null = null;
  for (const w of words) if (best === null || n.get(w)! > n.get(best)!) best = w;
  return best;
}
