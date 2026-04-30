import { readFile } from "fs/promises";
import { basename, dirname } from "path";
import type { UnifiedUsageEntry, RateLimitInfo } from "./types.js";

export async function parseCodexFile(filePath: string): Promise<UnifiedUsageEntry[]> {
  const content = await readFile(filePath, "utf-8");
  const lines = content.split("\n").filter((l) => l.trim());
  const entries: UnifiedUsageEntry[] = [];
  let currentModel = "unknown";
  let sessionId = basename(filePath, ".jsonl");
  const projectPath = basename(dirname(filePath));

  for (const line of lines) {
    let record: any;
    try { record = JSON.parse(line); } catch { continue; }
    if (record.type === "session_meta" && record.payload?.model) {
      currentModel = record.payload.model;
      if (record.payload.session_id) sessionId = record.payload.session_id;
      continue;
    }
    if (record.type === "event_msg" && record.payload?.type === "token_count") {
      const usage = record.payload.info?.last_token_usage;
      if (!usage) continue;
      entries.push({
        platform: "codex", model: currentModel, timestamp: record.timestamp ?? "",
        sessionId, projectPath,
        inputTokens: usage.input_tokens ?? 0, outputTokens: usage.output_tokens ?? 0,
        cacheWriteTokens: 0, cacheReadTokens: usage.cached_input_tokens ?? 0,
        reasoningTokens: usage.reasoning_output_tokens ?? 0, toolTokens: 0,
      });
    }
  }
  return entries;
}

export async function extractCodexRateLimit(filePath: string): Promise<RateLimitInfo | null> {
  const content = await readFile(filePath, "utf-8");
  const lines = content.split("\n").filter((l) => l.trim()).reverse();
  for (const line of lines) {
    let record: any;
    try { record = JSON.parse(line); } catch { continue; }
    if (record.type === "event_msg" && record.payload?.type === "token_count") {
      const rl = record.payload.rate_limits?.primary;
      if (!rl) continue;
      return { platform: "codex", usedPercent: rl.used_percent ?? 0, windowMinutes: rl.window_minutes ?? 300, resetsAt: rl.resets_at ?? null };
    }
  }
  return null;
}

export async function loadCodexUsage(sessionsDir: string, options?: { since?: string; until?: string }): Promise<UnifiedUsageEntry[]> {
  const entries: UnifiedUsageEntry[] = [];
  const globber = new Bun.Glob("**/*.jsonl");
  for await (const file of globber.scan({ cwd: sessionsDir, absolute: true })) {
    const fileEntries = await parseCodexFile(file);
    for (const e of fileEntries) {
      const date = e.timestamp.slice(0, 10);
      if (options?.since && date < options.since) continue;
      if (options?.until && date > options.until) continue;
      entries.push(e);
    }
  }
  return entries;
}
