import React, { useState, useEffect, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import { BarChart } from "../components/BarChart.js";
import { PATHS, AXT_CONFIG_PATH } from "../../core/paths.js";
import { aggregateDaily, computeBlocks } from "../../core/usage.js";
import { loadUnifiedUsage } from "../../core/usage-unified.js";
import type { UnifiedUsageEntry } from "../../core/types.js";
import { calculateCost } from "../../pricing/models.js";
import { loadConfig } from "../../config/index.js";
import { formatTokens, formatCost, budgetBar } from "../../cli/formatters.js";

interface Summary {
  sessions: number;
  messages: number;
  inputTokens: number;
  outputTokens: number;
  cacheWriteTokens: number;
  cacheReadTokens: number;
  cost: number;
}

function emptySummary(): Summary {
  return { sessions: 0, messages: 0, inputTokens: 0, outputTokens: 0, cacheWriteTokens: 0, cacheReadTokens: 0, cost: 0 };
}

interface TabState {
  today: Summary;
  week: Summary;
  month: Summary;
  chartData: { label: string; value: number }[];
  activeBlock: string;
  budgetLine: string;
  exchangeRate: number;
  lastRefresh: string;
}

const stateCache = new Map<string, TabState>();

interface Props {
  platform?: "claude" | "codex" | "gemini";
}

export function UsageTab({ platform }: Props) {
  const cacheKey = platform ?? "all";
  const cached = stateCache.get(cacheKey);

  const [today, setToday] = useState<Summary>(cached?.today ?? emptySummary());
  const [week, setWeek] = useState<Summary>(cached?.week ?? emptySummary());
  const [month, setMonth] = useState<Summary>(cached?.month ?? emptySummary());
  const [chartData, setChartData] = useState(cached?.chartData ?? []);
  const [activeBlock, setActiveBlock] = useState(cached?.activeBlock ?? "");
  const [budgetLine, setBudgetLine] = useState(cached?.budgetLine ?? "");
  const [exchangeRate, setExchangeRate] = useState(cached?.exchangeRate ?? 1400);
  const [loading, setLoading] = useState(!cached);
  const [lastRefresh, setLastRefresh] = useState(cached?.lastRefresh ?? "");

  const load = useCallback(async () => {
    setLoading(true);
    const config = await loadConfig(AXT_CONFIG_PATH);
    setExchangeRate(config.exchangeRate);
    const tz = config.timezone;
    const now = new Date();
    const todayStr = now.toLocaleDateString("en-CA", { timeZone: tz });
    const weekAgoStr = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toLocaleDateString("en-CA", { timeZone: tz });
    const monthStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;

    const allEntries = await loadUnifiedUsage({
      claudeProjectsDir: PATHS.projects,
      codexSessionsDir: PATHS.codexSessions,
      geminiTmpDir: PATHS.geminiTmp,
      since: monthStart,
      platform: platform ?? "all",
    });

    const summarize = (entries: UnifiedUsageEntry[]): Summary => {
      const sessions = new Set(entries.map((e) => e.sessionId)).size;
      const cost = entries.reduce((s, e) => s + calculateCost({ inputTokens: e.inputTokens, outputTokens: e.outputTokens, cacheCreationTokens: e.cacheWriteTokens, cacheReadTokens: e.cacheReadTokens }, e.model), 0);
      return {
        sessions, messages: entries.length,
        inputTokens: entries.reduce((s, e) => s + e.inputTokens, 0),
        outputTokens: entries.reduce((s, e) => s + e.outputTokens, 0),
        cacheWriteTokens: entries.reduce((s, e) => s + e.cacheWriteTokens, 0),
        cacheReadTokens: entries.reduce((s, e) => s + e.cacheReadTokens, 0),
        cost,
      };
    };

    const todayEntries = allEntries.filter((e) => e.timestamp.slice(0, 10) >= todayStr);
    const weekEntries = allEntries.filter((e) => e.timestamp.slice(0, 10) >= weekAgoStr);

    const newToday = summarize(todayEntries);
    const newWeek = summarize(weekEntries);
    const newMonth = summarize(allEntries);

    setToday(newToday);
    setWeek(newWeek);
    setMonth(newMonth);

    const legacyEntries = allEntries.map((e) => ({
      ...e,
      cacheCreationTokens: e.cacheWriteTokens,
    }));

    const daily = aggregateDaily(legacyEntries, tz).slice(-14);
    const newChartData = daily.map((d) => {
      const dayCost = allEntries
        .filter((e) => e.timestamp.slice(0, 10) === d.date)
        .reduce((s, e) => s + calculateCost({ inputTokens: e.inputTokens, outputTokens: e.outputTokens, cacheCreationTokens: e.cacheWriteTokens, cacheReadTokens: e.cacheReadTokens }, e.model), 0);
      return { label: d.date.slice(5), value: dayCost };
    });
    setChartData(newChartData);

    let newActiveBlock = "";
    const blocks = computeBlocks(legacyEntries, tz);
    const active = blocks.find((b) => b.isActive);
    if (active) {
      const start = new Date(active.startTime).toLocaleTimeString(config.locale, { timeZone: tz, hour: "2-digit", minute: "2-digit" });
      const end = new Date(active.endTime).toLocaleTimeString(config.locale, { timeZone: tz, hour: "2-digit", minute: "2-digit" });
      const burn = active.burnRatePerMin ? `${formatTokens(active.burnRatePerMin)}/min` : "";
      const blockCost = (active.inputTokens / 1e6 * 15) + (active.outputTokens / 1e6 * 75) + (active.cacheCreationTokens / 1e6 * 18.75) + (active.cacheReadTokens / 1e6 * 1.5);
      newActiveBlock = `Active Block: ${start}~${end}  ${formatTokens(active.totalTokens)} tokens  ${burn}  $${blockCost.toFixed(2)}`;
    }
    setActiveBlock(newActiveBlock);

    const newBudgetLine = budgetBar(summarize(allEntries).cost, config.monthlyBudget);
    setBudgetLine(newBudgetLine);

    const refreshTime = new Date().toLocaleTimeString();
    setLoading(false);
    setLastRefresh(refreshTime);

    stateCache.set(cacheKey, {
      today: newToday, week: newWeek, month: newMonth,
      chartData: newChartData, activeBlock: newActiveBlock, budgetLine: newBudgetLine,
      exchangeRate: config.exchangeRate, lastRefresh: refreshTime,
    });
  }, [platform, cacheKey]);

  useEffect(() => {
    if (!cached) load();
  }, []);

  useInput((input) => {
    if (input === "r") load();
  });

  const renderCard = (label: string, s: Summary) => (
    <Box flexDirection="column" borderStyle="single" paddingX={1} width={24}>
      <Text bold>{label}</Text>
      <Text>Sessions: {s.sessions}</Text>
      <Text>Messages: {s.messages}</Text>
      <Text>In:       {formatTokens(s.inputTokens)}</Text>
      <Text>Out:      {formatTokens(s.outputTokens)}</Text>
      <Text>Cache W:  {formatTokens(s.cacheWriteTokens)}</Text>
      <Text>Cache R:  {formatTokens(s.cacheReadTokens)}</Text>
      <Text>{formatCost(s.cost, exchangeRate)}</Text>
    </Box>
  );

  const title = platform
    ? `${platform.charAt(0).toUpperCase() + platform.slice(1)} Usage`
    : "All Platforms Usage";

  return (
    <Box flexDirection="column">
      <Box>
        <Text bold>{title}</Text>
        <Box flexGrow={1} />
        {loading && <Text color="yellow"> loading...</Text>}
        {lastRefresh && !loading && <Text dimColor> {lastRefresh}  r:refresh</Text>}
      </Box>
      <Box>
        {renderCard("Today", today)}
        {renderCard("This Week", week)}
        {renderCard("This Month", month)}
      </Box>
      {chartData.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold>Daily Trend (last 14 days)</Text>
          <BarChart data={chartData} maxWidth={30} />
        </Box>
      )}
      {activeBlock !== "" && <Text color="green">{activeBlock}</Text>}
      {budgetLine !== "" && <Text>{budgetLine}</Text>}
    </Box>
  );
}
