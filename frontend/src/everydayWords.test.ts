/**
 * E3 EVERYDAY WORDS (owner, 26 Nov 2026, goal G9 "easy to use"; lead-4; builder H).
 *
 * The client's engineer reads every screen. The words the system uses for its own insides (engine, passage, chunk, ingestion, kind, scope,
 * checklist, judge, worker, queue, model names, setting codes ...) are not shown outside "Advanced": the screen says the everyday word
 * instead (docs/ui-glossary.md, "Everyday words"). This test reads every frontend source file with a real parser and looks only at text a
 * person SEES: JSX text, a text attribute (title, aria-label, placeholder, label, alt), a string literal that reads as words (it holds
 * a space or starts with a capital letter), and template text. Whole words only, any case. Code names, keys, routes and API paths are
 * never looked at, so they stay as they are.
 *
 * Not checked here (their own owners): the Shell, menu and screen names (G); the answer panels (C, E5). Allowed to keep internal words:
 * ADVANCED, i.e. the Admin screen and the folded technical-details parts.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { parseAst } from "rolldown/parseAst";
import { describe, expect, it } from "vitest";

/** The internal words (whole words, any case). */
export const INTERNAL = [
  "engine", "engines", "ingestion", "ingest", "ingested", "ingesting", "lane", "lanes", "chunk", "chunks", "passage", "passages",
  "corpus", "rerank", "reranker", "reranking", "kind", "kinds", "scope", "scopes", "checklist", "checklists", "judge", "judged",
  "judges", "attack", "attacks", "attacked", "worker", "workers", "queue", "queued", "queues", "job", "jobs", "run id", "token",
  "tokens", "latency", "embedding", "embeddings", "vector", "vectors", "pipeline", "fts", "payload", "endpoint", "json", "sqlite",
  "llm", "prompt", "prompts", "inference", "provider", "egress", "stage", "stages", "routing", "routed", "general review",
  "local model", "route", "routes", "model", "models", "qwen", "ollama", "llama", "sonnet", "opus", "haiku",
];
const WORD = new RegExp(
  `(?<![A-Za-z0-9_])(${INTERNAL.map((w) => w.replace(/ /g, "\\s+")).join("|")})(?![A-Za-z0-9_])`,
  "gi",
);
/** Everyday English that only LOOKS like an internal word: "this kind of paper", "yours to judge". */
const EVERYDAY = [/\bkinds? of\b/gi, /\b(?:yours|you) to judge\b/gi];
/** Literal values that are lookup KEYS matched against the server's reason text, never shown (the plain sentence beside them is). */
const KEYS_NOT_SHOWN = new Set([
  "this paper kind has no field list",
  "this paper kind's field list does not carry the field",
  "second opinion model is the same or unknown",
]);
/** Text inside another owner's panel in a file that is otherwise judged: C's evidence and draft-answer part (E5) of Technical Queries. */
const OWNED_TEXT: { file: RegExp; text: RegExp; owner: string }[] = [
  { file: /^views\/TechnicalQueriesView\.tsx$/, text: /Found by the system/, owner: "C, E5" },
];
/** A setting's code name (AI_..., ..._ENABLED): never shown; the screen says what the setting does. */
const CODE = /\b(?:AI_[A-Z0-9_]+|[A-Z][A-Z0-9_]+_ENABLED)\b/g;
/** A screen's own heading line is G's (E1: screen-header lines): not judged here. */
const SCREEN_HEADER = new Set(["h1"]);
/** JSX attributes that never hold text a person reads; every OTHER attribute's string (title, label, hint, eyebrow, ...) is text. */
const NON_TEXT_ATTRS = new Set([
  "className", "id", "key", "href", "src", "type", "role", "name", "value", "defaultValue", "htmlFor", "autoComplete", "rel", "target",
  "method", "action", "style", "inputMode", "pattern", "accept", "form", "lang", "dir", "tabIndex", "aria-controls",
  "aria-describedby", "aria-labelledby", "aria-live", "aria-current", "aria-hidden", "aria-expanded", "aria-checked", "testId",
]);

/** Files this test does not judge: their own owners (G: Shell and menu; C: answer panels) and ADVANCED (may keep internal words). */
const NOT_JUDGED = [
  /^components\/Shell\.tsx$/, /^components\/CommandPalette\.tsx$/, /^routing\.ts$/, /^App\.tsx$/, // G
  // (the Chat answer panels, C's, are judged since the words job: C agreed, 27 Nov 2026)
  /^components\/review\/(crs\/|v2\/PointsList)/, // C, E5: the review result panel
  /^views\/(AdminScreen|AdminView)\.tsx$/, /^views\/admin\//, // ADVANCED: the Admin screen
  /DashboardTechnicalDetails|DocumentTechnicalDetails|ChunkInspector|FreeModelMemory/, // ADVANCED: folded technical details
];

type Hit = { file: string; line: number; word: string };
type Node = { type?: string; start?: number; [k: string]: unknown };

function isWordy(node: Node, parent: Node | null, text: string): boolean {
  if (!parent) return false;
  if (parent.type === "JSXAttribute") {
    const attr = String((parent.name as Node | undefined)?.name ?? "");
    if (NON_TEXT_ATTRS.has(attr) || attr.startsWith("data-") || /^on[A-Z]/.test(attr)) return false;
  }
  const notText = ["ImportDeclaration", "ExportNamedDeclaration", "ExportAllDeclaration", "ImportExpression", "TSLiteralType"];
  if (notText.includes(String(parent.type))) return false;
  if (parent.type === "BinaryExpression" && /^[!=]==?$/.test(String(parent.operator))) return false;
  if ((parent.type === "Property" || parent.type === "PropertyDefinition") && parent.key === node) return false;
  if (parent.type === "SwitchCase" || parent.type === "MemberExpression") return false;
  if (/^\/?api\//.test(text) || /^[a-z0-9_.\-/:]+$/.test(text)) return false; // ids, keys, paths, class names
  if (/^[A-Z][A-Z0-9_]+$/.test(text) || KEYS_NOT_SHOWN.has(text)) return false; // a code name held as data; a lookup key
  const tokens = text.trim().split(/\s+/);
  const cssLike = tokens.every((t) => /^[a-z0-9:[\]/.%_!-]+$/.test(t)) && tokens.filter((t) => /[-:[/]/.test(t)).length * 2 >= tokens.length;
  if (cssLike) return false; // a class name list ("model-prose border-l-2 ..."), not text
  return /\s/.test(text.trim()) || /^[A-Z]/.test(text);
}

/** Every internal word a person would SEE in `source`. */
export function shownInternalWords(source: string, file: string): Hit[] {
  const hits: Hit[] = [];
  const owned = OWNED_TEXT.filter((o) => o.file.test(file));
  for (const { raw, line } of shownTexts(source, file)) {
    if (owned.some((o) => o.text.test(raw))) continue;
    const text = EVERYDAY.reduce((t, rx) => t.replace(rx, " "), raw);
    for (const m of text.matchAll(WORD)) hits.push({ file, line, word: m[1].toLowerCase().replace(/\s+/g, " ") });
    for (const m of text.matchAll(CODE)) hits.push({ file, line, word: m[0] });
  }
  return hits;
}

/** Every piece of text a person would SEE in `source` (JSX text, a text attribute, a wordy string, template text), with its line. */
export function shownTexts(source: string, file: string): { raw: string; line: number }[] {
  const out: { raw: string; line: number }[] = [];
  const lineOf = (pos: number) => source.slice(0, pos).split("\n").length;
  const scan = (raw: string, pos: number) => out.push({ raw, line: lineOf(pos) });
  const ast = parseAst(source, { lang: file.endsWith("x") ? "tsx" : "ts" }, file) as unknown as Node;
  const walk = (n: unknown, parent: Node | null): void => {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) {
      for (const x of n) walk(x, parent);
      return;
    }
    const node = n as Node;
    if (node.type === "JSXText") scan(String(node.value), node.start ?? 0);
    else if (node.type === "Literal" && typeof node.value === "string") {
      if (isWordy(node, parent, node.value)) scan(node.value, node.start ?? 0);
    } else if (node.type === "TemplateLiteral" && parent?.type !== "TaggedTemplateExpression") {
      const quasis = node.quasis as { value: { cooked?: string; raw: string } }[];
      const text = quasis.map((q) => q.value.cooked ?? q.value.raw).join("");
      if (/\s/.test(text.trim()) && !/^[/?]/.test(text)) scan(text, node.start ?? 0); // a URL template is not text
    }
    if (node.type === "JSXElement" && SCREEN_HEADER.has(String(((node.openingElement as Node)?.name as Node)?.name))) return;
    for (const k of Object.keys(node)) if (k !== "parent" && node[k] && typeof node[k] === "object") walk(node[k], node);
  };
  walk(ast, null);
  return out;
}

/** PAGES REWRITTEN TO docs/WORDS.md (owner, 27 Nov 2026 10:57: "the TEXT ... written as well as possible, so anyone understands it
 *  easily"). Here the WORDS.md "Never on a screen" words are refused too, and a screen sentence over 25 words fails. A page joins this
 *  list in the PR that rewrites it. */
export const WORDS_DONE: RegExp[] = [
  /^views\/TechnicalQueriesView\.tsx$/, /^views\/technicalQueryQuestion\.ts$/, /^views\/TechnicalQueryCrossRefs\.tsx$/,
  /^views\/TechnicalQueryPosition\.tsx$/,
  // Documents (words job page 2)
  /^views\/DocumentsView\.tsx$/, /^components\/(DocumentCard|DocumentPreview|ExcludedViewer|PageImageViewer|Uploader|WorkerPanel)\.tsx$/,
  /^components\/classification\/(DocumentFilters|MetadataEditor|TypeFilter)\.tsx$/, /^components\/classification\/registerLabels\.ts$/,
  // Dashboard (words job page 3; its folded technical details may keep technical words)
  /^views\/(DashboardView|DashboardViewContent|DashboardPrimitives)\.tsx$/, /^components\/dashboard\/(AtAGlance|GlanceTiles|MetricWarning)\.tsx$/,
  // Review list (words job page 4)
  /^views\/SubmittalsLandingView\.tsx$/, /^components\/review\/workspace\/landing\/[A-Za-z]+\.tsx?$/,
  /^components\/review\/workspace\/(NewReviewDropZone|ViewModeSwitch)\.tsx$/, /^components\/review\/workspace\/(newReview|reviewWatch)\.ts$/,
  // the opened review's own lines (words job; H's review of the owner's file R3, R4, R6, R7, R8)
  /^components\/review\/general\/(GeneralResults|GeneralHistory|MeasuredBadge|HowReviewMade)\.tsx$/,
  // CRS and Reports (words job)
  /^views\/(ReportsScreen|ReportsView|ReviewCrsList)\.tsx$/,
  // Administration (words job; it may still name the AI models a person chooses between, so it keeps its place in NOT_JUDGED)
  /^views\/(AdminScreen|AdminView)\.tsx$/, /^views\/admin\/[A-Za-z]+\.tsx$/,
  // Chat (words job), its answer panels included
  /^views\/ChatView\.tsx$/, /^components\/chat\/[A-Za-z]+\.tsx?$/,
  // Standards (words job, the rest)
  /^views\/(StandardsView\.tsx|standardsLibrary\.ts)$/, /^components\/standards\/[A-Za-z]+\.tsx$/,
];
/** docs/WORDS.md "Never on a screen" (whole words or phrases, any case). */
export const NEVER = [
  "attachment", "attachments", "metadata", "extraction", "recognition", "mitigation", "carries the code", "fills itself",
  "form's own question section", "passage", "passages", "evidence", "provenance", "supersession", "found by the system",
];
const NEVER_RX = new RegExp(`(?<![A-Za-z0-9_])(${NEVER.map((w) => w.replace(/ /g, "\\s+")).join("|")})(?![A-Za-z0-9_])`, "gi");
/** A screen sentence's longest allowed length, in words (owner's rule: one idea, 15 words or fewer; over 25 fails the build). */
export const MAX_WORDS = 25;

/** On a rewritten page: the WORDS.md words a person would see, and every shown sentence over MAX_WORDS words. */
export function wordsDoneFindings(source: string, file: string): string[] {
  const found: string[] = [];
  for (const { raw, line } of shownTexts(source, file)) {
    // a class list ("evidence-quote mt-1.5 rounded-[var(--radius-sm)] ...") is styling, not text a person reads
    const tokens = raw.trim().split(/\s+/);
    if (tokens.length >= 3 && tokens.filter((t) => /[-[\]:]/.test(t)).length * 10 >= tokens.length * 6 && !/[.!?]$/.test(raw.trim())) continue;
    for (const m of raw.matchAll(NEVER_RX)) found.push(`${file}:${line} "${m[1]}"`);
    for (const sentence of raw.split(/(?<=[.!?])\s+/)) {
      const words = sentence.trim().split(/\s+/).filter(Boolean).length;
      if (words > MAX_WORDS) found.push(`${file}:${line} ${words} words: "${sentence.trim().slice(0, 80)}..."`);
    }
  }
  return found;
}

const SRC = resolve(__dirname);
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx?$/.test(e) && !/\.test\.tsx?$/.test(e) && !/\.d\.ts$/.test(e) ? [p] : [];
  });
}

describe("E3 everyday words", () => {
  it("shows no internal word outside Advanced and the parts other owners keep", () => {
    const hits = sources(SRC)
      .map((p) => relative(SRC, p).split("\\").join("/"))
      .filter((rel) => !NOT_JUDGED.some((rx) => rx.test(rel)))
      .flatMap((rel) => shownInternalWords(readFileSync(join(SRC, rel), "utf8"), rel));
    const shown = hits.map((h) => `${h.file}:${h.line} ${h.word}`);
    expect(shown.length, `internal words shown on a screen:\n${shown.join("\n")}`).toBe(0);
  });

  it("on a page rewritten to docs/WORDS.md, shows none of its never-on-a-screen words and no sentence over 25 words", () => {
    const found = sources(SRC)
      .map((p) => relative(SRC, p).split("\\").join("/"))
      .filter((rel) => WORDS_DONE.some((rx) => rx.test(rel)))
      .flatMap((rel) => wordsDoneFindings(readFileSync(join(SRC, rel), "utf8"), rel));
    expect(found.length, `words to rewrite (docs/WORDS.md):\n${found.join("\n")}`).toBe(0);
  });

  it("the WORDS.md check can fail: a planted banned word and a planted long sentence are found", () => {
    const long = Array.from({ length: 26 }, (_, i) => `word${i}`).join(" ");
    const planted = `export const A = () => <p>The attachment metadata is read. ${long}.</p>;`;
    expect(wordsDoneFindings(planted, "planted.tsx")).toEqual([
      'planted.tsx:1 "attachment"', 'planted.tsx:1 "metadata"', `planted.tsx:1 26 words: "${long.slice(0, 80)}..."`,
    ]);
  });

  it("can fail: it finds a planted internal word in shown text and ignores the same word in code", () => {
    const planted = [
      "export const A = () => <S eyebrow=\"Run id\" className=\"model-x\">The engine read 3 passages</S>;",
      "const k = row.kind === \"datasheet\" ? `${n} parts of pages` : \"\";",
      "const s = \"AI_CLAUSE_CHECKS_ENABLED is on\";",
      "const e = \"This kind of paper is yours to judge\"; const c = { setting: \"AI_CLAUSE_CHECKS_ENABLED\" };",
    ].join("\n");
    const words = shownInternalWords(planted, "planted.tsx").map((h) => h.word);
    expect(words).toEqual(["run id", "engine", "passages", "AI_CLAUSE_CHECKS_ENABLED"]);
  });
});
