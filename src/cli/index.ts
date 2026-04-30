import { Command } from "commander";
import { registerMarketCommands } from "./market.js";
import { registerPluginCommands } from "./plugin.js";
import { registerSkillCommands } from "./skill.js";
import { registerMcpCommands } from "./mcp.js";
import { registerUsageCommands } from "./usage.js";
import { registerPlanCommands } from "./plan.js";

export function createProgram(): Command {
  const program = new Command();
  program
    .name("axt")
    .description("Agent eXtension Tool")
    .version("0.1.0");

  registerMarketCommands(program);
  registerPluginCommands(program);
  registerSkillCommands(program);
  registerMcpCommands(program);
  registerUsageCommands(program);
  registerPlanCommands(program);

  program
    .command("tui")
    .description("Open TUI dashboard")
    .action(async () => {
      const { launchTui } = await import("../tui/App.js");
      await launchTui();
    });

  program.action(async () => {
    const { launchTui } = await import("../tui/App.js");
    await launchTui();
  });

  return program;
}
