import { readJson, writeJsonAtomic } from "./json-io.js";

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
}

function parsePluginId(id: string): { name: string; marketplace: string } {
  const atIdx = id.indexOf("@");
  if (atIdx === -1) return { name: id, marketplace: "unknown" };
  return { name: id.slice(0, atIdx), marketplace: id.slice(atIdx + 1) };
}

export async function listInstalledPlugins(ipPath: string): Promise<PluginInfo[]> {
  const data = await readJson<InstalledPluginsFile>(ipPath, { fallback: { version: 2, plugins: {} } });
  return Object.entries(data.plugins).map(([id, entries]) => {
    const entry = entries[0];
    const { name, marketplace } = parsePluginId(id);
    return { id, name, marketplace, version: entry.version, installPath: entry.installPath, scope: entry.scope, installedAt: entry.installedAt, lastUpdated: entry.lastUpdated };
  });
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
