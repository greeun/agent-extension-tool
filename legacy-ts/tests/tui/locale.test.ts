import { describe, test, expect } from "bun:test";
import { TUI_LOCALE } from "../../src/tui/locale.js";

describe("TUI_LOCALE", () => {
  test("is en-US", () => {
    expect(TUI_LOCALE).toBe("en-US");
  });

  test("is a valid Intl locale", () => {
    expect(() => new Intl.DateTimeFormat(TUI_LOCALE)).not.toThrow();
  });

  test("formats numbers in English", () => {
    const formatted = (1234567.89).toLocaleString(TUI_LOCALE);
    expect(formatted).toBe("1,234,567.89");
  });
});
