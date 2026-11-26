import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const root = join(process.cwd(), "dist", "assets");
// Round 13 (15 Nov 2026): 300 KiB -> 312000 bytes: +3,580 gzip bytes of real code (the list of documents before every start, the completeness banner).
// Order 14 (18 Nov 2026): 312000 -> 316000 bytes: the general review screens (+2.6 KB gzip) ship beside the earlier screens, which
// stay as the way back (REVIEW_OLD_ENGINE_ENABLED); lower it again when the earlier screens are removed. (This script sums every
// built .js/.css asset, lazy chunks included, so splitting code does not lower it.)
// Order 14 (18 Nov 2026, later): 316000 -> 317000 bytes: the general review's start-failure lines and running screen (G3, G4,
// about 0.7 KB gzip together); same way-back reason as above.
// After live (18 Nov 2026): 317000 -> 319000 bytes: the general review's "How this review was made" view (H, about 1.5 KB gzip).
// The earlier engine's screens still ship as the way back; retiring them after the new path is proven gives this back.
// After live 1 (18 Nov 2026): 319000 -> 320000 bytes: the live screen fixes (H3), the book-reason rule-5 wording (H4) and the
// confirmations count (H5); same way-back reason; retiring the earlier screens is on the after-proof list.
// After live 3 (18 Nov 2026): 320000 -> 324000 bytes: the comment cards, the engineer's decisions, the sign-off bar and the
// contractor copy (about 2.9 KB gzip); same way-back reason; retiring the earlier screens is on the after-proof list.
// Update 5 (19 Nov 2026): 324000 -> 325000 bytes: the contract parts read (How-made), the steps-not-run notice, the card / header /
// banner wording, the card chips, the plan-check timeout and the dashboard's general reviews (G; lead 4 allowed it); the earlier
// screens still ship as the way back; retiring them is on the after-proof list.
// Update 7 (25 Nov 2026): 325000 -> 325100 bytes: the "points decided by code" sentence in the results counts (A; the base
// had 4 bytes left; lead 4 to confirm); same way-back reason. The side-claim cut mark on the card (A, update 6) fits inside it.
// Update 7 (25 Nov 2026): 325100 -> 327000 bytes: a reason for every book, one chip per field with its pages, "Review this paper again",
// the AI's equipment in the header, "Choose Claude" for a held-back paper and the busy/stopped words (about 0.5 KB gzip; owner's deadline order).
// Technical queries (26 Nov 2026): 327000 -> 334000 bytes: technical queries screen, 26 Nov, lead decision (build 333496).
// Technical queries label fix (26 Nov 2026): 334000 -> 335000 bytes: technical queries label fix, 26 Nov, lead decision (build 334455).
// Update 9 (26 Nov 2026): 335000 -> 336000 bytes: update 9: zone-named times, in-page questions, score banner, 26 Nov, lead decision (build 335038).
// Update 10 (26 Nov 2026): 336000 -> 337000 bytes: update 10: Review model section, 26 Nov, lead decision (build 336107).
// Update 12 (26 Nov 2026): 337000 -> 339000 bytes: update 12: technical queries pages, draft guard, Chat, 26 Nov, lead decision (build 338387).
// Update 13 (26 Nov 2026): 339000 -> 340000 bytes: update 13: technical queries evidence, 26 Nov, lead decision (build 339095).
// Update 14 (26 Nov 2026): 340000 -> 341000 bytes: approved increase, from the look token file (look.css), needed for the restyle work; lead decision (build 340604).
// Update 15 (26 Nov 2026): 341000 -> 343000 bytes: approved increase, from the new-look restyle on all 11 pages (look.ts, LookParts), behind the off switch VITE_UI_NEW_LOOK; the owner decides the rollout; lead decision (build 342835).
// Update 16 (26 Nov 2026): 343000 -> 345000 bytes: approved increase, from the manager-view numbers (At a glance on the Dashboard) and the confirm-source-document button: content growth on the first screen; lead decision (build 344831).
// Update 17 (26 Nov 2026): 345000 -> 348000 bytes: approved increase, from the one-screen technical query page and the admin section for technical query reviewers: a real feature, not bloat; lead decision (build 347199). Later cleanup: the admin-only reviewers section can load lazily.
// Update 19 (26 Nov 2026): 348000 -> 350000 bytes: approved increase, from the owner's 7-point polish of the query page (build 348694); lead decision. The real fix, the admin-only reviewers section loaded lazily, is H's next small PR.
// (Superseded by the first-load gate below: the old all-asset total is printed, no longer gated.)
// First load (lead-4, 26 Nov 2026, option a): the gate measures what a user downloads first, no longer the sum of every asset. Chat,
// Technical Queries and the Review screens load when opened. Measured on the same build way: first load 300255 -> 261742 bytes (main
// 1dee12fa -> this change); all assets 347652 -> 355608 (splitting adds a little per chunk; printed, not gated). Budget 264000.
const max = 264000;
// FIRST LOAD (lead-4, 26 Nov 2026): the gate is what a new user downloads before the first screen draws: the files dist/index.html
// itself loads (its module script, its modulepreload links, its stylesheets). A screen loaded on demand (lazy) is not in it. The total
// of every asset is printed beside it, never gated, so lazy code stays visible and cannot hide growth.
const { readFile } = await import("node:fs/promises");
const gz = async (file) => gzipSync(await readFile(join(root, file))).length;
const files = (await readdir(root)).filter((name) => /\.(js|css)$/.test(name));
const html = await readFile(join(process.cwd(), "dist", "index.html"), "utf8");
const first = [...new Set([...html.matchAll(/(?:src|href)="\/assets\/([^"]+\.(?:js|css))"/g)].map((m) => m[1]))];
if (first.length === 0) { console.error("No first-load asset found in dist/index.html: build first."); process.exit(1); }
let firstLoad = 0;
for (const file of first) firstLoad += await gz(file);
let total = 0;
for (const file of files) total += await gz(file);
console.log(`First-load gzip: ${firstLoad} bytes across ${first.length} assets (budget ${max}); all assets, lazy included: ${total} bytes across ${files.length}`);
if (firstLoad > max) process.exit(1);
