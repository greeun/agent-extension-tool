import React, { useState, useEffect, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import { BarChart } from "../components/BarChart.js";
import { PATHS, AXT_CONFIG_PATH } from "../../core/paths.js";
import { loadUnifiedUsage } from "../../core/usage-unified.js";
import { calculateCost } from "../../pricing/models.js";
import { loadConfig } from "../../config/index.js";
import { computePlanUsage, getDaysInBillingPeriod } from "../../plans/index.js";
import { formatTokens, formatCost, budgetBar } from "@utils/format.js";
import { TUI_LOCALE } from "../locale.js";
import type { Platform } from "../../core/types.js";

interface PlatformSummary {
  platform: Platform;
  planLabel: string;
  cost: number;
  projected: number;
  monthlyCost: number;
  elapsed: number;
  inputTokens: number;
  outputTokens: number;
  cacheTokens: number;
}

interface OverviewState {
  summaries: PlatformSummary[];
  chartData: { label: string; value: number }[];
  totalCost: number;
  totalBudget: number;
  exchangeRate: number;
  lastRefresh: string;
}

let cachedState: OverviewState | null = null;

export function OverviewTab() {
  const [summaries, setSummaries] = useState<PlatformSummary[]>(cachedState?.summaries ?? []);
  const [chartData, setChartData] = useState(cachedState?.chartData ?? []);
  const [totalCost, setTotalCost] = useState(cachedState?.totalCost ?? 0);
  const [totalBudget, setTotalBudget] = useState(cachedState?.totalBudget ?? 0);
  const [exchangeRate, setExchangeRate] = useState(cachedState?.exchangeRate ?? 1400);
  const [loading, setLoading] = useState(!cachedState);
  const [lastRefresh, setLastRefresh] = useState(cachedState?.lastRefresh ?? "");

  const load = useCallback(async () => {
    setLoading(true);
    const config = await loadConfig(AXT_CONFIG_PATH);
    setExchangeRate(config.exchangeRate);
    const now = new Date();
    const monthStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;

    const entries = await loadUnifiedUsage({
      claudeProjectsDir: PATHS.projects,
      codexSessionsDir: PATHS.codexSessions,
      geminiTmpDir: PATHS.geminiTmp,
      since: monthStart,
    });

    const platforms: Platform[] = ["claude", "codex", "gemini"];
    const results: PlatformSummary[] = [];
    let total = 0;
    let budget = 0;

    for (const p of platforms) {
      const planConfig = config.plans?.[p];
      if (!planConfig) continue;

      const pEntries = entries.filter((e) => e.platform === p);
      const cost = pEntries.reduce((sum, e) =>
        sum + calculateCost({
          inputTokens: e.inputTokens, outputTokens: e.outputTokens,
          cacheCreationTokens: e.cacheWriteTokens, cacheReadTokens: e.cacheReadTokens,
        }, e.model), 0);

      const { elapsed, total: totalDays } = getDaysInBillingPeriod(planConfig.billingCycleStart, now);
      const usage = computePlanUsage(planConfig, cost, elapsed, totalDays);

      total += cost;
      budget += planConfig.monthlyCost;

      results.push({
        platform: p,
        planLabel: `${planConfig.plan} — $${planConfig.monthlyCost}/mo`,
        cost,
        projected: usage.projectedMonthlyCost,
        monthlyCost: planConfig.monthlyCost,
        elapsed,
        inputTokens: pEntries.reduce((s, e) => s + e.inputTokens, 0),
        outputTokens: pEntries.reduce((s, e) => s + e.outputTokens, 0),
        cacheTokens: pEntries.reduce((s, e) => s + e.cacheReadTokens + e.cacheWriteTokens, 0),
      });
    }

    setSummaries(results);
    setTotalCost(total);
    setTotalBudget(budget);

    const dailyMap = new Map<string, number>();
    for (const e of entries) {
      const date = e.timestamp.slice(0, 10);
      dailyMap.set(date, (dailyMap.get(date) ?? 0) +
        calculateCost({
          inputTokens: e.inputTokens, outputTokens: e.outputTokens,
          cacheCreationTokens: e.cacheWriteTokens, cacheReadTokens: e.cacheReadTokens,
        }, e.model));
    }
    const sorted = Array.from(dailyMap.entries()).sort().slice(-14);
    const newChartData = sorted.map(([date, val]) => ({ label: date.slice(5), value: val }));
    setChartData(newChartData);

    const refreshTime = new Date().toLocaleTimeString(TUI_LOCALE);
    setLoading(false);
    setLastRefresh(refreshTime);

    cachedState = {
      summaries: results, chartData: newChartData,
      totalCost: total, totalBudget: budget,
      exchangeRate: config.exchangeRate, lastRefresh: refreshTime,
    };
  }, []);

  useEffect(() => {
    if (!cachedState) load();
  }, []);

  useInput((input) => {
    if (input === "r") load();
  });

  return (
    <Box flexDirection="column">
      <Box>
        <Text bold> Total This Month: {formatCost(totalCost, exchangeRate)}</Text>
        <Box flexGrow={1} />
        {loading && <Text color="yellow"> loading...</Text>}
        {lastRefresh && !loading && <Text dimColor> {lastRefresh}  r:refresh</Text>}
      </Box>
      <Text> </Text>

      {summaries.map((s) => (
        <Box key={s.platform} flexDirection="column" marginBottom={1}>
          <Text bold>
            {` ${s.platform.charAt(0).toUpperCase() + s.platform.slice(1)} (${s.planLabel})`}
          </Text>
          {s.monthlyCost > 0 ? (
            <Text>  {budgetBar(s.cost, s.monthlyCost)}  est→${s.projected.toFixed(0)}</Text>
          ) : (
            <Text>  {formatCost(s.cost, exchangeRate)}</Text>
          )}
          <Text dimColor>
            {`  In: ${formatTokens(s.inputTokens)}  Out: ${formatTokens(s.outputTokens)}  Cache: ${formatTokens(s.cacheTokens)}`}
          </Text>
        </Box>
      ))}

      {chartData.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold> Daily Trend (14 days, all platforms)</Text>
          <BarChart data={chartData} maxWidth={30} />
        </Box>
      )}

      {totalBudget > 0 && (
        <Box marginTop={1}>
          <Text> {budgetBar(totalCost, totalBudget)}</Text>
        </Box>
      )}
    </Box>
  );
}
