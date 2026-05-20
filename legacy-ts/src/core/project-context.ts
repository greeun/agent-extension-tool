import { readdir, readFile, lstat } from "fs/promises";
import { join, basename } from "path";
import { homedir } from "os";

export interface ProjectContextItem {
  name: string;
  source: string;
  path: string;
  content: string;
  lines: number;
}

export async function loadProjectContext(cwd: string): Promise<ProjectContextItem[]> {
  const items: ProjectContextItem[] = [];
  const home = homedir();
  const claudeDir = join(home, ".claude");

  const candidates: { name: string; source: string; path: string }[] = [
    { name: "CLAUDE.md (global)", source: "global", path: join(home, "CLAUDE.md") },
    { name: "CLAUDE.md (user)", source: "user", path: join(claudeDir, "CLAUDE.md") },
    { name: "CLAUDE.md (project)", source: "project", path: join(cwd, "CLAUDE.md") },
    { name: "CLAUDE.md (project/.claude)", source: "project", path: join(cwd, ".claude", "CLAUDE.md") },
    { name: "settings.json (global)", source: "global", path: join(claudeDir, "settings.json") },
    { name: "settings.local.json (global)", source: "global", path: join(claudeDir, "settings.local.json") },
  ];

  const projectSettingsDir = join(claudeDir, "projects", cwd.replace(/\//g, "-").replace(/^-/, "-"));
  candidates.push(
    { name: "settings.json (project)", source: "project", path: join(projectSettingsDir, "settings.json") },
    { name: "settings.local.json (project)", source: "project", path: join(projectSettingsDir, "settings.local.json") },
  );

  for (const c of candidates) {
    const content = await safeRead(c.path);
    if (content !== null) {
      items.push({ ...c, content, lines: content.split("\n").length });
    }
  }

  const memoryDir = join(claudeDir, "projects", cwd.replace(/\//g, "-").replace(/^-/, "-"), "memory");
  const memFiles = await safeReaddir(memoryDir);
  for (const f of memFiles) {
    if (!f.endsWith(".md")) continue;
    const fullPath = join(memoryDir, f);
    const content = await safeRead(fullPath);
    if (content !== null) {
      items.push({ name: `Memory: ${basename(f, ".md")}`, source: "memory", path: fullPath, content, lines: content.split("\n").length });
    }
  }

  return items;
}

async function safeRead(path: string): Promise<string | null> {
  try {
    const stat = await lstat(path);
    if (!stat.isFile()) return null;
    return await readFile(path, "utf-8");
  } catch {
    return null;
  }
}

async function safeReaddir(dir: string): Promise<string[]> {
  try { return await readdir(dir); } catch { return []; }
}
