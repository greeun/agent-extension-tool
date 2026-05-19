import type { UsageEntry } from "../usage.js";

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
