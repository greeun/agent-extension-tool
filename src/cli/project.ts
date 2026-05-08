import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import {
  readProfile, writeProfile, linkToProject, unlinkFromProject,
  syncProject, listVaultItems, emptyProfile,
} from "../core/vault.js";
import type { VaultItem, ExtensionType } from "../core/vault.js";

export function registerProjectCommands(program: Command): void {
  const project = program.command("project").description("Manage project extension profile");

  project
    .command("init")
    .description("Create .axt-profile.json (empty profile)")
    .action(async () => {
      const cwd = process.cwd();
      const existing = await readProfile(cwd);
      if (existing) {
        console.log(chalk.yellow(".axt-profile.json already exists."));
        return;
      }
      await writeProfile(cwd, emptyProfile());
      console.log(chalk.green("✓ Created .axt-profile.json"));
    });

  project
    .command("add <type> <names...>")
    .description("Add vault extensions to project (type: skill, command, agent)")
    .action(async (type: string, names: string[]) => {
      const cwd = process.cwd();
      const vaultItems = await listVaultItems(PATHS.vault);
      for (const name of names) {
        const item = vaultItems.find((i) => i.name === name && i.type === type);
        if (!item) {
          console.log(chalk.red(`✗ ${type} "${name}" not found in vault`));
          continue;
        }
        await linkToProject(cwd, item);
        console.log(chalk.green(`✓ Linked ${type} "${name}" → .claude/${type}s/${name}`));
      }
    });

  project
    .command("remove <type> <name>")
    .description("Remove extension from project")
    .action(async (type: string, name: string) => {
      const cwd = process.cwd();
      const item: VaultItem = { name, type: type as ExtensionType, path: "", isLinked: true, isGlobalLinked: false };
      await unlinkFromProject(cwd, item);
      console.log(chalk.green(`✓ Unlinked ${type} "${name}"`));
    });

  project
    .command("sync")
    .description("Reconcile symlinks with .axt-profile.json")
    .action(async () => {
      const cwd = process.cwd();
      const result = await syncProject(cwd, PATHS.vault);
      for (const l of result.linked) console.log(chalk.green(`  + ${l}`));
      for (const u of result.unlinked) console.log(chalk.yellow(`  - ${u}`));
      for (const e of result.errors) console.log(chalk.red(`  ✗ ${e}`));
      if (result.linked.length === 0 && result.unlinked.length === 0 && result.errors.length === 0) {
        console.log("Already in sync.");
      }
    });

  project
    .command("status")
    .description("Show profile vs actual symlink state")
    .action(async () => {
      const cwd = process.cwd();
      const profile = await readProfile(cwd);
      if (!profile) {
        console.log("No .axt-profile.json found. Run `axt project init` first.");
        return;
      }
      const { lstat } = await import("fs/promises");
      const { join } = await import("path");
      console.log(chalk.bold("Extension profile status:"));
      const types = [
        { key: "skills" as const, type: "skill" },
        { key: "commands" as const, type: "command" },
        { key: "agents" as const, type: "agent" },
        { key: "plugins" as const, type: "plugin" },
      ];
      for (const { key, type } of types) {
        for (const name of profile.extensions[key]) {
          if (type === "plugin") {
            console.log(`  ${chalk.cyan(type.padEnd(8))} ${name} ${chalk.green("(in profile)")}`);
            continue;
          }
          const linkPath = join(cwd, ".claude", key, name);
          let linked = false;
          try {
            const s = await lstat(linkPath);
            linked = s.isSymbolicLink();
          } catch {}
          const status = linked ? chalk.green("✓ linked") : chalk.red("✗ missing");
          console.log(`  ${chalk.cyan(type.padEnd(8))} ${name.padEnd(25)} ${status}`);
        }
      }
    });
}
