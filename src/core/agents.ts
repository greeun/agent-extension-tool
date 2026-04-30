import { readdir, readFile, lstat } from "fs/promises";
import { join, basename } from "path";
import { PATHS } from "./paths.js";
import { listInstalledPlugins } from "./plugin.js";
import { readEnabledPlugins } from "./settings.js";

export type AgentSource = "user" | "project" | "plugin";

export interface AgentInfo {
  name: string;
  source: AgentSource;
  sourcePath: string;
  plugin?: string;
  description: string;
}

async function scanAgentsDir(
  dir: string,
  source: AgentSource,
  plugin?: string,
): Promise<AgentInfo[]> {
  let entries: string[];
  try { entries = await readdir(dir); } catch { return []; }

  const agents: AgentInfo[] = [];
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

    agents.push({
      name: plugin ? `${plugin}:${name}` : name,
      source,
      sourcePath: fullPath,
      plugin,
      description,
    });
  }
  return agents;
}

export async function listAllAgents(options: {
  projectDir?: string;
}): Promise<AgentInfo[]> {
  const result: AgentInfo[] = [];

  const userAgentsDir = join(PATHS.claudeDir, "agents");
  result.push(...await scanAgentsDir(userAgentsDir, "user"));

  if (options.projectDir) {
    const projAgentsDir = join(options.projectDir, ".claude", "agents");
    result.push(...await scanAgentsDir(projAgentsDir, "project"));
  }

  const plugins = await listInstalledPlugins(PATHS.installedPlugins);
  const enabled = await readEnabledPlugins(PATHS.settings);
  for (const p of plugins) {
    if (enabled[p.id] !== true) continue;
    const pluginAgentsDir = join(p.installPath, "agents");
    result.push(...await scanAgentsDir(pluginAgentsDir, "plugin", p.name));
  }

  return result;
}
