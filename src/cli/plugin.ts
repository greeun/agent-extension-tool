import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import { listInstalledPlugins, getPluginInfo, removeInstalledPlugin } from "../core/plugin.js";
import { readEnabledPlugins, setPluginEnabled, removePluginFromSettings } from "../core/settings.js";
import { rm } from "fs/promises";

export function registerPluginCommands(program: Command): void {
  const plugin = program.command("plugin").description("Manage plugins");

  plugin
    .command("list")
    .description("List installed plugins with status")
    .action(async () => {
      const plugins = await listInstalledPlugins(PATHS.installedPlugins);
      const enabled = await readEnabledPlugins(PATHS.settings);
      if (plugins.length === 0) { console.log("No plugins installed."); return; }
      console.log(chalk.bold(` ${"Plugin".padEnd(30)} ${"Version".padEnd(10)} ${"Status".padEnd(10)} ${"Marketplace"}`));
      console.log("─".repeat(75));
      let activeCount = 0;
      for (const p of plugins) {
        const isActive = enabled[p.id] === true;
        if (isActive) activeCount++;
        const status = isActive ? chalk.green("● active") : chalk.gray("○ off");
        console.log(` ${p.name.padEnd(30)} ${p.version.padEnd(10)} ${status.padEnd(19)} ${p.marketplace}`);
      }
      console.log(`\n ${plugins.length} installed (${activeCount} active, ${plugins.length - activeCount} disabled)`);
    });

  plugin
    .command("enable <id>")
    .description("Enable a plugin")
    .action(async (id: string) => {
      await setPluginEnabled(PATHS.settings, id, true);
      console.log(chalk.green(`✓ "${id}" enabled. Restart Claude Code to apply.`));
    });

  plugin
    .command("disable <id>")
    .description("Disable a plugin")
    .action(async (id: string) => {
      await setPluginEnabled(PATHS.settings, id, false);
      console.log(chalk.yellow(`○ "${id}" disabled. Restart Claude Code to apply.`));
    });

  plugin
    .command("info <id>")
    .description("Show plugin details")
    .action(async (id: string) => {
      const info = await getPluginInfo(PATHS.installedPlugins, id);
      if (!info) { console.log(chalk.red(`Plugin "${id}" not found.`)); return; }
      const enabled = await readEnabledPlugins(PATHS.settings);
      console.log(chalk.bold(info.name) + ` ${info.version}`);
      console.log(`Marketplace: ${info.marketplace}`);
      console.log(`Status: ${enabled[info.id] ? chalk.green("active") : chalk.gray("disabled")}`);
      console.log(`Path: ${info.installPath}`);
      console.log(`Installed: ${info.installedAt.slice(0, 10)}`);
      console.log(`Updated: ${info.lastUpdated.slice(0, 10)}`);
    });

  plugin
    .command("remove <id>")
    .description("Remove a plugin")
    .action(async (id: string) => {
      const info = await getPluginInfo(PATHS.installedPlugins, id);
      if (!info) { console.log(chalk.red(`Plugin "${id}" not found.`)); return; }
      await rm(info.installPath, { recursive: true, force: true });
      await removeInstalledPlugin(PATHS.installedPlugins, id);
      await removePluginFromSettings(PATHS.settings, id);
      console.log(chalk.green(`✓ "${id}" removed.`));
    });

  plugin
    .command("search <query>")
    .description("Search plugins across all marketplaces")
    .action(async (query: string) => {
      console.log(chalk.gray(`Searching for "${query}"...`));
      console.log(chalk.yellow("Search requires marketplace sync. Run: axt market sync"));
    });
}
