import { readdir, readFile, lstat } from "fs/promises";
import { join, basename } from "path";
import { PATHS } from "./paths.js";
import { listInstalledPlugins } from "./plugin.js";
import { readEnabledPlugins } from "./settings.js";

export type CommandSource = "user" | "project" | "plugin";

export interface CommandInfo {
  name: string;
  source: CommandSource;
  sourcePath: string;
  plugin?: string;
  description: string;
  content: string;
}

async function scanCommandDir(
  dir: string,
  source: CommandSource,
  plugin?: string,
): Promise<CommandInfo[]> {
  let entries: string[];
  try { entries = await readdir(dir); } catch { return []; }

  const commands: CommandInfo[] = [];
  for (const file of entries) {
    if (!file.endsWith(".md")) continue;
    const fullPath = join(dir, file);
    const stat = await lstat(fullPath);
    if (!stat.isFile()) continue;

    const raw = await readFile(fullPath, "utf-8");
    const name = basename(file, ".md");

    let description = "";
    const fmMatch = raw.match(/^---\s*\n([\s\S]*?)\n---/);
    if (fmMatch) {
      const descLine = fmMatch[1].match(/description:\s*"?([^"\n]+)"?/);
      if (descLine) description = descLine[1].trim();
    }
    if (!description) {
      const firstLine = raw.split("\n").find((l) => l.trim() && !l.startsWith("#") && !l.startsWith("---"));
      description = firstLine?.trim().slice(0, 80) ?? "";
    }

    commands.push({
      name: plugin ? `${plugin}:${name}` : name,
      source,
      sourcePath: fullPath,
      plugin,
      description,
      content: raw,
    });
  }
  return commands;
}

export async function listCommands(options: {
  projectDir?: string;
}): Promise<CommandInfo[]> {
  const result: CommandInfo[] = [];

  const userCmdDir = join(PATHS.claudeDir, "commands");
  result.push(...await scanCommandDir(userCmdDir, "user"));

  if (options.projectDir) {
    const projCmdDir = join(options.projectDir, ".claude", "commands");
    result.push(...await scanCommandDir(projCmdDir, "project"));
  }

  const plugins = await listInstalledPlugins(PATHS.installedPlugins);
  const enabled = await readEnabledPlugins(PATHS.settings);
  for (const p of plugins) {
    if (enabled[p.id] !== true) continue;
    const cmdDir = join(p.installPath, "commands");
    result.push(...await scanCommandDir(cmdDir, "plugin", p.name));
  }

  return result;
}
