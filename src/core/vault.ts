import { join } from "path";
import { readdir, stat, lstat } from "fs/promises";
import { readJson, writeJsonAtomic } from "./json-io.js";

export type ExtensionType = "skill" | "command" | "agent" | "plugin";

export interface VaultItem {
  name: string;
  type: ExtensionType;
  path: string;
  isLinked: boolean;
}

export interface AxtProfile {
  extensions: {
    skills: string[];
    commands: string[];
    agents: string[];
    plugins: string[];
  };
}

export interface SyncResult {
  linked: string[];
  unlinked: string[];
  errors: string[];
}

export interface MigrateResult {
  moved: string[];
  skipped: string[];
  errors: string[];
}

const PROFILE_NAME = ".axt-profile.json";

export function emptyProfile(): AxtProfile {
  return { extensions: { skills: [], commands: [], agents: [], plugins: [] } };
}

export async function readProfile(projectDir: string): Promise<AxtProfile | null> {
  const file = Bun.file(join(projectDir, PROFILE_NAME));
  if (!(await file.exists())) return null;
  return file.json() as Promise<AxtProfile>;
}

export async function writeProfile(projectDir: string, profile: AxtProfile): Promise<void> {
  await writeJsonAtomic(join(projectDir, PROFILE_NAME), profile);
}

export async function listVaultItems(vaultDir: string): Promise<VaultItem[]> {
  const items: VaultItem[] = [];

  const scanDir = async (subDir: string, type: ExtensionType) => {
    const dir = join(vaultDir, subDir);
    let entries: string[];
    try {
      entries = await readdir(dir);
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.startsWith(".")) continue;
      const fullPath = join(dir, entry);
      const s = await stat(fullPath);
      if (type === "skill" && s.isDirectory()) {
        items.push({ name: entry, type, path: fullPath, isLinked: false });
      } else if (type !== "skill" && s.isFile() && entry.endsWith(".md")) {
        items.push({ name: entry, type, path: fullPath, isLinked: false });
      }
    }
  };

  await scanDir("skills", "skill");
  await scanDir("commands", "command");
  await scanDir("agents", "agent");

  return items;
}

export interface PluginRef {
  id: string;
  name: string;
}

export async function listVaultItemsWithProjectState(
  vaultDir: string,
  projectDir: string,
  installedPlugins?: PluginRef[],
): Promise<VaultItem[]> {
  const items = await listVaultItems(vaultDir);

  const claudeDir = join(projectDir, ".claude");

  for (const item of items) {
    const targetDir = item.type === "skill" ? "skills" : item.type === "command" ? "commands" : "agents";
    const linkPath = join(claudeDir, targetDir, item.name);
    try {
      const s = await lstat(linkPath);
      item.isLinked = s.isSymbolicLink();
    } catch {
      item.isLinked = false;
    }
  }

  if (installedPlugins && installedPlugins.length > 0) {
    const settingsPath = join(claudeDir, "settings.json");
    let enabledPlugins: Record<string, boolean> = {};
    try {
      const settings = await readJson<{ enabledPlugins?: Record<string, boolean> }>(settingsPath, { fallback: {} });
      enabledPlugins = settings.enabledPlugins ?? {};
    } catch {}

    for (const p of installedPlugins) {
      items.push({
        name: p.name,
        type: "plugin",
        path: "",
        isLinked: enabledPlugins[p.id] === true,
      });
    }
  }

  return items;
}
