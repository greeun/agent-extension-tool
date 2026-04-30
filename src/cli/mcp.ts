import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import { listInstalledPlugins } from "../core/plugin.js";
import { readEnabledPlugins } from "../core/settings.js";
import { listMcpServers } from "../core/mcp.js";

export function registerMcpCommands(program: Command): void {
  const mcp = program.command("mcp").description("View MCP servers");

  mcp
    .command("list")
    .description("List MCP servers from active plugins")
    .action(async () => {
      const plugins = await listInstalledPlugins(PATHS.installedPlugins);
      const enabled = await readEnabledPlugins(PATHS.settings);
      const activePlugins = plugins.filter((p) => enabled[p.id] === true);
      const servers = await listMcpServers(activePlugins);
      if (servers.length === 0) { console.log("No MCP servers found in active plugins."); return; }
      console.log(chalk.bold(` ${"Server".padEnd(25)} ${"Command".padEnd(20)} Plugin`));
      console.log("─".repeat(70));
      for (const s of servers) {
        const cmd = [s.command, ...s.args].join(" ");
        console.log(` ${s.name.padEnd(25)} ${cmd.padEnd(20)} ${s.pluginId}`);
      }
      console.log(`\n ${servers.length} MCP server(s)`);
    });

  mcp
    .command("info <name>")
    .description("Show MCP server details")
    .action(async (name: string) => {
      const plugins = await listInstalledPlugins(PATHS.installedPlugins);
      const enabled = await readEnabledPlugins(PATHS.settings);
      const activePlugins = plugins.filter((p) => enabled[p.id] === true);
      const servers = await listMcpServers(activePlugins);
      const server = servers.find((s) => s.name === name);
      if (!server) { console.log(chalk.red(`MCP server "${name}" not found.`)); return; }
      console.log(chalk.bold(server.name));
      console.log(`Plugin: ${server.pluginId}`);
      console.log(`Command: ${server.command} ${server.args.join(" ")}`);
      if (Object.keys(server.env).length > 0) console.log(`Env: ${JSON.stringify(server.env)}`);
    });
}
