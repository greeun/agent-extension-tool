import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import { listVaultItems, migrateToVault } from "../core/vault.js";

export function registerVaultCommands(program: Command): void {
  const vault = program.command("vault").description("Manage extension vault");

  vault
    .command("list")
    .description("List all vault extensions")
    .action(async () => {
      const items = await listVaultItems(PATHS.vault);
      if (items.length === 0) {
        console.log("Vault is empty. Run `axt vault migrate` to move global extensions to vault.");
        return;
      }
      console.log(chalk.bold(`${"Name".padEnd(30)} ${"Type".padEnd(10)}`));
      console.log("─".repeat(42));
      for (const item of items) {
        console.log(`${item.name.padEnd(30)} ${chalk.cyan(item.type.padEnd(10))}`);
      }
      console.log(`\n ${items.length} extension(s) in vault`);
    });

  vault
    .command("migrate")
    .description("Move global extensions (~/.claude/skills, commands, agents) to vault")
    .action(async () => {
      console.log("Migrating global extensions to vault...");
      const result = await migrateToVault(PATHS.claudeDir, PATHS.vault);
      for (const m of result.moved) console.log(chalk.green(`  ✓ ${m}`));
      for (const s of result.skipped) console.log(chalk.yellow(`  ⊘ ${s} (already in vault)`));
      for (const e of result.errors) console.log(chalk.red(`  ✗ ${e}`));
      const total = result.moved.length + result.skipped.length + result.errors.length;
      if (total === 0) {
        console.log("No extensions found in global paths.");
      } else {
        console.log(`\nMoved ${result.moved.length}, skipped ${result.skipped.length}, errors ${result.errors.length}`);
      }
    });

  vault
    .command("add <path>")
    .description("Add extension to vault (directory for skill, .md file for command/agent)")
    .option("-t, --type <type>", "Extension type: skill, command, agent")
    .action(async (srcPath: string, opts: { type?: string }) => {
      const { stat, cp, mkdir } = await import("fs/promises");
      const { basename, join } = await import("path");
      const s = await stat(srcPath);
      let type = opts.type;
      if (!type) {
        type = s.isDirectory() ? "skill" : "command";
      }
      const name = basename(srcPath);
      const destDir = type === "skill" ? PATHS.vaultSkills : type === "command" ? PATHS.vaultCommands : PATHS.vaultAgents;
      await mkdir(destDir, { recursive: true });
      const destPath = join(destDir, name);
      await cp(srcPath, destPath, { recursive: s.isDirectory() });
      console.log(chalk.green(`✓ Added ${type} "${name}" to vault`));
    });

  vault
    .command("install <marketplace> <name>")
    .description("Install extension from marketplace directly to vault")
    .option("-t, --type <type>", "Extension type: skill, command, agent", "skill")
    .action(async (marketplace: string, name: string, opts: { type: string }) => {
      const { findPluginSourceDir } = await import("../core/plugin.js");
      const { join } = await import("path");
      const { cp, mkdir } = await import("fs/promises");
      const mktsDir = PATHS.marketplaces;
      const sourceDir = await findPluginSourceDir(join(mktsDir, marketplace), name);
      if (!sourceDir) {
        console.log(chalk.red(`✗ "${name}" not found in marketplace "${marketplace}"`));
        return;
      }
      const destDir = opts.type === "skill" ? PATHS.vaultSkills
        : opts.type === "command" ? PATHS.vaultCommands : PATHS.vaultAgents;
      await mkdir(destDir, { recursive: true });
      const destPath = join(destDir, name);
      await cp(sourceDir, destPath, { recursive: true });
      console.log(chalk.green(`✓ Installed ${opts.type} "${name}" from "${marketplace}" to vault`));
    });

  vault
    .command("link-global <type> <name>")
    .description("Symlink vault extension to global ~/.claude/ directory")
    .action(async (type: string, name: string) => {
      const { linkToGlobal, listVaultItems } = await import("../core/vault.js");
      const items = await listVaultItems(PATHS.vault);
      const item = items.find((i) => i.name === name && i.type === type);
      if (!item) {
        console.log(chalk.red(`✗ ${type} "${name}" not found in vault`));
        return;
      }
      await linkToGlobal(PATHS.claudeDir, item);
      console.log(chalk.green(`✓ Linked ${type} "${name}" to global (~/.claude/${type}s/${name})`));
    });

  vault
    .command("unlink-global <type> <name>")
    .description("Remove symlink from global ~/.claude/ directory")
    .action(async (type: string, name: string) => {
      const { unlinkFromGlobal } = await import("../core/vault.js");
      const item = { name, type: type as any, path: "", isLinked: false, isGlobalLinked: true };
      await unlinkFromGlobal(PATHS.claudeDir, item);
      console.log(chalk.green(`✓ Unlinked ${type} "${name}" from global`));
    });
}
