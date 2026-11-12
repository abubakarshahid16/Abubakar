/**
 * An answer's text, as a reader expects a chat answer to look: paragraphs,
 * bullet and numbered points, bold lead-ins ("**Partly.**", "**What I'd do:**")
 * and small superscript source numbers.
 *
 * NEVER HTML. Every piece becomes a React text node, so a model (or a
 * document) that writes `<img onerror=...>` shows those characters rather
 * than running them. Only the handful of marks the answer prompts ask for are
 * understood; anything else is shown as the characters it is.
 *
 * A source number is `[S1]` in the model's text. With `onCite` it becomes a
 * superscript button that opens that source; without it (a general answer,
 * which cites nothing) any stray marker is dropped rather than shown as a
 * reference to a document that was never read.
 */
import type { ReactNode } from "react";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; lines: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*(#{1,3})\s+(.*)$/;

export function blocksOf(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", lines: paragraph });
    if (list) blocks.push({ kind: "list", ...list });
    paragraph = [];
    list = null;
  };
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
    } else if (bullet || numbered) {
      const ordered = Boolean(numbered);
      if (paragraph.length || (list && list.ordered !== ordered)) flush();
      if (!list) list = { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else if (list && /^\s{2,}/.test(raw)) {
      // an indented continuation of the previous point
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      if (list) flush();
      paragraph.push(line);
    }
  }
  flush();
  return blocks;
}

// [S1], [S1, S2], [S1 "the exact words"] - the quoted form is the Claude
// lane's claim marker; the words were checked server-side and are shown in
// the source preview, not repeated inline.
const TOKEN = /(\$\$[^$\n]+\$\$|\$(?!\s)(?:[^$\n]*[^\s$])?\$|\*\*[^*\n]+\*\*|`[^`\n]+`|\[S\d+(?:\s*,\s*S?\d+)*(?:\s+"[^"\n]*")?\]|(?<![\w*])\*[^*\s][^*\n]*\*(?!\w)|(?<!\w)_[^_\s][^_\n]*_(?!\w))/g;

const TEX_WORDS: Record<string, string> = {
  times: "×", cdot: "·", approx: "≈", leq: "≤", le: "≤", geq: "≥", ge: "≥", neq: "≠", pm: "±", Delta: "Δ", delta: "δ",
  rightarrow: "→", to: "→", sigma: "σ", mu: "µ", rho: "ρ", pi: "π", alpha: "α", beta: "β", theta: "θ", degree: "°",
};

/** The chat does not typeset maths (no new package). A formula the model wrote in LaTeX is shown as plain readable
 * characters instead of raw markup: `$P_{\text{bara}} = P + 1$` becomes `P_bara = P + 1`. A `$...$` span with no
 * LaTeX mark in it (a price, "$5 to $10") is not a formula and is left as written. Returns null for those. */
export function texToPlain(span: string): string | null {
  const inner = span.replace(/^\$\$?|\$\$?$/g, "").trim();
  if (!/[\\^_{}]/.test(inner)) return null;
  let t = inner;
  t = t.replace(/\\(?:text|mathrm|mathbf|textbf|mathit|operatorname)\s*\{([^{}]*)\}/g, "$1");
  for (let i = 0; i < 3; i++) t = t.replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, "($1)/($2)");
  t = t.replace(/\\sqrt\s*\{([^{}]*)\}/g, "√($1)");
  t = t.replace(/\\(?:left|right)\b/g, "").replace(/\\[,;:! ]/g, " ");
  t = t.replace(/\\([A-Za-z]+)/g, (_m, name: string) => TEX_WORDS[name] ?? name);
  t = t.replace(/[_^]\{([^{}]*)\}/g, (m, x: string) => `${m[0]}${x}`).replace(/[{}]/g, "");
  return t.replace(/\s+/g, " ").trim();
}

function Inline({
  text,
  onCite,
  activeSource,
}: {
  text: string;
  onCite?: (index: number) => void;
  activeSource?: number | null;
}) {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(TOKEN)) {
    const token = match[0];
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    last = at + token.length;
    if (token.startsWith("$")) {
      const plain = texToPlain(token);
      out.push(plain === null ? token : <code key={key++} data-testid="formula" className="rounded bg-ink-800 px-1 font-mono text-[0.92em]">{plain}</code>);
    } else if (token.startsWith("**")) {
      out.push(<strong key={key++} className="font-semibold text-slateish-100">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(<code key={key++} className="rounded bg-ink-800 px-1 font-mono text-[0.92em]">{token.slice(1, -1)}</code>);
    } else if (token.startsWith("[S")) {
      const numbers = Array.from(token.replace(/"[^"]*"/, "").matchAll(/\d+/g), (m) => Number(m[0]));
      if (!onCite) {
        // General text cites nothing: a stray marker is removed, and the
        // space it leaves before punctuation with it.
        if (out.length && typeof out[out.length - 1] === "string") {
          out[out.length - 1] = (out[out.length - 1] as string).replace(/[ \t]+$/, "");
        }
        continue;
      }
      out.push(
        <sup key={key++} className="ms-0.5">
          {numbers.map((n, i) => (
            <button
              key={`${n}-${i}`}
              type="button"
              aria-label={`Source ${n}`}
              aria-pressed={activeSource === n - 1}
              onClick={() => onCite(n - 1)}
              className={[
                // Inline in a sentence, so exempt from the 44px target floor (WCAG
                // 2.5.8 inline exception): the floor would open a gap in the line.
                "mx-px min-h-0 rounded px-0.5 font-mono text-[0.75em] font-semibold leading-none motion-safe:transition-colors",
                activeSource === n - 1 ? "bg-signal-500/20 text-signal-300" : "text-signal-400 hover:text-signal-300",
              ].join(" ")}
            >
              {n}
            </button>
          ))}
        </sup>,
      );
    } else {
      out.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

export function Markdown({
  text,
  onCite,
  activeSource = null,
  className = "",
}: {
  text: string;
  onCite?: (index: number) => void;
  activeSource?: number | null;
  className?: string;
}) {
  const blocks = blocksOf(text);
  return (
    <div className={`chat-markdown space-y-3 text-[15px] leading-7 text-slateish-200 ${className}`}>
      {blocks.map((b, i) => {
        if (b.kind === "heading") {
          return (
            <p key={i} role="heading" aria-level={b.level + 2} className="font-semibold text-slateish-100">
              <Inline text={b.text} onCite={onCite} activeSource={activeSource} />
            </p>
          );
        }
        if (b.kind === "list") {
          const List = b.ordered ? "ol" : "ul";
          return (
            <List key={i} className={`${b.ordered ? "list-decimal" : "list-disc"} space-y-1 ps-6 marker:text-slateish-500`}>
              {b.items.map((item, j) => (
                <li key={j}>
                  <Inline text={item} onCite={onCite} activeSource={activeSource} />
                </li>
              ))}
            </List>
          );
        }
        return (
          <p key={i}>
            {b.lines.map((line, j) => (
              <span key={j}>
                {j > 0 && <br />}
                <Inline text={line} onCite={onCite} activeSource={activeSource} />
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}
