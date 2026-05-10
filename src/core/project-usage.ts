import { join } from "path";
import { readdir, stat, lstat, readlink } from "fs/promises";
import { readJson } from "./json-io.js";
import type { AxtProfile } from "./vault.js";

export interface ProjectRef {
  path: string;
  name: string;
}

export interface ExtensionUsage {
  type: "skill" | "command" | "agent" | "plugin";
  name: string;
  projects: ProjectRef[];
}

export type UsageIndex = Map<string, ExtensionUsage>;

async function decodeProjectDirName(encoded: string): Promise<string | null> {
  const segments = encoded.substring(1).split("-");
  let current = "/";

  let i = 0;
  while (i < segments.length) {
    let matched = false;
    for (let len = segments.length - i; len >= 1; len--) {
      const candidate = segments.slice(i, i + len).join("-");

      for (const prefix of ["", "."]) {
        const testPath = join(current, prefix + candidate);
        try {
          const s = await stat(testPath);
          if (s.isDirectory()) {
            current = testPath;
            i += len;
            matched = true;
            break;
          }
        } catch {}
      }
      if (matched) break;
    }
    if (!matched) return null;
  }

  return current;
}

function usageKey(type: string, name: string): string {
  return `${type}:${name}`;
}

function projectName(p: string): string {
  const parts = p.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? p;
}

async function scanProfileAt(
  projectPath: string,
  index: UsageIndex,
  ref: ProjectRef,
): Promise<void> {
  const profilePath = join(projectPath, ".axt-profile.json");
  let profile: AxtProfile;
  try {
    profile = await readJson<AxtProfile>(profilePath);
  } catch {
    return;
  }

  const ext = profile.extensions;
  for (const name of ext.skills ?? []) {
    addToIndex(index, "skill", name, ref);
  }
  for (const name of ext.commands ?? []) {
    addToIndex(index, "command", name, ref);
  }
  for (const name of ext.agents ?? []) {
    addToIndex(index, "agent", name, ref);
  }
  for (const name of ext.plugins ?? []) {
    addToIndex(index, "plugin", name, ref);
  }
}

async function scanSymlinksAt(
  projectPath: string,
  vaultDir: string,
  index: UsageIndex,
  ref: ProjectRef,
): Promise<void> {
  const dirs: { subDir: string; type: "skill" | "command" | "agent" }[] = [
    { subDir: "skills", type: "skill" },
    { subDir: "commands", type: "command" },
    { subDir: "agents", type: "agent" },
  ];

  for (const { subDir, type } of dirs) {
    const dir = join(projectPath, ".claude", subDir);
    let entries: string[];
    try {
      entries = await readdir(dir);
    } catch {
      continue;
    }

    for (const entry of entries) {
      if (entry.startsWith(".")) continue;
      const entryPath = join(dir, entry);
      try {
        const s = await lstat(entryPath);
        if (!s.isSymbolicLink()) continue;
        const target = await readlink(entryPath);
        if (target.startsWith(vaultDir)) {
          addToIndex(index, type, entry, ref);
        }
      } catch {}
    }
  }
}

async function scanPluginSettingsAt(
  projectPath: string,
  index: UsageIndex,
  ref: ProjectRef,
): Promise<void> {
  const settingsPath = join(projectPath, ".claude", "settings.json");
  try {
    const settings = await readJson<{ enabledPlugins?: Record<string, boolean> }>(settingsPath, { fallback: {} });
    const enabled = settings.enabledPlugins ?? {};
    for (const [id, val] of Object.entries(enabled)) {
      if (val) addToIndex(index, "plugin", id, ref);
    }
  } catch {}
}

function addToIndex(
  index: UsageIndex,
  type: string,
  name: string,
  ref: ProjectRef,
): void {
  const key = usageKey(type, name);
  let entry = index.get(key);
  if (!entry) {
    entry = { type: type as ExtensionUsage["type"], name, projects: [] };
    index.set(key, entry);
  }
  if (!entry.projects.some((p) => p.path === ref.path)) {
    entry.projects.push(ref);
  }
}

export async function scanProjectUsage(
  projectsDir: string,
  vaultDir: string,
  mode: "default" | "full" = "default",
): Promise<UsageIndex> {
  const index: UsageIndex = new Map();

  let dirNames: string[];
  try {
    dirNames = await readdir(projectsDir);
  } catch {
    return index;
  }

  const decodeTasks = dirNames.map(async (dirName) => {
    if (!dirName.startsWith("-")) return null;
    const decoded = await decodeProjectDirName(dirName);
    if (!decoded) return null;
    return { dirName, path: decoded };
  });

  const decoded = (await Promise.all(decodeTasks)).filter(
    (d): d is { dirName: string; path: string } => d !== null,
  );

  const scanTasks = decoded.map(async ({ path: projectPath }) => {
    const ref: ProjectRef = { path: projectPath, name: projectName(projectPath) };

    if (mode === "full") {
      await Promise.all([
        scanProfileAt(projectPath, index, ref),
        scanSymlinksAt(projectPath, vaultDir, index, ref),
        scanPluginSettingsAt(projectPath, index, ref),
      ]);
    } else {
      await scanProfileAt(projectPath, index, ref);
      await scanSymlinksAt(projectPath, vaultDir, index, ref);
    }
  });

  await Promise.all(scanTasks);
  return index;
}

export function getProjectCount(index: UsageIndex, type: string, name: string): number {
  return index.get(usageKey(type, name))?.projects.length ?? 0;
}

export function getProjects(index: UsageIndex, type: string, name: string): ProjectRef[] {
  return index.get(usageKey(type, name))?.projects ?? [];
}
