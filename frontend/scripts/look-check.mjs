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
const OPEN_FOLDS = process.env.LOOK_CHECK_FOLDS !== "closed";

/** Runs in the page: every visible text with its contrast, the short labels that wrap, and the main heading. */
function readPage() {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
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
    // a disabled control is exempt from the contrast rule (WCAG 1.4.3: inactive parts of the interface)
    return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0.05 && !el.closest("[aria-hidden=true], .sr-only, :disabled, [aria-disabled=true]");
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
  return { low, wraps, h1, sizes, caps };
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
    const r = await page.evaluate(readPage);
    const titleOk = r.h1 !== null && r.h1.toLowerCase().includes(menu.toLowerCase().replace(" & ", " ").split(" ")[0]);
    // every failure grouped by colour pair: one shared colour token usually explains many
    const pairs = {};
    for (const l of r.low) { const k = `${l.color} on ${l.background}`; pairs[k] = (pairs[k] ?? 0) + 1; }
    report.push({ mode, path, menu, lowContrast: r.low.length, wraps: r.wraps, allCaps: r.caps, title: r.h1, titleMatchesMenu: titleOk, fontSizes: r.sizes, pairs, worst: r.low.sort((a, b) => a.ratio - b.ratio).slice(0, 8) });
  }
  await ctx.close();
}
await browser.close();

const failing = report.filter((p) => p.lowContrast || p.wraps.length || p.allCaps.length || !p.titleMatchesMenu);
const sizes = [...new Set(report.flatMap((p) => Object.keys(p.fontSizes)))].sort((a, b) => parseFloat(a) - parseFloat(b));
const summary = {
  pages: report.length, failingPages: failing.length,
  lowContrastTexts: report.reduce((n, p) => n + p.lowContrast, 0),
  wrappingLabels: report.reduce((n, p) => n + p.wraps.length, 0),
  titleMismatches: report.filter((p) => !p.titleMatchesMenu).length,
  allCapsLabels: report.reduce((n, p) => n + p.allCaps.length, 0),
  fontSizesInUse: sizes,
  foldsOpened: OPEN_FOLDS,
};
console.log(JSON.stringify(summary));
for (const p of report) console.log(`${p.mode.padEnd(5)} ${p.menu.padEnd(28)} low contrast ${String(p.lowContrast).padStart(3)} · wraps ${p.wraps.length} · all caps ${p.allCaps.length} · title ${p.titleMatchesMenu ? "ok" : `"${p.title}"`}`);
if (OUT) writeFileSync(OUT, JSON.stringify({ summary, report }, null, 2));
process.exit(failing.length ? 1 : 0);
