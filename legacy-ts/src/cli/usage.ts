import { Command } from "commander";
import chalk from "chalk";
import { PATHS, AXT_CONFIG_PATH } from "../core/paths.js";
import { aggregateDaily, aggregateBySession, computeBlocks } from "../core/usage.js";
import type { UsageEntry } from "../core/usage.js";
import { loadUnifiedUsage } from "../core/usage-unified.js";
import type { UnifiedUsageEntry } from "../core/types.js";
import { calculateCost } from "../pricing/models.js";
import { loadConfig } from "../config/index.js";
import { formatTokens, formatCost, budgetBar } from "@utils/format.js";

function unifiedToUsageEntry(e: UnifiedUsageEntry): UsageEntry {
  return {
    model: e.model,
    inputTokens: e.inputTokens,
    outputTokens: e.outputTokens,
    cacheCreationTokens: e.cacheWriteTokens,
    cacheReadTokens: e.cacheReadTokens,
    sessionId: e.sessionId,
    projectPath: e.projectPath,
    timestamp: e.timestamp,
  };
}

export function registerUsageCommands(program: Command): void {
  const usage = program
    .command("usage")
    .description("Track token usage and costs")
    .option("--since <date>", "Start date (YYYYMMDD)")
    .option("--until <date>", "End date (YYYYMMDD)")
    .option("--model <name>", "Filter by model")
    .option("--project <name>", "Filter by project")
    .option("--breakdown", "Show per-model breakdown")
    .option("--timezone <tz>", "Timezone for grouping")
    .option("--locale <loc>", "Date locale")
    .option("--platform <name>", "Filter by platform (claude/codex/gemini/all)", "all")
    .option("--json", "Output JSON")
    .option("--csv", "Output CSV")
    .option("--export <path>", "Export to file");

  usage
    .command("today", { isDefault: true })
    .description("Today's usage summary")
    .action(async () => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const opts = usage.opts();
      const tz = opts.timezone ?? config.timezone;
      const today = new Date().toLocaleDateString("en-CA", { timeZone: tz });

      let unified = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        since: today,
        until: today,
        platform: opts.platform as any,
        project: opts.project,
      });
      if (opts.model) unified = unified.filter((e) => e.model.includes(opts.model));
      let entries = unified.map(unifiedToUsageEntry);

      if (entries.length === 0) { console.log("No usage data for today."); return; }

      const daily = aggregateDaily(entries, tz);
      const d = daily[0];
      const cost = entries.reduce((sum, e) => sum + calculateCost({ inputTokens: e.inputTokens, outputTokens: e.outputTokens, cacheCreationTokens: e.cacheCreationTokens, cacheReadTokens: e.cacheReadTokens }, e.model), 0);

      if (opts.json) { console.log(JSON.stringify({ ...d, cost: { usd: cost, krw: Math.round(cost * config.exchangeRate) } }, null, 2)); return; }

      console.log(chalk.bold(`Today (${today})`));
      console.log(`  Sessions:    ${d.sessions}`);
      console.log(`  Models:      ${d.models.join(", ")}`);
      console.log(`  In:          ${formatTokens(d.inputTokens)}`);
      console.log(`  Out:         ${formatTokens(d.outputTokens)}`);
      console.log(`  Cache Write: ${formatTokens(d.cacheCreationTokens)}`);
      console.log(`  Cache Read:  ${formatTokens(d.cacheReadTokens)}`);
      console.log(`  Cost:        ${formatCost(cost, config.exchangeRate)}`);
    });

  usage
    .command("week")
    .description("Weekly usage summary")
    .action(async () => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const opts = usage.opts();
      const tz = opts.timezone ?? config.timezone;
      const now = new Date();
      const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      const since = weekAgo.toLocaleDateString("en-CA", { timeZone: tz });
      const until = now.toLocaleDateString("en-CA", { timeZone: tz });

      let unified = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        since,
        until,
        platform: opts.platform as any,
        project: opts.project,
      });
      if (opts.model) unified = unified.filter((e) => e.model.includes(opts.model));
      let entries = unified.map(unifiedToUsageEntry);
      const daily = aggregateDaily(entries, tz);

      if (opts.json) { console.log(JSON.stringify(daily, null, 2)); return; }
      if (opts.csv) {
        console.log("date,sessions,input_tokens,output_tokens,cache_write_tokens,cache_read_tokens,cost_usd,cost_krw");
        for (const d of daily) {
          const cost = computeDayCost(entries, d.date, tz);
          console.log(`${d.date},${d.sessions},${d.inputTokens},${d.outputTokens},${d.cacheCreationTokens},${d.cacheReadTokens},${cost.toFixed(2)},${Math.round(cost * config.exchangeRate)}`);
        }
        return;
      }

      console.log(chalk.bold(`Week: ${since} ~ ${until}\n`));
      console.log(` ${"Date".padEnd(12)} ${"Sess".padEnd(6)} ${"In".padEnd(10)} ${"Out".padEnd(10)} ${"Cache W".padEnd(10)} ${"Cache R".padEnd(10)} Cost`);
      console.log("─".repeat(78));
      let totalCost = 0;
      for (const d of daily) {
        const cost = computeDayCost(entries, d.date, tz);
        totalCost += cost;
        console.log(` ${d.date.padEnd(12)} ${String(d.sessions).padEnd(6)} ${formatTokens(d.inputTokens).padEnd(10)} ${formatTokens(d.outputTokens).padEnd(10)} ${formatTokens(d.cacheCreationTokens).padEnd(10)} ${formatTokens(d.cacheReadTokens).padEnd(10)} ${formatCost(cost, config.exchangeRate)}`);
      }
      console.log("─".repeat(78));
      console.log(` ${"Total".padEnd(58)} ${formatCost(totalCost, config.exchangeRate)}`);
    });

  usage
    .command("month")
    .description("Monthly usage summary")
    .action(async () => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const opts = usage.opts();
      const tz = opts.timezone ?? config.timezone;
      const now = new Date();
      const since = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
      const until = now.toLocaleDateString("en-CA", { timeZone: tz });

      let unified = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        since,
        until,
        platform: opts.platform as any,
        project: opts.project,
      });
      if (opts.model) unified = unified.filter((e) => e.model.includes(opts.model));
      let entries = unified.map(unifiedToUsageEntry);
      const totalCost = entries.reduce((sum, e) => sum + calculateCost({ inputTokens: e.inputTokens, outputTokens: e.outputTokens, cacheCreationTokens: e.cacheCreationTokens, cacheReadTokens: e.cacheReadTokens }, e.model), 0);
      const sessions = new Set(entries.map((e) => e.sessionId)).size;

      console.log(chalk.bold(`Month: ${since} ~ ${until}`));
      console.log(`  Sessions:    ${sessions}`);
      console.log(`  Messages:    ${entries.length}`);
      console.log(`  Cost:        ${formatCost(totalCost, config.exchangeRate)}`);
      console.log();
      console.log(budgetBar(totalCost, config.monthlyBudget));
    });

  usage
    .command("blocks")
    .description("5-hour billing block report")
    .option("--active", "Show active block only")
    .action(async (cmdOpts: { active?: boolean }) => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const opts = usage.opts();
      const tz = opts.timezone ?? config.timezone;
      const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
      const since = threeDaysAgo.toLocaleDateString("en-CA", { timeZone: tz });

      const unified = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        since,
        platform: opts.platform as any,
      });
      const entries = unified.map(unifiedToUsageEntry);
      let blocks = computeBlocks(entries, tz);
      if (cmdOpts.active) blocks = blocks.filter((b) => b.isActive);

      console.log(chalk.bold(` ${"Block".padEnd(30)} ${"Status".padEnd(10)} ${"Tokens".padEnd(12)} ${"Burn Rate".padEnd(12)} Cost`));
      console.log("─".repeat(80));
      for (const b of blocks.reverse()) {
        const start = new Date(b.startTime).toLocaleString(config.locale, { timeZone: tz, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
        const end = new Date(b.endTime).toLocaleString(config.locale, { timeZone: tz, hour: "2-digit", minute: "2-digit" });
        const status = b.isActive ? chalk.green("● active") : chalk.gray("○ done");
        const burn = b.burnRatePerMin ? `${formatTokens(b.burnRatePerMin)}/min` : "—";
        const cost = (b.inputTokens / 1e6 * 15) + (b.outputTokens / 1e6 * 75) + (b.cacheCreationTokens / 1e6 * 18.75) + (b.cacheReadTokens / 1e6 * 1.5);
        console.log(` ${`${start}~${end}`.padEnd(30)} ${status.padEnd(19)} ${formatTokens(b.totalTokens).padEnd(12)} ${burn.padEnd(12)} $${cost.toFixed(2)}`);
      }
    });

  usage
    .command("session <id>")
    .description("Show specific session usage")
    .action(async (id: string) => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const opts = usage.opts();
      const unified = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        platform: opts.platform as any,
      });
      const entries = unified.map(unifiedToUsageEntry);
      const sessionEntries = entries.filter((e) => e.sessionId.startsWith(id));
      if (sessionEntries.length === 0) { console.log(chalk.red(`Session "${id}" not found.`)); return; }
      const sessions = aggregateBySession(sessionEntries);
      const s = sessions[0];
      const cost = sessionEntries.reduce((sum, e) => sum + calculateCost({ inputTokens: e.inputTokens, outputTokens: e.outputTokens, cacheCreationTokens: e.cacheCreationTokens, cacheReadTokens: e.cacheReadTokens }, e.model), 0);
      console.log(chalk.bold(`Session: ${s.sessionId}`));
      console.log(`  Project:     ${s.projectPath}`);
      console.log(`  Models:      ${s.models.join(", ")}`);
      console.log(`  Messages:    ${s.messageCount}`);
      console.log(`  In:          ${formatTokens(s.inputTokens)}`);
      console.log(`  Out:         ${formatTokens(s.outputTokens)}`);
      console.log(`  Cache Write: ${formatTokens(s.cacheCreationTokens)}`);
      console.log(`  Cache Read:  ${formatTokens(s.cacheReadTokens)}`);
      console.log(`  Cost:        ${formatCost(cost, config.exchangeRate)}`);
      console.log(`  Period:      ${s.firstTimestamp.slice(0, 19)} ~ ${s.lastTimestamp.slice(0, 19)}`);
    });
}

function computeDayCost(entries: any[], date: string, tz: string): number {
  return entries
    .filter((e) => new Date(e.timestamp).toLocaleDateString("en-CA", { timeZone: tz }) === date)
    .reduce((sum, e) => sum + calculateCost({ inputTokens: e.inputTokens, outputTokens: e.outputTokens, cacheCreationTokens: e.cacheCreationTokens, cacheReadTokens: e.cacheReadTokens }, e.model), 0);
}
