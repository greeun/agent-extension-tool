import { readJson, writeJsonAtomic } from "./json-io.js";
import { stat } from "fs/promises";
import { join } from "path";
import { AXT_CONFIG_DIR } from "./paths.js";

interface CacheEntry {
  mtime: number;
  entries: any[];
}

interface CacheFile {
  version: 1;
  lastUpdated: string;
  projectsDir?: string;
  files: Record<string, CacheEntry>;
}

const CACHE_DIR = join(AXT_CONFIG_DIR, "cache");

function getCachePath(platform: string): string {
  return join(CACHE_DIR, `${platform}-usage.json`);
}

export async function loadCachedUsage(platform: string): Promise<CacheFile> {
  return readJson<CacheFile>(getCachePath(platform), {
    fallback: { version: 1, lastUpdated: "", files: {} },
  });
}

export async function saveCachedUsage(platform: string, cache: CacheFile): Promise<void> {
  cache.lastUpdated = new Date().toISOString();
  await writeJsonAtomic(getCachePath(platform), cache);
}

export async function getFileMtime(filePath: string): Promise<number> {
  try {
    const s = await stat(filePath);
    return s.mtimeMs;
  } catch {
    return 0;
  }
}

export function isCacheValid(cache: CacheFile, maxAgeMs: number = 5 * 60 * 1000): boolean {
  if (!cache.lastUpdated) return false;
  const age = Date.now() - new Date(cache.lastUpdated).getTime();
  return age < maxAgeMs;
}
