import { useState, useEffect, useCallback, useRef } from "react";
import { Box, Text, useInput } from "ink";
import { BarChart } from "../components/BarChart.js";
import { PATHS, AXT_CONFIG_PATH } from "../../core/paths.js";
import { aggregateDaily, computeBlocks } from "../../core/usage.js";
import { loadUnifiedUsage } from "../../core/usage-unified.js";
import type { UnifiedUsageEntry } from "../../core/types.js";
import { calculateCost } from "../../pricing/models.js";
import { loadConfig } from "../../config/index.js";
import { formatTokens, formatCost, budgetBar } from "../../cli/formatters.js";
import { loadUsageInsights, type UsageInsights } from "../../core/usage-insights.js";

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
  insights: UsageInsights | null;
  insightDays: 1 | 7;
}

const stateCache = new Map<string, TabState>();

interface Props {
  platform?: "claude" | "codex" | "gemini";
  isFocused?: boolean;
  refreshKey?: number;
}

export function UsageTab({ platform, isFocused = true, refreshKey }: Props) {
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
  const [insights, setInsights] = useState<UsageInsights | null>(cached?.insights ?? null);
  const [insightDays, setInsightDays] = useState<1 | 7>(cached?.insightDays ?? 7);
  const [insightSubTab, setInsightSubTab] = useState<"overview" | "skills" | "agents" | "plugins">("overview");

  const mountedRef = useRef(false);

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
    setLastRefresh(refreshTime);

    let newInsights: UsageInsights | null = null;
    if (!platform || platform === "claude") {
      newInsights = await loadUsageInsights({
        days: insightDays,
        projectsDir: PATHS.projects,
        sessionMetaDir: `${PATHS.claudeDir}/usage-data/session-meta`,
        usageSnapshotPath: PATHS.usageSnapshot,
      }).catch(() => null);
      setInsights(newInsights);
    }

    setLoading(false);

    stateCache.set(cacheKey, {
      today: newToday, week: newWeek, month: newMonth,
      chartData: newChartData, activeBlock: newActiveBlock, budgetLine: newBudgetLine,
      exchangeRate: config.exchangeRate, lastRefresh: refreshTime,
      insights: newInsights,
      insightDays,
    });
  }, [platform, cacheKey, insightDays]);

  useEffect(() => {
    if (!cached) load();
    mountedRef.current = true;
  }, []);

  useEffect(() => {
    if (!mountedRef.current) return;
    if (!platform || platform === "claude") {
      load();
    }
  }, [insightDays]);

  useEffect(() => {
    if (!refreshKey) return;
    stateCache.delete(cacheKey);
    load();
  }, [refreshKey]);

  useInput((input) => {
    if (!isFocused) return;
    if (!platform || platform === "claude") {
      if (input === "d" || input === "w") {
        const newDays: 1 | 7 = input === "d" ? 1 : 7;
        setInsightDays(newDays);
        stateCache.delete(cacheKey);
      }
      if (input === "o") setInsightSubTab("overview");
      if (input === "s") setInsightSubTab("skills");
      if (input === "a") setInsightSubTab("agents");
      if (input === "p") setInsightSubTab("plugins");
    }
  });

  const renderLimitBar = (label: string, pct: number, resetsAt: Date) => {
    const filled = Math.round(pct / 5);
    const empty = 20 - filled;
    const bar = "█".repeat(Math.max(0, filled)) + "░".repeat(Math.max(0, empty));
    const resetStr = resetsAt.toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    return (
      <Box key={label}>
        <Text color="cyan">{label.padEnd(8)}</Text>
        <Text> [{bar}] </Text>
        <Text color={pct > 80 ? "red" : pct > 50 ? "yellow" : "green"}>{String(pct).padStart(3)}%</Text>
        <Text dimColor>  resets {resetStr}</Text>
      </Box>
    );
  };

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
      {(!platform || platform === "claude") && insights && (
        <Box flexDirection="column" marginTop={1}>
          {/* 서브탭 바 */}
          <Box>
            {(["overview", "skills", "agents", "plugins"] as const).map((t) => {
              const labels = { overview: "o:Overview", skills: "s:Skills", agents: "a:Agents", plugins: "p:Plugins" };
              const active = insightSubTab === t;
              return (
                <Box key={t} marginRight={1}>
                  <Text bold={active} inverse={active} color={active ? undefined : undefined} dimColor={!active}>
                    {` ${labels[t]} `}
                  </Text>
                </Box>
              );
            })}
            <Box flexGrow={1} />
            <Text dimColor>d:day  w:week</Text>
          </Box>

          {/* Overview 탭: 플랜 한도 + 인사이트 지표 */}
          {insightSubTab === "overview" && (
            <Box flexDirection="column" marginTop={1}>
              <Text bold dimColor>── Claude Plan Limits ──────────────────────</Text>
              {insights.planLimits ? (
                <>
                  {renderLimitBar("Session", insights.planLimits.sessionUsedPct, insights.planLimits.sessionResetsAt)}
                  {renderLimitBar("Week", insights.planLimits.weekUsedPct, insights.planLimits.weekResetsAt)}
                </>
              ) : (
                <Text dimColor>Plan data unavailable</Text>
              )}
              <Box marginTop={1}><Text bold dimColor>── Last {insightDays === 1 ? "24h" : "7d"} · What{"'"}s contributing? ────</Text></Box>
              {insights.subagentHeavyPct > 0 && (
                <Box flexDirection="column" marginTop={1}>
                  <Text>{insights.subagentHeavyPct}% of your usage came from subagent-heavy sessions</Text>
                  <Text dimColor>  Each subagent runs its own requests. Be deliberate about spawning them —</Text>
                  <Text dimColor>  consider configuring a cheaper model for simpler subagents.</Text>
                </Box>
              )}
              {insights.largeContextPct > 0 && (
                <Box flexDirection="column" marginTop={1}>
                  <Text>{insights.largeContextPct}% of your usage was at &gt;150k context</Text>
                  <Text dimColor>  Longer sessions are more expensive even when cached. /compact mid-task,</Text>
                  <Text dimColor>  /clear when switching to new tasks.</Text>
                </Box>
              )}
              {insights.parallelSessionPct > 0 && (
                <Box flexDirection="column" marginTop={1}>
                  <Text>{insights.parallelSessionPct}% of your usage was while 4+ sessions ran in parallel</Text>
                  <Text dimColor>  All sessions share one limit. If you don{"'"}t need them all at once,</Text>
                  <Text dimColor>  queueing uses it more evenly.</Text>
                </Box>
              )}
              {insights.pluginBreakdown.length > 0 && insights.pluginBreakdown[0].tokenPct > 0 && (
                <Box flexDirection="column" marginTop={1}>
                  <Text>{insights.pluginBreakdown[0].tokenPct}% of your usage came from plugin "{insights.pluginBreakdown[0].name}"</Text>
                  <Text dimColor>  Review what this plugin contributes — its agents, skills, and MCP tools all</Text>
                  <Text dimColor>  count toward your limit.</Text>
                </Box>
              )}
            </Box>
          )}

          {/* Skills 탭 */}
          {insightSubTab === "skills" && (
            <Box flexDirection="column" marginTop={1}>
              <Box>
                <Text bold dimColor>{"Skills"}</Text>
                <Text dimColor>{"                % of usage"}</Text>
              </Box>
              {insights.skillBreakdown.length === 0 && <Text dimColor>No skill data for this period.</Text>}
              {insights.skillBreakdown.map((s) => (
                <Box key={s.name}>
                  <Text dimColor>{"/"}{s.name.length > 34 ? s.name.slice(0, 33) + "…" : s.name.padEnd(34)}</Text>
                  <Text color="cyan">{String(s.tokenPct).padStart(4)}%</Text>
                </Box>
              ))}
            </Box>
          )}

          {/* Agents 탭 */}
          {insightSubTab === "agents" && (
            <Box flexDirection="column" marginTop={1}>
              <Box>
                <Text bold dimColor>{"Subagents"}</Text>
                <Text dimColor>{"             % of usage"}</Text>
              </Box>
              {insights.subagentBreakdown.length === 0 && <Text dimColor>No subagent data for this period.</Text>}
              {insights.subagentBreakdown.map((s) => (
                <Box key={s.name}>
                  <Text dimColor>{s.name.length > 34 ? s.name.slice(0, 33) + "…" : s.name.padEnd(34)}</Text>
                  <Text color="cyan">{String(s.tokenPct).padStart(4)}%</Text>
                </Box>
              ))}
            </Box>
          )}

          {/* Plugins 탭 */}
          {insightSubTab === "plugins" && (
            <Box flexDirection="column" marginTop={1}>
              <Box>
                <Text bold dimColor>{"Plugins"}</Text>
                <Text dimColor>{"               % of usage"}</Text>
              </Box>
              {insights.pluginBreakdown.length === 0 && <Text dimColor>No plugin data for this period.</Text>}
              {insights.pluginBreakdown.map((s) => (
                <Box key={s.name}>
                  <Text dimColor>{s.name.length > 34 ? s.name.slice(0, 33) + "…" : s.name.padEnd(34)}</Text>
                  <Text color="cyan">{String(s.tokenPct).padStart(4)}%</Text>
                </Box>
              ))}
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
