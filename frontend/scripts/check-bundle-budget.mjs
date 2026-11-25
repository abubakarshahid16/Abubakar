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
// had 4 bytes left; lead 4 to confirm); same way-back reason.
// Update 7 (25 Nov 2026): 325100 -> 327000 bytes: a reason for every book, one chip per field with its pages, "Review this paper again",
// the AI's equipment in the header, "Choose Claude" for a held-back paper and the busy/stopped words (about 0.5 KB gzip; owner's deadline order).
// Technical queries (26 Nov 2026): 327000 -> 334000 bytes: technical queries screen, 26 Nov, lead decision (build 333496).
// Technical queries label fix (26 Nov 2026): 334000 -> 335000 bytes: technical queries label fix, 26 Nov, lead decision (build 334455).
const max = 335000;
const files = (await readdir(root)).filter((name) => /\.(js|css)$/.test(name));
let total = 0;
for (const file of files) total += gzipSync(await (await import("node:fs/promises")).readFile(join(root, file))).length;
console.log(`Initial asset gzip: ${total} bytes across ${files.length} assets (budget ${max})`);
if (total > max) process.exit(1);
