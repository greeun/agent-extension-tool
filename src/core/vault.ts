import { join } from "path";
import { readdir, readlink, realpath, stat, lstat, symlink, unlink, mkdir, rename, cp, rm } from "fs/promises";
import { readJson, writeJsonAtomic } from "./json-io.js";

export type ExtensionType = "skill" | "command" | "agent" | "plugin";

export interface VaultItem {
  name: string;
  type: ExtensionType;
  path: string;
  description: string;
  isLinked: boolean;
  isGlobalLinked: boolean;
  inVault?: boolean;
  createdAt?: Date;
  updatedAt?: Date;
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

async function readDescription(filePath: string): Promise<string> {
  try {
    const content = await Bun.file(filePath).text();
    const match = content.match(/^---\s*\n([\s\S]*?)\n---/);
    if (match) {
      const descMatch = match[1].match(/^description:\s*(.+)$/m);
      if (descMatch) return descMatch[1].trim();
    }
  } catch {}
  return "";
}

async function readDescriptionForItem(fullPath: string, type: ExtensionType): Promise<string> {
  if (type === "skill") {
    const candidates = ["index.md", "SKILL.md"];
    for (const file of candidates) {
      const desc = await readDescription(join(fullPath, file));
      if (desc) return desc;
    }
    return "";
  }
  return readDescription(fullPath);
}

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
        const desc = await readDescriptionForItem(fullPath, type);
        items.push({ name: entry, type, path: fullPath, description: desc, isLinked: false, isGlobalLinked: false, inVault: true, createdAt: s.birthtime, updatedAt: s.mtime });
      } else if (type !== "skill" && s.isFile() && entry.endsWith(".md")) {
        const desc = await readDescriptionForItem(fullPath, type);
        items.push({ name: entry, type, path: fullPath, description: desc, isLinked: false, isGlobalLinked: false, inVault: true, createdAt: s.birthtime, updatedAt: s.mtime });
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
  description?: string;
  installPath?: string;
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

async function listGlobalNonVaultItems(globalDir: string, vaultDir: string): Promise<VaultItem[]> {
  const vaultItems = await listVaultItems(vaultDir);
  const vaultNamesByType = new Map<ExtensionType, Set<string>>();
  for (const item of vaultItems) {
    if (!vaultNamesByType.has(item.type)) vaultNamesByType.set(item.type, new Set());
    vaultNamesByType.get(item.type)!.add(item.name);
  }

  const items: VaultItem[] = [];

  const scanDir = async (subDir: string, type: ExtensionType) => {
    const dir = join(globalDir, subDir);
    const vaultNames = vaultNamesByType.get(type) ?? new Set();
    let entries: string[];
    try {
      entries = await readdir(dir);
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.startsWith(".")) continue;
      if (vaultNames.has(entry)) continue;
      const fullPath = join(dir, entry);
      let s;
      try {
        s = await stat(fullPath);
      } catch {
        continue;
      }
      if (type === "skill" && s.isDirectory()) {
        const desc = await readDescriptionForItem(fullPath, type);
        items.push({ name: entry, type, path: fullPath, description: desc, isLinked: false, isGlobalLinked: true, inVault: false, createdAt: s.birthtime, updatedAt: s.mtime });
      } else if (type !== "skill" && s.isFile() && entry.endsWith(".md")) {
        const desc = await readDescriptionForItem(fullPath, type);
        items.push({ name: entry, type, path: fullPath, description: desc, isLinked: false, isGlobalLinked: true, inVault: false, createdAt: s.birthtime, updatedAt: s.mtime });
      }
    }
  };

  await scanDir("skills", "skill");
  await scanDir("commands", "command");
  await scanDir("agents", "agent");

  return items;
}

export async function importToVault(globalDir: string, vaultDir: string, item: VaultItem): Promise<void> {
  if (item.type === "plugin") throw new Error("Plugins cannot be imported to vault.");

  const subDir = typeToDir(item.type);
  const srcPath = join(globalDir, subDir, item.name);
  const destPath = join(vaultDir, subDir, item.name);

  await mkdir(join(vaultDir, subDir), { recursive: true });

  try {
    await stat(destPath);
    throw new Error(`"${item.name}" already exists in vault`);
  } catch (e: any) {
    if (e.code !== "ENOENT") throw e;
  }

  const ls = await lstat(srcPath);
  if (ls.isSymbolicLink()) {
    const resolvedTarget = await realpath(srcPath);
    await symlink(resolvedTarget, destPath);
  } else {
    try {
      await rename(srcPath, destPath);
    } catch {
      const isDir = item.type === "skill";
      await cp(srcPath, destPath, { recursive: isDir });
      await rm(srcPath, { recursive: isDir });
    }
    await symlink(destPath, srcPath);
  }
}

export async function listVaultItemsWithProjectState(
  vaultDir: string,
  projectDir: string,
  installedPlugins?: PluginRef[],
  globalDir?: string,
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

    if (globalDir) {
      const globalLinkPath = join(globalDir, targetDir, item.name);
      try {
        const gs = await lstat(globalLinkPath);
        item.isGlobalLinked = gs.isSymbolicLink();
      } catch {
        item.isGlobalLinked = false;
      }
    }
  }

  if (installedPlugins && installedPlugins.length > 0) {
    const settingsPath = join(claudeDir, "settings.json");
    let enabledPlugins: Record<string, boolean> = {};
    try {
      const settings = await readJson<{ enabledPlugins?: Record<string, boolean> }>(settingsPath, { fallback: {} });
      enabledPlugins = settings.enabledPlugins ?? {};
    } catch {}

    let globalEnabledPlugins: Record<string, boolean> = {};
    if (globalDir) {
      try {
        const globalSettings = await readJson<{ enabledPlugins?: Record<string, boolean> }>(join(globalDir, "settings.json"), { fallback: {} });
        globalEnabledPlugins = globalSettings.enabledPlugins ?? {};
      } catch {}
    }

    for (const p of installedPlugins) {
      let createdAt: Date | undefined;
      let updatedAt: Date | undefined;
      if (p.installPath) {
        try {
          const ps = await stat(p.installPath);
          createdAt = ps.birthtime;
          updatedAt = ps.mtime;
        } catch {}
      }
      items.push({
        name: p.name,
        type: "plugin",
        path: p.installPath ?? "",
        description: p.description ?? "",
        isLinked: enabledPlugins[p.id] === true,
        isGlobalLinked: globalEnabledPlugins[p.id] === true,
        createdAt,
        updatedAt,
      });
    }
  }

  if (globalDir) {
    const globalItems = await listGlobalNonVaultItems(globalDir, vaultDir);
    for (const item of globalItems) {
      const targetDir = typeToDir(item.type);
      const linkPath = join(claudeDir, targetDir, item.name);
      try {
        const s = await lstat(linkPath);
        item.isLinked = s.isSymbolicLink();
      } catch {
        item.isLinked = false;
      }
    }
    items.push(...globalItems);
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
        const ls = await lstat(srcPath);
        if (ls.isSymbolicLink()) {
          const resolvedTarget = await realpath(srcPath);
          await symlink(resolvedTarget, destPath);
          result.moved.push(`${type}:${entry}`);
        } else {
          try {
            await rename(srcPath, destPath);
            result.moved.push(`${type}:${entry}`);
          } catch {
            if (isDir) {
              await cp(srcPath, destPath, { recursive: true });
            } else {
              await cp(srcPath, destPath);
            }
            await rm(srcPath, { recursive: true });
            result.moved.push(`${type}:${entry}`);
          }
        }
      } catch (e: any) {
        result.errors.push(`${type}:${entry}: ${e.message}`);
      }
    }
  }

  return result;
}
