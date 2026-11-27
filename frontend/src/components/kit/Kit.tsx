/**
 * THE SHARED KIT (owner, 27 Nov 2026 03:30; standing rule R1: one shared kit, no one-offs; R2: one owner for the look, builder C).
 * Every page builds its title, buttons, status chips, cards, tables, selects, inputs, notice boxes and tiles from these parts, and
 * styles none of them itself. The parts take no colour, size or className for their look: a new need is added HERE first.
 * Styling lives in kit.css; status colours are fixed per word in chipWords.ts.
 */
import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

import "./kit.css";
import { toneOfWord } from "./chipWords";

/** A page's one header: its title (the same size and weight on every page), an optional one-line lead, and its main actions. */
export function PageHeader({ title, lead, actions, titleId }: { title: string; lead?: ReactNode; actions?: ReactNode; titleId?: string }) {
  return (
    <header className="kit-header">
      <div className="kit-header__text">
        <h1 id={titleId} className="kit-title">{title}</h1>
        {lead ? <p className="kit-lead">{lead}</p> : null}
      </div>
      {actions ? <div className="kit-header__actions">{actions}</div> : null}
    </header>
  );
}

/** A section's heading inside a page (one size: 18). */
export function SectionTitle({ children, id }: { children: ReactNode; id?: string }) {
  return <h2 id={id} className="kit-section-title">{children}</h2>;
}

/** primary: the page's decision; secondary: everything else; danger: an action that removes or revokes (red words and edge). */
type Variant = "primary" | "secondary" | "danger";
type Size = "md" | "sm";
const buttonClass = (variant: Variant, size: Size) => `kit-btn kit-btn--${variant}${size === "sm" ? " kit-btn--sm" : ""}`;

/** The one button. `primary` is the page's main decision (one per area); everything else is `secondary`. */
export const Button = forwardRef<HTMLButtonElement, Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "style"> & { variant?: Variant; size?: Size }>(
  function Button({ variant = "secondary", size = "md", type = "button", ...rest }, ref) {
    return <button ref={ref} type={type} className={buttonClass(variant, size)} {...rest} />;
  },
);

/** A link that looks like the one button (a download, a page to open). */
export function ButtonLink({ variant = "secondary", size = "md", ...rest }: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "className" | "style"> & { variant?: Variant; size?: Size }) {
  return <a className={buttonClass(variant, size)} {...rest} />;
}

/** A status as a chip: its WORD decides its colour (chipWords.ts), the same on every page. `why` is the full sentence: shown on hover
 *  and always in the chip's own text for a screen reader. */
export function StatusChip({ word, why, testId }: { word: string; why?: string; testId?: string }) {
  return (
    <span className={`kit-chip kit-chip--${toneOfWord(word)}`} title={why} data-word={word} data-testid={testId}>
      {word}{why ? <span className="sr-only">: {why}</span> : null}
    </span>
  );
}

/** The one card: a raised box with an optional section title. */
export function Card({ title, children, labelledBy }: { title?: ReactNode; children: ReactNode; labelledBy?: string }) {
  return (
    <section className="kit-card" aria-labelledby={labelledBy}>
      {title ? <h2 id={labelledBy} className="kit-section-title">{title}</h2> : null}
      {children}
    </section>
  );
}

/** The one table: scrolls inside its own box, so it never widens the page. `columns` are the header words; rows are cells. */
export function Table({ caption, columns, rows }: { caption: string; columns: string[]; rows: Array<{ key: string; cells: ReactNode[] }> }) {
  return (
    <div className="kit-table-wrap">
      <table className="kit-table">
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={r.key}>{r.cells.map((cell, i) => <td key={i}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** The one text input, with its label and an optional hint under it. */
export function TextField({ label, hint, id, ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "style"> & { label: string; hint?: string; id: string }) {
  return (
    <div className="kit-field">
      <label className="kit-label" htmlFor={id}>{label}</label>
      <input id={id} className="kit-input" aria-describedby={hint ? `${id}-hint` : undefined} {...rest} />
      {hint ? <span id={`${id}-hint`} className="kit-hint">{hint}</span> : null}
    </div>
  );
}

/** The one select, with its label. */
export function SelectField({ label, hint, id, children, ...rest }: Omit<SelectHTMLAttributes<HTMLSelectElement>, "className" | "style"> & { label: string; hint?: string; id: string }) {
  return (
    <div className="kit-field">
      <label className="kit-label" htmlFor={id}>{label}</label>
      <select id={id} className="kit-select" aria-describedby={hint ? `${id}-hint` : undefined} {...rest}>{children}</select>
      {hint ? <span id={`${id}-hint`} className="kit-hint">{hint}</span> : null}
    </div>
  );
}

/** The one notice box: `info` (a fact to know), `warn` (check this), `problem` (something went wrong). */
export function Notice({ tone = "info", title, children }: { tone?: "info" | "warn" | "problem"; title?: string; children: ReactNode }) {
  return (
    <div className={`kit-notice kit-notice--${tone}`} role={tone === "problem" ? "alert" : "note"}>
      {title ? <p className="kit-notice__title">{title}</p> : null}
      <div>{children}</div>
    </div>
  );
}

/** A tile: one whole card that is one button to its list (the Dashboard's three tiles, owner 03:34). The big number is what waits;
 *  the figures under it say done (green) and late (red only when above 0; otherwise the words given, e.g. "no due dates set"). */
export function Tile({ name, number, label, done, late, lateWords, onOpen }: {
  name: string; number: number | null; label: string; done?: number | null; late?: number | null; lateWords?: string; onOpen: () => void;
}) {
  return (
    <button type="button" className="kit-tile" onClick={onOpen}>
      {/* the spaces between the parts are real text (they draw nothing in the tile's column): read aloud or copied, a tile says
          "Deliverables 1 waiting for you 1 done", never "Deliverables1waiting" (H's fix on main, 26 Nov 2026) */}
      <span className="kit-tile__name">{name}</span>{" "}
      {number === null ? <span className="kit-tile__unknown">Not known</span> : <span className="kit-tile__number">{number}</span>}{" "}
      <span className="kit-tile__label">{label}</span>{" "}
      <span className="kit-tile__figures">
        {typeof done === "number" ? <span className="kit-ok">{done} done</span> : null}{" "}
        {typeof late === "number" && late > 0 ? <span className="kit-late">{late} late</span> : lateWords ? <span>{lateWords}</span> : null}
      </span>
    </button>
  );
}

/** A row of tiles: side by side on a wide window, one column on a narrow one. */
export function Tiles({ children, label }: { children: ReactNode; label: string }) {
  return <div className="kit-tiles" role="group" aria-label={label}>{children}</div>;
}

/** Small grey text (an "updated 1 min ago" line): 13px, never mono. */
export function Small({ children }: { children: ReactNode }) {
  return <p className="kit-small">{children}</p>;
}

type Gap = 2 | 3 | 4 | 6;
/** Parts one under another, with one of the scale's gaps (8, 12, 16 or 24 px): the only way a page spaces its parts. */
export function Stack({ gap = 4, children, label }: { gap?: Gap; children: ReactNode; label?: string }) {
  return <div className={`kit-stack kit-gap-${gap}`} aria-label={label}>{children}</div>;
}

/** Parts side by side that wrap onto the next line on a narrow window. */
export function Row({ gap = 2, children, label }: { gap?: Gap; children: ReactNode; label?: string }) {
  return <div className={`kit-row kit-gap-${gap}`} aria-label={label}>{children}</div>;
}

/** A status chip that is also a button (the mailbox chip: its details open from it). The word sets the colour; `detail` follows in plain words. */
export function ChipButton({ word, detail, expanded, controls, onClick, testId }: { word: string; detail?: string; expanded?: boolean; controls?: string; onClick: () => void; testId?: string }) {
  return (
    <button type="button" className="kit-chip-btn" aria-expanded={expanded} aria-controls={controls} onClick={onClick} data-testid={testId}>
      <StatusChip word={word} />{detail ? <span className="kit-chip-btn__detail">{detail}</span> : null}
    </button>
  );
}

/** A button that reads as a link in running text (a count that filters, "show all"). `pressed` marks the one that is on.
 *  A LINK STAYS A LINK (owner, 27 Nov 2026: a fix, not a redesign): every control that was a text link keeps this part, never a Button.
 *  `tone`: action = the teal link, underlined on hover ("← Reviews", "page 4", "See all"); danger = the red underlined link (Cancel a run);
 *  inherit = a link inside a sentence, in the sentence's own colour, underlined. No tone: the quiet underlined word (the count line).
 *  `size`: xs (12px) or sm (14px), the link's own size where it stood apart; otherwise the text's size around it. */
export function LinkButton({ pressed, tone, size, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "style" | "type"> & {
  pressed?: boolean; tone?: "action" | "danger" | "inherit"; size?: "xs" | "sm";
}) {
  const cls = `kit-link${tone ? ` kit-link--${tone}` : ""}${size ? ` kit-link--${size}` : ""}`;
  return <button type="button" className={cls} aria-pressed={pressed} {...rest} />;
}

/** One row of a list that opens an item: the whole row is one button, its first line the item, its second where it stands. */
export function RowButton({ selected, first, second, onClick }: { selected?: boolean; first: ReactNode; second?: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className={`kit-row-btn${selected ? " kit-row-btn--selected" : ""}`} aria-current={selected ? "true" : undefined} onClick={onClick}>
      <span className="kit-row-btn__first">{first}</span>
      {second ? <span className="kit-row-btn__second">{second}</span> : null}
    </button>
  );
}

/** A neutral tag for an id or a code ("CFC-7", "PRO"): never a status, never coloured. */
export function Tag({ children, testId }: { children: ReactNode; testId?: string }) {
  return <span className="kit-tag" data-testid={testId}>{children}</span>;
}

/** One line of text that is cut with an ellipsis when too long; the whole text is in its title and stays in the page for readers. */
export function OneLine({ children, title }: { children: ReactNode; title: string }) {
  return <span className="kit-one-line" title={title}>{children}</span>;
}

/** A small menu of less-used actions, folded behind one secondary button ("More"). */
export function MoreMenu({ label = "More", children, testId }: { label?: string; children: ReactNode; testId?: string }) {
  return (
    <details className="kit-more" data-testid={testId}>
      <summary className="kit-btn kit-btn--secondary kit-btn--sm">{label}</summary>
      <div className="kit-more__panel">{children}</div>
    </details>
  );
}

/** A fold: a short title that opens to more (what a figure counts, how something was measured). */
export function Fold({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <details className="kit-fold" data-testid={testId}>
      <summary className="kit-fold__title">{title}</summary>
      <div className="kit-fold__body">{children}</div>
    </details>
  );
}
