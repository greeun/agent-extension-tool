import { Command } from "commander";
import chalk from "chalk";
import { homedir } from "os";
import { PATHS, AXT_CONFIG_PATH } from "../core/paths.js";
import { loadConfig } from "../config/index.js";
import { formatTokens, formatCost } from "./formatters.js";
import { analyzeContext, type Category } from "../core/context-analysis.js";

const CATEGORY_LABELS: Record<Category, string> = {
  "system-prompt": "System prompt",
  "claude-md": "CLAUDE.md",
  "settings": "Settings",
  "memory": "Memory",
  "skills": "Skills metadata",
  "mcp-tools": "MCP tools",
  "plugins": "Plugins",
  "hooks": "Hooks output",
  "commands": "Commands",
  "agents": "Agents",
  "git-status": "Git status",
  "user-context": "User context",
};

export function registerContextCommands(program: Command): void {
  program
    .command("context")
    .description("Analyze session-start context usage")
    .option("--detail", "Show individual items within categories")
    .option("--json", "Output as JSON")
    .option("--category <name>", "Filter by category")
    .option("--model <id>", "Model override", "claude-opus-4-6")
    .action(async (opts) => {
      const config = await loadConfig(AXT_CONFIG_PATH);

      const result = await analyzeContext({
        homeDir: homedir(),
        projectDir: process.cwd(),
        installedPluginsPath: PATHS.installedPlugins,
        model: opts.model,
        avgTurnsPerSession: 30,
        avgSessionsPerDay: 5,
      });

      if (opts.json) {
        console.log(JSON.stringify(result, null, 2));
        return;
      }

      // Header
      console.log(chalk.bold(
        `Context Usage: ${result.usedPercent.toFixed(1)}% of ${formatTokens(result.contextWindowSize)} (${formatTokens(result.totalTokens)} tokens)  Model: ${result.model}`
      ));
      console.log();

      // Group by category
      const groups = new Map<Category, typeof result.sources>();
      for (const s of result.sources) {
        if (opts.category && s.category !== opts.category) continue;
        const list = groups.get(s.category) ?? [];
        list.push(s);
        groups.set(s.category, list);
      }

      // Sort by tokens desc
      const sorted = [...groups.entries()].sort((a, b) => {
        const aTok = a[1].reduce((s, x) => s + x.estimatedTokens, 0);
        const bTok = b[1].reduce((s, x) => s + x.estimatedTokens, 0);
        return bTok - aTok;
      });

      // Table header
      console.log(
        `${chalk.bold("Category".padEnd(22))} ${chalk.bold("Items".padEnd(7))} ${chalk.bold("Tokens".padEnd(12))} ${chalk.bold("%".padEnd(8))}`
      );
      console.log("─".repeat(52));

      // Rows
      for (const [cat, catSources] of sorted) {
        const totalTokens = catSources.reduce((sum, s) => sum + s.estimatedTokens, 0);
        const totalPct = catSources.reduce((sum, s) => sum + s.percentage, 0);
        const label = CATEGORY_LABELS[cat] ?? cat;

        console.log(
          `${label.padEnd(22)} ${String(catSources.length).padEnd(7)} ${formatTokens(totalTokens).padEnd(12)} ${(totalPct.toFixed(1) + "%").padEnd(8)}`
        );

        if (opts.detail) {
          for (const s of catSources) {
            const hint = s.hint ? chalk.dim(` — ${s.hint}`) : "";
            console.log(
              chalk.dim(`  ${s.name.padEnd(30)} ${s.path ? s.path.slice(0, 30).padEnd(32) : "".padEnd(32)} ${formatTokens(s.estimatedTokens)} tok${hint}`)
            );
          }
        }
      }

      // Cost impact
      console.log();
      const ci = result.costImpact;
      console.log(chalk.bold(`Cost Impact (${ci.model})`));
      console.log(`  Cache write (1st call):     $${ci.cacheWriteCost.toFixed(3)}`);
      console.log(`  Cache read  (per turn):     $${ci.cacheReadCostPerTurn.toFixed(3)}`);
      console.log(`  Per session (avg ${ci.avgTurnsPerSession}t):     $${ci.perSessionCost.toFixed(2)}`);
      console.log(`  Monthly (avg ${ci.avgSessionsPerDay}/day):       ${formatCost(ci.monthlyCost, config.exchangeRate)}`);
    });
}
