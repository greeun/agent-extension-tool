import { describe, test, expect } from "bun:test";
import { formatTokens, formatCost, budgetBar } from "../../src/cli/formatters.js";

describe("formatTokens", () => {
  test("formats zero as plain number", () => {
    expect(formatTokens(0)).toBe("0");
  });

  test("formats small numbers as plain string", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1)).toBe("1");
  });

  test("formats thousands as K with one decimal", () => {
    expect(formatTokens(1_000)).toBe("1.0K");
    expect(formatTokens(1_500)).toBe("1.5K");
    expect(formatTokens(999_999)).toBe("1000.0K");
  });

  test("formats millions as M with one decimal", () => {
    expect(formatTokens(1_000_000)).toBe("1.0M");
    expect(formatTokens(2_500_000)).toBe("2.5M");
  });

  test("boundary: 1000 uses K, 999 does not", () => {
    expect(formatTokens(1000)).toContain("K");
    expect(formatTokens(999)).not.toContain("K");
  });
});

describe("formatCost", () => {
  test("formats USD with two decimal places", () => {
    const result = formatCost(1.5, 1400);
    expect(result).toContain("$1.50");
  });

  test("includes KRW equivalent with won symbol", () => {
    const result = formatCost(1, 1400);
    expect(result).toContain("₩");
    expect(result).toContain("1,400");
  });

  test("formats zero cost", () => {
    const result = formatCost(0, 1400);
    expect(result).toContain("$0.00");
  });
});

describe("budgetBar", () => {
  test("returns a string with a bar and percentage", () => {
    const bar = budgetBar(5, 100);
    expect(typeof bar).toBe("string");
    expect(bar).toContain("5%");
  });

  test("contains filled and empty bar characters", () => {
    const bar = budgetBar(50, 100);
    expect(bar).toContain("█");
    expect(bar).toContain("░");
  });

  test("bar is fully filled when at budget", () => {
    const bar = budgetBar(100, 100);
    expect(bar).toContain("100%");
    expect(bar).not.toContain("░");
  });

  test("shows 0% when usage is zero", () => {
    const bar = budgetBar(0, 100);
    expect(bar).toContain("0%");
    expect(bar).not.toContain("█");
  });

  test("respects custom width", () => {
    const narrow = budgetBar(50, 100, 10);
    expect(narrow).toContain("█".repeat(5));
  });

  test("clamps to 100% fill even when over budget", () => {
    const bar = budgetBar(200, 100);
    expect(bar).toContain("150%");
    expect(bar).not.toContain("░");
  });
});
