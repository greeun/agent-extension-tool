import { readJson, writeJsonAtomic } from "./json-io.js";
import { rm, access, readFile, writeFile } from "fs/promises";
import { existsSync, mkdirSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

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

  if (source.source !== "directory") {
    const url = source.source === "github"
      ? `https://github.com/${source.repo}.git`
      : source.url;
    const proc = Bun.spawn(["git", "clone", "--depth", "1", url, installLocation], {
      stdout: "pipe", stderr: "pipe",
    });
    const code = await proc.exited;
    if (code !== 0) {
      const stderr = await new Response(proc.stderr).text();
      throw new Error(`git clone failed (exit ${code}): ${stderr.trim()}`);
    }
  } else {
    try { await access(source.path); } catch {
      throw new Error(`Directory not found: ${source.path}`);
    }
  }

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

export interface SyncResult {
  before: string;
  after: string;
  updated: boolean;
}

const GCS_SHA_FILE = ".gcs-sha";

export function isGitRepo(dir: string): boolean {
  return existsSync(join(dir, ".git"));
}

export async function readShaFile(dir: string): Promise<string | null> {
  try {
    const sha = (await readFile(join(dir, GCS_SHA_FILE), "utf-8")).trim();
    return sha || null;
  } catch {
    return null;
  }
}

async function fetchGitHubHeadSha(repo: string): Promise<string> {
  const res = await fetch(`https://api.github.com/repos/${repo}/commits/HEAD`, {
    headers: { Accept: "application/vnd.github.sha" },
  });
  if (!res.ok) throw new Error(`GitHub API error: ${res.status} ${res.statusText}`);
  return (await res.text()).trim();
}

export async function downloadAndExtractTarball(repo: string, dest: string): Promise<string> {
  const sha = await fetchGitHubHeadSha(repo);
  const tarballUrl = `https://api.github.com/repos/${repo}/tarball/${sha}`;
  const res = await fetch(tarballUrl, {
    headers: { Accept: "application/vnd.github+json" },
    redirect: "follow",
  });
  if (!res.ok) throw new Error(`Tarball download failed: ${res.status} ${res.statusText}`);

  const tmpDir = join(tmpdir(), `axt-tarball-${Date.now()}`);
  mkdirSync(tmpDir, { recursive: true });
  const tarPath = join(tmpDir, "archive.tar.gz");

  try {
    await writeFile(tarPath, Buffer.from(await res.arrayBuffer()));
    const extractDir = join(tmpDir, "extract");
    mkdirSync(extractDir, { recursive: true });
    const proc = Bun.spawn(["tar", "xzf", tarPath, "-C", extractDir], { stdout: "pipe", stderr: "pipe" });
    const code = await proc.exited;
    if (code !== 0) {
      const stderr = await new Response(proc.stderr).text();
      throw new Error(`tar extract failed: ${stderr.trim()}`);
    }
    const entries = await (await import("fs/promises")).readdir(extractDir);
    const rootDir = entries[0];
    if (!rootDir) throw new Error("Tarball extracted empty");
    const srcDir = join(extractDir, rootDir);

    rmSync(dest, { recursive: true, force: true });
    mkdirSync(dest, { recursive: true });
    const { cpSync } = await import("fs");
    cpSync(srcDir, dest, { recursive: true });
    await writeFile(join(dest, GCS_SHA_FILE), sha);
    return sha;
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function getGitShortHash(dir: string): Promise<string> {
  const proc = Bun.spawn(["git", "-C", dir, "rev-parse", "--short", "HEAD"], { stdout: "pipe", stderr: "pipe" });
  const code = await proc.exited;
  if (code !== 0) throw new Error(`git rev-parse failed in ${dir} (exit ${code})`);
  const hash = (await new Response(proc.stdout).text()).trim();
  if (!hash) throw new Error(`git rev-parse returned empty in ${dir}`);
  return hash;
}

export interface VersionInfo {
  current: string;
  remote: string;
  updatable: boolean;
  error?: string;
}

async function fetchAndGetRemoteHash(dir: string): Promise<string> {
  const fetchProc = Bun.spawn(["git", "-C", dir, "fetch", "--quiet"], { stdout: "pipe", stderr: "pipe" });
  const fetchCode = await fetchProc.exited;
  if (fetchCode !== 0) {
    const stderr = await new Response(fetchProc.stderr).text();
    throw new Error(`git fetch failed in ${dir} (exit ${fetchCode}): ${stderr.trim()}`);
  }
  const proc = Bun.spawn(["git", "-C", dir, "rev-parse", "--short", "@{u}"], { stdout: "pipe", stderr: "pipe" });
  const code = await proc.exited;
  if (code !== 0) throw new Error(`No upstream tracking branch in ${dir}`);
  const hash = (await new Response(proc.stdout).text()).trim();
  if (!hash) throw new Error(`git rev-parse @{u} returned empty in ${dir}`);
  return hash;
}

export async function getLocalVersion(kmPath: string, name: string): Promise<string> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  const entry = data[name];
  if (!entry) return "?";
  if (entry.source.source === "directory") return "local";
  if (isGitRepo(entry.installLocation)) {
    try { return await getGitShortHash(entry.installLocation); } catch { return "error"; }
  }
  const sha = await readShaFile(entry.installLocation);
  return sha ? sha.slice(0, 7) : "unknown";
}

export async function getMarketplaceVersion(kmPath: string, name: string): Promise<VersionInfo> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  const entry = data[name];
  if (!entry) return { current: "?", remote: "?", updatable: false, error: `"${name}" not found` };
  if (entry.source.source === "directory") return { current: "local", remote: "local", updatable: false };

  if (isGitRepo(entry.installLocation)) {
    try {
      const current = await getGitShortHash(entry.installLocation);
      const remote = await fetchAndGetRemoteHash(entry.installLocation);
      return { current, remote, updatable: current !== remote };
    } catch (e: any) {
      return { current: "?", remote: "?", updatable: false, error: e.message };
    }
  }

  if (entry.source.source === "github") {
    try {
      const localSha = await readShaFile(entry.installLocation);
      const current = localSha ? localSha.slice(0, 7) : "unknown";
      const remoteSha = await fetchGitHubHeadSha(entry.source.repo);
      const remote = remoteSha.slice(0, 7);
      return { current, remote, updatable: current !== remote };
    } catch (e: any) {
      return { current: "?", remote: "?", updatable: false, error: e.message };
    }
  }

  return { current: "?", remote: "?", updatable: false, error: "Non-git source without .git directory" };
}

const DEFAULT_CONCURRENCY = 4;

export interface PooledError<T> { item: T; error: Error; }

export interface PooledResult<T, R> { results: Map<T, R>; errors: PooledError<T>[]; }

export async function pooledMap<T, R>(
  items: T[],
  fn: (item: T) => Promise<R>,
  opts?: { concurrency?: number; onResult?: (item: T, result: R) => void; onError?: (item: T, error: Error) => void },
): Promise<PooledResult<T, R>> {
  const concurrency = opts?.concurrency ?? DEFAULT_CONCURRENCY;
  const results = new Map<T, R>();
  const errors: PooledError<T>[] = [];
  const queue = [...items];
  const worker = async () => {
    while (queue.length > 0) {
      const item = queue.shift()!;
      try {
        const result = await fn(item);
        results.set(item, result);
        opts?.onResult?.(item, result);
      } catch (e: any) {
        const error = e instanceof Error ? e : new Error(String(e));
        errors.push({ item, error });
        opts?.onError?.(item, error);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
  return { results, errors };
}

export async function syncMarketplace(kmPath: string, name: string): Promise<SyncResult> {
  const data = await readJson<KnownMarketplaces>(kmPath, { fallback: {} });
  const entry = data[name];
  if (!entry) throw new Error(`Marketplace "${name}" not found`);

  let before: string;
  let after: string;

  if (entry.source.source === "directory") {
    before = after = "local";
  } else if (isGitRepo(entry.installLocation)) {
    before = await getGitShortHash(entry.installLocation);
    const proc = Bun.spawn(["git", "-C", entry.installLocation, "pull", "--ff-only"], { stdout: "pipe", stderr: "pipe" });
    const code = await proc.exited;
    if (code !== 0) {
      const stderr = await new Response(proc.stderr).text();
      throw new Error(`git pull failed for "${name}" (exit ${code}): ${stderr.trim()}`);
    }
    after = await getGitShortHash(entry.installLocation);
  } else if (entry.source.source === "github") {
    const localSha = await readShaFile(entry.installLocation);
    before = localSha ? localSha.slice(0, 7) : "unknown";
    const newSha = await downloadAndExtractTarball(entry.source.repo, entry.installLocation);
    after = newSha.slice(0, 7);
  } else {
    throw new Error(`Cannot sync "${name}": not a git repo and not a github source`);
  }

  entry.lastUpdated = new Date().toISOString();
  await writeJsonAtomic(kmPath, data);
  return { before, after, updated: before !== after };
}
