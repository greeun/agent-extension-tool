export interface ModelPricing {
  input: number;
  output: number;
  cacheWrite: number;
  cacheRead: number;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
}

const PRICING_TABLE: Record<string, ModelPricing> = {
  "claude-opus-4-7": { input: 15.0, output: 75.0, cacheWrite: 18.75, cacheRead: 1.5 },
  "claude-opus-4-6": { input: 15.0, output: 75.0, cacheWrite: 18.75, cacheRead: 1.5 },
  "claude-sonnet-4-6": { input: 3.0, output: 15.0, cacheWrite: 3.75, cacheRead: 0.3 },
  "claude-haiku-4-5": { input: 0.8, output: 4.0, cacheWrite: 1.0, cacheRead: 0.08 },

  // Codex
  "gpt-5": { input: 1.25, output: 10.0, cacheWrite: 0, cacheRead: 0.125 },
  "gpt-5.2-codex": { input: 1.75, output: 14.0, cacheWrite: 0, cacheRead: 0.175 },
  "gpt-5.3-codex": { input: 1.75, output: 14.0, cacheWrite: 0, cacheRead: 0.175 },
  "gpt-5.4": { input: 1.75, output: 14.0, cacheWrite: 0, cacheRead: 0.175 },

  // Gemini
  "gemini-2.5-pro": { input: 1.25, output: 10.0, cacheWrite: 0, cacheRead: 0.125 },
  "gemini-2.5-flash": { input: 0.30, output: 2.50, cacheWrite: 0, cacheRead: 0.03 },
  "gemini-2.5-flash-lite": { input: 0.10, output: 0.40, cacheWrite: 0, cacheRead: 0.01 },
  "gemini-3.1-pro-preview": { input: 2.0, output: 12.0, cacheWrite: 0, cacheRead: 0.20 },
  "gemini-3-flash-preview": { input: 0.50, output: 3.0, cacheWrite: 0, cacheRead: 0.05 },
};

export function getModelPricing(modelId: string): ModelPricing | null {
  if (PRICING_TABLE[modelId]) return PRICING_TABLE[modelId];
  for (const [key, pricing] of Object.entries(PRICING_TABLE)) {
    if (modelId.startsWith(key)) return pricing;
  }
  return null;
}

export function calculateCost(usage: TokenUsage, modelId: string): number {
  const pricing = getModelPricing(modelId);
  if (!pricing) return 0;
  return (
    (usage.inputTokens / 1_000_000) * pricing.input +
    (usage.outputTokens / 1_000_000) * pricing.output +
    (usage.cacheCreationTokens / 1_000_000) * pricing.cacheWrite +
    (usage.cacheReadTokens / 1_000_000) * pricing.cacheRead
  );
}

export function convertCurrency(
  amount: number,
  from: string,
  to: string,
  exchangeRate: number
): number {
  if (from === to) return amount;
  if (from === "usd" && to === "krw") return amount * exchangeRate;
  if (from === "krw" && to === "usd") return amount / exchangeRate;
  return amount;
}
