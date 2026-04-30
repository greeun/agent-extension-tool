import { Command } from "commander";
import chalk from "chalk";
import { PATHS } from "../core/paths.js";
import { listSkills, linkSkill, unlinkSkill } from "../core/skill.js";

export function registerSkillCommands(program: Command): void {
  const skill = program.command("skill").description("Manage standalone skills");

  skill
    .command("list")
    .description("List standalone skills")
    .action(async () => {
      const skills = await listSkills(PATHS.skills);
      if (skills.length === 0) { console.log("No standalone skills found."); return; }
      console.log(chalk.bold(` ${"Name".padEnd(30)} ${"Type".padEnd(10)} Path`));
      console.log("─".repeat(70));
      for (const s of skills) {
        const type = s.isSymlink ? chalk.cyan("symlink") : chalk.gray("dir");
        const path = s.isSymlink ? `→ ${s.target}` : s.path;
        console.log(` ${s.name.padEnd(30)} ${type.padEnd(19)} ${path}`);
      }
      console.log(`\n ${skills.length} skill(s)`);
    });

  skill
    .command("link <path>")
    .option("-n, --name <name>", "Skill name (defaults to directory name)")
    .description("Link a skill directory")
    .action(async (path: string, opts: { name?: string }) => {
      await linkSkill(PATHS.skills, path, opts.name);
      console.log(chalk.green(`✓ Skill linked.`));
    });

  skill
    .command("unlink <name>")
    .description("Unlink a skill")
    .action(async (name: string) => {
      await unlinkSkill(PATHS.skills, name);
      console.log(chalk.green(`✓ Skill "${name}" unlinked.`));
    });
}
