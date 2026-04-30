import { readJson, writeJsonAtomic } from "./json-io.js";
import { rm } from "fs/promises";
import { join } from "path";

export type MarketplaceSource =
  | { source: "github"; repo: string }
  | { source: "git"; url: string }
  | { source: "directory"; path: string };

interface MarketplaceEntry {
  source: MarketplaceSource;
  installLocation: string;
  lastUpdated: string;
  autoUpdate?: boolean;
}

type KnownMarketplaces = Record<string, MarketplaceEntry>;

export interface MarketplaceInfo {
  name: string;
  source: MarketplaceSource;
  installLocation: string;
  lastUpdated: string;
}

export function parseMarketplaceSource(input: string): MarketplaceSource {
  if (input.startsWith("github:")) return { source: "github", repo: input.slice("github:".length) };
  if (input.startsWith("git:")) return { source: "git", url: input.slice("git:".length) };
  if (input.startsWith("dir:")) return { source: "directory", path: input.slice("dir:".length) };
  if (input.includes("/") && !input.includes(":")) return { source: "github", repo: input };
  throw new Error(`Invalid source format: ${input}. Use github:user/repo, git:url, or dir:/path`);
}

export async function listMarketplaces(kmPath: string): Promise<MarketplaceInfo[]> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  return Object.entries(data).map(([name, entry]) => ({
    name, source: entry.source, installLocation: entry.installLocation, lastUpdated: entry.lastUpdated,
  }));
}

export async function addMarketplace(kmPath: string, marketplacesDir: string, name: string, source: MarketplaceSource): Promise<void> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  if (data[name]) throw new Error(`Marketplace "${name}" already exists`);
  const installLocation = source.source === "directory" ? source.path : join(marketplacesDir, name);
  data[name] = { source, installLocation, lastUpdated: new Date().toISOString() };
  await writeJsonAtomic(kmPath, data);
}

export async function removeMarketplace(kmPath: string, marketplacesDir: string, name: string): Promise<void> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  if (!data[name]) throw new Error(`Marketplace "${name}" not found`);
  const installLocation = data[name].installLocation;
  delete data[name];
  await writeJsonAtomic(kmPath, data);
  if (installLocation.startsWith(marketplacesDir)) {
    await rm(installLocation, { recursive: true, force: true });
  }
}

export async function syncMarketplace(kmPath: string, name: string): Promise<void> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  const entry = data[name];
  if (!entry) throw new Error(`Marketplace "${name}" not found`);
  if (entry.source.source === "github" || entry.source.source === "git") {
    const proc = Bun.spawn(["git", "-C", entry.installLocation, "pull", "--ff-only"], { stdout: "inherit", stderr: "inherit" });
    await proc.exited;
  }
  entry.lastUpdated = new Date().toISOString();
  await writeJsonAtomic(kmPath, data);
}
