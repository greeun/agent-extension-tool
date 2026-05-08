import { readJson, writeJsonAtomic } from "./json-io.js";
import { isGitRepo, readShaFile, downloadAndExtractTarball } from "./marketplace.js";
import { access } from "fs/promises";
import { cpSync } from "fs";
import { join } from "path";

interface PluginManifest {
  name?: string;
  description?: string;
  author?: string | { name: string; url?: string };
  homepage?: string;
  repository?: string | { url?: string };
  version?: string;
}

function normalizeString(val: unknown): string | undefined {
  if (typeof val === "string") return val;
  if (val && typeof val === "object" && "name" in val && typeof (val as any).name === "string") return (val as any).name;
  if (val && typeof val === "object" && "url" in val && typeof (val as any).url === "string") return (val as any).url;
  return undefined;
}

interface PluginEntry {
  scope: string;
  installPath: string;
  version: string;
  installedAt: string;
  lastUpdated: string;
  gitCommitSha?: string;
}

interface InstalledPluginsFile {
  version: number;
  plugins: Record<string, PluginEntry[]>;
}

export interface PluginInfo {
  id: string;
  name: string;
  marketplace: string;
  version: string;
  installPath: string;
  scope: string;
  installedAt: string;
  lastUpdated: string;
  author?: string;
  description?: string;
  homepage?: string;
  repository?: string;
}

function parsePluginId(id: string): { name: string; marketplace: string } {
  const atIdx = id.indexOf("@");
  if (atIdx === -1) return { name: id, marketplace: "unknown" };
  return { name: id.slice(0, atIdx), marketplace: id.slice(atIdx + 1) };
}

export async function listInstalledPlugins(ipPath: string): Promise<PluginInfo[]> {
  const data = await readJson<InstalledPluginsFile>(ipPath, { fallback: { version: 2, plugins: {} } });
  const results: PluginInfo[] = [];
  for (const [id, entries] of Object.entries(data.plugins)) {
    const entry = entries[0];
    const { name, marketplace } = parsePluginId(id);
    let manifest: PluginManifest = {};
    try {
      manifest = await readJson<PluginManifest>(join(entry.installPath, ".claude-plugin", "plugin.json"), { fallback: {} });
    } catch {}
    results.push({
      id, name, marketplace, version: entry.version, installPath: entry.installPath,
      scope: entry.scope, installedAt: entry.installedAt, lastUpdated: entry.lastUpdated,
      author: normalizeString(manifest.author), description: manifest.description,
      homepage: normalizeString(manifest.homepage), repository: normalizeString(manifest.repository),
    });
  }
  return results;
}

export async function getPluginInfo(ipPath: string, pluginId: string): Promise<PluginInfo | null> {
  const plugins = await listInstalledPlugins(ipPath);
  return plugins.find((p) => p.id === pluginId) ?? null;
}

export async function addInstalledPlugin(ipPath: string, opts: { id: string; version: string; installPath: string; scope: string }): Promise<void> {
  const data = await readJson<InstalledPluginsFile>(ipPath, { fallback: { version: 2, plugins: {} } });
  const now = new Date().toISOString();
  data.plugins[opts.id] = [{ scope: opts.scope, installPath: opts.installPath, version: opts.version, installedAt: now, lastUpdated: now }];
  await writeJsonAtomic(ipPath, data);
}

export async function removeInstalledPlugin(ipPath: string, pluginId: string): Promise<void> {
  const data = await readJson<InstalledPluginsFile>(ipPath, { fallback: { version: 2, plugins: {} } });
  delete data.plugins[pluginId];
  await writeJsonAtomic(ipPath, data);
}

interface MarketplaceSource {
  source: "github" | "git" | "directory";
  repo?: string;
  url?: string;
  path?: string;
}

interface MarketplaceEntry {
  source: MarketplaceSource;
  installLocation: string;
}

type KnownMarketplaces = Record<string, MarketplaceEntry>;

export async function findPluginSourceDir(marketplaceDir: string, pluginName: string): Promise<string | null> {
  const candidates = [
    join(marketplaceDir, "plugins", pluginName),
    join(marketplaceDir, pluginName),
    marketplaceDir,
  ];
  for (const dir of candidates) {
    try {
      await access(join(dir, ".claude-plugin", "plugin.json"));
      return dir;
    } catch {}
    try {
      await access(join(dir, "plugin.json"));
      return dir;
    } catch {}
  }
  return null;
}

export interface UpdateResult {
  updated: boolean;
  message: string;
}

export async function updatePlugin(ipPath: string, kmPath: string, pluginId: string): Promise<UpdateResult> {
  const { name, marketplace } = parsePluginId(pluginId);
  const kmData = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  const market = kmData[marketplace];
  if (!market) return { updated: false, message: `Marketplace "${marketplace}" not found` };
  if (market.source.source === "directory") return { updated: false, message: `Local directory — update not available` };

  const mktDir = market.installLocation;
  let sha = "";

  if (isGitRepo(mktDir)) {
    const pullProc = Bun.spawn(["git", "-C", mktDir, "pull", "--ff-only"], { stdout: "pipe", stderr: "pipe" });
    const pullCode = await pullProc.exited;
    if (pullCode !== 0) {
      const stderr = await new Response(pullProc.stderr).text();
      return { updated: false, message: `git pull failed: ${stderr.trim()}` };
    }
    const shaProc = Bun.spawn(["git", "-C", mktDir, "rev-parse", "HEAD"], { stdout: "pipe", stderr: "pipe" });
    await shaProc.exited;
    sha = (await new Response(shaProc.stdout).text()).trim();
  } else if (market.source.source === "github") {
    try {
      sha = await downloadAndExtractTarball(market.source.repo!, mktDir);
    } catch (e: any) {
      return { updated: false, message: `Tarball update failed: ${e.message}` };
    }
  } else {
    return { updated: false, message: `Cannot update: not a git repo and not a github source` };
  }

  const sourceDir = await findPluginSourceDir(mktDir, name);
  if (!sourceDir) return { updated: false, message: `"${name}" not found in marketplace` };

  const data = await readJson<InstalledPluginsFile>(ipPath, { fallback: { version: 2, plugins: {} } });
  const entries = data.plugins[pluginId];
  if (!entries?.[0]) return { updated: false, message: `Plugin "${name}" not in registry` };

  const entry = entries[0];
  cpSync(sourceDir, entry.installPath, { recursive: true, force: true });

  let newVersion = entry.version;
  try {
    const manifest = await readJson<{ version?: string }>(join(entry.installPath, ".claude-plugin", "plugin.json"), { fallback: {} });
    if (manifest.version) newVersion = manifest.version;
  } catch {}

  entry.version = newVersion;
  entry.lastUpdated = new Date().toISOString();
  if (sha) entry.gitCommitSha = sha;
  await writeJsonAtomic(ipPath, data);

  return { updated: true, message: `Updated "${name}" to ${newVersion}` };
}
