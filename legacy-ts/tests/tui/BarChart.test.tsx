import { describe, test, expect } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";
import { BarChart } from "../../src/tui/components/BarChart.js";

describe("BarChart", () => {
  test("renders a bar for each data entry", () => {
    const { lastFrame } = render(
      <BarChart data={[{ label: "Mon", value: 10 }, { label: "Tue", value: 20 }]} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Mon");
    expect(frame).toContain("Tue");
  });

  test("renders bar characters proportional to values", () => {
    const { lastFrame } = render(
      <BarChart data={[{ label: "A", value: 100 }, { label: "B", value: 50 }]} maxWidth={10} />
    );
    const frame = lastFrame() ?? "";
    const lines = frame.split("\n");
    const lineA = lines.find((l) => l.includes("A")) ?? "";
    const lineB = lines.find((l) => l.includes("B")) ?? "";
    const countBlocks = (line: string) => (line.match(/█/g) ?? []).length;
    expect(countBlocks(lineA)).toBeGreaterThan(countBlocks(lineB));
  });

  test("renders with a single data point (no division by zero)", () => {
    const { lastFrame } = render(
      <BarChart data={[{ label: "Only", value: 42 }]} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Only");
    expect(frame).toContain("█");
  });

  test("renders gracefully with all-zero values", () => {
    const { lastFrame } = render(
      <BarChart data={[{ label: "Zero", value: 0 }]} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Zero");
    // max = Math.max(0, 1) = 1, barLen = round(0/1 * 40) = 0 → no blocks
    expect(frame).not.toContain("█");
  });

  test("renders cost value next to each bar", () => {
    const { lastFrame } = render(
      <BarChart data={[{ label: "X", value: 5 }]} />
    );
    const frame = lastFrame() ?? "";
    expect(frame).toContain("$5");
  });
});
