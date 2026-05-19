import { test, expect } from "bun:test";
import { renderBar } from "../../src/utils/bar.js";

// quotaBar / makeBar (width 16, █/░), original: Math.round(Math.min(pct/100,1)*16)
test("matches quotaBar/makeBar", () => {
  for (const pct of [0, 12.5, 33.3, 50, 70, 90, 100]) {
    const filled = Math.round(Math.min(pct / 100, 1) * 16);
    const expected = "█".repeat(filled) + "░".repeat(16 - filled);
    expect(renderBar(filled, 16)).toBe(expected);
  }
});

// makeUsageBar (width 30, ▓/░)
test("matches makeUsageBar", () => {
  for (const pct of [0, 33.3, 50, 100]) {
    const filled = Math.round(Math.min(pct / 100, 1) * 30);
    const expected = "▓".repeat(filled) + "░".repeat(30 - filled);
    expect(renderBar(filled, 30, "▓")).toBe(expected);
  }
});

// CursorTab pctBar (width 20, █/░), original: Math.round(pct/100*20)
test("matches CursorTab pctBar", () => {
  for (const pct of [0, 25, 50, 87.4, 100]) {
    const filled = Math.round(pct / 100 * 20);
    const expected = "█".repeat(filled) + "░".repeat(20 - filled);
    expect(renderBar(filled, 20)).toBe(expected);
  }
});

// UsageTab renderLimitBar (width 20, █/░), original used Math.max guards
test("matches UsageTab renderLimitBar", () => {
  for (const pct of [0, 5, 50, 95, 100]) {
    const filled = Math.round(pct / 5);
    const empty = 20 - filled;
    const expected = "█".repeat(Math.max(0, filled)) + "░".repeat(Math.max(0, empty));
    expect(renderBar(filled, 20)).toBe(expected);
  }
});

// budgetBar inner bar (width 25, █/░)
test("matches budgetBar inner bar", () => {
  for (const [used, budget] of [[0, 10], [5, 10], [10, 10], [15, 10]] as const) {
    const pct = Math.min(used / budget, 1.5);
    const filled = Math.round(Math.min(pct, 1) * 25);
    const expected = "█".repeat(filled) + "░".repeat(25 - filled);
    expect(renderBar(filled, 25)).toBe(expected);
  }
});
