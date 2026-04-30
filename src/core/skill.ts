import { readdir, lstat, readlink, symlink, unlink } from "fs/promises";
import { join, basename } from "path";
import { PATHS } from "./paths.js";
import { listInstalledPlugins } from "./plugin.js";
import { readEnabledPlugins } from "./settings.js";

const IS_WINDOWS = process.platform === "win32";

export type SkillSource = "user" | "project" | "plugin";

export interface SkillInfo {
  name: string;
  path: string;
  isSymlink: boolean;
  target?: string;
  source: SkillSource;
  plugin?: string;
}

async function scanSkillsDir(
  skillsDir: string,
  source: SkillSource,
  plugin?: string,
): Promise<SkillInfo[]> {
  let entries: string[];
  try { entries = await readdir(skillsDir); } catch { return []; }

  const skills: SkillInfo[] = [];
  for (const entry of entries) {
    if (entry.startsWith(".")) continue;
    const fullPath = join(skillsDir, entry);
    const stat = await lstat(fullPath);
    if (!stat.isDirectory() && !stat.isSymbolicLink()) continue;
    const info: SkillInfo = {
      name: plugin ? `${plugin}:${entry}` : entry,
      path: fullPath,
      isSymlink: stat.isSymbolicLink(),
      source,
      plugin,
    };
    if (stat.isSymbolicLink()) { info.target = await readlink(fullPath); }
    skills.push(info);
  }
  return skills;
}

export async function listSkills(skillsDir: string): Promise<SkillInfo[]> {
  return scanSkillsDir(skillsDir, "user");
}

export async function listAllSkills(options: {
  projectDir?: string;
}): Promise<SkillInfo[]> {
  const result: SkillInfo[] = [];

  result.push(...await scanSkillsDir(PATHS.skills, "user"));

  if (options.projectDir) {
    const projSkillsDir = join(options.projectDir, ".claude", "skills");
    result.push(...await scanSkillsDir(projSkillsDir, "project"));
  }

  const plugins = await listInstalledPlugins(PATHS.installedPlugins);
  const enabled = await readEnabledPlugins(PATHS.settings);
  for (const p of plugins) {
    if (enabled[p.id] !== true) continue;
    const pluginSkillsDir = join(p.installPath, "skills");
    result.push(...await scanSkillsDir(pluginSkillsDir, "plugin", p.name));
  }

  return result;
}

export function isSymlinkSupported(): boolean {
  return !IS_WINDOWS;
}

export async function linkSkill(skillsDir: string, targetPath: string, name?: string): Promise<void> {
  if (IS_WINDOWS) throw new Error("Skill linking via symlink is not supported on Windows.");
  const skillName = name ?? basename(targetPath);
  const linkPath = join(skillsDir, skillName);
  await symlink(targetPath, linkPath);
}

export async function unlinkSkill(skillsDir: string, name: string): Promise<void> {
  if (IS_WINDOWS) throw new Error("Skill unlinking is not supported on Windows.");
  const fullPath = join(skillsDir, name);
  const stat = await lstat(fullPath);
  if (!stat.isSymbolicLink()) throw new Error(`"${name}" is not a symlink. Use rm to remove directories.`);
  await unlink(fullPath);
}
