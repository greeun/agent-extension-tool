import { readFile } from "fs/promises";
import { basename, dirname } from "path";
import { readJsonlRecords } from "@utils/jsonl.js";
import type { UnifiedUsageEntry } from "./types.js";

interface GeminiMessage {
  role: string; content?: string; timestamp?: string; model?: string;
  tokens?: { input: number; output: number; cached: number; thoughts: number; tool: number; total: number; };
}

interface GeminiSession { sessionId?: string; messages?: GeminiMessage[]; }

export async function parseGeminiFile(filePath: string): Promise<UnifiedUsageEntry[]> {
  const entries: UnifiedUsageEntry[] = [];

  let session: GeminiSession;
  if (filePath.endsWith(".jsonl")) {
    const records = await readJsonlRecords(filePath);
    if (records.length === 0) return [];
    session = records[0] as GeminiSession;
  } else {
    let content: string;
    try { content = await readFile(filePath, "utf-8"); } catch { return []; }
    try { session = JSON.parse(content); } catch { return []; }
  }

  const sessionId = session.sessionId ?? basename(filePath, ".json");
  const chatsDir = dirname(filePath);
  const projectSlug = basename(dirname(chatsDir));

  for (const msg of session.messages ?? []) {
    if (msg.role !== "gemini" || !msg.tokens) continue;
    entries.push({
      platform: "gemini", model: msg.model ?? "unknown", timestamp: msg.timestamp ?? "",
      sessionId, projectPath: projectSlug,
      inputTokens: msg.tokens.input ?? 0, outputTokens: msg.tokens.output ?? 0,
      cacheWriteTokens: 0, cacheReadTokens: msg.tokens.cached ?? 0,
      reasoningTokens: msg.tokens.thoughts ?? 0, toolTokens: msg.tokens.tool ?? 0,
    });
  }
  return entries;
}

export async function loadGeminiUsage(geminiTmpDir: string, options?: { since?: string; until?: string }): Promise<UnifiedUsageEntry[]> {
  const entries: UnifiedUsageEntry[] = [];
  const globber = new Bun.Glob("*/chats/session-*.{json,jsonl}");
  for await (const file of globber.scan({ cwd: geminiTmpDir, absolute: true })) {
    const fileEntries = await parseGeminiFile(file);
    for (const e of fileEntries) {
      const date = e.timestamp.slice(0, 10);
      if (options?.since && date < options.since) continue;
      if (options?.until && date > options.until) continue;
      entries.push(e);
    }
  }
  return entries;
}
