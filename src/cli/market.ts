import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import { listMarketplaces, addMarketplace, removeMarketplace, syncMarketplace, parseMarketplaceSource } from "../core/marketplace.js";

export function registerMarketCommands(program: Command): void {
  const market = program.command("market").description("Manage marketplaces");

  market
    .command("list")
    .description("List registered marketplaces")
    .action(async () => {
      const list = await listMarketplaces(PATHS.knownMarketplaces);
      if (list.length === 0) { console.log("No marketplaces registered."); return; }
      console.log(chalk.bold(`${"Name".padEnd(35)} ${"Source".padEnd(30)} ${"Updated"}`));
      console.log("─".repeat(80));
      for (const m of list) {
        const source = m.source.source === "github" ? `github:${(m.source as any).repo}`
          : m.source.source === "git" ? `git:${(m.source as any).url}`
          : `dir:${(m.source as any).path}`;
        console.log(`${m.name.padEnd(35)} ${source.padEnd(30)} ${m.lastUpdated.slice(0, 10)}`);
      }
      console.log(`\n ${list.length} marketplace(s)`);
    });

  market
    .command("add <source>")
    .description("Register a marketplace (github:user/repo, git:url, dir:path)")
    .action(async (sourceStr: string) => {
      const source = parseMarketplaceSource(sourceStr);
      const name = source.source === "github" ? source.repo.split("/").pop()!
        : source.source === "directory" ? (source as any).path.split("/").pop()
        : "custom-marketplace";
      await addMarketplace(PATHS.knownMarketplaces, PATHS.marketplaces, name, source);
      console.log(chalk.green(`✓ Marketplace "${name}" registered.`));
    });

  market
    .command("sync [name]")
    .description("Sync marketplace(s) with remote")
    .action(async (name?: string) => {
      if (name) {
        await syncMarketplace(PATHS.knownMarketplaces, name);
        console.log(chalk.green(`✓ "${name}" synced.`));
      } else {
        const list = await listMarketplaces(PATHS.knownMarketplaces);
        for (const m of list) {
          try { await syncMarketplace(PATHS.knownMarketplaces, m.name); console.log(chalk.green(`✓ ${m.name}`)); }
          catch (err: any) { console.log(chalk.red(`✗ ${m.name}: ${err.message}`)); }
        }
      }
    });

  market
    .command("remove <name>")
    .description("Unregister a marketplace")
    .action(async (name: string) => {
      await removeMarketplace(PATHS.knownMarketplaces, PATHS.marketplaces, name);
      console.log(chalk.green(`✓ Marketplace "${name}" removed.`));
    });
}
