import type { UnifiedUsageEntry, Platform } from "./types.js";
import { claudeLoader, codexLoader, geminiLoader, withCache, claudeToUnified } from "./usage/loader.js";

export { claudeToUnified };

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

  const jobs: Array<{ p: Platform; dir: string; loader: ReturnType<typeof withCache> }> = [
    { p: "claude", dir: options.claudeProjectsDir, loader: withCache(claudeLoader) },
    { p: "codex", dir: options.codexSessionsDir, loader: codexLoader },
    { p: "gemini", dir: options.geminiTmpDir, loader: geminiLoader },
  ];

  for (const job of jobs) {
    if (platform !== "all" && platform !== job.p) continue;
    try {
      const out = await job.loader.load({
        dir: job.dir,
        since: options.since,
        until: options.until,
        project: job.p === "claude" ? options.project : undefined,
        forceRefresh: job.p === "claude" ? options.forceRefresh : undefined,
      });
      entries.push(...out);
    } catch {}
  }

  return entries.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
}
