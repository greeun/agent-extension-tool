import { join } from "path";
import { readdir, stat } from "fs/promises";
import { writeJsonAtomic } from "./json-io.js";

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
