import { describe, test, expect, beforeAll, afterAll } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { DetailPanel } from "../../../src/tui/components/DetailPanel.js";
import chalk, { type ColorSupportLevel } from "chalk";

let originalChalkLevel: ColorSupportLevel;

beforeAll(() => {
  originalChalkLevel = chalk.level;
  chalk.level = 3 as ColorSupportLevel;
});

afterAll(() => {
  chalk.level = originalChalkLevel;
});

describe("DetailPanel (multiline + scroll)", () => {
  test("wraps long field values across multiple lines", () => {
    const longVal = "a".repeat(120);
    const { lastFrame } = render(
      <DetailPanel
        title="T"
        fields={[{ label: "P", value: longVal }]}
        maxHeight={20}
      />,
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("P:");
    expect((frame.match(/a/g) ?? []).length).toBeGreaterThan(80);
  });

  test("shows scroll indicator when content exceeds maxHeight", () => {
    const fields = Array.from({ length: 40 }, (_, i) => ({
      label: `K${i}`,
      value: `v${i}`,
    }));
    const { lastFrame } = render(
      <DetailPanel fields={fields} maxHeight={10} scroll={0} />,
    );
    const frame = lastFrame() ?? "";
    expect(/\[\d+-\d+ ?\/ ?\d+\]/.test(frame)).toBe(true);
  });

  test("scroll prop shifts which lines are visible", () => {
    const fields = Array.from({ length: 40 }, (_, i) => ({
      label: `K${i}`,
      value: `v${i}`,
    }));
    const a = render(<DetailPanel fields={fields} maxHeight={10} scroll={0} />).lastFrame() ?? "";
    const b = render(<DetailPanel fields={fields} maxHeight={10} scroll={20} />).lastFrame() ?? "";
    expect(a).toContain("K0:");
    expect(a.includes("K39:")).toBe(false);
    expect(b.includes("K0:")).toBe(false);
    expect(b).toContain("K20:");
  });

  test("focused=true colors the border cyan", () => {
    const { lastFrame } = render(
      <DetailPanel fields={[{ label: "A", value: "x" }]} focused />,
    );
    const frame = lastFrame() ?? "";
    expect(frame.includes("[36m")).toBe(true);
  });
});
