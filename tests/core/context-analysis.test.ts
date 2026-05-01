import { describe, test, expect } from "bun:test";
import { estimateTokens } from "../../src/core/context-analysis.js";

describe("estimateTokens", () => {
  test("estimates English text at ~1 token per 3.5 chars", () => {
    const text = "Hello world, this is a test string.";
    const tokens = estimateTokens(text);
    expect(tokens).toBe(Math.ceil(text.length / 3.5));
  });

  test("estimates Korean text at ~1 token per 1.5 chars", () => {
    const text = "안녕하세요 테스트입니다";
    const tokens = estimateTokens(text);
    expect(tokens).toBeGreaterThan(Math.ceil(text.length / 3.5));
  });

  test("handles mixed content", () => {
    const text = "Hello 안녕 world 세계";
    const tokens = estimateTokens(text);
    expect(tokens).toBeGreaterThan(0);
  });

  test("returns 0 for empty string", () => {
    expect(estimateTokens("")).toBe(0);
  });
});
