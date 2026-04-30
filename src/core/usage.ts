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

export interface DailyUsage {
  date: string;
  sessions: number;
  models: string[];
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
}

export interface SessionUsage {
  sessionId: string;
  projectPath: string;
  models: string[];
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  firstTimestamp: string;
  lastTimestamp: string;
  messageCount: number;
}

export interface BlockUsage {
  startTime: string;
  endTime: string;
  durationHours: number;
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  isActive: boolean;
  burnRatePerMin: number | null;
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

/**
 * Get the local date string for a timestamp in a given timezone.
 */
function getDateInTimezone(isoTimestamp: string, timezone: string): string {
  const date = new Date(isoTimestamp);
  return date.toLocaleDateString("en-CA", { timeZone: timezone }); // returns YYYY-MM-DD
}

/**
 * Aggregate usage entries by calendar date.
 */
export function aggregateDaily(entries: UsageEntry[], timezone: string): DailyUsage[] {
  const map = new Map<string, DailyUsage & { sessionSet: Set<string>; modelSet: Set<string> }>();

  for (const entry of entries) {
    const date = getDateInTimezone(entry.timestamp, timezone);

    if (!map.has(date)) {
      map.set(date, {
        date,
        sessions: 0,
        models: [],
        inputTokens: 0,
        outputTokens: 0,
        cacheCreationTokens: 0,
        cacheReadTokens: 0,
        sessionSet: new Set(),
        modelSet: new Set(),
      });
    }

    const day = map.get(date)!;
    day.inputTokens += entry.inputTokens;
    day.outputTokens += entry.outputTokens;
    day.cacheCreationTokens += entry.cacheCreationTokens;
    day.cacheReadTokens += entry.cacheReadTokens;
    day.sessionSet.add(entry.sessionId);
    day.modelSet.add(entry.model);
  }

  return Array.from(map.values())
    .sort((a, b) => a.date.localeCompare(b.date))
    .map(({ sessionSet, modelSet, ...rest }) => ({
      ...rest,
      sessions: sessionSet.size,
      models: Array.from(modelSet),
    }));
}

/**
 * Aggregate usage entries by session.
 */
export function aggregateBySession(entries: UsageEntry[]): SessionUsage[] {
  const map = new Map<
    string,
    SessionUsage & { modelSet: Set<string>; timestamps: string[] }
  >();

  for (const entry of entries) {
    if (!map.has(entry.sessionId)) {
      map.set(entry.sessionId, {
        sessionId: entry.sessionId,
        projectPath: entry.projectPath,
        models: [],
        inputTokens: 0,
        outputTokens: 0,
        cacheCreationTokens: 0,
        cacheReadTokens: 0,
        firstTimestamp: entry.timestamp,
        lastTimestamp: entry.timestamp,
        messageCount: 0,
        modelSet: new Set(),
        timestamps: [],
      });
    }

    const session = map.get(entry.sessionId)!;
    session.inputTokens += entry.inputTokens;
    session.outputTokens += entry.outputTokens;
    session.cacheCreationTokens += entry.cacheCreationTokens;
    session.cacheReadTokens += entry.cacheReadTokens;
    session.messageCount += 1;
    session.modelSet.add(entry.model);
    session.timestamps.push(entry.timestamp);
  }

  return Array.from(map.values()).map(({ modelSet, timestamps, ...rest }) => {
    const sorted = timestamps.slice().sort();
    return {
      ...rest,
      models: Array.from(modelSet),
      firstTimestamp: sorted[0] ?? rest.firstTimestamp,
      lastTimestamp: sorted[sorted.length - 1] ?? rest.lastTimestamp,
    };
  });
}

/**
 * Compute 5-hour billing blocks from usage entries.
 * Windows are aligned to UTC midnight: 00:00, 05:00, 10:00, 15:00, 20:00.
 */
export function computeBlocks(entries: UsageEntry[], timezone: string): BlockUsage[] {
  if (entries.length === 0) return [];

  const BLOCK_HOURS = 5;
  const BLOCK_MS = BLOCK_HOURS * 60 * 60 * 1000;

  // Group entries into 5-hour UTC windows
  const windowMap = new Map<number, UsageEntry[]>();

  for (const entry of entries) {
    const ts = new Date(entry.timestamp).getTime();
    // Align to 5-hour UTC window from midnight
    const dayStart = new Date(entry.timestamp);
    dayStart.setUTCHours(0, 0, 0, 0);
    const msSinceMidnight = ts - dayStart.getTime();
    const windowIndex = Math.floor(msSinceMidnight / BLOCK_MS);
    const windowStart = dayStart.getTime() + windowIndex * BLOCK_MS;

    if (!windowMap.has(windowStart)) {
      windowMap.set(windowStart, []);
    }
    windowMap.get(windowStart)!.push(entry);
  }

  const now = Date.now();
  const blocks: BlockUsage[] = [];

  for (const [windowStart, windowEntries] of windowMap) {
    const windowEnd = windowStart + BLOCK_MS;
    const startIso = new Date(windowStart).toISOString();
    const endIso = new Date(windowEnd).toISOString();

    let inputTokens = 0;
    let outputTokens = 0;
    let cacheCreationTokens = 0;
    let cacheReadTokens = 0;

    for (const entry of windowEntries) {
      inputTokens += entry.inputTokens;
      outputTokens += entry.outputTokens;
      cacheCreationTokens += entry.cacheCreationTokens;
      cacheReadTokens += entry.cacheReadTokens;
    }

    const totalTokens = inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens;
    const isActive = now >= windowStart && now < windowEnd;

    let burnRatePerMin: number | null = null;
    if (isActive) {
      const elapsedMs = now - windowStart;
      const elapsedMin = elapsedMs / 60_000;
      burnRatePerMin = elapsedMin > 0 ? totalTokens / elapsedMin : null;
    }

    blocks.push({
      startTime: startIso,
      endTime: endIso,
      durationHours: BLOCK_HOURS,
      totalTokens,
      inputTokens,
      outputTokens,
      cacheCreationTokens,
      cacheReadTokens,
      isActive,
      burnRatePerMin,
    });
  }

  // Sort by start time ascending
  blocks.sort((a, b) => a.startTime.localeCompare(b.startTime));

  return blocks;
}
