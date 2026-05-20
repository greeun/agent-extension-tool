import { describe, test, expect } from "bun:test";
import { truncateToWidth, sanitize, fitToWidth } from "../../src/tui/utils.js";

describe("truncateToWidth", () => {
  test("returns string unchanged when within width", () => {
    expect(truncateToWidth("hello", 10)).toBe("hello");
  });

  test("truncates ASCII string to exact width", () => {
    expect(truncateToWidth("hello world", 5)).toBe("hello");
  });

  test("returns empty string when maxW is 0", () => {
    expect(truncateToWidth("hello", 0)).toBe("");
  });

  test("handles wide characters (CJK) as width 2", () => {
    // Each CJK char is 2 columns wide
    const result = truncateToWidth("한글AB", 4);
    // "한글" takes 4 columns → "AB" would overflow
    expect(result).toBe("한글");
  });

  test("handles empty string", () => {
    expect(truncateToWidth("", 10)).toBe("");
  });
});

describe("sanitize", () => {
  test("replaces control characters with spaces", () => {
    expect(sanitize("hello\x00world")).toBe("hello world");
    expect(sanitize("tab\there")).toBe("tab here");
    expect(sanitize("newline\nhere")).toBe("newline here");
  });

  test("preserves normal ASCII characters", () => {
    expect(sanitize("hello world 123!")).toBe("hello world 123!");
  });

  test("replaces DEL (0x7f)", () => {
    expect(sanitize("before\x7fafter")).toBe("before after");
  });

  test("handles empty string", () => {
    expect(sanitize("")).toBe("");
  });

  test("handles string with no control characters", () => {
    const str = "normal text with punctuation: !@#$%";
    expect(sanitize(str)).toBe(str);
  });
});

describe("fitToWidth", () => {
  test("pads short string to target width", () => {
    const result = fitToWidth("hi", 5);
    expect(result).toBe("hi   ");
    expect(result.length).toBe(5);
  });

  test("truncates string that exceeds width", () => {
    const result = fitToWidth("hello world", 5);
    expect(result).toBe("hello");
  });

  test("exact-length string is unchanged", () => {
    expect(fitToWidth("hello", 5)).toBe("hello");
  });

  test("sanitizes control characters before fitting", () => {
    const result = fitToWidth("ab\x00cd", 6);
    expect(result).toBe("ab cd ");
  });

  test("width 0 returns empty string", () => {
    expect(fitToWidth("hello", 0)).toBe("");
  });

  test("pads wide-character strings correctly", () => {
    // "한" = 2 cols, so in width 4: "한" + 2 spaces = 4 cols total
    const result = fitToWidth("한", 4);
    expect(result).toBe("한  ");
  });
});
