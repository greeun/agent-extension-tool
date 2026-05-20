import type { UnifiedUsageEntry, Platform } from "../types.js";
import { loadAllUsage } from "./claude.js";
import { loadCodexUsage } from "../usage-codex.js";
import { loadGeminiUsage } from "../usage-gemini.js";
import type { UsageEntry } from "./claude.js";

export interface UsageLoadOptions {
  dir: string;
  since?: string;
  until?: string;
  project?: string;
  forceRefresh?: boolean;
}

export interface UsageLoader {
  platform: Platform;
  load(opts: UsageLoadOptions): Promise<UnifiedUsageEntry[]>;
}

export function claudeToUnified(entry: UsageEntry): UnifiedUsageEntry {
  return {
    platform: "claude",
    model: entry.model,
    timestamp: entry.timestamp,
    sessionId: entry.sessionId,
    projectPath: entry.projectPath,
    inputTokens: entry.inputTokens,
    outputTokens: entry.outputTokens,
    cacheWriteTokens: entry.cacheCreationTokens,
    cacheReadTokens: entry.cacheReadTokens,
    reasoningTokens: 0,
    toolTokens: 0,
  };
}

export const claudeLoader: UsageLoader = {
  platform: "claude",
  async load(opts) {
    const claude = await loadAllUsage(opts.dir, {
      since: opts.since,
      until: opts.until,
      project: opts.project,
      forceRefresh: opts.forceRefresh,
    });
    return claude.map(claudeToUnified);
  },
};

export const codexLoader: UsageLoader = {
  platform: "codex",
  load: (opts) => loadCodexUsage(opts.dir, { since: opts.since, until: opts.until }),
};

export const geminiLoader: UsageLoader = {
  platform: "gemini",
  load: (opts) => loadGeminiUsage(opts.dir, { since: opts.since, until: opts.until }),
};

/**
 * Capability decorator. Currently a pass-through: Claude's cache lives inside
 * loadAllUsage (mtime-based). codex/gemini intentionally remain uncached
 * (behavior preserved). The decorator exists so caching is expressible at the
 * interface level without changing runtime behavior.
 */
export function withCache(loader: UsageLoader): UsageLoader {
  return {
    platform: loader.platform,
    load: (opts) => loader.load(opts),
  };
}
