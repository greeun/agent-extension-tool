import { readJson, writeJsonAtomic } from "../core/json-io.js";
import type { PlanConfig } from "../plans/index.js";

export interface CcxConfig {
  currency: string[];
  exchangeRate: number;
  monthlyBudget: number;
  timezone: string;
  locale: string;
  startOfWeek: "monday" | "sunday";
  budgetWarningThreshold: number;
  plans?: {
    claude?: PlanConfig;
    codex?: PlanConfig;
    gemini?: PlanConfig;
  };
}

export const DEFAULT_CONFIG: CcxConfig = {
  currency: ["usd", "krw"],
  exchangeRate: 1400,
  monthlyBudget: 100,
  timezone: "Asia/Seoul",
  locale: "ko-KR",
  startOfWeek: "monday",
  budgetWarningThreshold: 0.8,
  plans: {
    claude: { plan: "max-5x", monthlyCost: 100, billingCycleStart: 1 },
    codex: { plan: "pro", monthlyCost: 200, billingCycleStart: 1 },
    gemini: { plan: "free", monthlyCost: 0, billingCycleStart: 1, dailyRequestLimit: 1000 },
  },
};

export async function loadConfig(configPath: string): Promise<CcxConfig> {
  const saved = await readJson<Partial<CcxConfig>>(configPath, { fallback: {} });
  return { ...DEFAULT_CONFIG, ...saved };
}

export async function saveConfig(
  configPath: string,
  config: CcxConfig
): Promise<void> {
  await writeJsonAtomic(configPath, config);
}
