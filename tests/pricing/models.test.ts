import { describe, test, expect } from "bun:test";
import {
  getModelPricing,
  calculateCost,
  convertCurrency,
  type TokenUsage,
} from "../../src/pricing/models.js";

describe("pricing", () => {
  test("getModelPricing returns rates for known model", () => {
    const pricing = getModelPricing("claude-opus-4-6");
    expect(pricing).toEqual({
      input: 15.0,
      output: 75.0,
      cacheWrite: 18.75,
      cacheRead: 1.5,
    });
  });

  test("getModelPricing matches partial model names", () => {
    const pricing = getModelPricing("claude-opus-4-6[1m]");
    expect(pricing!.input).toBe(15.0);
  });

  test("getModelPricing returns null for unknown model", () => {
    const pricing = getModelPricing("unknown-model-xyz");
    expect(pricing).toBeNull();
  });

  test("calculateCost computes total from 4 token types", () => {
    const usage: TokenUsage = {
      inputTokens: 1_000_000,
      outputTokens: 1_000_000,
      cacheCreationTokens: 1_000_000,
      cacheReadTokens: 1_000_000,
    };
    const cost = calculateCost(usage, "claude-opus-4-6");
    expect(cost).toBeCloseTo(15.0 + 75.0 + 18.75 + 1.5, 2);
  });

  test("calculateCost returns 0 for unknown model", () => {
    const usage: TokenUsage = {
      inputTokens: 1000,
      outputTokens: 1000,
      cacheCreationTokens: 0,
      cacheReadTokens: 0,
    };
    const cost = calculateCost(usage, "unknown");
    expect(cost).toBe(0);
  });

  test("convertCurrency USD to KRW", () => {
    expect(convertCurrency(10, "usd", "krw", 1400)).toBe(14000);
  });

  test("convertCurrency KRW to USD", () => {
    expect(convertCurrency(14000, "krw", "usd", 1400)).toBe(10);
  });

  test("convertCurrency same currency returns input", () => {
    expect(convertCurrency(50, "usd", "usd", 1400)).toBe(50);
  });

  test("getModelPricing returns rates for Codex models", () => {
    const pricing = getModelPricing("gpt-5.3-codex");
    expect(pricing).not.toBeNull();
    expect(pricing!.input).toBe(1.75);
    expect(pricing!.output).toBe(14.0);
    expect(pricing!.cacheRead).toBe(0.175);
  });

  test("getModelPricing returns rates for Gemini models", () => {
    const pricing = getModelPricing("gemini-2.5-pro");
    expect(pricing).not.toBeNull();
    expect(pricing!.input).toBe(1.25);
    expect(pricing!.output).toBe(10.0);
  });

  test("calculateCost works with Codex model", () => {
    const cost = calculateCost(
      { inputTokens: 1_000_000, outputTokens: 1_000_000, cacheCreationTokens: 0, cacheReadTokens: 1_000_000 },
      "gpt-5.3-codex"
    );
    expect(cost).toBeCloseTo(1.75 + 14.0 + 0.175, 2);
  });

  test("calculateCost works with Gemini model", () => {
    const cost = calculateCost(
      { inputTokens: 1_000_000, outputTokens: 1_000_000, cacheCreationTokens: 0, cacheReadTokens: 1_000_000 },
      "gemini-2.5-flash"
    );
    expect(cost).toBeCloseTo(0.30 + 2.50 + 0.03, 2);
  });
});
