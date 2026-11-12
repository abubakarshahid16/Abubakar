import { describe, expect, it } from "vitest";

import { equipmentLabel } from "./equipment";

describe("equipmentLabel", () => {
  it("shows one tag as it is and nothing for none", () => {
    expect(equipmentLabel(["P-100"])).toBe("P-100");
    expect(equipmentLabel([])).toBe("");
    expect(equipmentLabel(null)).toBe("");
  });
  it("shows the first tag and a count of the rest, never the whole string", () => {
    const tags = Array.from({ length: 40 }, (_, i) => `TAG-${i}`);
    expect(equipmentLabel(tags)).toBe("TAG-0 and 39 more");
  });
});
