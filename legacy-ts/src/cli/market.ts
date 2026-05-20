import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import { listMarketplaces, addMarketplace, removeMarketplace, syncMarketplace, parseMarketplaceSource, getMarketplaceVersion, pooledMap, type VersionInfo } from "../core/marketplace.js";

export function registerMarketCommands(program: Command): void {
  const market = program.command("market").description("Manage marketplaces");

  market
    .command("list")
    .description("List registered marketplaces")
    .action(async () => {
      const list = await listMarketplaces(PATHS.knownMarketplaces);
      if (list.length === 0) { console.log("No marketplaces registered."); return; }
      console.log(chalk.bold(`${"Name".padEnd(28)} ${"Current".padEnd(10)} ${"Latest".padEnd(10)} ${"Source".padEnd(28)} ${"Updated"}`));
      console.log("─".repeat(90));
      const { results: versions, errors } = await pooledMap(list, (m) => getMarketplaceVersion(PATHS.knownMarketplaces, m.name));
      for (const m of list) {
        const source = m.source.source === "github" ? `github:${(m.source as any).repo}`
          : m.source.source === "git" ? `git:${(m.source as any).url}`
          : `dir:${(m.source as any).path}`;
        const ver = versions.get(m) ?? { current: "?", remote: "?", updatable: false, error: "failed" };
        const currentCol = ver.error ? chalk.red(ver.current.padEnd(10)) : chalk.cyan(ver.current.padEnd(10));
        const latest = ver.error ? chalk.red(ver.remote.padEnd(10)) : ver.updatable ? chalk.yellow(ver.remote.padEnd(10)) : chalk.green(ver.remote.padEnd(10));
        console.log(`${m.name.padEnd(28)} ${currentCol} ${latest} ${source.padEnd(28)} ${m.lastUpdated.slice(0, 10)}`);
      }
      if (errors.length > 0) {
        console.log(chalk.red(`\n ${errors.length} error(s):`));
        for (const e of errors) console.log(chalk.red(`  ✗ ${(e.item as any).name}: ${e.error.message}`));
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
      const printResult = (n: string, result: { before: string; after: string; updated: boolean }) => {
        if (result.updated) {
          console.log(chalk.green(`✓ ${n}`) + chalk.gray(` ${result.before} → `) + chalk.cyan(result.after));
        } else {
          console.log(chalk.green(`✓ ${n}`) + chalk.gray(` ${result.after} (up to date)`));
        }
      };
      if (name) {
        printResult(name, await syncMarketplace(PATHS.knownMarketplaces, name));
      } else {
        const list = await listMarketplaces(PATHS.knownMarketplaces);
        const { errors } = await pooledMap(list, (m) => syncMarketplace(PATHS.knownMarketplaces, m.name), {
          onResult: (m, result) => printResult(m.name, result),
          onError: (m, error) => console.log(chalk.red(`✗ ${m.name}: ${error.message}`)),
        });
        if (errors.length > 0) console.log(chalk.red(`\n${errors.length} sync error(s)`));
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
