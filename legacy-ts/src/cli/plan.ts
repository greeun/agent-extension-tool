import { Command } from "commander";
import chalk from "chalk";
import { PATHS, AXT_CONFIG_PATH } from "../core/paths.js";
import { loadConfig, saveConfig } from "../config/index.js";
import { loadUnifiedUsage } from "../core/usage-unified.js";
import { calculateCost } from "../pricing/models.js";
import { computePlanUsage, getDaysInBillingPeriod } from "../plans/index.js";
import { formatCost, budgetBar } from "@utils/format.js";
import type { Platform } from "../core/types.js";

export function registerPlanCommands(program: Command): void {
  const plan = program.command("plan").description("View plan usage and cost projections");

  plan
    .command("overview", { isDefault: true })
    .description("All platforms plan summary")
    .action(async () => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const now = new Date();
      const monthStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;

      const entries = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        since: monthStart,
      });

      const platforms: Platform[] = ["claude", "codex", "gemini"];
      let totalCost = 0;

      for (const p of platforms) {
        const planConfig = config.plans?.[p];
        if (!planConfig) continue;

        const platformEntries = entries.filter((e) => e.platform === p);
        const cost = platformEntries.reduce((sum, e) =>
          sum + calculateCost({
            inputTokens: e.inputTokens,
            outputTokens: e.outputTokens,
            cacheCreationTokens: e.cacheWriteTokens,
            cacheReadTokens: e.cacheReadTokens,
          }, e.model), 0);

        const { elapsed, total } = getDaysInBillingPeriod(planConfig.billingCycleStart, now);
        const usage = computePlanUsage(planConfig, cost, elapsed, total);

        totalCost += cost;

        const label = `${p.charAt(0).toUpperCase() + p.slice(1)} (${planConfig.plan} — $${planConfig.monthlyCost}/mo)`;
        console.log(chalk.bold(label));
        console.log(`  사용량:    ${formatCost(cost, config.exchangeRate)}  (${elapsed}일 경과)`);
        console.log(`  일평균:    $${usage.dailyAvgCost.toFixed(2)}`);
        const estLabel = usage.projectedMonthlyCost > planConfig.monthlyCost && planConfig.monthlyCost > 0
          ? chalk.red(`$${usage.projectedMonthlyCost.toFixed(0)} ⚠ 초과 예상`)
          : `$${usage.projectedMonthlyCost.toFixed(0)}`;
        console.log(`  월말 예측: ${estLabel}`);
        if (planConfig.monthlyCost > 0) {
          console.log(`  ${budgetBar(cost, planConfig.monthlyCost)}`);
        }
        console.log();
      }

      console.log(chalk.bold(`Total: ${formatCost(totalCost, config.exchangeRate)}`));
    });

  plan
    .command("set <platform> <planName>")
    .description("Set plan for a platform")
    .action(async (platform: string, planName: string) => {
      const config = await loadConfig(AXT_CONFIG_PATH);
      if (!config.plans) config.plans = {} as any;
      const p = platform as Platform;
      if (!config.plans![p]) {
        config.plans![p] = { plan: planName, monthlyCost: 0, billingCycleStart: 1 };
      } else {
        config.plans![p]!.plan = planName;
      }
      await saveConfig(AXT_CONFIG_PATH, config);
      console.log(chalk.green(`✓ ${platform} plan set to "${planName}".`));
    });
}
