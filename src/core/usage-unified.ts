import type { UnifiedUsageEntry, Platform } from "./types.js";
import type { UsageEntry } from "./usage.js";
import { loadAllUsage } from "./usage.js";
import { loadCodexUsage } from "./usage-codex.js";
import { loadGeminiUsage } from "./usage-gemini.js";

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

interface LoadOptions {
  claudeProjectsDir: string;
  codexSessionsDir: string;
  geminiTmpDir: string;
  since?: string;
  until?: string;
  platform?: Platform | "all";
  project?: string;
  forceRefresh?: boolean;
}

export async function loadUnifiedUsage(options: LoadOptions): Promise<UnifiedUsageEntry[]> {
  const entries: UnifiedUsageEntry[] = [];
  const platform = options.platform ?? "all";
  const dateFilter = { since: options.since, until: options.until };

  if (platform === "all" || platform === "claude") {
    try {
      const claude = await loadAllUsage(options.claudeProjectsDir, {
        ...dateFilter,
        project: options.project,
        forceRefresh: options.forceRefresh,
      });
      entries.push(...claude.map(claudeToUnified));
    } catch {}
  }

  if (platform === "all" || platform === "codex") {
    try {
      const codex = await loadCodexUsage(options.codexSessionsDir, dateFilter);
      entries.push(...codex);
    } catch {}
  }

  if (platform === "all" || platform === "gemini") {
    try {
      const gemini = await loadGeminiUsage(options.geminiTmpDir, dateFilter);
      entries.push(...gemini);
    } catch {}
  }

  return entries.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
}
