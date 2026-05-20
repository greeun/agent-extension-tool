import { describe, test, expect } from "bun:test";
import { flattenDetailFields } from "../../../src/tui/components/flattenDetailFields.js";

describe("flattenDetailFields", () => {
  test("short single-line value produces one line per field", () => {
    const out = flattenDetailFields(
      [
        { label: "A", value: "short" },
        { label: "B", value: "also short" },
      ],
      80,
    );
    expect(out.length).toBe(2);
    expect(out[0]).toContain("A:");
    expect(out[0]).toContain("short");
    expect(out[1]).toContain("B:");
  });

  test("long value wraps across multiple visual lines", () => {
    const longValue = "x".repeat(120);
    const out = flattenDetailFields([{ label: "Path", value: longValue }], 40);
    // 40 - "Path: ".length = 34 chars per line for the value
    // 120 / 34 = 4 lines (ceil)
    expect(out.length).toBe(4);
    expect(out[0]).toContain("Path: ");
    // continuation lines must NOT repeat the label
    expect(out[1].startsWith("Path:")).toBe(false);
  });

  test("continuation lines are indented to align under the value", () => {
    const out = flattenDetailFields(
      [{ label: "Lbl", value: "a".repeat(30) }],
      20,
    );
    // "Lbl: " = 5 cols → indent of 5 spaces on continuation
    expect(out.length).toBeGreaterThan(1);
    expect(out[1].startsWith("     ")).toBe(true);
  });

  test("empty values render as a single line with em dash placeholder", () => {
    const out = flattenDetailFields([{ label: "X", value: "" }], 80);
    expect(out).toEqual(["X: —"]);
  });

  test("width <= label length still produces at least one line per field", () => {
    const out = flattenDetailFields([{ label: "LongLabel", value: "abc" }], 4);
    expect(out.length).toBeGreaterThanOrEqual(1);
    expect(out[0]).toContain("LongLabel");
  });
});
