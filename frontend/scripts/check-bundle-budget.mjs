import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const root = join(process.cwd(), "dist", "assets");
// Round 13 (15 Nov 2026): 300 KiB -> 312000 bytes: +3,580 gzip bytes of real code (the list of documents before every start, the completeness banner).
// Order 14 (18 Nov 2026): 312000 -> 316000 bytes: the general review screens (+2.6 KB gzip) ship beside the earlier screens, which
// stay as the way back (REVIEW_OLD_ENGINE_ENABLED); lower it again when the earlier screens are removed. (This script sums every
// built .js/.css asset, lazy chunks included, so splitting code does not lower it.)
const max = 316000;
const files = (await readdir(root)).filter((name) => /\.(js|css)$/.test(name));
let total = 0;
for (const file of files) total += gzipSync(await (await import("node:fs/promises")).readFile(join(root, file))).length;
console.log(`Initial asset gzip: ${total} bytes across ${files.length} assets (budget ${max})`);
if (total > max) process.exit(1);
