import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

type Rgb = [number, number, number];

function parseHex(value: string): Rgb {
  const hex = value.replace("#", "");
  return [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255) as Rgb;
}

function luminance(rgb: Rgb): number {
  const linear = rgb.map((channel) =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  ) as Rgb;
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground: Rgb, background: Rgb): number {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function blend(foreground: Rgb, background: Rgb, alpha: number): Rgb {
  return foreground.map((channel, index) => channel * alpha + background[index] * (1 - alpha)) as Rgb;
}

function tokensFor(css: string, selector: string): Record<string, Rgb> {
  const start = css.indexOf(selector);
  const end = start < 0 ? -1 : css.indexOf("\n}\n", start);
  const block = start >= 0 && end >= 0 ? css.slice(start, end) : "";
  return Object.fromEntries(
    [...block.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((match) => [match[1], parseHex(match[2])]),
  );
}

const css = readFileSync(path.join(process.cwd(), "src", "index.css"), "utf8");
const light = tokensFor(css, ':root[data-theme="light"]');
const dark = tokensFor(css, ':root[data-theme="dark"]');

describe("text token contrast", () => {
  it("keeps every readable tertiary, quiet, warning, and status pair above WCAG AA", () => {
    const pairs: Array<[string, Record<string, Rgb>, string, string]> = [
      ["light quiet on sidebar", light, "slateish-500", "ink-850"],
      ["light quiet on page", light, "slateish-500", "ink-900"],
      ["light tertiary on sidebar", light, "slateish-400", "ink-850"],
      ["light tertiary on card", light, "slateish-400", "ink-800"],
      ["light warning on page", light, "warn-500", "ink-900"],
      ["dark quiet on sidebar", dark, "slateish-500", "ink-850"],
      ["dark quiet on card", dark, "slateish-500", "ink-800"],
      ["dark tertiary on sidebar", dark, "slateish-400", "ink-850"],
      ["dark tertiary on active", dark, "slateish-400", "ink-700"],
      ["dark warning on card", dark, "warn-500", "ink-800"],
    ];
    for (const [label, theme, foreground, background] of pairs) {
      expect(theme[foreground], `${label} foreground token`).toBeDefined();
      expect(theme[background], `${label} background token`).toBeDefined();
      expect(contrast(theme[foreground], theme[background]), label).toBeGreaterThanOrEqual(4.5);
    }

    const overlays: Array<[string, Record<string, Rgb>, string, string, string, number]> = [
      ["light quiet on signal overlay", light, "slateish-500", "signal-500", "ink-850", 0.1],
      ["light tertiary on signal overlay", light, "slateish-400", "signal-500", "ink-850", 0.1],
      ["light warning on warning overlay", light, "warn-500", "warn-500", "ink-900", 0.15],
      ["dark quiet on signal overlay", dark, "slateish-500", "signal-500", "ink-850", 0.1],
      ["dark tertiary on signal overlay", dark, "slateish-400", "signal-500", "ink-850", 0.1],
      ["dark warning on warning overlay", dark, "warn-500", "warn-500", "ink-800", 0.15],
    ];
    for (const [label, theme, foreground, overlay, surface, alpha] of overlays) {
      expect(
        contrast(theme[foreground], blend(theme[overlay], theme[surface], alpha)),
        label,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});
