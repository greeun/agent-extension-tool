import { statSync } from "fs";
import { getModelPricing, getContextWindowSize } from "@pricing/models.js";
import type { ContextSource, ContextAnalysis, AnalyzeOptions } from "./types.js";
import { collectContextSources } from "./collect.js";

// ── Optimization Hints ─────────────────────────────────────────────────────

export function addHints(sources: ContextSource[]): void {
  const sortedByTokens = [...sources].sort((a, b) => b.estimatedTokens - a.estimatedTokens);
  const topNames = sortedByTokens.slice(0, 3).map((s) => s.name);

  for (const s of sources) {
    switch (s.category) {
      case "system-prompt":
        s.hint = `${s.estimatedTokens} tok (fixed, cannot reduce)`;
        break;
      case "user-context":
      case "git-status":
        s.hint = `${s.estimatedTokens} tok (fixed)`;
        break;
      case "claude-md":
        if (s.estimatedTokens > 500) {
          s.hint = `${s.estimatedTokens} tok — review for unnecessary sections`;
        }
        break;
      case "memory": {
        if (s.path) {
          try {
            const mtime = statSync(s.path).mtimeMs;
            const daysOld = Math.floor((Date.now() - mtime) / (24 * 60 * 60 * 1000));
            if (daysOld > 90) {
              s.hint = `${s.estimatedTokens} tok — not modified in ${daysOld} days (>90 days)`;
            }
          } catch {}
        }
        if (!s.hint && s.estimatedTokens > 100) {
          s.hint = `${s.estimatedTokens} tok`;
        }
        break;
      }
      case "skills":
        if (topNames.includes(s.name)) {
          s.hint = `${s.estimatedTokens} tok — top context consumer`;
        }
        break;
      case "hooks":
        s.hint = `~${s.estimatedTokens} tok estimated output`;
        break;
      case "mcp-tools":
        s.hint = `deferred — minimal context impact`;
        break;
      default:
        if (s.estimatedTokens > 100) {
          s.hint = `${s.estimatedTokens} tok`;
        }
    }
  }
}

// ── analyzeContext ─────────────────────────────────────────────────────────

export async function analyzeContext(options: AnalyzeOptions): Promise<ContextAnalysis> {
  const sources = await collectContextSources(options);
  const totalTokens = sources.reduce((sum, s) => sum + s.estimatedTokens, 0);
  const contextWindowSize = getContextWindowSize(options.model) ?? 1_000_000;
  const usedPercent = (totalTokens / contextWindowSize) * 100;

  const pricing = getModelPricing(options.model);
  const cacheWriteCost = pricing ? (totalTokens / 1_000_000) * pricing.cacheWrite : 0;
  const cacheReadCostPerTurn = pricing ? (totalTokens / 1_000_000) * pricing.cacheRead : 0;
  const perSessionCost = cacheWriteCost + (options.avgTurnsPerSession - 1) * cacheReadCostPerTurn;
  const monthlyCost = perSessionCost * options.avgSessionsPerDay * 30;

  addHints(sources);

  return {
    totalTokens,
    contextWindowSize,
    usedPercent,
    model: options.model,
    sources,
    costImpact: {
      model: options.model,
      cacheWriteCost,
      cacheReadCostPerTurn,
      avgTurnsPerSession: options.avgTurnsPerSession,
      avgSessionsPerDay: options.avgSessionsPerDay,
      perSessionCost,
      monthlyCost,
    },
  };
}
