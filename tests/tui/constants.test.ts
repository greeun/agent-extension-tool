import { describe, test, expect } from "bun:test";
import { SOURCE_COLORS } from "../../src/tui/constants.js";

describe("SOURCE_COLORS", () => {
  test("has an entry for each source type", () => {
    expect(SOURCE_COLORS.user).toBeDefined();
    expect(SOURCE_COLORS.project).toBeDefined();
    expect(SOURCE_COLORS.local).toBeDefined();
    expect(SOURCE_COLORS.plugin).toBeDefined();
  });

  test("all values are non-empty strings", () => {
    for (const color of Object.values(SOURCE_COLORS)) {
      expect(typeof color).toBe("string");
      expect(color.length).toBeGreaterThan(0);
    }
  });

  test("each color is a valid Ink color name", () => {
    const validColors = ["cyan", "green", "yellow", "magenta", "blue", "red", "white", "gray"];
    for (const color of Object.values(SOURCE_COLORS)) {
      expect(validColors).toContain(color);
    }
  });
});
