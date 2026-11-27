/**
 * The Technical Queries list column, built ONLY from the shared kit (owner, 27 Nov 2026 03:30; standing rule R1; listed in kitPages.ts):
 * the page header, the mailbox chip, the count line that filters, one toolbar, and the queries as one- or two-line rows.
 * The mailbox panel, the filters, the new-query form and the More menu's contents are the page's own and come in as `panels`.
 */
import type { ReactNode } from "react";

import { ChipButton, LinkButton, MoreMenu, Notice, PageHeader, RowButton, Button, Small, Stack, StatusChip, Tag, OneLine } from "../components/kit/Kit";
import type { TechnicalQuery, TechnicalQueryAssignee } from "../api/client";
import { formatWhen } from "../format/when";
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
          {line.parts.map((part, index) => <span key={part.view}>{index ? ", " : ""}<LinkButton pressed={quick === part.view} onClick={() => toggle(part.view)}>{part.n} {part.words}</LinkButton></span>)}
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
              first={<>{tag ? <Tag testId="query-tag">{tag}</Tag> : null}{item.discipline_code ? <Tag>{item.discipline_code}</Tag> : null}<OneLine title={title}>{title}</OneLine></>}
              second={<>
                <StatusChip word={statusChip(item.status).words} testId="status-chip" />
                {item.contractor_name || who ? <span>{[item.contractor_name, who].filter(Boolean).join(" · ")}</span> : null}
                {item.due_at ? <span>due {formatWhen(item.due_at).split(",")[0]}</span> : null}
                {/* SAID ONCE, NOT ON EVERY ROW (owner's written order, 27 Nov 2026 10:59): "No query number" is the count line's "N of them need a
                    query number" (it filters to them) and "No contractor" is the notice above; a row carries neither, and the opened query
                    still says its own problems in full */}
              </>} />
          );
        })}
      </div>
    </Stack>
  );
}
