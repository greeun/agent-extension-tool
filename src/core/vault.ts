import { join } from "path";
import { readdir, readlink, stat, lstat, symlink, unlink, mkdir, rename, cp, rm } from "fs/promises";
import { readJson, writeJsonAtomic } from "./json-io.js";

export type ExtensionType = "skill" | "command" | "agent" | "plugin";

export interface VaultItem {
  name: string;
  type: ExtensionType;
  path: string;
  isLinked: boolean;
  isGlobalLinked: boolean;
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
      let s;
      try {
        s = await stat(fullPath);
      } catch {
        continue;
      }
      if (type === "skill" && s.isDirectory()) {
        items.push({ name: entry, type, path: fullPath, isLinked: false, isGlobalLinked: false });
      } else if (type !== "skill" && s.isFile() && entry.endsWith(".md")) {
        items.push({ name: entry, type, path: fullPath, isLinked: false, isGlobalLinked: false });
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

const IS_WINDOWS = process.platform === "win32";

function typeToDir(type: ExtensionType): string {
  if (type === "skill") return "skills";
  if (type === "command") return "commands";
  if (type === "agent") return "agents";
  throw new Error(`Cannot link type "${type}" — plugins use enabledPlugins`);
}

export async function linkToProject(projectDir: string, item: VaultItem): Promise<void> {
  if (IS_WINDOWS) throw new Error("Vault linking is not supported on Windows.");
  if (item.type === "plugin") throw new Error("Plugins use enabledPlugins, not symlinks.");

  const dir = join(projectDir, ".claude", typeToDir(item.type));
  await mkdir(dir, { recursive: true });

  const linkPath = join(dir, item.name);
  try {
    const s = await lstat(linkPath);
    if (!s.isSymbolicLink()) {
      throw new Error(`"${item.name}" already exists as a real file in ${dir}`);
    }
    await unlink(linkPath);
  } catch (e: any) {
    if (e.code !== "ENOENT") throw e;
  }

  await symlink(item.path, linkPath);

  const profile = (await readProfile(projectDir)) ?? emptyProfile();
  const key = typeToDir(item.type) as keyof AxtProfile["extensions"];
  if (!profile.extensions[key].includes(item.name)) {
    profile.extensions[key].push(item.name);
  }
  await writeProfile(projectDir, profile);
}

export async function unlinkFromProject(projectDir: string, item: VaultItem): Promise<void> {
  if (IS_WINDOWS) throw new Error("Vault linking is not supported on Windows.");
  if (item.type === "plugin") throw new Error("Plugins use enabledPlugins, not symlinks.");

  const dir = join(projectDir, ".claude", typeToDir(item.type));
  const linkPath = join(dir, item.name);
  try {
    const s = await lstat(linkPath);
    if (s.isSymbolicLink()) await unlink(linkPath);
  } catch (e: any) {
    if (e.code !== "ENOENT") throw e;
  }

  const profile = (await readProfile(projectDir)) ?? emptyProfile();
  const key = typeToDir(item.type) as keyof AxtProfile["extensions"];
  profile.extensions[key] = profile.extensions[key].filter((n) => n !== item.name);
  await writeProfile(projectDir, profile);
}

export async function linkToGlobal(globalDir: string, item: VaultItem): Promise<void> {
  if (IS_WINDOWS) throw new Error("Vault linking is not supported on Windows.");
  if (item.type === "plugin") throw new Error("Plugins use enabledPlugins, not symlinks.");

  const dir = join(globalDir, typeToDir(item.type));
  await mkdir(dir, { recursive: true });

  const linkPath = join(dir, item.name);
  try {
    const s = await lstat(linkPath);
    if (!s.isSymbolicLink()) {
      throw new Error(`"${item.name}" already exists as a real file in ${dir}`);
    }
    await unlink(linkPath);
  } catch (e: any) {
    if (e.code !== "ENOENT") throw e;
  }

  await symlink(item.path, linkPath);
}

export async function unlinkFromGlobal(globalDir: string, item: VaultItem): Promise<void> {
  if (IS_WINDOWS) throw new Error("Vault linking is not supported on Windows.");
  if (item.type === "plugin") throw new Error("Plugins use enabledPlugins, not symlinks.");

  const dir = join(globalDir, typeToDir(item.type));
  const linkPath = join(dir, item.name);
  try {
    const s = await lstat(linkPath);
    if (s.isSymbolicLink()) await unlink(linkPath);
  } catch (e: any) {
    if (e.code !== "ENOENT") throw e;
  }
}

export async function syncProject(projectDir: string, vaultDir: string): Promise<SyncResult> {
  if (IS_WINDOWS) throw new Error("Vault linking is not supported on Windows.");

  const profile = (await readProfile(projectDir)) ?? emptyProfile();
  const result: SyncResult = { linked: [], unlinked: [], errors: [] };

  const typeDefs: { type: ExtensionType; dir: string; profileKey: keyof AxtProfile["extensions"] }[] = [
    { type: "skill", dir: "skills", profileKey: "skills" },
    { type: "command", dir: "commands", profileKey: "commands" },
    { type: "agent", dir: "agents", profileKey: "agents" },
  ];

  for (const { type, dir, profileKey } of typeDefs) {
    const vaultSubDir = join(vaultDir, dir);
    const projectSubDir = join(projectDir, ".claude", dir);
    await mkdir(projectSubDir, { recursive: true });

    const declared = new Set(profile.extensions[profileKey]);

    for (const name of declared) {
      const vaultPath = join(vaultSubDir, name);
      const linkPath = join(projectSubDir, name);
      try {
        await stat(vaultPath);
      } catch {
        result.errors.push(`${type}:${name} not found in vault`);
        continue;
      }
      try {
        const s = await lstat(linkPath);
        if (s.isSymbolicLink()) continue;
      } catch {}
      try {
        await symlink(vaultPath, linkPath);
        result.linked.push(`${type}:${name}`);
      } catch (e: any) {
        result.errors.push(`${type}:${name}: ${e.message}`);
      }
    }

    let entries: string[];
    try {
      entries = await readdir(projectSubDir);
    } catch {
      continue;
    }
    for (const entry of entries) {
      const linkPath = join(projectSubDir, entry);
      try {
        const s = await lstat(linkPath);
        if (!s.isSymbolicLink()) continue;
        const target = await readlink(linkPath);
        if (!target.startsWith(vaultSubDir)) continue;
        if (!declared.has(entry)) {
          await unlink(linkPath);
          result.unlinked.push(`${type}:${entry}`);
        }
      } catch {}
    }
  }

  return result;
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
        isGlobalLinked: false,
      });
    }
  }

  return items;
}

export async function migrateToVault(globalDir: string, vaultDir: string): Promise<MigrateResult> {
  const result: MigrateResult = { moved: [], skipped: [], errors: [] };

  await mkdir(join(vaultDir, "skills"), { recursive: true });
  await mkdir(join(vaultDir, "commands"), { recursive: true });
  await mkdir(join(vaultDir, "agents"), { recursive: true });

  const typeDefs: { type: ExtensionType; dir: string; isDir: boolean }[] = [
    { type: "skill", dir: "skills", isDir: true },
    { type: "command", dir: "commands", isDir: false },
    { type: "agent", dir: "agents", isDir: false },
  ];

  for (const { type, dir, isDir } of typeDefs) {
    const srcDir = join(globalDir, dir);
    let entries: string[];
    try {
      entries = await readdir(srcDir);
    } catch {
      continue;
    }

    for (const entry of entries) {
      if (entry.startsWith(".")) continue;
      const srcPath = join(srcDir, entry);
      const destPath = join(vaultDir, dir, entry);
      let s;
      try {
        s = await stat(srcPath);
      } catch {
        continue;
      }

      if (isDir && !s.isDirectory()) continue;
      if (!isDir && !s.isFile()) continue;
      if (!isDir && !entry.endsWith(".md")) continue;

      try {
        await stat(destPath);
        result.skipped.push(`${type}:${entry}`);
        continue;
      } catch {}

      try {
        await rename(srcPath, destPath);
        result.moved.push(`${type}:${entry}`);
      } catch {
        try {
          if (isDir) {
            await cp(srcPath, destPath, { recursive: true });
          } else {
            await cp(srcPath, destPath);
          }
          await rm(srcPath, { recursive: true });
          result.moved.push(`${type}:${entry}`);
        } catch (e: any) {
          result.errors.push(`${type}:${entry}: ${e.message}`);
        }
      }
    }
  }

  return result;
}
