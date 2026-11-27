#!/usr/bin/env node
/**
 * THE LOOK CHECK (owner, 26 Nov 2026 23:05: "why do I have to tell"): before a page is called done, a machine reads every page of the
 * running app, in light AND dark, at laptop width, and fails on what the owner found by hand:
 *   - CONTRAST: any visible text whose colour against its own background is under 4.5 : 1 (WCAG AA; the owner's readable minimum).
 *   - WRAPPING: a short label (a button, link, tab, chip or label of at most four words) that breaks onto a second line.
 *   - TITLE: the page's main heading differs from its name in the side menu.
 *   - ALL CAPS: a label written in capitals by style (the spec: sentence case, bold).
 * Every fold (<details>) on the page is opened first, so the text a reader sees after one click is measured too; set
 * LOOK_CHECK_FOLDS=closed to measure only what shows on arrival.
 * It reads only what is on screen; it changes nothing. Run it against a practice copy, never the live app:
 *
 *   node frontend/scripts/look-check.mjs http://127.0.0.1:5191 out.json
 *
 * Exit 1 when any page fails, 0 otherwise. Uses the Chrome installed on this computer (Playwright's channel "chrome").
 */
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.argv[2] ?? "http://127.0.0.1:5191";
const OUT = process.argv[3] ?? null;
/** The 11 menu pages and the menu name each one's title must carry. */
export const PAGES = [
  ["/dashboard", "Dashboard"], ["/review", "AI Submittal Review"], ["/documents", "Documents"], ["/standards", "Standards Library"],
  ["/analysis", "Analysis Hub"], ["/chat", "Chat"], ["/reports", "CRS & Reports"], ["/deliverables", "Deliverables"],
  ["/ingestion", "Ingestion"], ["/technicalQueries", "Technical Queries and CFCs"], ["/admin", "Administration"],
];
export const MIN_CONTRAST = 4.5;
// LOOK_CHECK_ONLY="/kit.html|Shared kit": measure just that page (the kit's preview) instead of the 11 menu pages
if (process.env.LOOK_CHECK_ONLY) PAGES.splice(0, PAGES.length, process.env.LOOK_CHECK_ONLY.split("|"));
const OPEN_FOLDS = process.env.LOOK_CHECK_FOLDS !== "closed";
const EXEMPT_DISABLED = process.env.LOOK_CHECK_DISABLED === "exempt";
/** A narrow window (a small laptop, or a split screen): no page may scroll sideways at this width (owner's live walk, 27 Nov 2026). */
export const NARROW_WIDTH = 803;

/** Runs in the page: WORDS broken across lines inside a button, link or chip (F's scan, 27 Nov 2026: "Op / en", "No t si gn ed" passed
 *  every other check). A word of more than 15 characters (a standard's file name) may break; a shorter one never. */
function splitWords() {
  const out = [];
  const els = [...document.querySelectorAll("main button, main a, main span")].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && e.childElementCount === 0 && (e.textContent || "").trim(); });
  for (const e of els) {
    const n = e.firstChild; if (!n || n.nodeType !== 3) continue;
    for (const m of n.textContent.matchAll(/\S+/g)) {
      if (m[0].length > 15) continue;
      const rg = document.createRange();
      try { rg.setStart(n, m.index); rg.setEnd(n, m.index + m[0].length); } catch { continue; }
      if (new Set([...rg.getClientRects()].map((x) => Math.round(x.top))).size > 1) { out.push(m[0]); break; }
    }
  }
  return out;
}

/** Runs in the page: how much wider than the window it is, and the widest elements that stick out (tag, classes, width). */
function tooWide() {
  const W = document.documentElement.clientWidth;
  const over = document.documentElement.scrollWidth - W;
  if (over <= 0) return { over: 0, culprits: [] };
  const culprits = [...document.querySelectorAll("body *")].map((el) => ({ el, r: el.getBoundingClientRect() }))
    .filter(({ r }) => r.right > W + 1 && r.width > 0)
    .sort((a, b) => b.r.right - a.r.right).slice(0, 5)
    .map(({ el, r }) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 4).join(".")} right=${Math.round(r.right)} w=${Math.round(r.width)}`);
  return { over, culprits };
}

/** Runs in the page: every visible text with its contrast, the short labels that wrap, and the main heading. */
function readPage(EXEMPT_DISABLED) {
  // ANY CSS colour, read by the browser itself (owner's live walk, 27 Nov 2026: Tailwind's see-through colours, such as bg-ink-850/60,
  // compute to oklab()/color-mix(), which a pattern for rgb() could not read, so those layers were skipped and Ingestion's 2.8 : 1 passed)
  const paint = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const parse = (c) => {
    if (!c || c === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
    const m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m) { const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    paint.clearRect(0, 0, 1, 1); paint.fillStyle = "#000"; paint.fillStyle = c; paint.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = paint.getImageData(0, 0, 1, 1).data;
    return { r, g, b, a: a / 255 };
  };
  const over = (top, under) => ({
    r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1,
  });
  const background = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    const htmlBg = parse(getComputedStyle(document.body).backgroundColor);
    if (htmlBg && htmlBg.a > 0) bg = htmlBg.a >= 1 ? htmlBg : over(htmlBg, bg);
    for (let i = layers.length - 1; i >= 0; i--) bg = layers[i].a >= 1 ? layers[i] : over(layers[i], bg);
    return bg;
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const shown = (el) => {
    if (el.closest("details:not([open])") && !el.closest("summary")) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = getComputedStyle(el);
    // a disabled control is held to the same rule (owner's live walk, 27 Nov 2026: a disabled "Run analysis" at 1.1 : 1 is unreadable,
    // whatever WCAG 1.4.3 exempts); LOOK_CHECK_DISABLED=exempt gives the WCAG reading
    return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0.05 && !el.closest(EXEMPT_DISABLED ? "[aria-hidden=true], .sr-only, :disabled, [aria-disabled=true]" : "[aria-hidden=true], .sr-only");
  };
  const low = [];
  const sizes = {};
  for (const el of document.querySelectorAll("body *")) {
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();
    if (!own || !shown(el)) continue;
    const s = getComputedStyle(el);
    sizes[s.fontSize] = (sizes[s.fontSize] ?? 0) + 1;
    const fg = parse(s.color);
    if (!fg) continue;
    // faded text (an opacity on the element or any parent) is as faint as it looks: its alpha carries every opacity above it
    for (let e = el; e; e = e.parentElement) fg.a *= Number(getComputedStyle(e).opacity);
    const bg = background(el);
    const value = ratio(fg.a >= 1 ? fg : over(fg, bg), bg);
    if (value < 4.5) low.push({ text: own.slice(0, 50), ratio: Math.round(value * 100) / 100, color: s.color, background: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`, size: s.fontSize, where: el.closest("nav, aside") ? "menu" : "page" });
  }
  const wraps = [];
  for (const el of document.querySelectorAll("button, a, label, summary, [role=tab], span[class*=rounded-full]")) {
    const text = (el.textContent ?? "").trim().replace(/\s+/g, " ");
    // a label that holds its own field (an input, a select) spans two lines by design: only the words are checked
    if (!text || text.split(" ").length > 4 || !shown(el) || el.querySelector("input, select, textarea")) continue;
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.3;
    const rects = [...el.getClientRects()];
    const tall = el.getBoundingClientRect().height > lineHeight * 1.8 + 24; // padding allowed
    const lines = new Set(rects.map((r) => Math.round(r.top))).size;
    if (lines > 1 || (tall && el.tagName !== "BUTTON")) wraps.push(text.slice(0, 40));
  }
  // labels written in capitals by style (the spec: sentence case, bold)
  const caps = [...document.querySelectorAll("main *")].filter((el) => getComputedStyle(el).textTransform === "uppercase" && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && shown(el)).map((el) => el.textContent.trim().slice(0, 30));
  const h1 = document.querySelector("main h1")?.textContent?.trim() ?? null;
  // SAMENESS (owner, 27 Nov 2026 03:30: five button looks, chips boxed here and plain there, three title styles): how many DIFFERENT
  // looks this page uses for a button, a chip and a page title; the shared kit's target is 1 each (a disabled button is its own state)
  const look = (el, keys) => { const st = getComputedStyle(el); return keys.map((k) => st[k]).join("|"); };
  // a button's look is its fill, edge, corner, weight and words' colour (its size, small or normal, is not a different look); a tile
  // is a card that opens a list, counted with the cards, not the buttons. The kit's target: 2 (one primary, one secondary).
  const btnKeys = ["backgroundColor", "borderTopColor", "borderTopWidth", "borderTopLeftRadius", "fontWeight", "color"];
  const buttons = [...document.querySelectorAll("main button, main a.kit-btn")].filter((el) => shown(el) && !el.matches(":disabled, [aria-disabled=true], [role=tab], summary, .kit-tile, .kit-row-btn, .kit-chip-btn"));
  // a list row, a tile and a chip button are kit parts of their own (one look each by construction), not action buttons
  const buttonLooks = new Set(buttons.map((el) => look(el, btnKeys)));
  const chips = [...document.querySelectorAll("main span, main a")].filter((el) => { const st = getComputedStyle(el); return shown(el) && parseFloat(st.borderTopLeftRadius) >= 9 && parseFloat(st.borderTopWidth) > 0 && el.getBoundingClientRect().height < 32; });
  const chipShapes = new Set(chips.map((el) => look(el, ["borderTopLeftRadius", "borderTopWidth", "fontSize", "fontWeight", "paddingLeft"])));
  const titles = [...document.querySelectorAll("main h1")].filter(shown);
  const titleLooks = new Set(titles.map((el) => look(el, ["fontSize", "fontWeight", "color"])));
  return { low, wraps, h1, sizes, caps, sameness: { buttonLooks: buttonLooks.size, chipShapes: chipShapes.size, titleLooks: titleLooks.size, titles: titles.length } };
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const report = [];
for (const mode of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: mode });
  await ctx.addInitScript((m) => { try { localStorage.setItem("rag-intelligence-theme", m); } catch { /* no storage */ } }, mode);
  const page = await ctx.newPage();
  for (const [path, menu] of PAGES) {
    await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(1500);
    if (OPEN_FOLDS) {  // a fold opened shows text a reader sees after one click: measure it too (twice: a fold may hold folds)
      for (let i = 0; i < 2; i++) await page.evaluate(() => document.querySelectorAll("details:not([open])").forEach((d) => { d.open = true; }));
      await page.waitForTimeout(300);
    }
    const r = await page.evaluate(readPage, EXEMPT_DISABLED);
    r.split = await page.evaluate(splitWords);
    // the page's visible main heading must BE its menu name (integrator, 27 Nov 2026: "Analysis" passed for "Analysis Hub" and
    // "Deliverables & timeline" for "Deliverables" while only the first word was compared); case, spacing and "&"/"and" aside
    const norm = (t) => String(t ?? "").toLowerCase().replace(/&/g, " and ").replace(/\s+/g, " ").trim();
    const titleOk = r.h1 !== null && norm(r.h1) === norm(menu);
    // every failure grouped by colour pair: one shared colour token usually explains many
    const pairs = {};
    for (const l of r.low) { const k = `${l.color} on ${l.background}`; pairs[k] = (pairs[k] ?? 0) + 1; }
    report.push({ mode, path, menu, splitWords: r.split, sameness: r.sameness, lowContrast: r.low.length, wraps: r.wraps, allCaps: r.caps, title: r.h1, titleMatchesMenu: titleOk, fontSizes: r.sizes, pairs, worst: r.low.sort((a, b) => a.ratio - b.ratio).slice(0, 8) });
  }
  await ctx.close();
}
// THE NARROW WINDOW: every page at NARROW_WIDTH, once (width does not change with the theme)
const wide = [];
const narrowSplit = [];
{
  const ctx = await browser.newContext({ viewport: { width: NARROW_WIDTH, height: 800 } });
  const page = await ctx.newPage();
  for (const [path, menu] of PAGES) {
    await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(1500);
    const w = await page.evaluate(tooWide);
    if (w.over > 0) wide.push({ path, menu, overPx: w.over, culprits: w.culprits });
    const split = await page.evaluate(splitWords);
    if (split.length) narrowSplit.push({ path, menu, words: split.slice(0, 5), count: split.length });
  }
  await ctx.close();
}
await browser.close();

const failing = report.filter((p) => p.lowContrast || p.wraps.length || p.allCaps.length || !p.titleMatchesMenu || p.splitWords.length);
const failingCount = failing.length + wide.length + narrowSplit.length;
const sizes = [...new Set(report.flatMap((p) => Object.keys(p.fontSizes)))].sort((a, b) => parseFloat(a) - parseFloat(b));
const summary = {
  pages: report.length, failingPages: failing.length,
  lowContrastTexts: report.reduce((n, p) => n + p.lowContrast, 0),
  wrappingLabels: report.reduce((n, p) => n + p.wraps.length, 0),
  titleMismatches: report.filter((p) => !p.titleMatchesMenu).length,
  allCapsLabels: report.reduce((n, p) => n + p.allCaps.length, 0),
  fontSizesInUse: sizes,
  foldsOpened: OPEN_FOLDS,
  disabledCounted: !EXEMPT_DISABLED,
  tooWideAt803: wide.length,
  splitWords: report.reduce((n, p) => n + p.splitWords.length, 0),
  splitWordsAt803: narrowSplit.reduce((n, p) => n + p.count, 0),
};
console.log(JSON.stringify(summary));
for (const p of report) console.log(`${p.mode.padEnd(5)} ${p.menu.padEnd(28)} low contrast ${String(p.lowContrast).padStart(3)} · wraps ${p.wraps.length} · all caps ${p.allCaps.length} · title ${p.titleMatchesMenu ? "ok" : `"${p.title}"`}`);
for (const p of report.filter((x) => x.mode === "light")) console.log(`looks ${p.menu.padEnd(28)} buttons ${p.sameness.buttonLooks} · chip shapes ${p.sameness.chipShapes} · title styles ${p.sameness.titleLooks} (${p.sameness.titles} h1)`);
for (const p of report.filter((x) => x.splitWords.length)) console.log(`split ${p.mode} ${p.menu.padEnd(22)} words broken across lines: ${p.splitWords.slice(0, 5).join(", ")}`);
for (const n of narrowSplit) console.log(`split 803 ${n.menu.padEnd(24)} ${n.count} words broken across lines: ${n.words.join(", ")}`);
for (const w of wide) console.log(`narrow ${w.menu.padEnd(28)} ${w.overPx}px wider than a ${NARROW_WIDTH}px window: ${w.culprits[0] ?? ""}`);
if (OUT) writeFileSync(OUT, JSON.stringify({ summary, report, wide, narrowSplit }, null, 2));
process.exit(failingCount ? 1 : 0);
