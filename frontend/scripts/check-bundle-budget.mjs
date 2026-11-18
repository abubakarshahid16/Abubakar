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
const max = 319000;
const files = (await readdir(root)).filter((name) => /\.(js|css)$/.test(name));
let total = 0;
for (const file of files) total += gzipSync(await (await import("node:fs/promises")).readFile(join(root, file))).length;
console.log(`Initial asset gzip: ${total} bytes across ${files.length} assets (budget ${max})`);
if (total > max) process.exit(1);
