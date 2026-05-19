import { readFile, stat } from "fs/promises";
import { join, basename, dirname } from "path";
import { loadCachedUsage, saveCachedUsage, getFileMtime, isCacheValid } from "./cache.js";

export interface UsageEntry {
  model: string;
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  sessionId: string;
  projectPath: string;
  timestamp: string;
}


/**
 * Parse a JSONL file and extract assistant usage entries.
 */
export async function parseJsonlFile(filePath: string): Promise<UsageEntry[]> {
  const content = await readFile(filePath, "utf-8");
  const lines = content.split("\n").filter((line) => line.trim().length > 0);

  const projectPath = basename(dirname(filePath));
  const results: UsageEntry[] = [];

  for (const line of lines) {
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }

    if (record.type !== "assistant") continue;

    const message = record.message as Record<string, unknown> | undefined;
    if (!message) continue;

    const usage = message.usage as Record<string, unknown> | undefined;
    if (!usage) continue;

    results.push({
      model: (message.model as string) ?? "unknown",
      inputTokens: (usage.input_tokens as number) ?? 0,
      outputTokens: (usage.output_tokens as number) ?? 0,
      cacheCreationTokens: (usage.cache_creation_input_tokens as number) ?? 0,
      cacheReadTokens: (usage.cache_read_input_tokens as number) ?? 0,
      sessionId: (record.sessionId as string) ?? "",
      projectPath,
      timestamp: (record.timestamp as string) ?? "",
    });
  }

  return results;
}

/**
 * Load all usage entries from projectsDir, with optional filtering.
 */
export async function loadAllUsage(
  projectsDir: string,
  options?: { since?: string; until?: string; project?: string; forceRefresh?: boolean }
): Promise<UsageEntry[]> {
  const sinceMs = options?.since ? new Date(options.since).getTime() : null;
  const untilMs = options?.until ? new Date(options.until).getTime() : null;
  const projectFilter = options?.project ?? null;

  let cache = await loadCachedUsage("claude");

  if (!options?.forceRefresh && isCacheValid(cache) && cache.projectsDir === projectsDir) {
    const allCached: UsageEntry[] = [];
    for (const entries of Object.values(cache.files)) {
      allCached.push(...entries.entries);
    }
    return filterEntries(allCached, sinceMs, untilMs, projectFilter);
  }

  if (cache.projectsDir !== projectsDir) {
    cache = { version: 1, lastUpdated: "", projectsDir, files: {} };
  }
  cache.projectsDir = projectsDir;

  let files: string[] = [];
  try {
    const globber = new Bun.Glob("*/*.jsonl");
    for await (const file of globber.scan({ cwd: projectsDir, absolute: true })) {
      files.push(file);
    }
  } catch {
    files = [];
  }

  if (files.length === 0) {
    return [];
  }

  let changed = false;
  for (const filePath of files) {
    const projectName = basename(dirname(filePath));
    if (projectFilter && projectName !== projectFilter) continue;

    const mtime = await getFileMtime(filePath);
    const cached = cache.files[filePath];

    if (cached && cached.mtime >= mtime) continue;

    const entries = await parseJsonlFile(filePath);
    cache.files[filePath] = { mtime, entries };
    changed = true;
  }

  if (changed) {
    await saveCachedUsage("claude", cache);
  }

  const allEntries: UsageEntry[] = [];
  for (const entries of Object.values(cache.files)) {
    allEntries.push(...entries.entries);
  }

  return filterEntries(allEntries, sinceMs, untilMs, projectFilter);
}

function filterEntries(
  entries: UsageEntry[],
  sinceMs: number | null,
  untilMs: number | null,
  projectFilter: string | null
): UsageEntry[] {
  return entries.filter((entry) => {
    if (projectFilter && entry.projectPath !== projectFilter) return false;
    if (sinceMs !== null) {
      const ts = new Date(entry.timestamp).getTime();
      if (ts < sinceMs) return false;
    }
    if (untilMs !== null) {
      const ts = new Date(entry.timestamp).getTime();
      if (ts > untilMs) return false;
    }
    return true;
  });
}

export { aggregateDaily, aggregateBySession, computeBlocks } from "./usage/aggregate.js";
export type { DailyUsage, SessionUsage, BlockUsage } from "./usage/aggregate.js";

