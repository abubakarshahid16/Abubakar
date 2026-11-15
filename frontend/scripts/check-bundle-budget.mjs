import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const root = join(process.cwd(), "dist", "assets");
// Round 13 (15 Nov 2026): 300 KiB -> 312000 bytes: +3,580 gzip bytes of real code (the list of documents before every start, the completeness banner).
const max = 312000;
const files = (await readdir(root)).filter((name) => /\.(js|css)$/.test(name));
let total = 0;
for (const file of files) total += gzipSync(await (await import("node:fs/promises")).readFile(join(root, file))).length;
console.log(`Initial asset gzip: ${total} bytes across ${files.length} assets (budget ${max})`);
if (total > max) process.exit(1);
